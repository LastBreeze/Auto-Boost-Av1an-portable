import os
import sys
import psutil
import subprocess
import time
import shutil
import concurrent.futures
import gc
import random
import threading
import queue
import re
import json
import statistics
from pathlib import Path
import vapoursynth as vs

# --- CONFIGURATION ---
VERBOSE = False  # Set to True to see all raw output for troubleshooting

BASE_DIR = Path(__file__).parent.parent.resolve()
TOOLS_DIR = BASE_DIR / "tools"
AV1AN_DIR = TOOLS_DIR / "av1an"
AV1AN_EXE = AV1AN_DIR / "av1an.exe"
FORKS_DIR = AV1AN_DIR / "svt-av1 forks"
SAMPLE_FILE = TOOLS_DIR / "sample.mkv"
CONFIG_FILE = TOOLS_DIR / "workercount-ssimu2.txt"
TEMP_DIR = TOOLS_DIR / "ssimu2_bench_temp"

# FFVship paths
FFVSHIP_NVIDIA_EXE = TOOLS_DIR / "FFVship" / "FFVship_nvidia" / "FFVship.exe"
FFVSHIP_VULKAN_EXE = TOOLS_DIR / "FFVship" / "FFVship_Vulkan" / "FFVship.exe"

# Updated path: Both scripts are in the tools folder
AUTO_BOOST_SCRIPT = TOOLS_DIR / "Auto-Boost-Av1an.py"

# Benchmark Settings
SKIP = 3
STALL_TIMEOUT = 10.0  # Seconds to wait before killing stalled process

# vs-zip CPU worker measurement tuning
TARGET_CPU_UTILIZATION = 0.90   # Aim for ~90% CPU load with vs-zip workers
SPILLOVER_WEIGHT = 0.5          # Fraction of measured usage ABOVE 1 core counted as
                                # real per-worker demand. A lone worker opportunistically
                                # spills onto idle cores it doesn't strictly need, so its
                                # raw measurement overstates demand under contention.
CPU_WARMUP_SECONDS = 3.0        # Ignore vs-zip spin-up before sampling CPU usage
VSZIP_PROBE_DURATION = 12       # Seconds for the 1-worker measurement pass

# GPU / Plugin Paths
VS_PLUGINS_DIR = BASE_DIR / "VapourSynth" / "vs-plugins"
VS_HIP_SOURCE_DIR = TOOLS_DIR / "vs-hip"

try:
    from vstools import core, clip_async_render
except ImportError:
    print("Error: vstools not found.", file=sys.stderr)
    sys.exit(1)


FILTER_SETTING_KEYS = ("downscale", "denoise", "deband")

def read_settings_values() -> dict:
    settings_paths = [BASE_DIR / "settings.txt", TOOLS_DIR / "settings.txt"]
    values = {}
    for settings_path in settings_paths:
        if not settings_path.exists():
            continue
        try:
            for raw_line in settings_path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw_line.strip()
                if not line or line.startswith(("#", ";", "[")) or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip().lower()] = value.strip()
        except Exception:
            pass
    return values

def settings_filters_enabled() -> bool:
    values = read_settings_values()
    return any(values.get(key, "false").lower() == "true" for key in FILTER_SETTING_KEYS)


# ---------------------------------------------------------------------------
# .bat FILE HELPERS (optimize-workers support)
# ---------------------------------------------------------------------------

BAT_SET_RE = re.compile(r'^set\s+"?([^=\s"]+)\s*=(.*?)"?\s*$', re.IGNORECASE)


def find_active_bat_file():
    """Locate the .bat that launched this run via the tools/bat-used-*.txt marker."""
    try:
        markers = sorted(TOOLS_DIR.glob("bat-used-*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        markers = []
    for marker in markers:
        name = marker.name
        if not (name.startswith("bat-used-") and name.endswith(".txt")):
            continue
        bat_name = name[len("bat-used-"):-len(".txt")]
        bat_path = BASE_DIR / bat_name
        if bat_path.is_file():
            return bat_path
    return None


def parse_bat_settings(bat_path):
    """Parse `set "key=value"` (and bare key=value) lines from a .bat into a dict."""
    settings = {}
    try:
        text = Path(bat_path).read_text(encoding="utf-8", errors="replace")
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("::") or line.lower().startswith("rem "):
                continue
            m = BAT_SET_RE.match(line)
            if m:
                settings[m.group(1).lower()] = m.group(2).strip()
            elif "=" in line and " " not in line.split("=", 1)[0] and "%" not in line.split("=", 1)[0]:
                k, v = line.split("=", 1)
                settings.setdefault(k.strip().lower(), v.strip())
    except Exception as e:
        print(f"[Optimize] Warning: Could not parse {bat_path}: {e}", file=sys.stderr)
    return settings


def set_bat_value_fixed_width(bat_path, key, value):
    """Write key=value into the .bat WITHOUT changing the file's byte length.

    cmd.exe reads a running batch file by byte offset, so any edit made while
    the .bat is executing must keep every byte offset identical. bat-builder
    writes these values with padding spaces so the number fits in-place."""
    value = str(value)
    key_l = key.lower()
    bat_path = Path(bat_path)
    try:
        with open(bat_path, "r", encoding="utf-8", errors="replace", newline="") as f:
            content = f.read()
    except Exception as e:
        print(f"[Optimize] Error reading {bat_path}: {e}", file=sys.stderr)
        return False

    lines = content.splitlines(keepends=True)
    for idx, raw in enumerate(lines):
        body = raw.rstrip("\r\n")
        ending = raw[len(body):]
        stripped = body.strip()
        lead = body[:len(body) - len(body.lstrip())]
        m = BAT_SET_RE.match(stripped)
        if m and m.group(1).lower() == key_l:
            prefix = f'set "{m.group(1)}='
            width = len(stripped) - len(prefix) - 1  # minus closing quote
            suffix = '"'
        elif "=" in stripped and " " not in stripped.split("=", 1)[0] and stripped.split("=", 1)[0].strip().lower() == key_l:
            actual_key = stripped.split("=", 1)[0]
            prefix = f"{actual_key}="
            width = len(stripped) - len(prefix)
            suffix = ""
        else:
            continue

        if len(value) <= width:
            padded = value + " " * (width - len(value))
        else:
            padded = value
            print(f"[Optimize] Warning: value '{value}' is wider than the reserved "
                  f"space for {key} in the .bat; file length will change.", file=sys.stderr)

        lines[idx] = lead + prefix + padded + suffix + ending
        try:
            with open(bat_path, "w", encoding="utf-8", errors="replace", newline="") as f:
                f.write("".join(lines))
            return True
        except Exception as e:
            print(f"[Optimize] Error writing {bat_path}: {e}", file=sys.stderr)
            return False

    print(f"[Optimize] Warning: {key} line not found in {bat_path.name}.", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# CPU MEASUREMENT + FILTERED BENCHMARK SOURCE
# ---------------------------------------------------------------------------

class _CpuSampler(threading.Thread):
    """Samples this process's settled CPU usage (in cores) on a background thread.

    vs-zip runs in-process via VapourSynth threads, so the whole-process CPU
    percent IS the vs-zip worker load (plus decode overhead, which real runs
    also pay). The first CPU_WARMUP_SECONDS are skipped so the spin-up burst
    (graph construction, indexing, lookahead) is not counted."""

    def __init__(self, warmup=3.0, interval=0.25):
        super().__init__(daemon=True)
        self._warmup = warmup
        self._interval = interval
        self._stop_event = threading.Event()
        self.samples = []

    def run(self):
        try:
            proc = psutil.Process(os.getpid())
            proc.cpu_percent(None)  # prime the counter
            start = time.time()
            while True:
                if self._stop_event.wait(self._interval):
                    break
                pct = proc.cpu_percent(None)
                if time.time() - start >= self._warmup and pct > 0:
                    self.samples.append(pct / 100.0)
        except Exception:
            pass

    def stop(self):
        """Stop sampling and return the median settled cores used (0.0 if unknown)."""
        self._stop_event.set()
        try:
            self.join(timeout=2)
        except Exception:
            pass
        if not self.samples:
            return 0.0
        return statistics.median(self.samples)


def build_benchmark_source_clip():
    """Return (clip, description) for the vs-zip benchmark source.

    When settings.txt filtering is enabled, this mirrors the temporary
    VapourSynth script that Auto-Boost-Av1an.py builds (initialize_clip ->
    denoise/deband hooks -> downscale -> finalize_clip) and exec()s it the
    same way Auto-Boost does, so the benchmark pays the same filtering CPU
    cost as a real metrics pass. Crop is left off for the benchmark, which
    only makes the result slightly conservative."""
    if not settings_filters_enabled():
        return core.ffms2.Source(source=str(SAMPLE_FILE)), "raw sample (no settings.txt filters enabled)"

    values = read_settings_values()
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    vpy_path = TEMP_DIR / "bench_source.vpy"
    cache_path = TEMP_DIR / "bench_source.ffindex"

    do_downscale = values.get("downscale", "false").lower() == "true"
    target_res = values.get("target_resolution", "1920x1080")
    kernel = values.get("kernel_type", "Hermite")
    do_denoise = values.get("denoise", "false").lower() == "true"
    denoise_setting = values.get("denoise_setting", "")
    do_deband = values.get("deband", "false").lower() == "true"
    deband_setting = values.get("deband_setting", "")

    denoise_line = denoise_setting if do_denoise and denoise_setting else ""
    deband_line = deband_setting if do_deband and deband_setting else ""

    vpy_template = """
from vstools import vs, core, initialize_clip, finalize_clip
try:
    from vsdenoise import DFTTest
except Exception:
    DFTTest = None
core.max_cache_size = 1024

# Load Source
src = core.ffms2.Source(source=r"{source}", cachefile=r"{cache}")

# Initialize (Fixes Placebo bitdepth error by ensuring 16-bit)
src = initialize_clip(src)

# Optional settings.txt denoise/deband hooks
{denoise_line}
{deband_line}

# DOWNSCALE
should_downscale = {downscale}
target_res_str = "{target_res}"
user_kernel = "{kernel}"

if should_downscale:
    k_map = {{
        "hermite": "hermite",
        "bilinear": "triangle",
        "bicubic": "catmull_rom",
        "gaussian": "gaussian",
        "catmull_rom": "catmull_rom",
        "mitchell": "mitchell",
        "lanczos": "lanczos",
        "spline36": "spline36"
    }}
    pl_filter = k_map.get(user_kernel.lower(), "spline36")
    target_w = 0
    target_h = 0
    if "x" in target_res_str.lower():
        try:
            w_str, h_str = target_res_str.lower().split("x")
            target_w = int(w_str)
            target_h = int(h_str)
        except Exception:
            pass
    else:
        try:
            target_w = int(target_res_str)
        except Exception:
            pass
    if target_w > 0:
        if target_h == 0:
            target_h = int(target_w * src.height / src.width)
            if target_h % 2 != 0:
                target_h -= 1
        if target_w % 2 != 0:
            target_w -= 1
        if target_w < src.width or target_h < src.height:
            src = core.placebo.Resample(src, target_w, target_h, filter=pl_filter)

# Finalize (Sets 10-bit output)
final = finalize_clip(src)
final.set_output(0)
"""
    try:
        vpy_path.write_text(vpy_template.format(
            source=str(SAMPLE_FILE),
            cache=str(cache_path),
            denoise_line=denoise_line,
            deband_line=deband_line,
            downscale=str(do_downscale),
            target_res=target_res,
            kernel=kernel,
        ), encoding="utf-8")

        vpy_vars = {}
        exec(compile(vpy_path.read_text(encoding="utf-8"), str(vpy_path), "exec"), globals(), vpy_vars)
        clip = vpy_vars.get("final", vpy_vars.get("src"))
        if clip is None:
            raise RuntimeError("script produced no clip")
        return clip, "filtered source (settings.txt filters applied, crop off)"
    except Exception as e:
        print(f"   Warning: filtered benchmark source failed ({e}); using raw sample.", file=sys.stderr)
        return core.ffms2.Source(source=str(SAMPLE_FILE)), "raw sample (filtered script failed)"

def write_ssimu2_config(tool="vs-hip", filter_tool="vs-hip", workercount=1, variant="nvidia", streams=1):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(f"tool={tool}\n")
        f.write(f"filter-tool={filter_tool}\n")
        f.write(f"workercount={max(1, int(workercount))}\n")
        if variant:
            f.write(f"variant={variant}\n")
        if streams:
            f.write(f"streams={max(1, int(streams))}\n")

def force_remove(path: Path):
    if not path.exists():
        return
    try:
        path.unlink(missing_ok=True)
    except (PermissionError, OSError):
        try:
            trash_name = path.with_suffix(f".trash_{random.randint(1000,9999)}")
            path.rename(trash_name)
        except:
            pass

def cleanup_temp_files():
    try:
        if hasattr(vs.core, 'clear_cache'):
            vs.core.clear_cache()
    except:
        pass
    gc.collect()

    if TEMP_DIR.exists():
        try:
            shutil.rmtree(TEMP_DIR)
        except:
            subprocess.run(f'rmdir /s /q "{TEMP_DIR}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for ext in [".ffindex", ".lwi", ".json"]:
        f = SAMPLE_FILE.with_suffix(SAMPLE_FILE.suffix + ext)
        if f.exists():
            try:
                f.unlink()
            except:
                pass
    
    for f in VS_PLUGINS_DIR.glob("*.trash_*"):
        try:
            f.unlink(missing_ok=True)
        except:
            pass

def setup_svt_av1_fork(target_fork="5fish"):
    """Swaps in the standard SVT-AV1 encoder build for benchmarking."""
    print(f"Setting up SVT-AV1 fork: {target_fork}", file=sys.stderr)

    fork_parent = None
    if FORKS_DIR.exists():
        for f in FORKS_DIR.iterdir():
            if f.is_dir() and target_fork.lower() in f.name.lower():
                fork_parent = f
                break

    if fork_parent:
        target_subfolder = None
        subfolders = [d for d in fork_parent.iterdir() if d.is_dir()]

        if not target_subfolder:
            for sub in subfolders:
                if 'x86-64-v3' in sub.name.lower():
                    target_subfolder = sub
                    break

        if not target_subfolder and subfolders:
            target_subfolder = subfolders[0]

        if target_subfolder:
            exe_src = target_subfolder / "SvtAv1EncApp.exe"
            exe_dest = AV1AN_DIR / "SvtAv1EncApp.exe"

            try:
                if exe_dest.exists():
                    exe_dest.unlink()
            except Exception as e:
                print(f"   - Warning: Could not clean up old SVT-AV1 files: {e}", file=sys.stderr)

            if exe_src.exists():
                try:
                    shutil.copy2(exe_src, exe_dest)
                    print(f"   - Copied SvtAv1EncApp.exe from {target_subfolder.name}", file=sys.stderr)
                except Exception as e:
                    print(f"   - Error copying fork files: {e}", file=sys.stderr)
            else:
                print(f"   - Error: SvtAv1EncApp.exe not found in {target_subfolder}", file=sys.stderr)
    else:
        print(f"   - Warning: Could not find a fork directory matching '{target_fork}' in {FORKS_DIR}", file=sys.stderr)

def run_fast_pass():
    print("Generating benchmark assets (Fast Pass)...", file=sys.stderr)
    output_file = TEMP_DIR / "sample_fastpass.mkv"
    if not TEMP_DIR.exists():
        TEMP_DIR.mkdir(parents=True, exist_ok=True)

    vpy_content = f"""
import vapoursynth as vs
core = vs.core
src = core.ffms2.Source(source=r"{SAMPLE_FILE}")
src.set_output()
"""
    vpy_path = TEMP_DIR / "source.vpy"
    with open(vpy_path, "w", encoding="utf-8") as f:
        f.write(vpy_content)

    cmd = [
        str(AV1AN_EXE), "-i", str(vpy_path), "-e", "svt-av1",
        "-c", "mkvmerge", "-w", "2",
        "-m", "bestsource", 
        "-v", "--preset 10 --crf 35", "-o", str(output_file)
    ]

    try:
        if VERBOSE:
            print(f"[Fast Pass CMD] {' '.join(cmd)}", file=sys.stderr)
        
        print("-" * 50, file=sys.stderr)
        subprocess.run(cmd, check=True, cwd=TEMP_DIR)
        print("-" * 50, file=sys.stderr)
        return output_file
    except subprocess.CalledProcessError as e:
        print(f"Error: Fast pass generation failed. {e}", file=sys.stderr)
        return None

def calculate_optimal_count(rss_per_worker, cores_per_worker):
    """Size the vs-zip worker count from MEASURED settled CPU usage.

    One vs-zip 'worker' is one VapourSynth thread (core.num_threads), so its
    baseline demand is 1 core. Anything measured above that with a single
    worker is mostly opportunistic spillover (decode threads spreading over
    idle cores) and is only partially counted via SPILLOVER_WEIGHT."""
    total_ram = psutil.virtual_memory().total
    cpu_threads = os.cpu_count() or 1

    if rss_per_worker <= 0:
        rss_per_worker = 100 * 1024 * 1024
    safe_ram = total_ram * 0.85
    max_workers_ram = max(1, int(safe_ram / rss_per_worker))

    if cores_per_worker and cores_per_worker > 0:
        effective = 1.0 + max(0.0, cores_per_worker - 1.0) * SPILLOVER_WEIGHT
        effective = max(0.5, min(effective, float(cpu_threads)))
        max_workers_cpu = max(1, int((cpu_threads * TARGET_CPU_UTILIZATION) / effective))
    else:
        # Could not measure CPU - fall back to the old conservative cap
        max_workers_cpu = max(1, cpu_threads // 2)

    return max(1, min(max_workers_ram, max_workers_cpu, cpu_threads))


def _print_progress(percent: float, end: bool = False, elapsed: float = 0.0):
    if end:
        sys.stderr.write(f"\r      Progress: 100.0%  (Time: {elapsed:.2f}s)\n")
    else:
        sys.stderr.write(f"\r      Progress: {percent:.1f}% ")
        sys.stderr.flush()

# --- BENCHMARK FUNCTIONS ---

def benchmark_gpu_candidate(dll_name: str, encoded_file: Path, num_streams: int):
    print(f"   Benchmarking vs-hip GPU ({dll_name} | Streams: {num_streams})...", file=sys.stderr)

    bench_script = f"""
import sys
import time
import vapoursynth as vs

try:
    from vstools import core, clip_async_render
except Exception:
    sys.exit(2)

core = vs.core
SKIP = {SKIP}
DURATION = 10.0

def emit_progress(p):
    try:
        sys.stdout.write(f"PROGRESS:{{p}}\\n")
        sys.stdout.flush()
    except Exception:
        pass

try:
    src = core.ffms2.Source(source=r"{SAMPLE_FILE}").resize.Bicubic(format=vs.RGB24, matrix_in_s="709")[::SKIP]
    enc = core.ffms2.Source(source=r"{str(encoded_file)}").resize.Bicubic(format=vs.RGB24, matrix_in_s="709")[::SKIP]

    # Injected numStream
    res = core.vship.SSIMULACRA2(src, enc, numStream={num_streams})

    # Total frames of the SKIPPED clip - this is what actually gets rendered.
    total_frames = max(1, int(res.num_frames))

    start = time.time()
    last_emit = [0.0]
    last_n = [-1]
    eff_frames = [0]

    def p(n, t):
        if n is None:
            return

        if n > last_n[0]:
            delta = n - last_n[0]
            if delta < 0:
                delta = 0
            eff_frames[0] += delta * SKIP
            last_n[0] = n

        elapsed = time.time() - start

        if elapsed - last_emit[0] >= 0.15:
            last_emit[0] = elapsed
            # The run ends when EITHER the frame-skipped clip completes OR
            # DURATION elapses, whichever comes first. Progress must reflect
            # both: a fast GPU can finish the whole skipped clip in ~2s, so a
            # purely time-based percent would sit at ~20% and jump to 100%.
            done = max(0, last_n[0] + 1)
            prog_frames = (done / total_frames) * 100.0
            prog_time = (elapsed / DURATION) * 100.0
            prog = min(100.0, max(prog_frames, prog_time))
            emit_progress(prog)

        if elapsed > DURATION:
            raise KeyboardInterrupt

    try:
        clip_async_render(res, outfile=None, progress=p)
    except KeyboardInterrupt:
        pass
    except Exception:
        pass

    elapsed = time.time() - start
    if elapsed <= 0:
        sys.exit(3)

    if eff_frames[0] <= 0:
        try:
            eff_frames[0] = int(res.num_frames) * SKIP
        except Exception:
            eff_frames[0] = 0

    fps = (eff_frames[0] / elapsed) if eff_frames[0] > 0 else 0.0
    sys.stdout.write(f"FPS:{{fps}}\\n")
    sys.stdout.write(f"ELAPSED:{{elapsed}}\\n")
    sys.stdout.flush()

except Exception as e:
    sys.stderr.write(f"VSHIP_ERROR:{{e}}\\n")
    sys.exit(4)
"""

    def _reader_thread(stdout_pipe, q: queue.Queue):
        try:
            for ln in stdout_pipe:
                q.put(ln)
        except Exception:
            pass
        finally:
            q.put(None)

    fps = 0.0
    elapsed_time = 0.0
    saw_progress = False
    last_percent = 0.0
    stall_start_time = time.time()
    
    init_deadline = time.time() + 15.0 

    try:
        with subprocess.Popen(
            [sys.executable, "-c", bench_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=BASE_DIR,
            text=True,
            encoding="utf-8",
            errors="replace"
        ) as proc:
            
            if proc.stdout is None:
                sys.stderr.write("\n")
                return 0.0, 0.0

            q_lines: queue.Queue = queue.Queue()
            t = threading.Thread(target=_reader_thread, args=(proc.stdout, q_lines), daemon=True)
            t.start()
            
            # Read stderr purely for verbose logging
            def _stderr_reader():
                for err_line in proc.stderr:
                    if VERBOSE:
                        sys.stderr.write(f"[vs-hip stderr] {err_line.strip()}\n")
            
            t_err = threading.Thread(target=_stderr_reader, daemon=True)
            t_err.start()

            while True:
                now = time.time()

                if (not saw_progress) and (now > init_deadline) and (proc.poll() is None):
                    sys.stderr.write(" [Timeout: No start]\n")
                    proc.kill()
                    return 0.0, 0.0

                if saw_progress and (now - stall_start_time > STALL_TIMEOUT) and (proc.poll() is None):
                    sys.stderr.write(f" [Timeout: Stalled at {last_percent:.1f}%]\n")
                    proc.kill()
                    return 0.0, 0.0

                if proc.poll() is not None and q_lines.empty():
                    break

                try:
                    item = q_lines.get(timeout=0.1)
                except queue.Empty:
                    continue

                if item is None:
                    break

                line = item.strip()

                if line.startswith("PROGRESS:"):
                    try:
                        percent = float(line.split(":", 1)[1])
                        if abs(percent - last_percent) > 0.01:
                            stall_start_time = time.time()
                            last_percent = percent
                        
                        saw_progress = True
                        if not VERBOSE:
                            _print_progress(percent, end=False)
                    except:
                        pass
                elif line.startswith("FPS:"):
                    try:
                        fps = float(line.split(":", 1)[1])
                    except:
                        fps = 0.0
                elif line.startswith("ELAPSED:"):
                    try:
                        elapsed_time = float(line.split(":", 1)[1])
                    except:
                        elapsed_time = 0.0
                elif VERBOSE:
                    sys.stderr.write(f"[vs-hip stdout] {line}\n")

            if not VERBOSE:
                if saw_progress or last_percent > 0.0:
                    _print_progress(100.0, end=True, elapsed=elapsed_time)
                else:
                    sys.stderr.write("\n")

    except Exception:
        sys.stderr.write("\n")
        return 0.0, 0.0

    return (fps, elapsed_time) if fps > 0 else (0.0, 0.0)

def run_gpu_suite(dll_name, encoded_file, variant_name):
    src_dll = VS_HIP_SOURCE_DIR / dll_name
    dst_dll = VS_PLUGINS_DIR / dll_name

    if not src_dll.exists():
        return 0.0, 1, 0.0

    for f in VS_PLUGINS_DIR.glob("libvship*.dll"):
        force_remove(f)

    try:
        shutil.copy(src_dll, dst_dll)
    except:
        return 0.0, 1, 0.0

    results = []

    for s in range(1, 5):
        fps, elapsed_time = benchmark_gpu_candidate(dll_name, encoded_file, num_streams=s)
        
        if s == 1 and fps <= 0.0:
            print(f"   [vs-hip-{variant_name}] Stream=1 failed. Skipping remaining tests.", file=sys.stderr)
            return 0.0, 1, 0.0
        
        if fps > 0:
            results.append((fps, s, elapsed_time))

    if not results:
        return 0.0, 1, 0.0

    best = max(results, key=lambda x: x[0])
    return best[0], best[1], best[2]


def benchmark_ffvship(exe_path: Path, encoded_file: Path, gpu_threads: int, variant_name: str):
    print(f"   Benchmarking GPU (FFVship {variant_name.capitalize()} | Streams: {gpu_threads})...", file=sys.stderr)
    
    json_path = TEMP_DIR / f"ffvship_{gpu_threads}.json"
    
    cmd = [
        str(exe_path),
        "--source", str(SAMPLE_FILE),
        "--encoded", str(encoded_file),
        "-t", "3",
        "-g", str(gpu_threads),
        "--json", str(json_path)
    ]
    
    if VERBOSE:
        print(f"   [FFVship CMD] {' '.join(cmd)}", file=sys.stderr)
    
    fps = 0.0
    start_time = time.time()
    try:
        proc = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True, 
            errors="replace",
            cwd=str(exe_path.parent)
        )
        for line in proc.stdout:
            if VERBOSE:
                print(f"   [FFVship OUT] {line.strip()}", file=sys.stderr)
            match = re.search(r"at\s+([0-9.]+)\s+fps", line, re.IGNORECASE)
            if match:
                fps = float(match.group(1))
        
        proc.wait(timeout=60)
        elapsed_time = time.time() - start_time
        
        if not VERBOSE:
            print(f"      Done. (Time: {elapsed_time:.2f}s)", file=sys.stderr)

        # Parse the JSON file directly 
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if VERBOSE:
                        print(f"   [FFVship JSON] {data}", file=sys.stderr)
                        
                    if "fps" in data:
                        fps = float(data["fps"])
                    elif "speed" in data:
                        fps = float(data["speed"])
            except Exception as e:
                if VERBOSE:
                    print(f"   [FFVship JSON Error] {e}", file=sys.stderr)

    except Exception as e:
        elapsed_time = time.time() - start_time
        print(f"   [FFVship Error] {e}", file=sys.stderr)
        
    return fps, elapsed_time

def run_ffvship_suite(exe_path: Path, variant_name: str, encoded_file: Path):
    if not exe_path.exists():
        return 0.0, 1, 0.0

    results = []
    for s in range(1, 5):
        fps, elapsed_time = benchmark_ffvship(exe_path, encoded_file, s, variant_name)
        
        if s == 1 and fps <= 0.0:
            print(f"   [FFVship-{variant_name}] Stream=1 failed. Skipping remaining tests.", file=sys.stderr)
            return 0.0, 1, 0.0
            
        if fps > 0:
            results.append((fps, s, elapsed_time))
            
    if not results:
        return 0.0, 1, 0.0
        
    best = max(results, key=lambda x: x[0])
    return best[0], best[1], best[2]


def benchmark_cpu_vszip(encoded_file, use_filters=False):
    """Benchmark vs-zip CPU workers.

    use_filters=False (regular mode): settings.txt is NOT read and NO filters
    are applied - the raw sample is used directly for the general worker test.
    use_filters=True (optimize mode): the source is built through the user's
    real settings.txt filtering chain."""
    print("   Benchmarking CPU (vs-zip - Single Worker probe)...", file=sys.stderr)
    if use_filters:
        source_clip, source_desc = build_benchmark_source_clip()
    else:
        source_clip = core.ffms2.Source(source=str(SAMPLE_FILE))
        source_desc = "raw sample (regular mode: settings.txt not read, no filters)"
    print(f"   vs-zip benchmark source: {source_desc}", file=sys.stderr)

    fps_1, rss, elapsed_1, cores_1 = _run_vszip_internal(
        1, encoded_file, duration=VSZIP_PROBE_DURATION, source_clip=source_clip)

    if fps_1 <= 0:
        return 0, 1, 0.0

    cpu_threads = os.cpu_count() or 1
    opt_workers = calculate_optimal_count(rss, cores_1)

    if cores_1 > 0:
        print(f"   Measured settled usage (1 worker): {cores_1:.2f} cores "
              f"({100.0 * cores_1 / cpu_threads:.0f}% of CPU)", file=sys.stderr)
        print(f"   Targeting {int(TARGET_CPU_UTILIZATION * 100)}% of {cpu_threads} threads "
              f"-> {opt_workers} workers (spillover weight {SPILLOVER_WEIGHT})", file=sys.stderr)
    else:
        print(f"   Warning: Could not measure per-worker CPU. Falling back to "
              f"{opt_workers} workers (threads/2 cap).", file=sys.stderr)

    print(f"   Benchmarking CPU (vs-zip - {opt_workers} Workers)...", file=sys.stderr)
    fps_opt, _, elapsed_opt, cores_total = _run_vszip_internal(
        opt_workers, encoded_file, duration=10, source_clip=source_clip)

    # Confirmation pass: if the chosen count oversaturates the CPU, scale it
    # back proportionally toward the target load.
    if cores_total > cpu_threads * 0.97 and opt_workers > 1:
        scaled = max(1, int(opt_workers * (cpu_threads * TARGET_CPU_UTILIZATION) / cores_total))
        if scaled < opt_workers:
            print(f"   Confirmation run oversaturated the CPU ({cores_total:.1f}/{cpu_threads} cores). "
                  f"Scaling workers {opt_workers} -> {scaled}.", file=sys.stderr)
            opt_workers = scaled
    elif cores_total > 0:
        print(f"   Confirmation run settled at {cores_total:.1f}/{cpu_threads} cores "
              f"({100.0 * cores_total / cpu_threads:.0f}% of CPU).", file=sys.stderr)

    return fps_opt, opt_workers, elapsed_opt

def _run_vszip_internal(workers, encoded_file, duration, source_clip=None):
    if not hasattr(core, 'vszip'):
        return 0, 0, 0.0, 0.0

    core.num_threads = workers

    if source_clip is None:
        source_clip = core.ffms2.Source(source=str(SAMPLE_FILE))
    src = source_clip.resize.Bicubic(format=vs.RGB24, matrix_in_s="709")[::SKIP]
    enc = core.ffms2.Source(source=str(encoded_file)).resize.Bicubic(format=vs.RGB24, matrix_in_s="709")[::SKIP]

    try:
        res = core.vszip.SSIMULACRA2(src, enc)
    except:
        return 0, 0, 0.0, 0.0

    # Total frames of the SKIPPED clip - the run ends when either this many
    # frames are rendered or `duration` elapses, whichever comes first.
    total_frames = max(1, int(res.num_frames))

    # Sample this process's CPU usage while rendering. The first
    # CPU_WARMUP_SECONDS are excluded so vs-zip/ffms2 spin-up (graph build,
    # indexing, lookahead) is not counted as sustained per-worker cost.
    cpu_sampler = _CpuSampler(warmup=CPU_WARMUP_SECONDS)
    cpu_sampler.start()

    start = time.time()
    max_rss = [0]
    frames_sampled_done = [0]
    last_n = [-1]

    stall_data = {
        'last_update': time.time(),
        'last_count': 0
    }

    def p(n, t):
        if n is None:
            return

        if n > last_n[0]:
            delta = n - last_n[0]
            if delta < 0:
                delta = 0
            frames_sampled_done[0] += delta
            last_n[0] = n

            stall_data['last_update'] = time.time()
            stall_data['last_count'] = frames_sampled_done[0]

        elapsed = time.time() - start

        if (time.time() - stall_data['last_update']) > STALL_TIMEOUT:
            raise RuntimeError("Stalled")

        # Progress is the max of frame-based and time-based completion, since
        # the run ends when either the skipped clip finishes or `duration`
        # elapses. Prevents the ~20% -> 100% jump when rendering outpaces
        # the timer.
        prog_frames = (frames_sampled_done[0] / total_frames) * 100.0
        prog_time = (elapsed / duration) * 100.0
        prog = min(100.0, max(prog_frames, prog_time))

        if not VERBOSE:
            _print_progress(prog, end=False)

        if n % 10 == 0:
            try:
                max_rss[0] = max(max_rss[0], psutil.Process(os.getpid()).memory_info().rss)
            except:
                pass

        if elapsed > duration:
            raise KeyboardInterrupt

    try:
        clip_async_render(res, outfile=None, progress=p)
    except RuntimeError as re_err:
        if "Stalled" in str(re_err):
            cpu_sampler.stop()
            sys.stderr.write("\n[Timeout] vs-zip stalled.\n")
            return 0, 0, 0.0, 0.0
    except:
        pass

    settled_cores = cpu_sampler.stop()
    elapsed = time.time() - start

    if not VERBOSE:
        _print_progress(100.0, end=True, elapsed=elapsed)

    effective_frames = frames_sampled_done[0] * SKIP
    fps = (effective_frames / elapsed) if elapsed > 0 else 0

    del res, src, enc
    return fps, max_rss[0], elapsed, settled_cores

def update_auto_boost_script(winning_streams):
    """
    Updates the numStream parameter in Auto-Boost-Av1an.py.
    Target: result = core.vship.SSIMULACRA2(..., numStream = X)
    """
    if not AUTO_BOOST_SCRIPT.exists():
        print(f"Warning: {AUTO_BOOST_SCRIPT} not found. Skipping edit.", file=sys.stderr)
        return

    try:
        content = AUTO_BOOST_SCRIPT.read_text(encoding="utf-8")
        
        # Regex to find SSIMULACRA2 call and replace numStream value
        pattern = r"(result\s*=\s*core\.vship\.SSIMULACRA2\(.*numStream\s*=\s*)(\d+)(.*\))"
        
        if not re.search(pattern, content):
            return

        new_content = re.sub(
            pattern,
            f"\\g<1>{winning_streams}\\g<3>",
            content
        )
        
        if new_content != content:
            AUTO_BOOST_SCRIPT.write_text(new_content, encoding="utf-8")
            print(f"   [Auto-Config] Updated Auto-Boost-Av1an.py to numStream={winning_streams}", file=sys.stderr)
            
    except Exception as e:
        print(f"Error editing Auto-Boost-Av1an.py: {e}", file=sys.stderr)

# --- MAIN ---

def run_full_suite(target_fork="5fish", use_filters=False):
    """Run the full GPU + CPU benchmark suite and write workercount-ssimu2.txt.

    In regular mode (use_filters=False, the default), settings.txt is never
    read and no filters are applied to the general vs-zip worker test.
    Optimize mode passes use_filters=True to benchmark through the user's
    real filtering chain.

    Returns the measured vs-zip CPU worker count, or None if vs-zip failed."""
    vszip_workers = None
    try:
        cleanup_temp_files()

        # Setup specific SVT-AV1 fork with AVX-512 detection before pass
        setup_svt_av1_fork(target_fork=target_fork)

        encoded_file = run_fast_pass()
        if not encoded_file:
            raise RuntimeError("Fast pass failed")

        results = []

        # 1. Test vs-hip NVIDIA
        fps_vsnv, s_vsnv, time_vsnv = run_gpu_suite("libvship_NVIDIA.dll", encoded_file, "nvidia")
        if fps_vsnv > 0:
            print(f"   [vs-hip-nvidia] FPS: {fps_vsnv:.2f} | Streams: {s_vsnv} | Time: {time_vsnv:.2f}s", file=sys.stderr)
            results.append({"tool": "vs-hip", "variant": "nvidia", "fps": fps_vsnv, "workers": 1, "streams": s_vsnv, "time": time_vsnv})
        else:
            print("   [vs-hip-nvidia] Not compatible or failed.", file=sys.stderr)

        # 2. Test vs-hip VULKAN
        fps_vsvk, s_vsvk, time_vsvk = run_gpu_suite("libvship_VULKAN.dll", encoded_file, "vulkan")
        if fps_vsvk > 0:
            print(f"   [vs-hip-vulkan] FPS: {fps_vsvk:.2f} | Streams: {s_vsvk} | Time: {time_vsvk:.2f}s", file=sys.stderr)
            results.append({"tool": "vs-hip", "variant": "vulkan", "fps": fps_vsvk, "workers": 1, "streams": s_vsvk, "time": time_vsvk})
        else:
            print("   [vs-hip-vulkan] Not compatible or failed.", file=sys.stderr)

        # Remove DLLs to keep environment clean
        for f in VS_PLUGINS_DIR.glob("libvship*.dll"):
            force_remove(f)

        # 3. Test FFVship NVIDIA
        fps_ffnv, s_ffnv, time_ffnv = run_ffvship_suite(FFVSHIP_NVIDIA_EXE, "nvidia", encoded_file)
        if fps_ffnv > 0:
            print(f"   [FFVship-nvidia] FPS: {fps_ffnv:.2f} | Streams: {s_ffnv} | Time: {time_ffnv:.2f}s", file=sys.stderr)
            results.append({"tool": "ffvship_nvidia", "variant": "nvidia", "fps": fps_ffnv, "workers": s_ffnv, "streams": s_ffnv, "time": time_ffnv})

        # 4. Test FFVship VULKAN
        fps_ffvk, s_ffvk, time_ffvk = run_ffvship_suite(FFVSHIP_VULKAN_EXE, "vulkan", encoded_file)
        if fps_ffvk > 0:
            print(f"   [FFVship-vulkan] FPS: {fps_ffvk:.2f} | Streams: {s_ffvk} | Time: {time_ffvk:.2f}s", file=sys.stderr)
            results.append({"tool": "ffvship_vulkan", "variant": "vulkan", "fps": fps_ffvk, "workers": s_ffvk, "streams": s_ffvk, "time": time_ffvk})

        # 5. Test vs-zip
        fps_zip, w_zip, time_zip = benchmark_cpu_vszip(encoded_file, use_filters=use_filters)
        if fps_zip > 0:
            print(f"   [vs-zip]        FPS: {fps_zip:.2f} | Workers: {w_zip} | Time: {time_zip:.2f}s", file=sys.stderr)
            results.append({"tool": "vs-zip", "variant": "cpu", "fps": fps_zip, "workers": w_zip, "streams": 0, "time": time_zip})
            vszip_workers = w_zip

        # Regular mode never reads settings.txt; only optimize mode consults it.
        filters_enabled = settings_filters_enabled() if use_filters else False

        if not results:
            print("All benchmarks failed. Defaulting to vs-hip config so filtered runs do not select FFVship.", file=sys.stderr)
            write_ssimu2_config(tool="vs-hip", filter_tool="vs-hip", workercount=1, variant="nvidia", streams=1)
            return None

        winner = max(results, key=lambda x: x['fps'])
        variant_str = winner.get('variant', '')
        stream_str = f"| Streams: {winner['streams']}" if winner['streams'] > 0 else ""
        print(f"\nWinner: {winner['tool']} ({variant_str}) | FPS: {winner['fps']:.2f} | Time: {winner['time']:.2f}s {stream_str}", file=sys.stderr)

        # Determine best filter tool (must be vs-hip or vs-zip when filtering is enabled).
        filter_candidates = [r for r in results if r['tool'] in ['vs-hip', 'vs-zip']]
        vs_hip_candidates = [r for r in filter_candidates if r['tool'] == 'vs-hip']
        if filters_enabled and vs_hip_candidates:
            # Prefer vs-hip for any filtering in settings.txt, even if vs-zip benchmarks faster.
            filter_winner = max(vs_hip_candidates, key=lambda x: x['fps'])
        elif filter_candidates:
            filter_winner = max(filter_candidates, key=lambda x: x['fps'])
        else:
            filter_winner = {'tool': 'vs-hip', 'variant': 'nvidia', 'streams': 1}
        filter_tool = filter_winner['tool']

        # POST-WINNER SETUP
        if winner['tool'] == "vs-hip":
            dll_name = f"libvship_{winner['variant'].upper()}.dll"
            src = VS_HIP_SOURCE_DIR / dll_name
            dst = VS_PLUGINS_DIR / dll_name
            if src.exists():
                shutil.copy(src, dst)
            
            update_auto_boost_script(winner['streams'])
        else:
            for f in VS_PLUGINS_DIR.glob("libvship*.dll"):
                force_remove(f)

        # WRITE CONFIG
        config_variant = winner.get('variant', 'nvidia')
        config_streams = winner.get('streams', winner.get('workers', 1))
        if winner['tool'] == 'vs-hip':
            config_streams = winner.get('streams', 1)
        write_ssimu2_config(
            tool=winner['tool'],
            filter_tool=filter_tool,
            workercount=winner['workers'],
            variant=config_variant,
            streams=config_streams,
        )
        if filters_enabled and filter_tool not in ('vs-hip', 'vs-zip'):
            print("   [Config] Filtering is enabled; forced filter-tool to vs-hip/vs-zip.", file=sys.stderr)

        return vszip_workers

    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        write_ssimu2_config(tool="vs-hip", filter_tool="vs-hip", workercount=1, variant="nvidia", streams=1)
        return None
    finally:
        cleanup_temp_files()


def run_optimize_mode(bat_arg=None):
    """One-time optimized vs-zip benchmark driven by a generated .bat with
    optimize-workers=true. Writes custom-ssim2-workers back into the .bat.

    - If workercount-ssimu2.txt does not exist yet, the FULL suite runs once
      (tool selection + vs-zip) and the vs-zip result is stored in the .bat.
    - If it exists but custom-ssim2-workers is empty, only the vs-zip portion
      is re-benchmarked (fast pass + measurement) with the user's filtering.
    - If custom-ssim2-workers already has a value, this returns immediately."""
    bat_path = None
    if bat_arg and Path(bat_arg).is_file():
        bat_path = Path(bat_arg).resolve()
    else:
        bat_path = find_active_bat_file()

    if not bat_path:
        print("[Optimize] Could not locate the launching .bat file. Skipping optimized benchmark.", file=sys.stderr)
        return

    bat = parse_bat_settings(bat_path)

    if bat.get("optimize-workers", "").strip().lower() not in ("true", "1", "yes", "on"):
        # This bat did not opt in - nothing to do.
        return

    existing = bat.get("custom-ssim2-workers", "").strip()
    if existing.isdigit() and int(existing) > 0:
        print(f"[Optimize] custom-ssim2-workers already set to {existing} in "
              f"{bat_path.name}. Skipping benchmark.", file=sys.stderr)
        return

    fork = (bat.get("fork", "5fish") or "5fish").strip()

    print("\n-------------------------------------------------------------------------------", file=sys.stderr)
    print(f"[Optimize] One-time optimized SSIMU2 (vs-zip) benchmark for: {bat_path.name}", file=sys.stderr)
    print("-------------------------------------------------------------------------------", file=sys.stderr)

    if CONFIG_FILE.exists():
        # Tool selection is already benchmarked - only measure vs-zip CPU
        # workers, through the user's real filtering chain.
        vszip_workers = None
        try:
            cleanup_temp_files()
            setup_svt_av1_fork(target_fork=fork)
            encoded_file = run_fast_pass()
            if encoded_file:
                fps_zip, w_zip, _ = benchmark_cpu_vszip(encoded_file, use_filters=True)
                if fps_zip > 0:
                    vszip_workers = w_zip
        except Exception as e:
            print(f"[Optimize] vs-zip benchmark error: {e}", file=sys.stderr)
        finally:
            cleanup_temp_files()
    else:
        # First run: the full suite handles tool selection AND the improved
        # vs-zip measurement in one pass.
        vszip_workers = run_full_suite(target_fork=fork, use_filters=True)

    if vszip_workers:
        if set_bat_value_fixed_width(bat_path, "custom-ssim2-workers", vszip_workers):
            print(f"[Optimize] Wrote custom-ssim2-workers={vszip_workers} into {bat_path.name}", file=sys.stderr)
            print("[Optimize] Clear that value in the .bat to re-run this benchmark.", file=sys.stderr)
    else:
        print("[Optimize] vs-zip benchmark failed; leaving custom-ssim2-workers empty.", file=sys.stderr)


def _parse_cli(argv):
    optimize = False
    bat_arg = None
    i = 0
    while i < len(argv):
        if argv[i] == "--optimize-bat":
            optimize = True
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                bat_arg = argv[i + 1]
                i += 2
            else:
                i += 1
        else:
            i += 1
    return optimize, bat_arg


if __name__ == "__main__":
    optimize, bat_arg = _parse_cli(sys.argv[1:])
    if optimize:
        run_optimize_mode(bat_arg)
    else:
        run_full_suite()