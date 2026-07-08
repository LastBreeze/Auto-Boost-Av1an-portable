import sys
import subprocess
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glob
import shutil
import shlex
import re
import urllib.parse
import urllib.request
from pathlib import Path
from wakepy import keep
from svt_fork_setup import setup_svt_av1_fork

BLUE = "\033[94m"
RESET = "\033[0m"

def scene_detection_env():
    """Environment for scene detection subprocesses.

    Forces unbuffered Python output so live progress lines from
    Progressive-Scene-Detection.py are visible in the parent console.
    """
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["AUTOBOOST_SCENE_X264_PROGRESS"] = "1"
    return env

def parse_settings_lines(lines):
    """Parse settings.txt lines into a case-insensitive key/value dict."""
    settings = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith(("#", ";", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        settings[key.strip().lower()] = value.strip()
    return settings


def set_settings_value(settings_path, key, value):
    """Set key=value in settings.txt, preserving the rest of the file, and return parsed settings."""
    key_l = key.lower()
    lines = []
    found = False
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";", "[")) or "=" not in line:
            continue
        k, _ = line.split("=", 1)
        if k.strip().lower() == key_l:
            lines[idx] = f"{k.strip()}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    with open(settings_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return parse_settings_lines(lines)

# --- Optimized worker settings (read from the generating .bat file) ---
_BAT_SET_RE = re.compile(r'^set\s+"?([^=\s"]+)\s*=(.*?)"?\s*$', re.IGNORECASE)


def find_active_bat_file(tools_dir, root_dir):
    """Locate the .bat that launched this run via the tools/bat-used-*.txt marker."""
    markers = glob.glob(os.path.join(tools_dir, "bat-used-*.txt"))
    markers.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for marker in markers:
        name = os.path.basename(marker)
        if not (name.startswith("bat-used-") and name.endswith(".txt")):
            continue
        bat_name = name[len("bat-used-"):-len(".txt")]
        bat_path = os.path.join(root_dir, bat_name)
        if os.path.isfile(bat_path):
            return bat_path
    return None


def read_bat_optimize_settings(tools_dir, root_dir):
    """Parse optimize-workers, custom av1an workers, and custom SSIMU2
    tool/worker settings from the active .bat. Returns an empty dict when the settings are absent, so
    callers proceed exactly as before."""
    bat_path = find_active_bat_file(tools_dir, root_dir)
    if not bat_path:
        return {}
    wanted = {"optimize-workers", "custom-av1an-workers", "custom-ssim2-workers", "custom-ssim2-tool"}
    settings = {}
    try:
        with open(bat_path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f.read().splitlines():
                line = raw.strip()
                if not line or line.startswith("::") or line.lower().startswith("rem "):
                    continue
                m = _BAT_SET_RE.match(line)
                key = value = None
                if m:
                    key, value = m.group(1).lower(), m.group(2).strip()
                elif "=" in line and " " not in line.split("=", 1)[0] and "%" not in line.split("=", 1)[0]:
                    k, v = line.split("=", 1)
                    key, value = k.strip().lower(), v.strip()
                if key in wanted:
                    settings[key] = value
    except Exception:
        return {}
    return settings


def svt_fork_display_name(fork):
    fork_key = (fork or "essential").strip().lower()
    if fork_key in ("svt-av1-essential", "essential"):
        return "Essential"
    if fork_key in ("svt-av1-hdr", "hdr"):
        return "HDR"
    if fork_key in ("5fish", "svt-av1-psy", "psy"):
        return "psy 5fish"
    if fork_key == "custom":
        return "custom"
    return (fork or "essential").strip() or "Essential"


def parse_bool_setting(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def resolve_configured_path(configured_path, root_dir, tools_dir, default_filename="ntfy.txt"):
    configured_path = (configured_path or "").strip().strip('"')
    if not configured_path:
        return os.path.join(tools_dir, default_filename)

    if re.match(r"^[A-Za-z]:[\\/]", configured_path):
        if os.name != "nt":
            drive = configured_path[0].lower()
            rest = configured_path[2:].lstrip("\\/").replace("\\", "/")
            return os.path.join("/mnt", drive, rest)
        return configured_path

    if os.path.isabs(configured_path):
        return configured_path

    if os.name != "nt":
        configured_path = configured_path.replace("\\", "/")

    return os.path.join(root_dir, configured_path)


def read_ntfy_config(settings, root_dir, tools_dir):
    ntfy_path_setting = (settings or {}).get("ntfy", "").strip()
    if ntfy_path_setting.lower() in ("", "false", "off", "none", "disabled"):
        if not ntfy_path_setting:
            ntfy_path_setting = os.path.join(tools_dir, "ntfy.txt")
        else:
            return {}, None
    ntfy_path = resolve_configured_path(ntfy_path_setting, root_dir, tools_dir)
    if not os.path.exists(ntfy_path):
        return {}, ntfy_path

    config = {}
    try:
        with open(ntfy_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith(("#", ";")):
                    continue
                if "=" in stripped:
                    key, value = stripped.split("=", 1)
                    config[key.strip().lower()] = value.strip()
                elif "secretword" not in config:
                    # Backward compatibility with older one-line ntfy.txt files.
                    config["secretword"] = stripped
    except Exception as e:
        print(f"[Dispatch] Warning: Could not read ntfy settings from {ntfy_path}: {e}")
    return config, ntfy_path


def send_ntfy_notification(settings, root_dir, tools_dir, title, message):
    ntfy_config, ntfy_path = read_ntfy_config(settings, root_dir, tools_dir)
    secret_word = ntfy_config.get("secretword", "").strip()
    pc_name = ntfy_config.get("pcname", "").strip() or "this PC"
    if not secret_word:
        if ntfy_path:
            print(f"[Dispatch] ntfy not sent; secretword missing or empty in: {ntfy_path}")
        return False

    body = f"{message}\nPC: {pc_name}"
    topic = urllib.parse.quote(secret_word, safe="")
    request = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=body.encode("utf-8"),
        headers={
            "Title": title,
            "Tags": "movie_camera",
            "Priority": "default",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        print("[Dispatch] ntfy notification sent.")
        return True
    except Exception as e:
        print(f"[Dispatch] Warning: Failed to send ntfy notification: {e}")
        return False

WINDOWS_MAX_PATH = 260


def display_path_for_length(path):
    """Return the Windows-style path users see, so length warnings match Windows tools."""
    abs_path = os.path.abspath(path)
    normalized = abs_path.replace("/", "\\")
    lower = normalized.lower()
    if lower.startswith("\\mnt\\") and len(normalized) > 6 and normalized[5].isalpha() and normalized[6:7] == "\\":
        return f"{normalized[5].upper()}:\\{normalized[7:]}"
    return normalized


def pause_for_long_paths(long_paths):
    print("\n" + "=" * 80)
    print("[Dispatch] ERROR: One or more backend file paths exceed the Windows 260-character limit.")
    print("[Dispatch] Processing has been paused/stopped before encoding to avoid tool failures.")
    print("[Dispatch] The full filename + folder path is too long for Windows tools.")
    print("[Dispatch] Please rename your input filenames to be shorter and/or move the")
    print("[Dispatch] Auto-Boost-Av1an-portable folder to a lower drive path, then run this again.")
    print("-" * 80)
    for path in long_paths:
        print(f"[Dispatch] {len(path)} characters: {path}")
    print("=" * 80)
    try:
        input("Press Enter to exit...")
    except EOFError:
        pass
    sys.exit(1)


def warn_and_pause_if_paths_too_long(input_files, video_output_dir, temp_dir):
    long_paths = []
    for input_path in input_files:
        filename = os.path.basename(input_path)
        basename = os.path.splitext(filename)[0]
        video_input_dir = os.path.dirname(input_path)
        backend_artifact_dir = os.path.join(video_input_dir, basename)
        paths_to_check = [
            input_path,
            os.path.join(video_output_dir, basename + "-output.mkv"),
            os.path.join(temp_dir, f"{basename}.vpy"),
            os.path.join(temp_dir, f"{basename}.ffindex"),
            os.path.join(temp_dir, f"{basename}_scenedetect.json"),
            os.path.join(temp_dir, f"{basename}-output.mkv"),
            os.path.join(video_input_dir, f"{basename}-av1.mkv"),
            backend_artifact_dir,
            os.path.join(backend_artifact_dir, f"{basename}.vpy"),
            os.path.join(backend_artifact_dir, f"{basename}.ffindex"),
            os.path.join(backend_artifact_dir, f"{basename}-av1.mkv"),
        ]
        for path in paths_to_check:
            display_path = display_path_for_length(path)
            if len(display_path) > WINDOWS_MAX_PATH:
                long_paths.append(display_path)

    if long_paths:
        seen = set()
        unique_long_paths = []
        for path in long_paths:
            if path not in seen:
                seen.add(path)
                unique_long_paths.append(path)
        pause_for_long_paths(unique_long_paths)


def sanitize_input_filenames(video_input_dir, extensions):
    """Replace parentheses in supported video filenames with safe inner spaces before processing."""
    supported_exts = {pattern[1:].lower() for pattern in extensions if pattern.startswith("*")}
    renamed = 0
    for filename in sorted(os.listdir(video_input_dir)):
        src_path = os.path.join(video_input_dir, filename)
        if not os.path.isfile(src_path):
            continue
        stem, ext = os.path.splitext(filename)
        if ext.lower() not in supported_exts or ("(" not in stem and ")" not in stem):
            continue

        safe_stem = " ".join(stem.replace("(", " ").replace(")", " ").split()) or "video"
        dst_path = os.path.join(video_input_dir, f"{safe_stem}{ext}")
        suffix = 1
        while os.path.exists(dst_path):
            dst_path = os.path.join(video_input_dir, f"{safe_stem}_{suffix}{ext}")
            suffix += 1

        os.rename(src_path, dst_path)
        renamed += 1
        print(f"[Dispatch] Renamed input file for Python-safe filename: {filename} -> {os.path.basename(dst_path)}")

    return renamed



def gather_input_files(video_input_dir, extensions):
    input_files = []
    for ext in extensions:
        input_files.extend(sorted(glob.glob(os.path.join(video_input_dir, ext))))
    return input_files


def scan_for_new_input_files(video_input_dir, extensions, known_input_files):
    """Rescan video-input between encodes and queue files added after startup."""
    sanitize_input_filenames(video_input_dir, extensions)
    current_files = gather_input_files(video_input_dir, extensions)
    new_files = [path for path in current_files if path not in known_input_files]
    if new_files:
        print(f"{BLUE}[Dispatch] New input file(s) detected in video-input; adding to queue:{RESET}")
        for path in new_files:
            print(f"{BLUE}{os.path.basename(path)}{RESET}")
        known_input_files.update(new_files)
    return new_files

def load_script_settings(settings_path):
    """Read settings.txt once into a case-insensitive key/value dict."""
    if not os.path.exists(settings_path):
        return {}
    try:
        with open(settings_path, "r", encoding="utf-8", errors="replace") as f:
            return parse_settings_lines(f.read().splitlines())
    except Exception:
        return {}


def get_script_setting(settings, key_name, default_value):
    """Return a setting from a dict loaded by load_script_settings()."""
    return settings.get(key_name.lower(), default_value)


def setting_is_true(settings, key_name, default_value="False"):
    return get_script_setting(settings, key_name, default_value).strip().lower() in ("1", "true", "yes", "y", "on")


def read_crop_int(value, key_name):
    try:
        crop_value = int(value)
    except (TypeError, ValueError):
        print(f"[Dispatch] Warning: Invalid manual crop {key_name}={value!r}; using 0.")
        return 0
    if crop_value < 0:
        print(f"[Dispatch] Warning: Invalid manual crop {key_name}={crop_value}; using 0.")
        return 0
    if crop_value % 2 != 0:
        adjusted = crop_value - 1
        print(f"[Dispatch] Warning: Manual crop {key_name}={crop_value} is not mod2; using {adjusted}.")
        return adjusted
    return crop_value


def report_crop_status(mode, top, bottom, left, right):
    normalized_mode = (mode or "off").lower()
    active = any((top, bottom, left, right))
    if normalized_mode == "off":
        print(f"{BLUE}[Dispatch] Crop: off{RESET}")
    elif active:
        print(f"{BLUE}[Dispatch] Crop: {normalized_mode} active (top={top}, bottom={bottom}, left={left}, right={right}){RESET}")
    else:
        print(f"{BLUE}[Dispatch] Crop: {normalized_mode} selected, no crop values active{RESET}")


def report_filter_status(do_downscale, target_res, kernel, do_denoise, denoise_setting, do_deband, deband_setting):
    active_filters = []
    if do_downscale:
        active_filters.append(f"downscale: target_resolution={target_res}, kernel_type={kernel}")
    if do_denoise:
        active_filters.append(f"denoise: denoise_setting={denoise_setting or 'enabled'}")
    if do_deband:
        active_filters.append(f"deband: deband_setting={deband_setting or 'enabled'}")

    if not active_filters:
        print(f"{BLUE}[Dispatch] Filters active: none{RESET}")
        return

    for filter_status in active_filters:
        print(f"{BLUE}[Dispatch] Filter active: {filter_status}{RESET}")


def parse_crop_values_from_vpy(vpy_path):
    if not os.path.exists(vpy_path):
        return None
    try:
        with open(vpy_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return None
    match = re.search(r"std\.Crop\(([^)]*)\)", text)
    if not match:
        return 0, 0, 0, 0
    values = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    for key, value in re.findall(r"(top|bottom|left|right)\s*=\s*(-?\d+)", match.group(1)):
        values[key] = int(value)
    return values["top"], values["bottom"], values["left"], values["right"]


def detect_crop_values(source_path, tools_dir):
    """Use tools/cropdetect.py to detect crop values, matching Auto-Boost-Av1an.py behavior."""
    cropdetect_script = os.path.join(tools_dir, "cropdetect.py")
    print("[Dispatch] Detecting crop values via cropdetect.py...")
    print(f"[Dispatch] Source: {os.path.basename(source_path)}")
    if not os.path.exists(cropdetect_script):
        print(f"[Dispatch] Warning: cropdetect.py not found at {cropdetect_script}. Proceeding with 0 crop.")
        return 0, 0, 0, 0

    csv_output = os.path.join(os.path.dirname(source_path), f"{Path(source_path).stem}_crop.csv")

    def run_crop_process(aggressive_mode):
        cmd = [sys.executable, cropdetect_script, source_path, "--out", csv_output, "--samples", "3", "--progress-mode"]
        mode_label = "Aggressive" if aggressive_mode else "Standard"
        if aggressive_mode:
            cmd.append("--aggressive")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if line.startswith("PROGRESS:"):
                    print(f"[Dispatch] Cropdetect ({mode_label}): {line.split(':', 1)[1]}%", end="\r")
                elif line:
                    print(f"[Dispatch] Cropdetect ({mode_label}): {line}")
            print(" " * 80, end="\r")
            return proc.wait() == 0
        except Exception as e:
            print(f"[Dispatch] Warning: Error during crop detection: {e}")
            return False

    def parse_csv_result():
        if not os.path.exists(csv_output):
            print("[Dispatch] Warning: Crop CSV not found after execution.")
            return 0, 0, 0, 0, ""
        import csv
        try:
            with open(csv_output, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            if not rows:
                return 0, 0, 0, 0, ""
            row = rows[0]
            orig_w = int(row.get("width", "0"))
            orig_h = int(row["height"])
            c_w = int(row.get("crop_w", orig_w))
            c_h = int(row["crop_h"])
            c_x = int(row.get("crop_x", "0"))
            c_y = int(row["crop_y"])
            top = c_y
            bottom = orig_h - (c_y + c_h)
            left = c_x
            right = orig_w - (c_x + c_w) if orig_w else 0
            top, bottom, left, right = [v - 1 if v % 2 else v for v in (top, bottom, left, right)]
            return top, bottom, left, right, row.get("crop", "")
        except Exception as e:
            print(f"[Dispatch] Warning: Failed to parse crop CSV: {e}")
            return 0, 0, 0, 0, ""

    if not run_crop_process(aggressive_mode=False):
        return 0, 0, 0, 0
    top, bottom, left, right, crop_str = parse_csv_result()
    if top == 0 and bottom == 0 and left == 0 and right == 0:
        print("[Dispatch] No crop found. Retrying with --aggressive mode...")
        if run_crop_process(aggressive_mode=True):
            top, bottom, left, right, crop_str = parse_csv_result()
    if any((top, bottom, left, right)):
        print(f"[Dispatch] Crop Found: Top={top}, Bottom={bottom}, Left={left}, Right={right} (Based on {crop_str})")
    else:
        print("[Dispatch] No crop detected (0 on all sides).")
    return top, bottom, left, right


def build_vapoursynth_script(source_path, temp_dir, tools_dir, settings, autocrop, convert_yuv420p10=False):
    """Build the per-input .vpy script used as av1an input."""
    basename = Path(source_path).stem
    vpy_file = os.path.join(temp_dir, f"{basename}.vpy")
    cache_file = os.path.join(temp_dir, f"{basename}.ffindex")

    s_crop_mode = get_script_setting(settings, "crop", "auto")
    s_crop_top = get_script_setting(settings, "top", "0")
    s_crop_bottom = get_script_setting(settings, "bottom", "0")
    s_crop_left = get_script_setting(settings, "left", "0")
    s_crop_right = get_script_setting(settings, "right", "0")
    do_downscale = setting_is_true(settings, "downscale", "False")
    target_res = get_script_setting(settings, "target_resolution", "1920x1080")
    kernel = get_script_setting(settings, "kernel_type", "Hermite")
    do_denoise = setting_is_true(settings, "denoise", "False")
    denoise_setting = get_script_setting(settings, "denoise_setting", "")
    do_deband = setting_is_true(settings, "deband", "False")
    deband_setting = get_script_setting(settings, "deband_setting", "")

    requested_crop_mode = s_crop_mode.strip().lower()
    if not autocrop:
        crop_mode = "off"
    elif requested_crop_mode in ("auto", "manual", "off"):
        crop_mode = requested_crop_mode
    else:
        print(f"[Dispatch] Warning: Unknown crop mode {s_crop_mode!r}; using auto.")
        crop_mode = "auto"

    rebuild_vpy = not os.path.exists(vpy_file)
    if not rebuild_vpy:
        try:
            with open(vpy_file, "r", encoding="utf-8", errors="replace") as f:
                existing_vpy_text = f.read()
            if r'\"' in existing_vpy_text:
                print(f"[Dispatch] Existing VapourSynth script has legacy escaped quotes; rebuilding: {vpy_file}")
                rebuild_vpy = True
        except Exception as e:
            print(f"[Dispatch] Warning: Could not inspect existing VapourSynth script ({e}); rebuilding: {vpy_file}")
            rebuild_vpy = True

    if rebuild_vpy:
        crop_top = crop_bottom = crop_left = crop_right = 0
        if crop_mode == "auto":
            crop_top, crop_bottom, crop_left, crop_right = detect_crop_values(source_path, tools_dir)
        elif crop_mode == "manual":
            crop_top = read_crop_int(s_crop_top, "top")
            crop_bottom = read_crop_int(s_crop_bottom, "bottom")
            crop_left = read_crop_int(s_crop_left, "left")
            crop_right = read_crop_int(s_crop_right, "right")
        report_crop_status(crop_mode, crop_top, crop_bottom, crop_left, crop_right)
        report_filter_status(do_downscale, target_res, kernel, do_denoise, denoise_setting, do_deband, deband_setting)

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

# Conversion
if {convert}:
    src = src.resize.Bicubic(format=vs.YUV420P10)

# Initialize (Fixes Placebo bitdepth error by ensuring 16-bit)
src = initialize_clip(src)

# Optional settings.txt denoise/deband hooks
{denoise_line}
{deband_line}

# 1. CROP
if {ct} > 0 or {cb} > 0 or {cl} > 0 or {cr} > 0:
    src = src.std.Crop(top={ct}, bottom={cb}, left={cl}, right={cr})

# 2. DOWNSCALE
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
        with open(vpy_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(vpy_template.format(
                source=source_path,
                cache=cache_file,
                ct=crop_top,
                cb=crop_bottom,
                cl=crop_left,
                cr=crop_right,
                downscale=str(do_downscale),
                target_res=target_res,
                kernel=kernel,
                convert=str(convert_yuv420p10),
                denoise_line=denoise_line,
                deband_line=deband_line,
            ))
        print(f"[Dispatch] Built VapourSynth script: {vpy_file}")
    else:
        existing_crop_values = parse_crop_values_from_vpy(vpy_file) or (0, 0, 0, 0)
        report_crop_status(crop_mode, *existing_crop_values)
        report_filter_status(do_downscale, target_res, kernel, do_denoise, denoise_setting, do_deband, deband_setting)
        print(f"[Dispatch] Reusing existing VapourSynth script: {vpy_file}")

    return vpy_file


def main():
    # --- Configuration ---
    script_path = os.path.abspath(__file__)
    tools_dir = os.path.dirname(script_path)
    root_dir = os.path.dirname(tools_dir)
    
    video_input_dir = os.path.join(root_dir, "video-input")
    video_output_dir = os.path.join(root_dir, "video-output")
    temp_dir = os.path.join(root_dir, "temp")
    
    # Scripts & Tools
    av1an_exe = os.path.join(tools_dir, "av1an", "av1an.exe")
    scene_detect_script = os.path.join(tools_dir, "Progressive-Scene-Detection.py")
    
    # UPDATED: Use the specific av1an- versions of tag and mux
    tag_script = os.path.join(tools_dir, "av1an-tag.py")
    mux_script = os.path.join(tools_dir, "av1an-mux.py")
    
    # --- Ensure Directories Exist ---
    if not os.path.exists(video_input_dir):
        os.makedirs(video_input_dir)
        print(f"[Dispatch] Created missing input directory: {video_input_dir}")
        sys.exit(0)
    if not os.path.exists(video_output_dir):
        os.makedirs(video_output_dir)
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
        
    # --- Argument Parsing ---
    args = sys.argv[1:]
    
    quality = "30"
    workers = "1"
    photon_noise = "0"
    final_speed = "4"
    final_params = ""
    resume = False
    selected_fork = "essential"
    avx512 = False
    denoise_setting = None
    autocrop = False
    convert_yuv420p10 = False
    
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--fork" and i + 1 < len(args):
            selected_fork = args[i+1]
            i += 2
        elif arg == "--avx512":
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                avx512 = parse_bool_setting(args[i + 1])
                i += 2
            else:
                avx512 = True
                i += 1
        elif arg == "--denoise" and i + 1 < len(args):
            val = args[i+1].strip().lower()
            denoise_setting = "True" if val in ("1", "true", "yes", "y", "on") else "False"
            i += 2
        elif arg == "--autocrop":
            autocrop = True
            i += 1
        elif arg == "--convert-to-YUV420P10":
            convert_yuv420p10 = True
            i += 1
        elif arg == "--quality" and i + 1 < len(args):
            quality = args[i+1]
            i += 2
        elif arg == "--workers" and i + 1 < len(args):
            workers = args[i+1]
            i += 2
        elif arg == "--photon-noise" and i + 1 < len(args):
            photon_noise = args[i+1]
            i += 2
        elif arg == "--final-speed" and i + 1 < len(args):
            final_speed = args[i+1]
            i += 2
        elif arg == "--final-params" and i + 1 < len(args):
            # This captures the 'av1an_settings' string passed from batch
            final_params = args[i+1]
            i += 2
        elif arg == "--resume":
            resume = True
            i += 1
        else:
            i += 1


    # --- Optimized worker override from the generating .bat (optional) ---
    # Written by the one-time benchmark (workercount.py --optimize-bat).
    # When absent, everything proceeds exactly as before.
    bat_opt = read_bat_optimize_settings(tools_dir, root_dir)
    if bat_opt.get("optimize-workers", "").strip().lower() in ("true", "1", "yes", "on"):
        custom_enc = bat_opt.get("custom-av1an-workers", "").strip()
        if custom_enc.isdigit() and int(custom_enc) > 0:
            workers = custom_enc
            print(f"{BLUE}[Dispatch] Using optimized av1an worker count from bat: {workers}{RESET}")

    settings_path = os.path.join(root_dir, "settings.txt")
    settings = None
    if denoise_setting is not None:
        try:
            settings = set_settings_value(settings_path, "denoise", denoise_setting)
            print(f"[Dispatch] Set settings.txt denoise={denoise_setting}")
        except Exception as e:
            print(f"[Dispatch] Warning: Failed to update settings.txt denoise: {e}")
    if settings is None:
        settings = load_script_settings(settings_path)
    ntfy_settings = settings

    setup_svt_av1_fork(tools_dir, selected_fork, avx512=avx512, verbose=True)
            
    # --- Gather Input Files ---
    extensions = ("*.mkv", "*.mp4", "*.m2ts")
    sanitize_input_filenames(video_input_dir, extensions)
    input_files = gather_input_files(video_input_dir, extensions)
    known_input_files = set(input_files)
    
    if not input_files:
        print(f"[Dispatch] No video files found in {video_input_dir}")
        sys.exit(0)

    warn_and_pause_if_paths_too_long(input_files, video_output_dir, temp_dir)
        
    print(f"[Dispatch] Found {len(input_files)} files to process.")

    # --- Main Processing Loop ---
    input_index = 0
    while input_index < len(input_files):
        input_abspath_origin = input_files[input_index]
        input_index += 1
        filename = os.path.basename(input_abspath_origin)
        basename = os.path.splitext(filename)[0]
        
        final_output_path = os.path.join(video_output_dir, basename + "-output.mkv")
        
        print("\n" + "="*80)
        print(f"Processing: {filename}")
        print("="*80)
        
        if os.path.exists(final_output_path):
            print(f"[Dispatch] Output file already exists: {final_output_path}")
            continue

        try:
            # Note: We are NO LONGER moving the file to temp. 
            # We read directly from input_abspath_origin.
            
            # 1. Scene Detection
            # We run this in temp_dir so the JSON appears there
            json_file = f"{basename}_scenedetect.json"
            json_abspath = os.path.join(temp_dir, json_file)
            
            if os.path.exists(json_abspath):
                print(f"[Dispatch] Skipping scene detection (JSON exists).")
            else:
                print("[Dispatch] Running Scene Detection...")
                cmd_scene = [
                    sys.executable,
                    scene_detect_script,
                    "-i", input_abspath_origin,
                    "-o", json_file 
                ]
                try:
                    subprocess.check_call(cmd_scene, cwd=temp_dir, env=scene_detection_env())
                except subprocess.CalledProcessError:
                    print("[Dispatch] Scene detection failed. Proceeding anyway.")

            # 2. Build VapourSynth input script from settings.txt
            vpy_abspath = build_vapoursynth_script(
                input_abspath_origin,
                temp_dir,
                tools_dir,
                settings,
                autocrop=autocrop,
                convert_yuv420p10=convert_yuv420p10,
            )

            # 3. Encoding (Direct Av1an Call)
            av1_output = f"{basename}-av1.mkv"
            
            # Construct Encoder Parameters (-v)
            # Combine quality (CRF), preset, and the batch settings
            encoder_params = f"--crf {quality} --preset {final_speed} {final_params}"
            
            # Clean up double spaces if any
            encoder_params = " ".join(encoder_params.split())

            # We run Av1an in video_input_dir, so artifacts appear there (and we can resume if needed).
            # We pass json_abspath because the json is in temp.
            cmd_av1an = [
                av1an_exe,
                "-i", vpy_abspath,
                "-e", "svt-av1",
                "--no-defaults",
                "--photon-noise", photon_noise,
                "-w", workers,
                "-s", json_abspath,
                "-o", av1_output,
                "-v", encoder_params
            ]
            
            if resume:
                cmd_av1an.append("--resume")
                
            print(f"[Dispatch] Starting Av1an Encoding...")
            print(f"svt-av1 fork: {svt_fork_display_name(selected_fork)}")
            
            try:
                with keep.running():
                    # Run in video_input_dir so temp folders created by av1an stay with source until done
                    subprocess.check_call(cmd_av1an, cwd=video_input_dir)
            except subprocess.CalledProcessError:
                print("[Dispatch] Encoding failed.")
                send_ntfy_notification(
                    ntfy_settings,
                    root_dir,
                    tools_dir,
                    "Auto-Boost encode failed",
                    "An encode failed.",
                )
                continue

            # 3. Move Av1an Artifacts from video-input to Temp
            # Artifacts are: {basename}-av1.mkv and {basename} (folder)
            av1_file_src = os.path.join(video_input_dir, f"{basename}-av1.mkv")
            av1_folder_src = os.path.join(video_input_dir, basename)
            
            av1_file_dst = os.path.join(temp_dir, f"{basename}-av1.mkv")
            av1_folder_dst = os.path.join(temp_dir, basename)
            
            print("[Dispatch] Moving encoding artifacts to temp folder...")
            
            # Move the folder
            if os.path.exists(av1_folder_src):
                if os.path.exists(av1_folder_dst):
                    try:
                        shutil.rmtree(av1_folder_dst)
                    except Exception as e:
                        print(f"[Dispatch] Warning: Failed to clean destination folder {av1_folder_dst}: {e}")
                try:
                    shutil.move(av1_folder_src, av1_folder_dst)
                    print(f"[Dispatch] Moved folder: {av1_folder_src} -> {av1_folder_dst}")
                except Exception as e:
                    print(f"[Dispatch] Error moving folder: {e}")
            else:
                print(f"[Dispatch] Warning: Expected temp folder not found at {av1_folder_src}")
                
            # Move the file
            if os.path.exists(av1_file_src):
                if os.path.exists(av1_file_dst):
                    try:
                        os.remove(av1_file_dst)
                    except Exception as e:
                        print(f"[Dispatch] Warning: Failed to clean destination file {av1_file_dst}: {e}")
                try:
                    shutil.move(av1_file_src, av1_file_dst)
                    print(f"[Dispatch] Moved file: {av1_file_src} -> {av1_file_dst}")
                except Exception as e:
                    print(f"[Dispatch] Error moving encoded file: {e}")
            else:
                print(f"[Dispatch] Warning: Expected encoded file not found at {av1_file_src}")

            # 4. Tagging (using av1an-tag.py)
            print("[Dispatch] Applying Tags...")
            try:
                subprocess.check_call([sys.executable, tag_script], cwd=temp_dir)
            except subprocess.CalledProcessError:
                print("[Dispatch] Warning: Tagging reported an error.")

            # 5. Muxing (using av1an-mux.py)
            print("[Dispatch] Muxing...")
            try:
                subprocess.check_call([sys.executable, mux_script], cwd=temp_dir)
            except subprocess.CalledProcessError:
                print("[Dispatch] Muxing failed.")
                continue
                
            # 6. Move Final Output
            temp_output_mkv = os.path.join(temp_dir, f"{basename}-output.mkv")
            
            output_moved = False
            if os.path.exists(temp_output_mkv):
                print(f"[Dispatch] Moving final file to: {final_output_path}")
                try:
                    shutil.move(temp_output_mkv, final_output_path)
                    output_moved = True
                except Exception as e:
                    print(f"[Dispatch] Error moving output file: {e}")
            else:
                print(f"[Dispatch] Error: Expected output file not found: {temp_output_mkv}")

            if output_moved:
                newly_detected_files = scan_for_new_input_files(video_input_dir, extensions, known_input_files)
                if newly_detected_files:
                    warn_and_pause_if_paths_too_long(newly_detected_files, video_output_dir, temp_dir)
                    input_files.extend(newly_detected_files)
        
        except Exception as e:
            print(f"[Dispatch] Critical Error during processing: {e}")
            send_ntfy_notification(
                ntfy_settings,
                root_dir,
                tools_dir,
                "Auto-Boost encode failed",
                "An encode failed.",
            )

    send_ntfy_notification(
        ntfy_settings,
        root_dir,
        tools_dir,
        "Auto-Boost encode complete",
        "All queued encodes are complete.",
    )

    print("\n" + "="*80)
    print("Av1an Direct Batch Complete.")
    print("="*80)

if __name__ == "__main__":
    main()