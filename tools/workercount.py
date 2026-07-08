import os
import re
import sys
import glob
import psutil
import subprocess
import time
import shutil

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
AV1AN_PATH = "av1an"
MKVMERGE_EXE = os.path.join(TOOLS_DIR, "MKVToolNix", "mkvmerge.exe")
VIDEO_INPUT_DIR = os.path.join(BASE_DIR, "video-input")
SAMPLE_FILE = os.path.join(TOOLS_DIR, "sample.mkv")                  # legacy fallback
BENCH_SAMPLE_FILE = os.path.join(TOOLS_DIR, "benchmark-sample.mkv")  # created from video-input
CONFIG_FILE = os.path.join(TOOLS_DIR, "workercount-config.txt")
BENCH_TEMP_DIR = os.path.join(TOOLS_DIR, "workercount_bench_temp")
TEST_OUTPUT_FILE = os.path.join(BASE_DIR, "workercount-test-output.mkv")

# Encoder params used for the DEFAULT (non-optimized) test
ENCODER_PARAMS = " --preset 4 --crf 30 --lp 3"

# --- TUNING ---
# The benchmark finds the worker-count SWEET SPOT by measuring REAL encode
# throughput (frames per second actually written by the encoder) at several
# worker counts and keeping the fastest. This is the only reliable signal on
# power/thermally limited CPUs (especially laptops), where adding workers
# collapses clock speeds: CPU usage still reads 100%, but fps drops hard.
RAM_HEADROOM = 0.90              # Candidates that push RAM past 90% are rejected
FIRST_FRAME_TIMEOUT = 420        # Max seconds to wait for the FIRST encoded frame
                                 # of the first candidate (includes one-time scene
                                 # detection + source indexing at slow presets)
WARMUP_AFTER_FIRST_FRAME = 15    # Seconds of settling after frames start flowing
                                 # before the measurement window opens
MEASURE_WINDOW = 45              # Seconds of steady-state throughput measured
MAX_CANDIDATE_SECONDS = 900      # Hard safety timeout per candidate
POLL_INTERVAL = 1.0              # Seconds between frame-count/RAM polls
SEARCH_BUDGET = 6                # Max worker counts tested (typical runs use 3-4)
TIE_MARGIN = 0.03                # Within 3% fps counts as a tie -> prefer FEWER workers
SAMPLE_MAX_AGE_SECONDS = 6 * 3600  # Reuse an existing benchmark sample this recent

FILTER_SETTING_KEYS = ("downscale", "denoise", "deband")
VIDEO_EXTENSIONS = (".mkv", ".mp4", ".m2ts")

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


def set_bat_value(bat_path, key, value):
    """Write key=value into the .bat WITHOUT changing the file's byte length.

    cmd.exe reads a running batch file by byte offset, so an edit made while
    the .bat is executing must not shift any bytes. bat-builder reserves
    trailing spaces AFTER the closing quote of each custom line; cmd ignores
    everything after the closing quote of a `set "key=value"` line, so the
    value is written inside the quotes and the leftover reserve stays as
    padding. `if defined` checks in the .bat keep working because an empty
    quoted value leaves the variable undefined."""
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
            new_core = lead + f'set "{m.group(1)}={value}"'
        elif ("=" in stripped and " " not in stripped.split("=", 1)[0]
                and stripped.split("=", 1)[0].strip().lower() == key_l):
            new_core = lead + f"{stripped.split('=', 1)[0]}={value}"
        else:
            continue

        if len(new_core) <= len(body):
            new_body = new_core + " " * (len(body) - len(new_core))
        else:
            new_body = new_core
            print(f"[Optimize] Warning: value '{value}' is wider than the reserved "
                  f"space for {key}; the .bat byte length will change. If this run "
                  f"was launched by that .bat, re-launch it before encoding.", file=sys.stderr)

        lines[idx] = new_body + ending
        try:
            with open(bat_path, "w", encoding="utf-8", errors="replace", newline="") as f:
                f.write("".join(lines))
            return True
        except Exception as e:
            print(f"[Optimize] Error writing {bat_path}: {e}", file=sys.stderr)
            return False

    print(f"[Optimize] Warning: {key} line not found in {os.path.basename(bat_path)}.", file=sys.stderr)
    return False


def bat_runs_ssimu2_optimize(bat_path):
    """True when the launching .bat will also run ssimu2-workercount.py later,
    meaning the benchmark sample must be left in place for it."""
    try:
        with open(bat_path, "r", encoding="utf-8", errors="replace") as f:
            return "ssimu2-workercount.py" in f.read()
    except Exception:
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


def build_filtered_vpy(values, source_path):
    """Build a temporary VapourSynth script mirroring the real dispatch/Auto-Boost
    pipeline (initialize_clip -> denoise/deband -> downscale -> finalize_clip) so
    the benchmark includes the cost of the user's filtering. Crop is left off
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
            source=source_path,
            cache=cache_path,
            denoise_line=denoise_line,
            deband_line=deband_line,
            downscale=str(do_downscale),
            target_res=target_res,
            kernel=kernel,
        ))
    return vpy_path


# ---------------------------------------------------------------------------
# BENCHMARK SAMPLE CREATION (mirrors extras/create-sample.bat)
# ---------------------------------------------------------------------------

def find_first_input_video():
    """First real source file in video-input (skips encode artifacts)."""
    if not os.path.isdir(VIDEO_INPUT_DIR):
        return None
    for name in sorted(os.listdir(VIDEO_INPUT_DIR)):
        path = os.path.join(VIDEO_INPUT_DIR, name)
        if not os.path.isfile(path):
            continue
        stem, ext = os.path.splitext(name)
        if ext.lower() not in VIDEO_EXTENSIONS:
            continue
        if stem.lower().endswith(("-av1", "-output")):
            continue
        return path
    return None


def delete_benchmark_sample():
    for pattern in ("benchmark-sample*.mkv", "benchmark-sample.mkv.*"):
        for path in glob.glob(os.path.join(TOOLS_DIR, pattern)):
            try:
                os.remove(path)
                print(f"[Sample] Deleted {os.path.basename(path)}", file=sys.stderr)
            except OSError:
                pass


def ensure_benchmark_sample(force=False):
    """Create tools/benchmark-sample.mkv: a 90 second, audio-free cut of the
    first video in video-input, made with mkvmerge exactly like
    extras/create-sample.bat (--no-audio --split parts:00:03:00-00:04:30).
    Falls back to the first 90 seconds for short sources. Reuses a recent
    sample so workercount.py and ssimu2-workercount.py share one file.
    Returns the sample path, or None if it could not be created."""
    if not force and os.path.exists(BENCH_SAMPLE_FILE):
        try:
            if time.time() - os.path.getmtime(BENCH_SAMPLE_FILE) < SAMPLE_MAX_AGE_SECONDS:
                print(f"[Sample] Reusing recent benchmark sample: "
                      f"{os.path.basename(BENCH_SAMPLE_FILE)}", file=sys.stderr)
                return BENCH_SAMPLE_FILE
        except OSError:
            pass

    source = find_first_input_video()
    if not source:
        print("[Sample] No source video found in video-input.", file=sys.stderr)
        return None

    mkvmerge = MKVMERGE_EXE if os.path.exists(MKVMERGE_EXE) else "mkvmerge"

    # Clear any previous sample and stale split parts
    for path in glob.glob(os.path.join(TOOLS_DIR, "benchmark-sample*.mkv")):
        try:
            os.remove(path)
        except OSError:
            pass

    # Prefer 3:00-4:30 (skips intros); fall back to 0:00-1:30 for short sources,
    # where mkvmerge produces no output file at all.
    for time_range in ("00:03:00-00:04:30", "00:00:00-00:01:30"):
        cmd = [mkvmerge, "-o", BENCH_SAMPLE_FILE, "--no-audio",
               "--split", f"parts:{time_range}", source]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
        except FileNotFoundError:
            print("[Sample] Warning: mkvmerge not found; cannot create benchmark sample.", file=sys.stderr)
            return None
        except subprocess.TimeoutExpired:
            print("[Sample] Warning: mkvmerge timed out; cannot create benchmark sample.", file=sys.stderr)
            return None

        produced = None
        if os.path.exists(BENCH_SAMPLE_FILE) and os.path.getsize(BENCH_SAMPLE_FILE) > 1024 * 1024:
            produced = BENCH_SAMPLE_FILE
        else:
            # Some mkvmerge versions append part numbers when splitting
            parts = sorted(glob.glob(os.path.join(TOOLS_DIR, "benchmark-sample-0*.mkv")))
            if parts and os.path.getsize(parts[0]) > 1024 * 1024:
                try:
                    os.replace(parts[0], BENCH_SAMPLE_FILE)
                    produced = BENCH_SAMPLE_FILE
                except OSError:
                    produced = parts[0]
                for extra in parts[1:]:
                    try:
                        os.remove(extra)
                    except OSError:
                        pass

        if produced:
            print(f"[Sample] Created 90s benchmark sample (no audio) from "
                  f"{os.path.basename(source)} [{time_range}].", file=sys.stderr)
            return produced

    print(f"[Sample] Warning: mkvmerge produced no usable sample from "
          f"{os.path.basename(source)}.", file=sys.stderr)
    return None


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

    # 3. Clean up the benchmark temp folder (per-candidate av1an temps,
    #    scenes json, temporary VapourSynth script and its cache)
    if os.path.isdir(BENCH_TEMP_DIR):
        try:
            shutil.rmtree(BENCH_TEMP_DIR)
            print("   - Deleted: workercount_bench_temp", file=sys.stderr)
        except OSError:
            print("   - Warning: Could not delete workercount_bench_temp (File in use).", file=sys.stderr)


def kill_process_tree(pid):
    """Kills a process and all of its children."""
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


# ---------------------------------------------------------------------------
# THROUGHPUT MEASUREMENT (frames actually encoded per second)
# ---------------------------------------------------------------------------

def count_ivf_frames(path):
    """Count complete frames in a (possibly still-growing) IVF file by walking
    its 12-byte frame headers. Safe to run while the encoder is writing."""
    frames = 0
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            header = f.read(32)
            if len(header) < 32 or header[:4] != b"DKIF":
                return 0
            pos = 32
            while pos + 12 <= size:
                f.seek(pos)
                frame_header = f.read(12)
                if len(frame_header) < 12:
                    break
                frame_size = int.from_bytes(frame_header[:4], "little")
                if frame_size <= 0 or pos + 12 + frame_size > size:
                    break
                frames += 1
                pos += 12 + frame_size
    except OSError:
        return 0
    return frames


def count_encoded_frames(temp_dir):
    """Total frames written so far across all chunk .ivf files in an av1an temp dir."""
    total = 0
    for root, _dirs, files in os.walk(temp_dir):
        for name in files:
            if name.lower().endswith(".ivf"):
                total += count_ivf_frames(os.path.join(root, name))
    return total


def measure_encode_fps(input_path, encoder_params, workers, scenes_file, first_candidate):
    """Run av1an with `workers` workers and measure real steady-state encode
    throughput by counting frames written into the chunk files.

    Timeline: wait for the first encoded frame (scene detection and lookahead
    happen before it), let things settle for WARMUP_AFTER_FIRST_FRAME, then
    measure frames over MEASURE_WINDOW and kill the encode. If the whole clip
    finishes early, fps is computed over the full encoding span instead.

    Returns (fps, rss_peak_bytes)."""
    candidate_temp = os.path.join(BENCH_TEMP_DIR, f"av1an_w{workers}")
    shutil.rmtree(candidate_temp, ignore_errors=True)
    os.makedirs(candidate_temp, exist_ok=True)
    if os.path.exists(TEST_OUTPUT_FILE):
        try:
            os.remove(TEST_OUTPUT_FILE)
        except OSError:
            pass

    cmd = [
        AV1AN_PATH,
        "-i", input_path,
        "-y",
        "--workers", str(workers),
        "-e", "svt-av1",
        "-m", "bestsource",
        "--temp", candidate_temp,
        "--scenes", scenes_file,
        "-o", TEST_OUTPUT_FILE,
        "-v", " " + encoder_params.strip(),
    ]

    try:
        process = subprocess.Popen(cmd, cwd=BASE_DIR,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print("Error: av1an executable not found.", file=sys.stderr)
        return 0.0, 0

    start = time.time()
    init_timeout = FIRST_FRAME_TIMEOUT if first_candidate else max(120, FIRST_FRAME_TIMEOUT // 2)
    first_frame_time = None
    frames_seen = 0          # monotonic max (av1an deletes its temp on completion)
    f0 = t0 = None
    fps = 0.0
    rss_peak = 0

    try:
        while True:
            exited = process.poll() is not None
            now = time.time()

            if now - start > MAX_CANDIDATE_SECONDS:
                print("   ! Candidate hit the hard safety timeout.", file=sys.stderr)
                break

            # Track peak RAM of the whole process tree
            if not exited:
                try:
                    parent = psutil.Process(process.pid)
                    rss = parent.memory_info().rss
                    for child in parent.children(recursive=True):
                        try:
                            rss += child.memory_info().rss
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    if rss > rss_peak:
                        rss_peak = rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            frames_seen = max(frames_seen, count_encoded_frames(candidate_temp))

            if first_frame_time is None:
                if frames_seen > 0:
                    first_frame_time = now
                elif exited:
                    break  # process ended without producing any frames
                elif now - start > init_timeout:
                    print("   ! Timed out waiting for the first encoded frame.", file=sys.stderr)
                    break

            if first_frame_time is not None:
                if f0 is None and (exited or now - first_frame_time >= WARMUP_AFTER_FIRST_FRAME):
                    f0, t0 = frames_seen, now
                if f0 is not None and (exited or now - t0 >= MEASURE_WINDOW):
                    f1, t1 = frames_seen, now
                    if exited or f1 <= f0:
                        # Encode finished (or too fast to window): use the whole span
                        span = t1 - first_frame_time
                        fps = (f1 / span) if span > 0 and f1 > 0 else 0.0
                    else:
                        span = t1 - t0
                        fps = (f1 - f0) / span if span > 0 else 0.0
                    break

            if exited:
                break

            time.sleep(POLL_INTERVAL)
    finally:
        if process.poll() is None:
            kill_process_tree(process.pid)
        time.sleep(1)
        shutil.rmtree(candidate_temp, ignore_errors=True)
        if os.path.exists(TEST_OUTPUT_FILE):
            for attempt in range(3):
                try:
                    os.remove(TEST_OUTPUT_FILE)
                    break
                except OSError:
                    time.sleep(1)

    return fps, rss_peak


# ---------------------------------------------------------------------------
# SWEET-SPOT SEARCH
# ---------------------------------------------------------------------------

def sweet_spot_search(measure_fn, start, hard_max, budget=SEARCH_BUDGET,
                      tie_margin=TIE_MARGIN, label="workers"):
    """Hill-climb over worker counts using measured fps.

    measure_fn(w) -> fps (0.0 for failed/unsafe candidates). Starts at `start`,
    probes one step up; if that's not a clear win, probes one step down;
    keeps climbing in the winning direction while fps improves by more than
    tie_margin. With step 2 the winner's neighbors are refined by 1.
    Final pick: among everything within tie_margin of the best fps, the
    LOWEST worker count wins (fewer workers = less RAM, snappier system).

    Returns (best_worker_count_or_None, {tested: fps})."""
    results = {}

    def test(w):
        w = max(1, min(int(w), hard_max))
        if w in results:
            return w
        if len(results) >= budget:
            return None
        print(f"\n   Testing {w} {label}...", file=sys.stderr)
        fps = measure_fn(w)
        results[w] = fps
        if fps > 0:
            print(f"   -> {w} {label}: {fps:.2f} fps", file=sys.stderr)
        else:
            print(f"   -> {w} {label}: no throughput (failed, timed out, or unsafe)", file=sys.stderr)
        return w

    def fps_of(w):
        return results.get(w, -1.0)

    step = 1 if start <= 4 else 2
    test(start)

    up = start + step
    down = start - step
    if up <= hard_max and test(up) is not None and fps_of(up) > fps_of(start) * (1 + tie_margin):
        w = up
        while w + step <= hard_max and len(results) < budget:
            if test(w + step) is None or fps_of(w + step) <= fps_of(w) * (1 + tie_margin):
                break
            w += step
    elif down >= 1 and test(down) is not None and fps_of(down) > fps_of(start) * (1 + tie_margin):
        w = down
        while w - step >= 1 and len(results) < budget:
            if test(w - step) is None or fps_of(w - step) <= fps_of(w) * (1 + tie_margin):
                break
            w -= step

    # Refine around the current best when coarse-stepping
    if step == 2 and len(results) < budget:
        best_w = max(results, key=lambda k: results[k])
        for cand in (best_w - 1, best_w + 1):
            if 1 <= cand <= hard_max and cand not in results and len(results) < budget:
                test(cand)

    valid = {w: f for w, f in results.items() if f > 0}
    if not valid:
        return None, results
    best_fps = max(valid.values())
    contenders = [w for w, f in valid.items() if f >= best_fps * (1 - tie_margin)]
    return min(contenders), results


def run_benchmark(input_path, encoder_params):
    """Find the encode worker sweet spot for the given input and params."""
    cpu_threads = os.cpu_count() or 1
    physical_cores = psutil.cpu_count(logical=False) or max(1, cpu_threads // 2)
    total_ram = psutil.virtual_memory().total
    lp = parse_lp(encoder_params)
    start = max(1, min(cpu_threads, physical_cores // max(1, lp)))

    os.makedirs(BENCH_TEMP_DIR, exist_ok=True)
    scenes_file = os.path.join(BENCH_TEMP_DIR, "bench_scenes.json")

    print(f"\nFinding the worker-count sweet spot on {os.path.basename(str(input_path))}", file=sys.stderr)
    print(f"Encoder params: {encoder_params.strip()}", file=sys.stderr)
    print(f"CPU: {physical_cores} cores / {cpu_threads} threads (--lp {lp}) | "
          f"starting at {start} workers", file=sys.stderr)
    print("Each candidate is measured on REAL encode throughput for "
          f"~{WARMUP_AFTER_FIRST_FRAME + MEASURE_WINDOW}s of steady encoding "
          "(1-3 minutes per test; scene detection runs once).", file=sys.stderr)

    state = {"first": True}
    ram_limited = []

    def measure(w):
        fps, rss_peak = measure_encode_fps(input_path, encoder_params, w, scenes_file, state["first"])
        state["first"] = False
        if rss_peak > total_ram * RAM_HEADROOM:
            print(f"   ! {w} workers pushed RAM to {rss_peak // (1024**2)} MB "
                  f"(>{int(RAM_HEADROOM * 100)}% of system RAM) - rejected.", file=sys.stderr)
            ram_limited.append(w)
            return 0.0
        return fps

    best, results = sweet_spot_search(measure, start, cpu_threads)

    print("\n------------------------------------------------")
    print(f"   - Total System RAM: {total_ram // (1024**2)} MB")
    print(f"   - CPU: {physical_cores} cores / {cpu_threads} threads")
    for w in sorted(results):
        marker = "  <-- sweet spot" if w == best else ""
        fps_str = f"{results[w]:.2f} fps" if results[w] > 0 else "failed/unsafe"
        print(f"   - {w} workers: {fps_str}{marker}")
    if ram_limited:
        print(f"   - RAM-limited counts: {sorted(ram_limited)}")
    if best is None:
        best = max(1, cpu_threads // (lp + 1))
        print(f"   - WARNING: No candidate produced throughput. "
              f"Falling back to {best} workers (threads/(lp+1)).")
    else:
        print(f"   - Calculated Optimal Workers: {best}")
    print("------------------------------------------------")

    return best


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

def resolve_benchmark_input():
    """Prefer a fresh 90s sample cut from the user's actual source in
    video-input; fall back to the bundled tools/sample.mkv."""
    sample = ensure_benchmark_sample()
    if sample:
        return sample
    if os.path.exists(SAMPLE_FILE):
        print(f"[Sample] Falling back to {os.path.basename(SAMPLE_FILE)}.", file=sys.stderr)
        return SAMPLE_FILE
    return None


def maybe_delete_benchmark_sample(bat_path=None):
    """Delete the benchmark sample unless ssimu2-workercount.py will still
    need it later in the same .bat run."""
    if bat_path is None:
        bat_path = find_active_bat_file()
    if bat_path and bat_runs_ssimu2_optimize(bat_path):
        print("[Sample] Keeping benchmark sample for the SSIMU2 benchmark step.", file=sys.stderr)
        return
    delete_benchmark_sample()


def run_normal_mode():
    input_path = resolve_benchmark_input()
    if not input_path:
        print("Error: No benchmark source available (video-input is empty and "
              "tools\\sample.mkv is missing). Defaulting to 1.")
        workers = 1
    else:
        workers = run_benchmark(input_path, ENCODER_PARAMS)
        cleanup_temp_folders()
        maybe_delete_benchmark_sample()

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

    print("\n-------------------------------------------------------------------------------")
    print(f"[Optimize] One-time optimized encode benchmark for: {os.path.basename(bat_path)}")
    print("-------------------------------------------------------------------------------")

    source_path = resolve_benchmark_input()
    if not source_path:
        print("[Optimize] Error: No benchmark source available (video-input is empty "
              "and tools\\sample.mkv is missing). Skipping.")
        return

    # --- Set up the same SVT-AV1 fork the bat will use ---
    fork = (bat.get("fork", "essential") or "essential").strip()
    avx512 = ("--avx512" in bat.get("avx512_flag", "")
              or bat.get("avx512", "").strip().lower() in ("true", "1", "yes", "on"))
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
    input_path = source_path
    values = read_settings_values()
    if settings_filters_enabled(values):
        try:
            input_path = build_filtered_vpy(values, source_path)
            print("[Optimize] settings.txt filtering detected - benchmarking through a "
                  "temporary VapourSynth script so filter cost is included.")
        except Exception as e:
            print(f"[Optimize] Warning: Could not build filtered VapourSynth script ({e}). "
                  f"Benchmarking unfiltered sample instead.")
            input_path = source_path
    else:
        print("[Optimize] No settings.txt filtering enabled - benchmarking unfiltered sample.")

    workers = run_benchmark(input_path, encoder_params)

    if set_bat_value(bat_path, "custom-av1an-workers", workers):
        print(f"[Optimize] Wrote custom-av1an-workers={workers} into {os.path.basename(bat_path)}")
        print("[Optimize] Clear that value in the .bat to re-run this benchmark.")

    if not os.path.exists(CONFIG_FILE):
        write_config(workers)
        print("[Optimize] Also wrote tools\\workercount-config.txt (used by non-optimized bats).")

    cleanup_temp_folders()
    maybe_delete_benchmark_sample(bat_path)


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
