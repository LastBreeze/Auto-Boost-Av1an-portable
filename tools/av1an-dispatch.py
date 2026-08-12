import sys
import subprocess
import os
import atexit
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glob
import json
import shutil
import shlex
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from wakepy import keep
from svt_fork_setup import setup_svt_av1_fork

BLUE = "\033[94m"
RED = "\033[91m"
RESET = "\033[0m"

PLUGIN_ENV_VAR = "VAPOURSYNTH_EXTRA_PLUGIN_PATH"


def vs_plugin_dir():
    """Absolute path to the package's vs-plugins folder, or "" if it is gone."""
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(root_dir, "VapourSynth", "vs-plugins")
    return candidate if os.path.isdir(candidate) else ""


def ensure_vs_plugin_path():
    """Point VapourSynth at the package's vs-plugins folder.

    VapourSynth used to run in portable mode: a portable.vs marker next to
    python.exe made the core autoload VapourSynth\\vs-plugins, which is where
    this package keeps ffms2, DFTTest, libvs_placebo and vszip. VapourSynth 78
    dropped that and reads VAPOURSYNTH_EXTRA_PLUGIN_PATH instead; without it
    the generated scripts fail with "No attribute with the name ffms2 exists".

    Child processes (av1an, vspipe, cropdetect) inherit the variable, so one
    call at startup covers the whole run.
    """
    found = vs_plugin_dir()
    if not found:
        return ""

    existing = [part for part in os.environ.get(PLUGIN_ENV_VAR, "").split(os.pathsep) if part]
    if not existing:
        # Set a single path: valid whether the core reads one path or a list.
        os.environ[PLUGIN_ENV_VAR] = found
    elif not any(os.path.normcase(part) == os.path.normcase(found) for part in existing):
        os.environ[PLUGIN_ENV_VAR] = os.pathsep.join(existing + [found])

    return found


ensure_vs_plugin_path()


def format_elapsed_hhmmss(seconds):
    """Format elapsed seconds as hh:mm:ss, allowing totals longer than 24 hours."""
    total_seconds = max(0, int(float(seconds) + 0.5))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def print_av1an_timing_report(report):
    print("\n" + "-" * 80)
    print(f"Av1an time report for: {report['filename']}")
    print("Time format legend: hh:mm:ss = hours:minutes:seconds")
    print(f"Av1an encoding time: {format_elapsed_hhmmss(report['av1an_encoding'])}")
    print("-" * 80)

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


def is_hdr_fork(fork):
    return (fork or "").strip().lower() in ("svt-av1-hdr", "hdr")


def parse_mediainfo_color_metadata(mediainfo_text):
    """Return detected color metadata from MediaInfo text."""
    metadata = {
        "primaries": "",
        "transfer": "",
        "matrix": "",
        "hdr_format": "",
        "chroma_position": "",
        "color_range_full": False,
        "mastering_primaries": "",
        "mastering_luminance": "",
        "max_cll": "",
        "max_fall": "",
        "is_bt709": False,
        "is_bt601": False,
        "is_hdr": False,
    }
    for line in mediainfo_text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key_l = key.strip().lower()
        value = value.strip()
        value_l = value.lower()
        if key_l == "color primaries":
            metadata["primaries"] = value
        elif key_l == "transfer characteristics":
            metadata["transfer"] = value
        elif key_l == "matrix coefficients":
            metadata["matrix"] = value
        elif key_l == "hdr format":
            metadata["hdr_format"] = value
        elif key_l == "chroma subsampling":
            type_match = re.search(r"type\s*(\d)", value_l)
            if type_match:
                metadata["chroma_position"] = type_match.group(1)
        elif key_l == "color range":
            metadata["color_range_full"] = value_l == "full"
        elif key_l == "mastering display color primaries":
            metadata["mastering_primaries"] = value
        elif key_l == "mastering display luminance":
            metadata["mastering_luminance"] = value
        elif key_l == "maximum content light level":
            metadata["max_cll"] = value
        elif key_l == "maximum frame-average light level":
            metadata["max_fall"] = value

    prim_l = metadata["primaries"].lower()
    trans_l = metadata["transfer"].lower()
    mat_l = metadata["matrix"].lower()
    hdr_format_l = metadata["hdr_format"].lower()
    metadata["is_bt709"] = (
        metadata["primaries"] == "BT.709"
        and metadata["transfer"] == "BT.709"
        and metadata["matrix"] == "BT.709"
    )
    metadata["is_bt601"] = "bt.601" in prim_l and "bt.601" in trans_l and "bt.601" in mat_l
    hdr_markers = (
        "hdr", "dolby vision", "smpte st 2084", "st 2084", "pq",
        "hlg", "arib std-b67", "bt.2020", "bt2020", "smpte 2086"
    )
    metadata["is_hdr"] = any(marker in hdr_format_l for marker in hdr_markers) or any(
        marker in text for text in (prim_l, trans_l, mat_l) for marker in hdr_markers
    )
    return metadata


# --- MediaInfo -> SVT-AV1-HDR color flag mapping (Appendix A.2 of the SVT-AV1 User Guide) ---

# CIE 1931 G/B/R coordinates for common mastering display primaries (white point D65).
KNOWN_MASTERING_PRIMARIES = {
    "display p3": "G(0.265,0.690)B(0.15,0.06)R(0.68,0.32)",
    "p3 d65": "G(0.265,0.690)B(0.15,0.06)R(0.68,0.32)",
    "dci p3": "G(0.265,0.690)B(0.15,0.06)R(0.68,0.32)",
    "p3": "G(0.265,0.690)B(0.15,0.06)R(0.68,0.32)",
    "bt.2020": "G(0.17,0.797)B(0.131,0.046)R(0.708,0.292)",
    "bt.2100": "G(0.17,0.797)B(0.131,0.046)R(0.708,0.292)",
    "bt.709": "G(0.30,0.60)B(0.15,0.06)R(0.64,0.33)",
}


def _format_nits(value):
    """4000.0 -> '4000', 0.0050 -> '0.005', 0.0001 -> '0.0001' (matches StaxRip-style output)."""
    return f"{value:g}"


def map_color_primaries_code(value):
    v = (value or "").lower()
    if "bt.2020" in v or "bt.2100" in v:
        return "9"
    if "bt.709" in v:
        return "1"
    if "display p3" in v or "p3 d65" in v or "smpte 432" in v or "smpte eg 432" in v:
        return "12"
    if "dci p3" in v or "p3 dci" in v or "smpte 431" in v or "smpte rp 431" in v:
        return "11"
    if "bt.601" in v:
        return "6"
    if "bt.470 system m" in v:
        return "4"
    if "bt.470" in v:
        return "5"
    if "smpte 240" in v:
        return "7"
    if "xyz" in v or "smpte 428" in v:
        return "10"
    if "ebu" in v:
        return "22"
    return None


def map_transfer_code(value):
    v = (value or "").lower()
    if "pq" in v or "2084" in v:
        return "16"
    if "hlg" in v or "b67" in v:
        return "18"
    if "bt.2020" in v:
        return "15" if "12" in v else "14"
    if "bt.709" in v:
        return "1"
    if "bt.601" in v:
        return "6"
    if "srgb" in v or "sycc" in v:
        return "13"
    if "smpte 428" in v or "st 428" in v:
        return "17"
    if "linear" in v:
        return "8"
    if "smpte 240" in v:
        return "7"
    if "bt.470 system m" in v:
        return "4"
    if "bt.470" in v:
        return "5"
    return None


def map_matrix_code(value):
    v = (value or "").lower()
    if "ictcp" in v:
        return "14"
    if "bt.2020" in v and "constant" in v and "non" not in v:
        return "10"
    if "bt.2020" in v or "bt.2100" in v:
        return "9"
    if "bt.709" in v:
        return "1"
    if "bt.601" in v:
        return "6"
    if "ycgco" in v:
        return "8"
    if "smpte 240" in v:
        return "7"
    if "fcc" in v:
        return "4"
    if "bt.470" in v:
        return "5"
    if "identity" in v:
        return "0"
    return None


def build_mastering_display_value(metadata):
    """Build the --mastering-display G(x,y)B(x,y)R(x,y)WP(x,y)L(max,min) value from MediaInfo text."""
    prim_text = (metadata.get("mastering_primaries") or "").strip()
    lum_text = (metadata.get("mastering_luminance") or "").strip()
    if not prim_text or not lum_text:
        return None

    gbr_wp = None
    # Coordinate form: "R: x=0.680000 y=0.320000, G: ..., B: ..., White point: x=... y=..."
    coords = re.findall(
        r"(R|G|B|White point)\s*:?\s*x\s*=?\s*([0-9.]+)[ ,;]+y\s*=?\s*([0-9.]+)",
        prim_text,
        re.IGNORECASE,
    )
    coord_map = {name.lower(): (x, y) for name, x, y in coords}
    if all(k in coord_map for k in ("g", "b", "r")):
        wp = coord_map.get("white point", ("0.3127", "0.329"))
        gbr_wp = (
            f"G({coord_map['g'][0]},{coord_map['g'][1]})"
            f"B({coord_map['b'][0]},{coord_map['b'][1]})"
            f"R({coord_map['r'][0]},{coord_map['r'][1]})"
            f"WP({wp[0]},{wp[1]})"
        )
    else:
        # Named form: "Display P3", "BT.2020", etc.
        prim_l = prim_text.lower()
        for name, value in KNOWN_MASTERING_PRIMARIES.items():
            if name in prim_l:
                gbr_wp = value + "WP(0.3127,0.329)"
                break
    if not gbr_wp:
        return None

    min_match = re.search(r"min\s*:\s*([0-9.]+)", lum_text, re.IGNORECASE)
    max_match = re.search(r"max\s*:\s*([0-9.]+)", lum_text, re.IGNORECASE)
    if not (min_match and max_match):
        return None
    try:
        l_max = _format_nits(float(max_match.group(1)))
        l_min = _format_nits(float(min_match.group(1)))
    except ValueError:
        return None
    return f"{gbr_wp}L({l_max},{l_min})"


def build_content_light_value(metadata):
    """Build the --content-light max_cll,max_fall value from MediaInfo text like '1 264 cd/m2'."""
    def _int_of(text):
        if not text:
            return None
        head = re.split(r"cd", text, flags=re.IGNORECASE)[0]
        digits = re.sub(r"[^\d]", "", head)
        return digits or None

    max_cll = _int_of(metadata.get("max_cll", ""))
    max_fall = _int_of(metadata.get("max_fall", ""))
    if max_cll and max_fall:
        return f"{max_cll},{max_fall}"
    return None


def build_hdr_color_flags(metadata):
    """Return the SVT-AV1-HDR color flag string for an HDR source, or None if
    the primaries/transfer/matrix could not be mapped. Values never contain
    spaces so they survive param-string whitespace splitting."""
    primaries_code = map_color_primaries_code(metadata.get("primaries", ""))
    transfer_code = map_transfer_code(metadata.get("transfer", ""))
    matrix_code = map_matrix_code(metadata.get("matrix", ""))
    if not (primaries_code and transfer_code and matrix_code):
        return None

    flags = (
        f" --color-primaries {primaries_code}"
        f" --transfer-characteristics {transfer_code}"
        f" --matrix-coefficients {matrix_code}"
    )
    if metadata.get("chroma_position") in ("1", "2"):
        flags += f" --chroma-sample-position {metadata['chroma_position']}"
    if metadata.get("color_range_full"):
        flags += " --color-range 1"
    mastering_display = build_mastering_display_value(metadata)
    if mastering_display:
        flags += f" --mastering-display {mastering_display}"
    content_light = build_content_light_value(metadata)
    if content_light:
        flags += f" --content-light {content_light}"
    return flags


def detect_color_metadata(input_path, mediainfo_exe):
    if not os.path.exists(mediainfo_exe):
        return None
    try:
        res = subprocess.run(
            [mediainfo_exe, input_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception as e:
        print(f"[Dispatch] Warning: MediaInfo color detection failed: {e}")
        return None
    if res.returncode != 0:
        print(f"[Dispatch] Warning: MediaInfo color detection failed with exit code {res.returncode}.")
        return None
    return parse_mediainfo_color_metadata(res.stdout)


def pause_for_hdr_color_settings(input_path, color_metadata):
    print("\n" + "=" * 80)
    print(f"{RED}[Dispatch] ERROR: HDR color settings are detected in the input file, but they could not be auto-mapped.{RESET}")
    print(f"{RED}[Dispatch] Input: {os.path.basename(input_path)}{RESET}")
    print(f"{RED}[Dispatch] You need to manually edit the color settings for your .bat file before using the SVT-AV1-HDR fork,{RESET}")
    print(f"{RED}[Dispatch] or set tonemap=True in the .bat to tonemap HDR to SDR.{RESET}")
    print(f"{RED}[Dispatch] Detected color settings:{RESET}")
    print(f"{RED}[Dispatch]   Color primaries: {color_metadata.get('primaries') or 'unknown'}{RESET}")
    print(f"{RED}[Dispatch]   Transfer characteristics: {color_metadata.get('transfer') or 'unknown'}{RESET}")
    print(f"{RED}[Dispatch]   Matrix coefficients: {color_metadata.get('matrix') or 'unknown'}{RESET}")
    if color_metadata.get("hdr_format"):
        print(f"{RED}[Dispatch]   HDR format: {color_metadata['hdr_format']}{RESET}")
    print("=" * 80)
    try:
        input("Press Enter to exit...")
    except EOFError:
        pass
    sys.exit(1)


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
            os.path.join(temp_dir, f"{basename}_scenedetect.zoned.json"),
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


# --- Original input filename bookkeeping ---
# Source videos are renamed to Python-safe names before anything else touches
# them. The name each file had beforehand is recorded here (and mirrored to a
# small JSON file inside video-input) so the file can be renamed back to it once
# that file is finished. A run that dies before it can restore leaves the record
# behind, and the next run picks it up and finishes the job.
ORIGINAL_NAMES_RECORD = ".original-input-names.json"

_ORIGINAL_INPUT_NAMES = {}     # absolute sanitized path -> original filename
_RESTORED_INPUT_NAMES = set()  # absolute restored paths, so rescans leave them alone


def _original_names_record_path(video_input_dir):
    return os.path.join(video_input_dir, ORIGINAL_NAMES_RECORD)


def _write_original_names_record(video_input_dir):
    """Mirror the in-memory record to disk so a killed run can still be undone."""
    entries = {
        os.path.basename(path): original
        for path, original in _ORIGINAL_INPUT_NAMES.items()
        if os.path.dirname(path) == video_input_dir
    }
    record_path = _original_names_record_path(video_input_dir)
    try:
        if entries:
            with open(record_path, "w", encoding="utf-8") as handle:
                json.dump(entries, handle, indent=2, ensure_ascii=False)
        elif os.path.exists(record_path):
            os.remove(record_path)
    except OSError as e:
        print(f"[Dispatch] Warning: could not update {ORIGINAL_NAMES_RECORD}: {e}")


def load_original_names_record(video_input_dir):
    """Adopt renames left behind by a previous run that never got to restore them."""
    record_path = _original_names_record_path(video_input_dir)
    if not os.path.isfile(record_path):
        return
    try:
        with open(record_path, "r", encoding="utf-8") as handle:
            entries = json.load(handle)
    except (OSError, ValueError) as e:
        print(f"[Dispatch] Warning: could not read {ORIGINAL_NAMES_RECORD}: {e}")
        return
    if not isinstance(entries, dict):
        return
    for current_name, original_name in entries.items():
        current_path = os.path.join(video_input_dir, current_name)
        if isinstance(original_name, str) and os.path.isfile(current_path):
            _ORIGINAL_INPUT_NAMES.setdefault(current_path, original_name)
    _write_original_names_record(video_input_dir)


def record_original_filename(video_input_dir, current_name, original_name):
    """Remember what a sanitized input file was called before it was renamed."""
    _ORIGINAL_INPUT_NAMES[os.path.join(video_input_dir, current_name)] = original_name
    _write_original_names_record(video_input_dir)


def restore_input_filename(current_path):
    """Rename a finished input file back to the name it arrived with.

    Returns the restored path, or None when there was nothing to restore.
    """
    original_name = _ORIGINAL_INPUT_NAMES.get(current_path)
    if not original_name:
        return None

    video_input_dir = os.path.dirname(current_path)
    if not os.path.isfile(current_path):
        # Moved or deleted while it was being processed - nothing left to rename.
        _ORIGINAL_INPUT_NAMES.pop(current_path, None)
        _write_original_names_record(video_input_dir)
        return None

    dst_path = os.path.join(video_input_dir, original_name)
    if os.path.exists(dst_path):
        same = False
        try:
            same = os.path.samefile(dst_path, current_path)
        except OSError:
            same = False
        if not same:
            print(f"{RED}[Dispatch] Warning: cannot restore {os.path.basename(current_path)} -> "
                  f"{original_name}: a different file already has that name.{RESET}")
            return None

    try:
        os.rename(current_path, dst_path)
    except OSError as e:
        print(f"{RED}[Dispatch] Warning: could not restore original filename "
              f"{original_name}: {e}{RESET}")
        return None

    _ORIGINAL_INPUT_NAMES.pop(current_path, None)
    _RESTORED_INPUT_NAMES.add(dst_path)
    _write_original_names_record(video_input_dir)
    print(f"[Dispatch] Restored original input filename: "
          f"{os.path.basename(current_path)} -> {original_name}")
    return dst_path


def restore_all_input_filenames():
    """Put back every input filename still recorded as renamed."""
    for current_path in sorted(_ORIGINAL_INPUT_NAMES):
        restore_input_filename(current_path)


def sanitize_filename_stem(stem):
    """Drop parentheses and turn every run of whitespace into a single dot.

    Square brackets are left alone - "[" and "]" are safe in a filename for the
    tools this dispatcher drives.
    """
    safe_stem = ".".join(stem.replace("(", " ").replace(")", " ").split())
    # A leading dot hides the file, Windows silently drops a trailing dot, and
    # runs of dots confuse extension parsing - normalize all three.
    safe_stem = re.sub(r"\.{2,}", ".", safe_stem).strip(".")
    return safe_stem or "video"


def sanitize_input_filenames(video_input_dir, extensions):
    """Drop parentheses and replace spaces with dots in supported video filenames.

    The original name of every renamed file is recorded so it can be restored
    once the encode for that file is finished (see restore_input_filenames).
    """
    supported_exts = {pattern[1:].lower() for pattern in extensions if pattern.startswith("*")}
    renamed = 0
    for filename in sorted(os.listdir(video_input_dir)):
        src_path = os.path.join(video_input_dir, filename)
        if not os.path.isfile(src_path):
            continue
        stem, ext = os.path.splitext(filename)
        if ext.lower() not in supported_exts:
            continue
        if src_path in _RESTORED_INPUT_NAMES:
            # Already processed and renamed back - do not sanitize it a second time.
            continue

        safe_stem = sanitize_filename_stem(stem)
        if f"{safe_stem}{ext}" == filename:
            continue

        dst_path = os.path.join(video_input_dir, f"{safe_stem}{ext}")
        suffix = 1
        while os.path.exists(dst_path):
            dst_path = os.path.join(video_input_dir, f"{safe_stem}_{suffix}{ext}")
            suffix += 1

        os.rename(src_path, dst_path)
        record_original_filename(video_input_dir, os.path.basename(dst_path), filename)
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


DEHALO_DEFAULTS = {
    "strength": 5,
    "rmode": 17,
    "hot": False,
    "smode": False,
    "edgemask": "Prewitt",
}

# AWarp rejects a warp depth outside -128..127. edge_cleaner adds 4 to strength
# when smode is on, so the usable ceiling drops by 4 in that mode.
DEHALO_STRENGTH_MAX = 127
DEHALO_SMODE_STRENGTH_MAX = DEHALO_STRENGTH_MAX - 4

# vsrgtools maps 1-24 onto the zsmooth Repair plugin and 26-28 onto expression
# fallbacks; 0 is a no-op and 25 is unimplemented.
DEHALO_RMODES = frozenset(list(range(0, 25)) + [26, 27, 28])

# Keys from the old dehalo_alpha implementation. They are silently ignored now,
# so say so rather than letting a stale settings.txt look like it still applies.
DEHALO_LEGACY_KEYS = ("dehalo_rx", "dehalo_ry", "dehalo_brightstr", "dehalo_darkstr",
                      "dehalo_lowsens", "dehalo_highsens", "dehalo_ss")

DEHALO_EDGEMASK_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def read_dehalo_int(value, key_name, default_value, minimum=None, maximum=None):
    """Validate a whole-number [dehalo] setting before it is written into the .vpy."""
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        print(f"[Dispatch] Warning: Invalid {key_name}={value!r}; using {default_value}.")
        return default_value
    if minimum is not None and parsed < minimum:
        print(f"[Dispatch] Warning: {key_name}={parsed} is below {minimum}; using {minimum}.")
        return minimum
    if maximum is not None and parsed > maximum:
        print(f"[Dispatch] Warning: {key_name}={parsed} is above {maximum}; using {maximum}.")
        return maximum
    return parsed


def read_dehalo_bool(settings, key_name, default_value=False):
    raw = get_script_setting(settings, key_name, str(default_value)).strip().lower()
    if raw in ("1", "true", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "no", "n", "off"):
        return False
    print(f"[Dispatch] Warning: Invalid {key_name}={raw!r}; using {default_value}.")
    return default_value


def read_dehalo_rmode(value):
    """Validate dehalo_rmode against the repair modes vsrgtools actually implements."""
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        print(f"[Dispatch] Warning: Invalid dehalo_rmode={value!r}; using 17.")
        return 17
    if parsed not in DEHALO_RMODES:
        print(f"[Dispatch] Warning: dehalo_rmode={parsed} is not a supported repair mode; using 17.")
        return 17
    return parsed


def read_dehalo_edgemask(value):
    """Validate dehalo_edgemask.

    The name is written into the generated .vpy as a string literal, so it is
    restricted to a bare identifier. Whether that identifier is a real
    vsmasktools edge detector is resolved inside the .vpy, which keeps this
    working across vsmasktools versions that add or rename detectors.
    """
    name = str(value).strip()
    if not name:
        return "Prewitt"
    if not DEHALO_EDGEMASK_RE.match(name):
        print(f"[Dispatch] Warning: Invalid dehalo_edgemask={value!r}; using Prewitt.")
        return "Prewitt"
    return name


def warn_dehalo_legacy_keys(settings):
    """Warn about [dehalo] keys left over from the dehalo_alpha implementation."""
    stale = [key for key in DEHALO_LEGACY_KEYS if key in settings]
    if stale:
        print(f"[Dispatch] Warning: settings.txt [dehalo] still has {', '.join(stale)}; "
              "these are ignored since dehalo now uses edge_cleaner.")


def read_dehalo_settings(settings):
    """Return the validated [dehalo] values used by the VapourSynth template."""
    warn_dehalo_legacy_keys(settings)
    smode = read_dehalo_bool(settings, "dehalo_smode", False)
    strength_max = DEHALO_SMODE_STRENGTH_MAX if smode else DEHALO_STRENGTH_MAX
    return {
        "strength": read_dehalo_int(get_script_setting(settings, "dehalo_strength", "5"), "dehalo_strength", 5, minimum=0, maximum=strength_max),
        "rmode": read_dehalo_rmode(get_script_setting(settings, "dehalo_rmode", "17")),
        "hot": read_dehalo_bool(settings, "dehalo_hot", False),
        "smode": smode,
        "edgemask": read_dehalo_edgemask(get_script_setting(settings, "dehalo_edgemask", "Prewitt")),
    }


def dehalo_filter_state(do_dehalo, dehalo_values):
    """Compact [dehalo] description for the .vpy cache-invalidation marker.

    The parameters are part of the marker so that changing one rebuilds a cached
    .vpy; with only the on/off state in there, a strength change would silently
    reuse the old script.
    """
    if not do_dehalo:
        return "False"
    values = dehalo_values or DEHALO_DEFAULTS
    return ("edge_cleaner(strength={strength},rmode={rmode},hot={hot},"
            "smode={smode},edgemask={edgemask})").format(**values)


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


def report_filter_status(do_downscale, target_res, kernel, do_denoise, denoise_setting, do_deband, deband_setting, do_dehalo=False, dehalo_values=None):
    active_filters = []
    if do_downscale:
        active_filters.append(f"downscale: target_resolution={target_res}, kernel_type={kernel}")
    if do_dehalo and dehalo_values:
        active_filters.append(
            "dehalo (edge_cleaner): strength={strength}, rmode={rmode}, hot={hot}, "
            "smode={smode}, edgemask={edgemask}".format(**dehalo_values)
        )
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


def build_vapoursynth_script(source_path, temp_dir, tools_dir, settings, autocrop, convert_yuv420p10=False, tonemap=False):
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
    do_dehalo = setting_is_true(settings, "dehalo", "False")
    dehalo_values = read_dehalo_settings(settings) if do_dehalo else None
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

    # Marker written into the generated .vpy so a cached script is rebuilt whenever a
    # settings.txt filter is toggled. Without it an existing .vpy is reused as-is and a
    # newly enabled filter would silently never run.
    filter_state_marker = (
        f"# Filter state: dehalo={dehalo_filter_state(do_dehalo, dehalo_values)}, "
        f"denoise={do_denoise}, deband={do_deband}"
    )

    rebuild_vpy = not os.path.exists(vpy_file)
    if not rebuild_vpy:
        try:
            with open(vpy_file, "r", encoding="utf-8", errors="replace") as f:
                existing_vpy_text = f.read()
            if r'\"' in existing_vpy_text:
                print(f"[Dispatch] Existing VapourSynth script has legacy escaped quotes; rebuilding: {vpy_file}")
                rebuild_vpy = True
            elif ("do_tonemap = True" in existing_vpy_text) != bool(tonemap):
                print(f"[Dispatch] Existing VapourSynth script tonemap state differs; rebuilding: {vpy_file}")
                rebuild_vpy = True
            elif filter_state_marker not in existing_vpy_text:
                print(f"[Dispatch] Existing VapourSynth script filter state differs; rebuilding: {vpy_file}")
                rebuild_vpy = True
            elif "_plugin_dir" not in existing_vpy_text:
                # Written before the vs-plugins fallback existed; on VapourSynth
                # 78 it would fail to find ffms2.
                print(f"[Dispatch] Existing VapourSynth script predates the plugin fallback; rebuilding: {vpy_file}")
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
        report_filter_status(do_downscale, target_res, kernel, do_denoise, denoise_setting, do_deband, deband_setting, do_dehalo, dehalo_values)

        denoise_line = denoise_setting if do_denoise and denoise_setting else ""
        deband_line = deband_setting if do_deband and deband_setting else ""
        # Placeholders still need values when dehalo is off; the block is gated on do_dehalo.
        dehalo_args = dehalo_values or DEHALO_DEFAULTS

        vpy_template = """
from vstools import vs, core, initialize_clip, finalize_clip
try:
    from vsdenoise import DFTTest
except Exception:
    DFTTest = None
core.max_cache_size = 1024
{filter_state}

# VapourSynth 78 dropped the portable.vs autoload of the package's vs-plugins
# folder, so ffms2/DFTTest/placebo/vszip are loaded by hand when the core did
# not pick them up on its own. A no-op on installs that still autoload.
import os as _os
_plugin_dir = r"{plugin_dir}"
if _plugin_dir and not hasattr(core, "ffms2") and _os.path.isdir(_plugin_dir):
    for _dll in sorted(_os.listdir(_plugin_dir)):
        if _dll.lower().endswith(".dll"):
            try:
                core.std.LoadPlugin(_os.path.join(_plugin_dir, _dll))
            except Exception:
                pass

# Load Source
src = core.ffms2.Source(source=r"{source}", cachefile=r"{cache}")

# Conversion
if {convert}:
    src = src.resize.Bicubic(format=vs.YUV420P10)

# Initialize (Fixes Placebo bitdepth error by ensuring 16-bit)
src = initialize_clip(src)

# Tonemap HDR -> SDR (libplacebo; libvs_placebo.dll autoloads from the plugins directory)
do_tonemap = {tonemap}
if do_tonemap:
    src = core.fmtc.bitdepth(src, bits=16)
    src = core.placebo.Tonemap(src, src_csp=1, dst_csp=0, dynamic_peak_detection=1, gamut_mapping=1, tone_mapping_function=1, metadata=0, contrast_recovery=0.0, smoothing_period=20.0, percentile=100.0)
    # Tonemap returns RGB or 4:4:4 output; SVT-AV1 only supports 4:2:0, so convert
    # back to YUV420P16 here. finalize_clip then produces the same 10-bit
    # YUV420P10 output as the non-tonemap pipeline.
    if src.format.color_family == vs.RGB:
        src = src.resize.Bicubic(format=vs.YUV420P16, matrix_s="709")
    elif src.format.id != vs.YUV420P16:
        src = src.resize.Bicubic(format=vs.YUV420P16)
    src = src.std.SetFrameProps(_Matrix=1, _Transfer=1, _Primaries=1)

# DEHALO (settings.txt [dehalo]; always runs before denoise)
do_dehalo = {dehalo}
if do_dehalo:
    from vsdehalo import edge_cleaner
    from vsmasktools import EdgeDetect, Prewitt
    # edge_cleaner warps edges via awarpsharp, which needs the AWarp plugin.
    if not hasattr(core, "awarp"):
        raise RuntimeError(
            "dehalo=True needs the AWarp plugin: put AWarp.dll in VapourSynth/vs-plugins, "
            "or set dehalo=False in settings.txt."
        )
    try:
        dehalo_edgemask = EdgeDetect.ensure_obj("{dh_edgemask}")
    except Exception:
        print("[dehalo] Unknown dehalo_edgemask '{dh_edgemask}'; using Prewitt.")
        dehalo_edgemask = Prewitt
    src = edge_cleaner(
        src,
        strength={dh_strength},
        rmode={dh_rmode},
        hot={dh_hot},
        smode={dh_smode},
        edgemask=dehalo_edgemask,
    )

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
                plugin_dir=vs_plugin_dir(),
                ct=crop_top,
                cb=crop_bottom,
                cl=crop_left,
                cr=crop_right,
                downscale=str(do_downscale),
                target_res=target_res,
                kernel=kernel,
                convert=str(convert_yuv420p10),
                tonemap=str(bool(tonemap)),
                denoise_line=denoise_line,
                deband_line=deband_line,
                dehalo=str(do_dehalo),
                dh_strength=dehalo_args["strength"],
                dh_rmode=dehalo_args["rmode"],
                dh_hot=str(bool(dehalo_args["hot"])),
                dh_smode=str(bool(dehalo_args["smode"])),
                dh_edgemask=dehalo_args["edgemask"],
                filter_state=filter_state_marker,
            ))
        if tonemap:
            print(f"{BLUE}[Dispatch] Filter active: tonemap HDR -> SDR (BT.709) via libplacebo{RESET}")
        print(f"[Dispatch] Built VapourSynth script: {vpy_file}")
    else:
        existing_crop_values = parse_crop_values_from_vpy(vpy_file) or (0, 0, 0, 0)
        report_crop_status(crop_mode, *existing_crop_values)
        report_filter_status(do_downscale, target_res, kernel, do_denoise, denoise_setting, do_deband, deband_setting, do_dehalo, dehalo_values)
        print(f"[Dispatch] Reusing existing VapourSynth script: {vpy_file}")

    return vpy_file


def resolve_fgs_table_path(param_str, root_dir, tools_dir=None):
    """Rewrite any relative '--fgs-table <path>' in an encoder params string
    to an absolute path so av1an worker processes (which run in their own
    working directories) can find the table file.

    Relative paths are resolved against the portable package root first,
    then the tools directory, then the current working directory. The
    resolved path uses forward slashes (accepted by Windows and safe for
    av1an's shell-style splitting of --video-params) and is double-quoted
    only when it contains whitespace.
    """
    if not param_str or "--fgs-table" not in param_str:
        return param_str

    pattern = re.compile(r'(--fgs-table[ \t]+)("([^"]*)"|\'([^\']*)\'|(\S+))')

    def _repl(match):
        raw = match.group(3) or match.group(4) or match.group(5) or ""
        if not raw:
            return match.group(0)
        if os.path.isabs(raw):
            resolved = os.path.abspath(raw)
        else:
            candidates = [os.path.join(root_dir, raw)]
            if tools_dir:
                candidates.append(os.path.join(tools_dir, raw))
            candidates.append(os.path.abspath(raw))
            resolved = next((c for c in candidates if os.path.isfile(c)), candidates[0])
            resolved = os.path.abspath(resolved)
        if not os.path.isfile(resolved):
            print(f"{RED}[Dispatch] WARNING: film grain table not found: {resolved}{RESET}")
            print(f"{RED}[Dispatch]          Place '{raw}' in the package root next to the .bat file.{RESET}")
        resolved = resolved.replace("\\", "/")
        if any(ch.isspace() for ch in resolved):
            resolved = f'"{resolved}"'
        print(f"[Dispatch] Resolved film grain table path: {resolved}")
        return match.group(1) + resolved

    return pattern.sub(_repl, param_str)


# --- ZONES SUPPORT ---
# A zones.txt overrides encoder settings for individual frame ranges. The file
# is discovered exactly the way Auto-Boost-Av1an.py discovers it: an sXXeXX tag
# in the input filename maps to <sxxexx>-zones.txt sitting next to the video.
#
# av1an's own --zones flag is not usable here. av1an only parses a zones file
# on the code path where it runs scene detection itself; when it is handed a
# finished scenes JSON with -s it loads that file and never looks at --zones
# (av1an-core/src/context.rs, split_routine). We always pass -s, so the zone
# overrides are baked into a copy of the scenes JSON instead.

# Flags av1an consumes itself when parsing a zone line. They are not encoder
# parameters, so they are pulled out of video_params and mapped to the matching
# zone_overrides fields.
AV1AN_ZONE_FLAGS = (
    "--photon-noise",
    "--photon-noise-width",
    "--photon-noise-height",
    "--chroma-noise",
    "--extra-split",
    "-x",
    "--min-scene-len",
    "--passes",
)

ZONE_LEADING_FRAMES_RE = re.compile(r"^(\s*)(\d+)(\s+)(-?\d+)")

# Shorter than this and a chunk is not worth encoding on its own.
MIN_USEFUL_SCENE_FRAMES = 5


def find_zones_file(video_path):
    """Return the sXXeXX-zones.txt that belongs to this input, or None.

    Example: 'Awesome Show - S01E02 1080p.mkv' -> 's01e02-zones.txt'
    """
    match = re.search(r"([sS]\d{2}[eE]\d{2})", Path(video_path).stem)
    if not match:
        return None
    zones_path = os.path.join(
        os.path.dirname(os.path.abspath(video_path)),
        f"{match.group(1).lower()}-zones.txt",
    )
    return zones_path if os.path.isfile(zones_path) else None


def split_param_string(param_str):
    """Split an encoder parameter string into argv-style tokens."""
    if not param_str:
        return []
    try:
        return shlex.split(param_str)
    except ValueError:
        return param_str.split()


def parse_param_tokens(tokens):
    """['--crf', '26', '--tune=2'] -> {'--crf': '26', '--tune': '2'} (order kept)."""
    params = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if not token.startswith("-"):
            i += 1
            continue
        if "=" in token:
            key, value = token.split("=", 1)
            params[key] = value
            i += 1
        elif i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
            params[token] = tokens[i + 1]
            i += 2
        else:
            params[token] = None
            i += 1
    return params


def param_dict_to_tokens(params):
    tokens = []
    for key, value in params.items():
        tokens.append(key)
        if value is not None:
            tokens.append(value)
    return tokens


def merge_zone_params(base_tokens, zone_tokens, reset):
    """Merge a zone's parameters over the base encoder parameters.

    Returns (video_params, av1an_flags). With 'reset' on the zone line the base
    parameters are dropped instead of inherited, matching av1an's own handling.
    """
    if reset:
        merged = {}
    else:
        merged = {
            key: value
            for key, value in parse_param_tokens(base_tokens).items()
            if key not in AV1AN_ZONE_FLAGS
        }
    av1an_flags = {}
    for key, value in parse_param_tokens(zone_tokens).items():
        if key in AV1AN_ZONE_FLAGS:
            av1an_flags[key] = value
        else:
            merged[key] = value
    return param_dict_to_tokens(merged), av1an_flags


def build_zone_overrides(base_tokens, zone, base_photon_noise):
    """Build the zone_overrides object av1an expects inside a scenes JSON."""
    video_params, av1an_flags = merge_zone_params(base_tokens, zone["params"], zone["reset"])

    def int_flag(*names, default=None):
        for name in names:
            value = av1an_flags.get(name)
            if value is None:
                continue
            try:
                return int(value)
            except ValueError:
                print(f"{RED}[Dispatch] Warning: zone line {zone['lineno']} has a non-numeric {name}; ignoring it.{RESET}")
        return default

    photon_noise = int_flag("--photon-noise")
    if photon_noise is None and not zone["reset"]:
        photon_noise = base_photon_noise
    chroma_noise = parse_bool_setting(av1an_flags.get("--chroma-noise"), default=False)

    return {
        "encoder": "svt_av1",
        "passes": int_flag("--passes", default=1),
        "video_params": video_params,
        "photon_noise": photon_noise if photon_noise else None,
        "photon_noise_height": int_flag("--photon-noise-height"),
        "photon_noise_width": int_flag("--photon-noise-width"),
        "chroma_noise": chroma_noise,
        # av1an's own defaults; the scenes are already split, so these only
        # travel with the override object.
        "extra_splits_len": int_flag("-x", "--extra-split", default=240),
        "min_scene_len": int_flag("--min-scene-len", default=24),
        "target_quality": None,
    }


def load_zones_file(zones_path, total_frames, scene_cuts=()):
    """Read a zones.txt, repair ranges av1an cannot use, and save the repairs.

    av1an's end_frame is exclusive, so two ranges that are meant to run
    back-to-back have to share a frame number:

        right:  90 100 svt-av1 --crf 20
                100 200 svt-av1 --crf 25
        wrong:  90 100 svt-av1 --crf 20
                101 200 svt-av1 --crf 25

    The 'wrong' form leaves frame 100 in neither zone, so av1an encodes it as a
    one-frame chunk with the base settings. A genuine overlap is worse: av1an
    bails with "Zones file contains overlapping zones". Both are fixed here and
    written back to the file (the original is kept as <name>.bak), so AfterZone
    and any later run see the corrected ranges too.

    scene_cuts is the set of frames scene detection already splits on. When a
    one-frame gap can be closed on one of those frames, it is closed there, so
    the junction lands on a real cut instead of slicing a one-frame chunk off
    the scene next to it.
    """
    with open(zones_path, "r", encoding="utf-8", errors="replace") as f:
        raw_lines = f.read().splitlines()

    zones = []
    for index, raw_line in enumerate(raw_lines):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lineno = index + 1
        parts = line.split(maxsplit=3)
        if len(parts) < 3:
            print(f"{RED}[Dispatch] Warning: skipping zone line {lineno} (needs 'start end encoder [params]').{RESET}")
            continue
        try:
            start = int(parts[0])
            end_raw = int(parts[1])
        except ValueError:
            print(f"{RED}[Dispatch] Warning: skipping zone line {lineno} (frame numbers are not integers).{RESET}")
            continue

        tokens = split_param_string(parts[3]) if len(parts) > 3 else []
        reset = bool(tokens) and tokens[0] == "reset"
        if reset:
            tokens = tokens[1:]

        if start >= total_frames:
            print(f"{RED}[Dispatch] Warning: skipping zone line {lineno} (starts at {start}, past the last frame {total_frames}).{RESET}")
            continue
        end = total_frames if end_raw == -1 else end_raw
        if end > total_frames:
            print(f"{RED}[Dispatch] Warning: zone line {lineno} ends at {end}, past the last frame; clamping to {total_frames}.{RESET}")
            end = total_frames
        if start >= end:
            print(f"{RED}[Dispatch] Warning: skipping zone line {lineno} (start {start} is not before end {end}).{RESET}")
            continue

        zones.append({
            "start": start,
            "end": end,
            "params": tokens,
            "reset": reset,
            "lineno": lineno,
            "raw_index": index,
            "orig_start": start,
            "orig_end_raw": end_raw,
            "orig_end": end,
        })

    zones.sort(key=lambda zone: zone["start"])

    for current, following in zip(zones, zones[1:]):
        if current["end"] == following["start"] - 1:
            # end_frame is exclusive: back-to-back ranges share a frame number.
            # Prefer the side that is already a scene cut, otherwise pull the
            # later zone's start back onto the earlier zone's end.
            if following["start"] in scene_cuts and current["end"] not in scene_cuts:
                print(f"{BLUE}[Dispatch] Zone line {current['lineno']}: end {current['end']} -> {following['start']} "
                      f"(closing the one-frame gap before zone line {following['lineno']} on a scene cut; "
                      f"end_frame is exclusive).{RESET}")
                current["end"] = following["start"]
            else:
                print(f"{BLUE}[Dispatch] Zone line {following['lineno']}: start {following['start']} -> {current['end']} "
                      f"(closing the one-frame gap after zone line {current['lineno']}; end_frame is exclusive).{RESET}")
                following["start"] = current["end"]
        elif current["end"] > following["start"]:
            print(f"{RED}[Dispatch] Warning: zone line {current['lineno']} overlaps zone line {following['lineno']}; "
                  f"trimming its end {current['end']} -> {following['start']}.{RESET}")
            current["end"] = following["start"]

    zones = [zone for zone in zones if zone["start"] < zone["end"]]

    changed = [
        zone for zone in zones
        if zone["start"] != zone["orig_start"] or zone["end"] != zone["orig_end"]
    ]
    if changed:
        backup_path = zones_path + ".bak"
        try:
            shutil.copyfile(zones_path, backup_path)
        except Exception as e:
            print(f"{RED}[Dispatch] Warning: Could not back up {os.path.basename(zones_path)} ({e}); leaving it unedited.{RESET}")
        else:
            for zone in changed:
                keep_minus_one = zone["orig_end_raw"] == -1 and zone["end"] == zone["orig_end"]
                end_text = "-1" if keep_minus_one else str(zone["end"])
                raw_lines[zone["raw_index"]] = ZONE_LEADING_FRAMES_RE.sub(
                    lambda m, zone=zone, end_text=end_text: f"{m.group(1)}{zone['start']}{m.group(3)}{end_text}",
                    raw_lines[zone["raw_index"]],
                    count=1,
                )
            with open(zones_path, "w", encoding="utf-8", newline="\r\n") as f:
                f.write("\n".join(raw_lines) + "\n")
            print(f"{BLUE}[Dispatch] Rewrote {len(changed)} zone line(s) in {os.path.basename(zones_path)} "
                  f"(original saved as {os.path.basename(backup_path)}).{RESET}")

    return zones


def apply_zones_to_scene_list(scenes, zones, base_tokens, base_photon_noise):
    """Cut each zone out of the scene list and give the cut-out part its overrides."""
    for zone in zones:
        overrides = build_zone_overrides(base_tokens, zone, base_photon_noise)
        new_scenes = []
        for scene in scenes:
            scene_start = scene["start_frame"]
            scene_end = scene["end_frame"]
            if scene_start >= zone["end"] or zone["start"] >= scene_end:
                new_scenes.append(scene)
                continue
            if scene_start < zone["start"]:
                new_scenes.append({**scene, "end_frame": zone["start"]})
            new_scenes.append({
                **scene,
                "start_frame": max(scene_start, zone["start"]),
                "end_frame": min(scene_end, zone["end"]),
                "zone_overrides": overrides,
            })
            if scene_end > zone["end"]:
                new_scenes.append({**scene, "start_frame": zone["end"]})
        scenes = new_scenes
    scenes.sort(key=lambda scene: scene["start_frame"])
    return scenes


def merge_sliver_scenes(scenes):
    """Absorb chunks too short to encode on their own into the neighbouring chunk
    that already carries the same settings.

    A zone edge landing a frame or two before a scene cut slices a sliver off
    the scene next to it: zone 4053-4641 against a cut at 4643 leaves a 2-frame
    chunk at 4641-4643. That sliver is the leftover of the following scene and
    still has that scene's settings, so the chunk boundary can simply be moved
    up against the zone edge. Nothing about how a frame is encoded changes;
    only the chunk it belongs to.

    Merging is refused when the two chunks disagree on settings, so a sliver
    between two different zones is reported instead of being silently
    re-encoded with the wrong parameters.

    Returns (scenes, fixes).
    """
    merged = []
    fixes = []
    for scene in scenes:
        previous = merged[-1] if merged else None
        if previous is not None and previous["zone_overrides"] == scene["zone_overrides"]:
            previous_frames = previous["end_frame"] - previous["start_frame"]
            scene_frames = scene["end_frame"] - scene["start_frame"]
            if min(previous_frames, scene_frames) < MIN_USEFUL_SCENE_FRAMES:
                sliver = previous if previous_frames < scene_frames else scene
                fixes.append({
                    "start": sliver["start_frame"],
                    "end": sliver["end_frame"],
                    "frames": min(previous_frames, scene_frames),
                    "new_start": previous["start_frame"],
                    "new_end": scene["end_frame"],
                })
                previous["end_frame"] = scene["end_frame"]
                continue
        merged.append(dict(scene))
    return merged, fixes


def zoned_scenes_path(scenes_json_path):
    root, ext = os.path.splitext(scenes_json_path)
    return f"{root}.zoned{ext}"


def remove_stale_zoned_scenes(scenes_json_path):
    stale_path = zoned_scenes_path(scenes_json_path)
    if os.path.exists(stale_path):
        try:
            os.remove(stale_path)
            print(f"[Dispatch] Removed stale zoned scenes file: {os.path.basename(stale_path)}")
        except Exception as e:
            print(f"[Dispatch] Warning: Could not remove stale zoned scenes file: {e}")


def apply_zones_file(input_path, scenes_json_path, encoder_params, photon_noise):
    """Bake a matching zones.txt into a copy of the scenes JSON.

    Returns the scenes file av1an should be given: the zoned copy when zones
    were applied, otherwise the untouched scene detection JSON.
    """
    zones_path = find_zones_file(input_path)
    if not zones_path:
        remove_stale_zoned_scenes(scenes_json_path)
        return scenes_json_path

    print(f"{BLUE}[Dispatch] Zones file found: {os.path.basename(zones_path)}{RESET}")
    if not os.path.exists(scenes_json_path):
        print(f"{RED}[Dispatch] Warning: Scenes file missing, so zones cannot be applied: {scenes_json_path}{RESET}")
        return scenes_json_path

    with open(scenes_json_path, "r", encoding="utf-8") as f:
        scenes_data = json.load(f)

    total_frames = scenes_data.get("frames")
    if not isinstance(total_frames, int) or total_frames <= 0:
        print(f"{RED}[Dispatch] Warning: Scenes file has no usable frame count; skipping zones.{RESET}")
        return scenes_json_path

    scene_cuts = {
        scene["start_frame"]
        for key in ("split_scenes", "scenes")
        for scene in scenes_data.get(key) or []
    }
    scene_cuts.add(total_frames)

    zones = load_zones_file(zones_path, total_frames, scene_cuts)
    if not zones:
        print(f"{RED}[Dispatch] Warning: No usable zone lines in {os.path.basename(zones_path)}; encoding without zones.{RESET}")
        remove_stale_zoned_scenes(scenes_json_path)
        return scenes_json_path

    base_tokens = split_param_string(encoder_params)
    try:
        base_photon_noise = int(str(photon_noise).strip())
    except (TypeError, ValueError):
        base_photon_noise = 0

    zones_filename = os.path.basename(zones_path)
    print(f"{BLUE}[Dispatch] Applying zones file: {zones_filename} "
          f"({len(zones)} zone(s), end frame is exclusive){RESET}")
    for zone in zones:
        summary = " ".join(zone["params"]) or "(no parameter changes)"
        reset_note = " reset" if zone["reset"] else ""
        print(f"{BLUE}[Dispatch]   frames {zone['start']}-{zone['end']}{reset_note}: {summary}{RESET}")

    # av1an encodes from split_scenes; scenes is kept in step so the file stays coherent.
    sliver_fixes = []
    for key in ("scenes", "split_scenes"):
        if isinstance(scenes_data.get(key), list):
            zoned = apply_zones_to_scene_list(
                scenes_data[key], zones, base_tokens, base_photon_noise
            )
            scenes_data[key], fixes = merge_sliver_scenes(zoned)
            if key == "split_scenes":
                sliver_fixes = fixes

    for fix in sliver_fixes:
        print(f"{BLUE}[Dispatch] Zone edge left a {fix['frames']}-frame chunk at frames "
              f"{fix['start']}-{fix['end']}; moved the chunk boundary up against the zone, "
              f"so that chunk now runs {fix['new_start']}-{fix['new_end']} with its existing settings.{RESET}")

    # Anything still too short disagrees with both neighbours on settings, so it
    # cannot be absorbed without changing how those frames are encoded.
    for scene in scenes_data.get("split_scenes") or []:
        length = scene["end_frame"] - scene["start_frame"]
        if length >= MIN_USEFUL_SCENE_FRAMES:
            continue
        where = f"frames {scene['start_frame']}-{scene['end_frame']}"
        if scene["zone_overrides"]:
            print(f"{RED}[Dispatch] Warning: the zone at {where} is only {length} frame(s) long and is encoded as its own "
                  f"chunk. Widen that range in the zones file if that was not intended.{RESET}")
        else:
            print(f"{RED}[Dispatch] Warning: a {length}-frame chunk remains at {where}, between two zones that use "
                  f"different settings, so it cannot be absorbed. Close that gap in the zones file to remove it.{RESET}")

    output_path = zoned_scenes_path(scenes_json_path)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(scenes_data, f, indent=2)

    print(f"[Dispatch] Wrote zoned scenes file: {output_path}")
    print(f"{BLUE}[Dispatch] Zones from {zones_filename} are applied to this encode.{RESET}")
    return output_path


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
    mediainfo_exe = os.path.join(tools_dir, "MediaInfo_CLI", "MediaInfo.exe")
    
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
    
    crf = "30"
    workers = "1"
    photon_noise = "0"
    final_speed = "4"
    final_params = ""
    resume = False
    selected_fork = "essential"
    arch = "x86-64-v3"
    denoise_setting = None
    autocrop = False
    convert_yuv420p10 = False
    tonemap_enabled = False
    
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--tonemap":
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                tonemap_enabled = parse_bool_setting(args[i + 1])
                i += 2
            else:
                tonemap_enabled = True
                i += 1
        elif arg == "--fork" and i + 1 < len(args):
            selected_fork = args[i+1]
            i += 2
        elif arg == "--arch" and i + 1 < len(args) and not args[i + 1].startswith("--"):
            arch = args[i + 1]
            i += 2
        elif arg == "--avx512":
            # Kept for .bat files generated before ARCH replaced AVX512.
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                arch = "avx512" if parse_bool_setting(args[i + 1]) else "x86-64-v3"
                i += 2
            else:
                arch = "avx512"
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
        elif arg in ("--crf", "--quality") and i + 1 < len(args):
            crf = args[i+1]
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

    # Rewrite relative --fgs-table paths in the encoder params to absolute
    # paths anchored at the package root, so SvtAv1EncApp can open the table
    # regardless of the working directory av1an spawns its workers in.
    final_params = resolve_fgs_table_path(final_params, root_dir, tools_dir)

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

    setup_svt_av1_fork(tools_dir, selected_fork, arch=arch, verbose=True)
            
    # --- Gather Input Files ---
    extensions = ("*.mkv", "*.mp4", "*.m2ts")
    load_original_names_record(video_input_dir)
    # Backstop for Ctrl-C and unhandled errors: every recorded rename still gets
    # undone on the way out, not only after a clean finish.
    atexit.register(restore_all_input_filenames)
    sanitize_input_filenames(video_input_dir, extensions)
    input_files = gather_input_files(video_input_dir, extensions)
    known_input_files = set(input_files)
    
    if not input_files:
        print(f"[Dispatch] No video files found in {video_input_dir}")
        sys.exit(0)

    warn_and_pause_if_paths_too_long(input_files, video_output_dir, temp_dir)
        
    print(f"[Dispatch] Found {len(input_files)} files to process.")

    # --- Main Processing Loop ---
    timing_reports = []
    batch_started_at = time.monotonic()
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
            restore_input_filename(input_abspath_origin)
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

            # 2. Color Space Detection / HDR handling
            color_metadata = detect_color_metadata(input_abspath_origin, mediainfo_exe)
            is_bt709 = bool(color_metadata and color_metadata["is_bt709"])
            is_bt601 = bool(color_metadata and color_metadata["is_bt601"])
            is_hdr_source = bool(color_metadata and color_metadata["is_hdr"])
            tonemap_this_file = tonemap_enabled and is_hdr_source

            bt709_flags = " --color-primaries 1 --transfer-characteristics 1 --matrix-coefficients 1"
            bt601_flags = " --color-primaries 6 --transfer-characteristics 6 --matrix-coefficients 6"
            current_color_flags = ""
            if tonemap_this_file:
                # Tonemapped output is SDR BT.709.
                current_color_flags = bt709_flags
                print(f"{BLUE}[Dispatch] HDR source detected; tonemapping HDR to SDR (BT.709) via libplacebo.{RESET}")
            elif is_hdr_source and is_hdr_fork(selected_fork):
                # Auto detect: build SVT-AV1-HDR color settings from MediaInfo.
                hdr_flags = build_hdr_color_flags(color_metadata)
                if hdr_flags:
                    current_color_flags = hdr_flags
                    print(f"{BLUE}[Dispatch] HDR source detected; auto-applying SVT-AV1-HDR color settings:{RESET}")
                    print(f"{BLUE}[Dispatch]  {hdr_flags.strip()}{RESET}")
                else:
                    pause_for_hdr_color_settings(input_abspath_origin, color_metadata)
            elif is_hdr_source:
                print(f"{BLUE}[Dispatch] HDR source detected. This fork encodes it as-is (set tonemap=True in the .bat to tonemap to SDR).{RESET}")
            elif is_bt709:
                current_color_flags = bt709_flags
                if is_hdr_fork(selected_fork):
                    print("[Dispatch] MediaInfo confirmed full BT.709 source; copying BT.709 color settings for SVT-AV1-HDR fork.")
                else:
                    print("[Dispatch] MediaInfo confirmed full BT.709 source.")
            elif is_bt601:
                current_color_flags = bt601_flags
                print("[Dispatch] MediaInfo confirmed full BT.601 source.")

            # 3. Build VapourSynth input script from settings.txt
            vpy_abspath = build_vapoursynth_script(
                input_abspath_origin,
                temp_dir,
                tools_dir,
                settings,
                autocrop=autocrop,
                convert_yuv420p10=convert_yuv420p10,
                tonemap=tonemap_this_file,
            )

            # 3. Encoding (Direct Av1an Call)
            av1_output = f"{basename}-av1.mkv"
            
            # Construct Encoder Parameters (-v)
            # Combine CRF, preset, and the batch settings
            encoder_params = f"--crf {crf} --preset {final_speed} {final_params}"
            if current_color_flags:
                encoder_params += current_color_flags
            
            # Clean up double spaces if any
            encoder_params = " ".join(encoder_params.split())

            # 3b. Zones: bake any matching <sxxexx>-zones.txt into a copy of the
            # scenes JSON. Zones inherit encoder_params, so this has to run after
            # the color flags are folded in above.
            scenes_for_av1an = json_abspath
            try:
                scenes_for_av1an = apply_zones_file(
                    input_abspath_origin, json_abspath, encoder_params, photon_noise
                )
            except Exception as e:
                print(f"{RED}[Dispatch] Warning: Could not apply zones file ({e}); encoding without zones.{RESET}")
                scenes_for_av1an = json_abspath

            # We run Av1an in video_input_dir, so artifacts appear there (and we can resume if needed).
            # We pass an absolute scenes path because the json lives in temp.
            cmd_av1an = [
                av1an_exe,
                "-i", vpy_abspath,
                "-e", "svt-av1",
                "--no-defaults",
                "--keep",
                "--photon-noise", photon_noise,
                "-w", workers,
                "-s", scenes_for_av1an,
                "-o", av1_output,
                "-v", encoder_params
            ]
            
            if resume:
                cmd_av1an.append("--resume")
                
            print(f"[Dispatch] Starting Av1an Encoding...")
            print(f"svt-av1 fork: {svt_fork_display_name(selected_fork)}")
            av1an_started_at = time.monotonic()
            
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

            av1an_elapsed = time.monotonic() - av1an_started_at

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
                timing_report = {
                    "filename": filename,
                    "av1an_encoding": av1an_elapsed,
                }
                timing_reports.append(timing_report)
                print_av1an_timing_report(timing_report)

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
        finally:
            # This file is done with (encoded, skipped or failed) - give it its
            # original name back.
            restore_input_filename(input_abspath_origin)

    restore_all_input_filenames()
    batch_elapsed = time.monotonic() - batch_started_at

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

    if timing_reports:
        print("\nFinal Av1an time reports:")
        for timing_report in timing_reports:
            print_av1an_timing_report(timing_report)

    print("\nTime format legend: hh:mm:ss = hours:minutes:seconds")
    print(f"Total time for all files: {format_elapsed_hhmmss(batch_elapsed)}")

if __name__ == "__main__":
    main()