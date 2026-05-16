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
from pathlib import Path
import vapoursynth as vs

# --- CONFIGURATION ---
VERBOSE = False  # Set to True to see all raw output for troubleshooting

BASE_DIR = Path(__file__).parent.parent.resolve()
TOOLS_DIR = BASE_DIR / "tools"
AV1AN_EXE = TOOLS_DIR / "av1an" / "av1an.exe"
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

# GPU / Plugin Paths
VS_PLUGINS_DIR = BASE_DIR / "VapourSynth" / "vs-plugins"
VS_HIP_SOURCE_DIR = TOOLS_DIR / "vs-hip"

try:
    from vstools import core, clip_async_render
except ImportError:
    print("Error: vstools not found.", file=sys.stderr)
    sys.exit(1)

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

def calculate_optimal_count(fps, rss_per_worker):
    if fps <= 0:
        return 1
    total_ram = psutil.virtual_memory().total
    cpu_threads = os.cpu_count() or 1
    safe_ram = total_ram * 0.85
    if rss_per_worker <= 0:
        rss_per_worker = 100 * 1024 * 1024
    max_workers_ram = int(safe_ram / rss_per_worker)
    max_workers = min(max_workers_ram, cpu_threads)
    return max(1, max_workers)

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
            prog = min(100.0, (elapsed / DURATION) * 100.0)
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


def benchmark_cpu_vszip(encoded_file):
    print("   Benchmarking CPU (vs-zip - Single Worker)...", file=sys.stderr)
    fps_1, rss, elapsed_1 = _run_vszip_internal(1, encoded_file, duration=5)
    
    if fps_1 <= 0:
        return 0, 1, 0.0

    opt_workers = calculate_optimal_count(fps_1, rss)

    if opt_workers > 1:
        print("   populating 90% of system ram with multiple workers", file=sys.stderr)

    print(f"   Benchmarking CPU (vs-zip - {opt_workers} Workers)...", file=sys.stderr)
    fps_opt, _, elapsed_opt = _run_vszip_internal(opt_workers, encoded_file, duration=10)

    return fps_opt, opt_workers, elapsed_opt

def _run_vszip_internal(workers, encoded_file, duration):
    if not hasattr(core, 'vszip'):
        return 0, 0, 0.0

    core.num_threads = workers

    src = core.ffms2.Source(source=str(SAMPLE_FILE)).resize.Bicubic(format=vs.RGB24, matrix_in_s="709")[::SKIP]
    enc = core.ffms2.Source(source=str(encoded_file)).resize.Bicubic(format=vs.RGB24, matrix_in_s="709")[::SKIP]

    try:
        res = core.vszip.SSIMULACRA2(src, enc)
    except:
        return 0, 0, 0.0

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

        prog = min(100.0, (elapsed / duration) * 100.0)
        
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
            sys.stderr.write("\n[Timeout] vs-zip stalled.\n")
            return 0, 0, 0.0
    except:
        pass

    elapsed = time.time() - start
    
    if not VERBOSE:
        _print_progress(100.0, end=True, elapsed=elapsed)

    effective_frames = frames_sampled_done[0] * SKIP
    fps = (effective_frames / elapsed) if elapsed > 0 else 0

    del res, src, enc
    return fps, max_rss[0], elapsed

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

if __name__ == "__main__":
    try:
        cleanup_temp_files()
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
        fps_zip, w_zip, time_zip = benchmark_cpu_vszip(encoded_file)
        if fps_zip > 0:
            print(f"   [vs-zip]        FPS: {fps_zip:.2f} | Workers: {w_zip} | Time: {time_zip:.2f}s", file=sys.stderr)
            results.append({"tool": "vs-zip", "variant": "cpu", "fps": fps_zip, "workers": w_zip, "streams": 0, "time": time_zip})

        if not results:
            print("All benchmarks failed. Defaulting to ffvship_nvidia.", file=sys.stderr)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                f.write("tool=ffvship_nvidia\ndownscale-tool=vs-zip\nworkercount=3\n")
            sys.exit(0)

        winner = max(results, key=lambda x: x['fps'])
        variant_str = winner.get('variant', '')
        stream_str = f"| Streams: {winner['streams']}" if winner['streams'] > 0 else ""
        print(f"\nWinner: {winner['tool']} ({variant_str}) | FPS: {winner['fps']:.2f} | Time: {winner['time']:.2f}s {stream_str}", file=sys.stderr)

        # Determine best downscale tool (vs-hip or vs-zip)
        downscale_candidates = [r for r in results if r['tool'] in ['vs-hip', 'vs-zip']]
        if downscale_candidates:
            ds_winner = max(downscale_candidates, key=lambda x: x['fps'])
            ds_tool = ds_winner['tool']
        else:
            ds_tool = 'vs-zip'

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
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(f"tool={winner['tool']}\n")
            f.write(f"downscale-tool={ds_tool}\n")
            f.write(f"workercount={winner['workers']}\n")

    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write("tool=ffvship_nvidia\ndownscale-tool=vs-zip\nworkercount=3\n")
    finally:
        cleanup_temp_files()