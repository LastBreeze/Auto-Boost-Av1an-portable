import os
import re
import sys
import glob
import psutil
import subprocess
import time
import math
import shutil
import statistics

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
AV1AN_PATH = "av1an"
SAMPLE_FILE = os.path.join(TOOLS_DIR, "sample.mkv")
CONFIG_FILE = os.path.join(TOOLS_DIR, "workercount-config.txt")
BENCH_TEMP_DIR = os.path.join(TOOLS_DIR, "workercount_bench_temp")
TEST_OUTPUT_FILE = os.path.join(BASE_DIR, "workercount-test-output.mkv")

# Encoder params used for the DEFAULT (non-optimized) test
ENCODER_PARAMS = " --preset 4 --crf 30 --lp 3"

# --- TUNING ---
TARGET_CPU_UTILIZATION = 0.90  # Aim for ~90% CPU load during real encodes
RAM_HEADROOM = 0.90            # Never plan to use more than 90% of total RAM
SAMPLE_INTERVAL = 0.5          # Seconds between measurements
MAX_TEST_SECONDS = 900         # Hard safety timeout (15 min) - test normally
                               # runs to completion on its own
IDLE_CORES = 0.4               # Below this many cores of usage = idle gap
                               # between chunks, not counted

# Spin-up exclusion:
# SVT-AV1 maxes out the CPU for the first several seconds of EVERY chunk
# while it scans ahead / fills its lookahead buffer. Those bursts must not
# be counted as the worker's sustained cost.
GLOBAL_SPINUP_SECONDS = 12     # Ignore this long after encoding first begins
CHUNK_SPINUP_SECONDS = 8       # Ignore this long after each new chunk starts

# Spillover discount:
# A single worker alone on an idle machine opportunistically spreads onto
# idle cores, so its measured usage OVERSTATES what it needs when several
# workers compete. We count the encoder's --lp cores as its true demand,
# and only a fraction of anything measured above that.
SPILLOVER_WEIGHT = 0.5         # 0.0 = trust --lp fully (most workers)
                               # 1.0 = trust raw measurement fully (fewest workers)

FILTER_SETTING_KEYS = ("downscale", "denoise", "deband")

# Regex for `set "key=value"` (or bare key=value) lines inside a .bat file
BAT_SET_RE = re.compile(r'^set\s+"?([^=\s"]+)\s*=(.*?)"?\s*$', re.IGNORECASE)


# ---------------------------------------------------------------------------
# .bat FILE HELPERS (optimize-workers support)
# ---------------------------------------------------------------------------

def find_active_bat_file():
    """Locate the .bat that launched this run via the tools/bat-used-*.txt marker."""
    markers = glob.glob(os.path.join(TOOLS_DIR, "bat-used-*.txt"))
    markers.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for marker in markers:
        name = os.path.basename(marker)
        if not (name.startswith("bat-used-") and name.endswith(".txt")):
            continue
        bat_name = name[len("bat-used-"):-len(".txt")]
        bat_path = os.path.join(BASE_DIR, bat_name)
        if os.path.isfile(bat_path):
            return bat_path
    return None


def parse_bat_settings(bat_path):
    """Parse `set "key=value"` (and bare key=value) lines from a .bat into a dict."""
    settings = {}
    try:
        with open(bat_path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f.read().splitlines():
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
    writes these values with padding spaces so the number fits in-place.
    """
    value = str(value)
    key_l = key.lower()
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
            actual_key = m.group(1)
            prefix = f'set "{actual_key}='
            width = len(stripped) - len(prefix) - 1  # minus closing quote
            suffix = '"'
        elif "=" in stripped and stripped.split("=", 1)[0].strip().lower() == key_l and " " not in stripped.split("=", 1)[0]:
            actual_key = stripped.split("=", 1)[0]
            prefix = f"{actual_key}="
            width = len(stripped) - len(prefix)
            suffix = ""
        else:
            continue

        if len(value) <= width:
            padded = value + " " * (width - len(value))
        else:
            # Value doesn't fit in the reserved space. Writing anyway would
            # shift byte offsets in a running .bat, so warn loudly.
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

    print(f"[Optimize] Warning: {key} line not found in {os.path.basename(bat_path)}.", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# settings.txt HELPERS (filtering awareness)
# ---------------------------------------------------------------------------

def read_settings_values():
    settings_paths = [os.path.join(BASE_DIR, "settings.txt"), os.path.join(TOOLS_DIR, "settings.txt")]
    values = {}
    for settings_path in settings_paths:
        if not os.path.exists(settings_path):
            continue
        try:
            with open(settings_path, "r", encoding="utf-8", errors="replace") as f:
                for raw_line in f.read().splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith(("#", ";", "[")) or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    values[key.strip().lower()] = value.strip()
        except Exception:
            pass
    return values


def settings_filters_enabled(values=None):
    if values is None:
        values = read_settings_values()
    return any(values.get(key, "false").lower() == "true" for key in FILTER_SETTING_KEYS)


def build_filtered_vpy(values):
    """Build a temporary VapourSynth script mirroring the real dispatch/Auto-Boost
    pipeline (initialize_clip -> denoise/deband -> downscale -> finalize_clip) so
    the benchmark includes the CPU cost of the user's filtering. Crop is left off
    for the benchmark; that only makes the result slightly conservative."""
    os.makedirs(BENCH_TEMP_DIR, exist_ok=True)
    vpy_path = os.path.join(BENCH_TEMP_DIR, "bench_source.vpy")
    cache_path = os.path.join(BENCH_TEMP_DIR, "bench_source.ffindex")

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
    with open(vpy_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(vpy_template.format(
            source=SAMPLE_FILE,
            cache=cache_path,
            denoise_line=denoise_line,
            deband_line=deband_line,
            downscale=str(do_downscale),
            target_res=target_res,
            kernel=kernel,
        ))
    return vpy_path


# ---------------------------------------------------------------------------
# CLEANUP
# ---------------------------------------------------------------------------

def cleanup_temp_folders():
    """Deletes temp folders and the test output files with retry logic."""
    print("Cleaning up temporary test files...", file=sys.stderr)

    # Wait 2 seconds to let Windows release file locks
    time.sleep(2)

    # 1. Clean up folders starting with a period
    try:
        for item in os.listdir(BASE_DIR):
            item_path = os.path.join(BASE_DIR, item)
            if os.path.isdir(item_path) and item.startswith("."):
                deleted = False
                for attempt in range(3):
                    try:
                        shutil.rmtree(item_path)
                        print(f"   - Deleted: {item}", file=sys.stderr)
                        deleted = True
                        break
                    except OSError:
                        time.sleep(1)

                if not deleted:
                    print(f"   - Warning: Could not fully delete {item} (File in use).", file=sys.stderr)
    except Exception as e:
        print(f"Error during folder cleanup: {e}", file=sys.stderr)

    # 2. Clean up the test output video files
    for output_file in (TEST_OUTPUT_FILE, os.path.join(BASE_DIR, "sample_svt-av1.mkv")):
        if os.path.exists(output_file):
            deleted = False
            for attempt in range(3):
                try:
                    os.remove(output_file)
                    print(f"   - Deleted: {os.path.basename(output_file)}", file=sys.stderr)
                    deleted = True
                    break
                except OSError:
                    time.sleep(1)

            if not deleted:
                print(f"   - Warning: Could not delete {os.path.basename(output_file)} (File in use).", file=sys.stderr)

    # 3. Clean up the temporary benchmark VapourSynth script folder
    if os.path.isdir(BENCH_TEMP_DIR):
        try:
            shutil.rmtree(BENCH_TEMP_DIR)
            print("   - Deleted: workercount_bench_temp", file=sys.stderr)
        except OSError:
            print("   - Warning: Could not delete workercount_bench_temp (File in use).", file=sys.stderr)


def kill_process_tree(pid):
    """Kills a process and all of its children. Only used if the safety
    timeout is hit - normally the test runs to completion."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    for child in parent.children(recursive=True):
        try:
            child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        parent.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def parse_lp(params):
    """Reads the --lp value out of the encoder param string. Defaults to 3."""
    m = re.search(r"--lp\s+(\d+)", params)
    return int(m.group(1)) if m else 3


def looks_like_encoder(name):
    name = (name or "").lower()
    return "svt" in name or "av1" in name


# ---------------------------------------------------------------------------
# CORE BENCHMARK
# ---------------------------------------------------------------------------

def get_optimal_workers(input_path=SAMPLE_FILE, encoder_params=ENCODER_PARAMS):
    print(f"Running one-time RAM + CPU test on {os.path.basename(input_path)}...", file=sys.stderr)
    print(f"Encoder params: {encoder_params.strip()}", file=sys.stderr)
    print("The full sample clip will be encoded with 1 worker - this may take a few minutes.", file=sys.stderr)

    cmd = [
        AV1AN_PATH,
        "-i", input_path,
        "-y",
        "--workers", "1",
        "--verbose",
        "-e", "svt-av1",
        "-m", "bestsource",
        "--cache-mode", "temp",
        "-o", TEST_OUTPUT_FILE,
        "-v", " " + encoder_params.strip(),
    ]

    try:
        process = subprocess.Popen(cmd, cwd=BASE_DIR)
    except FileNotFoundError:
        print("Error: av1an executable not found.", file=sys.stderr)
        return 1

    max_total_rss = 0
    tracked = {}                 # pid -> psutil.Process (kept alive so cpu_percent intervals work)
    seen_encoder_pids = set()    # encoder pids we've seen (new pid = new chunk)
    encode_start = None          # timestamp when the first encoder appeared
    exclude_until = None         # samples before this timestamp are spin-up
    settled_samples = []         # (cores_used) during settled encoding only
    all_encode_samples = []      # every non-idle sample after encode start (for diagnostics)
    timed_out = False
    start_time = time.time()

    try:
        while True:
            if process.poll() is not None:
                break
            now = time.time()
            if now - start_time > MAX_TEST_SECONDS:
                timed_out = True
                break

            try:
                parent = psutil.Process(process.pid)
                current_procs = {parent.pid: parent}
                for child in parent.children(recursive=True):
                    current_procs[child.pid] = child
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break

            current_rss = 0
            total_cpu_pct = 0.0
            new_encoder_started = False

            for pid, proc in list(current_procs.items()):
                try:
                    if pid not in tracked:
                        proc.cpu_percent(None)  # prime counter; first reading not counted
                        tracked[pid] = proc
                        if looks_like_encoder(proc.name()) and pid not in seen_encoder_pids:
                            seen_encoder_pids.add(pid)
                            new_encoder_started = True
                    else:
                        total_cpu_pct += tracked[pid].cpu_percent(None)
                    current_rss += tracked[pid].memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    tracked.pop(pid, None)

            # Forget pids that no longer exist
            for pid in list(tracked.keys()):
                if pid not in current_procs:
                    tracked.pop(pid, None)

            if current_rss > max_total_rss:
                max_total_rss = current_rss

            cores_used = total_cpu_pct / 100.0

            # Track when encoding actually begins (first encoder process),
            # and open a spin-up exclusion window at the start of EVERY chunk.
            if new_encoder_started:
                if encode_start is None:
                    encode_start = now
                    exclude_until = now + GLOBAL_SPINUP_SECONDS
                else:
                    exclude_until = max(exclude_until or 0, now + CHUNK_SPINUP_SECONDS)

            if encode_start is not None and cores_used >= IDLE_CORES:
                all_encode_samples.append(cores_used)
                if exclude_until is None or now >= exclude_until:
                    settled_samples.append(cores_used)

            time.sleep(SAMPLE_INTERVAL)
    finally:
        if process.poll() is None:
            kill_process_tree(process.pid)

    test_duration = time.time() - start_time
    if timed_out:
        print(f"\nWarning: Test hit the {MAX_TEST_SECONDS}s safety timeout. "
              f"Consider using a shorter sample clip.", file=sys.stderr)

    # --- Calculations ---
    if max_total_rss == 0:
        print("\nWarning: Could not measure RAM. Defaulting to 1 worker.")
        cleanup_temp_folders()
        return 1

    total_ram = psutil.virtual_memory().total
    cpu_threads = os.cpu_count() or 1
    lp = parse_lp(encoder_params)

    # RAM limit: leave headroom
    safe_ram_limit = total_ram * RAM_HEADROOM
    max_workers_ram = max(1, int(safe_ram_limit / max_total_rss))

    # CPU limit: based on the SETTLED usage of one worker, with spin-up
    # bursts excluded and idle gaps between chunks excluded.
    if settled_samples:
        measured_cores = statistics.median(settled_samples)
        sample_note = (f"{len(settled_samples)} settled samples "
                       f"({len(all_encode_samples)} total, spin-up excluded)")
    elif all_encode_samples:
        # Clip too short to ever settle - fall back to the median of
        # everything, which will be conservative (includes bursts).
        measured_cores = statistics.median(all_encode_samples)
        sample_note = (f"WARNING: clip too short to settle, used all "
                       f"{len(all_encode_samples)} samples (result is conservative - "
                       f"use a longer sample.mkv)")
    else:
        measured_cores = None
        sample_note = "WARNING: no CPU samples captured, used --lp heuristic"

    if measured_cores is not None:
        measured_cores = max(0.5, min(measured_cores, float(cpu_threads)))
        # A lone worker spills onto idle cores it doesn't strictly need.
        # True demand is at least --lp cores; count only a fraction of the
        # spillover above that.
        effective_cores = lp + max(0.0, measured_cores - lp) * SPILLOVER_WEIGHT
        effective_cores = max(1.0, min(effective_cores, float(cpu_threads)))
        max_workers_cpu = int((cpu_threads * TARGET_CPU_UTILIZATION) / effective_cores)
    else:
        effective_cores = float(lp + 1)
        max_workers_cpu = max(1, int(cpu_threads / (lp + 1)))

    max_workers_cpu = max(1, max_workers_cpu)

    final_workers = max(1, min(max_workers_ram, max_workers_cpu, cpu_threads))

    print("\n------------------------------------------------")
    print(f"   - Total System RAM: {total_ram // (1024**2)} MB")
    print(f"   - Peak RAM (1 Worker): {max_total_rss // (1024**2)} MB")
    print(f"   - CPU Threads: {cpu_threads} (--lp {lp})")
    print(f"   - Test duration: {test_duration:.0f}s, chunks seen: {len(seen_encoder_pids)}")
    print(f"   - CPU sampling: {sample_note}")
    if measured_cores is not None:
        print(f"   - Settled usage (1 worker): {measured_cores:.2f} cores "
              f"({100.0 * measured_cores / cpu_threads:.0f}% of CPU)")
        print(f"   - Effective demand per worker: {effective_cores:.2f} cores "
              f"(spillover weight {SPILLOVER_WEIGHT})")
    print(f"   - Max workers by RAM: {max_workers_ram}")
    print(f"   - Max workers by CPU (target {int(TARGET_CPU_UTILIZATION * 100)}% load): {max_workers_cpu}")
    print(f"   - Calculated Optimal Workers: {final_workers}")
    print("------------------------------------------------")

    cleanup_temp_folders()

    return final_workers


def write_config(workers):
    try:
        with open(CONFIG_FILE, "w") as f:
            f.write(f"workers={workers}\n")
        return True
    except Exception as e:
        print(f"Error writing config file: {e}")
        return False


# ---------------------------------------------------------------------------
# MODES
# ---------------------------------------------------------------------------

def run_normal_mode():
    if not os.path.exists(SAMPLE_FILE):
        print(f"Error: {SAMPLE_FILE} missing. Defaulting to 1.")
        workers = 1
    else:
        workers = get_optimal_workers()

    if write_config(workers):
        print("\nOne-time test complete. Auto worker count set.")
        print("You may manually edit tools\\workercount-config.txt if needed")


def run_optimize_mode(bat_arg=None):
    """Benchmark using the launching .bat's real encoder preset/params plus any
    settings.txt filtering, then write custom-av1an-workers back into the .bat."""
    bat_path = None
    if bat_arg and os.path.isfile(bat_arg):
        bat_path = os.path.abspath(bat_arg)
    else:
        bat_path = find_active_bat_file()

    if not bat_path:
        print("[Optimize] Could not locate the launching .bat file. Skipping optimized benchmark.")
        return

    bat = parse_bat_settings(bat_path)

    if bat.get("optimize-workers", "").strip().lower() not in ("true", "1", "yes", "on"):
        # This bat did not opt in - proceed as normal (do nothing here).
        return

    existing = bat.get("custom-av1an-workers", "").strip()
    if existing.isdigit() and int(existing) > 0:
        print(f"[Optimize] custom-av1an-workers already set to {existing} in "
              f"{os.path.basename(bat_path)}. Skipping benchmark.")
        if not os.path.exists(CONFIG_FILE):
            write_config(int(existing))
        return

    if not os.path.exists(SAMPLE_FILE):
        print(f"[Optimize] Error: {SAMPLE_FILE} missing. Cannot run optimized benchmark.")
        return

    print("\n-------------------------------------------------------------------------------")
    print(f"[Optimize] One-time optimized encode benchmark for: {os.path.basename(bat_path)}")
    print("-------------------------------------------------------------------------------")

    # --- Set up the same SVT-AV1 fork the bat will use ---
    fork = (bat.get("fork", "essential") or "essential").strip()
    avx512 = "--avx512" in bat.get("avx512_flag", "")
    try:
        sys.path.insert(0, TOOLS_DIR)
        from svt_fork_setup import setup_svt_av1_fork
        setup_svt_av1_fork(TOOLS_DIR, fork, avx512=avx512, verbose=True)
    except Exception as e:
        print(f"[Optimize] Warning: Could not set up SVT-AV1 fork '{fork}': {e}")

    # --- Build the real encoder parameters from the bat ---
    quality = bat.get("quality", "30").strip() or "30"
    speed = bat.get("final_speed", "4").strip() or "4"
    extra = (bat.get("final_params") or bat.get("av1an_settings") or "").strip()
    encoder_params = " ".join(f"--crf {quality} --preset {speed} {extra}".split())

    # --- Include the user's filtering chain when enabled ---
    input_path = SAMPLE_FILE
    values = read_settings_values()
    if settings_filters_enabled(values):
        try:
            input_path = build_filtered_vpy(values)
            print("[Optimize] settings.txt filtering detected - benchmarking through a "
                  "temporary VapourSynth script so filter CPU cost is included.")
        except Exception as e:
            print(f"[Optimize] Warning: Could not build filtered VapourSynth script ({e}). "
                  f"Benchmarking raw sample instead.")
            input_path = SAMPLE_FILE
    else:
        print("[Optimize] No settings.txt filtering enabled - benchmarking raw sample.")

    workers = get_optimal_workers(input_path=input_path, encoder_params=encoder_params)

    if set_bat_value_fixed_width(bat_path, "custom-av1an-workers", workers):
        print(f"[Optimize] Wrote custom-av1an-workers={workers} into {os.path.basename(bat_path)}")
        print("[Optimize] Clear that value in the .bat to re-run this benchmark.")

    if not os.path.exists(CONFIG_FILE):
        write_config(workers)
        print("[Optimize] Also wrote tools\\workercount-config.txt (used by non-optimized bats).")


def parse_cli(argv):
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
    optimize, bat_arg = parse_cli(sys.argv[1:])
    if optimize:
        run_optimize_mode(bat_arg)
    else:
        run_normal_mode()
