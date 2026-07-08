import sys
import subprocess
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glob
import re
import shutil
import urllib.parse
import urllib.request
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


def load_script_settings(settings_path):
    """Read settings.txt once into a case-insensitive key/value dict."""
    if not os.path.exists(settings_path):
        return {}
    try:
        with open(settings_path, "r", encoding="utf-8", errors="replace") as f:
            return parse_settings_lines(f.read().splitlines())
    except Exception:
        return {}

def set_settings_value(settings_path, key, value):
    """Set key=value in settings.txt, preserving the rest of the file."""
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

def main():
    # --- Configuration ---
    # Paths relative to this script (tools/dispatch.py)
    # Root is Auto-Boost-Av1an-portable
    script_path = os.path.abspath(__file__)
    tools_dir = os.path.dirname(script_path)
    root_dir = os.path.dirname(tools_dir)
    
    video_input_dir = os.path.join(root_dir, "video-input")
    video_output_dir = os.path.join(root_dir, "video-output")
    temp_dir = os.path.join(root_dir, "temp")
    
    # Scripts
    av1an_script = os.path.join(tools_dir, "Auto-Boost-Av1an.py")
    scene_detect_script = os.path.join(tools_dir, "Progressive-Scene-Detection.py")
    tag_script = os.path.join(tools_dir, "tag.py")
    mux_script = os.path.join(tools_dir, "mux.py")
    
    # Locate MediaInfo
    mediainfo_exe = os.path.join(tools_dir, "MediaInfo_CLI", "MediaInfo.exe")
    
    # --- Ensure Directories Exist ---
    if not os.path.exists(video_input_dir):
        os.makedirs(video_input_dir)
        print(f"[Dispatch] Created missing input directory: {video_input_dir}")
        sys.exit(0)

    if not os.path.exists(video_output_dir):
        os.makedirs(video_output_dir)

    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    # --- Argument Parsing (settings + dispatcher-only options) ---
    args = sys.argv[1:]
    denoise_setting = None
    initial_args = []
    idx = 0
    while idx < len(args):
        if args[idx] == "--denoise" and idx + 1 < len(args):
            val = args[idx + 1].strip().lower()
            denoise_setting = "True" if val in ("1", "true", "yes", "y", "on") else "False"
            idx += 2
        else:
            initial_args.append(args[idx])
            idx += 1
    args = initial_args

    # --- Copy settings.txt to Temp ---
    # Auto-Boost-Av1an.py searches CWD (temp) for settings.txt
    settings_src = os.path.join(root_dir, "settings.txt")
    settings_dst = os.path.join(temp_dir, "settings.txt")

    if denoise_setting is not None:
        try:
            set_settings_value(settings_src, "denoise", denoise_setting)
            print(f"[Dispatch] Set settings.txt denoise={denoise_setting}")
        except Exception as e:
            print(f"[Dispatch] Warning: Failed to update settings.txt denoise: {e}")

    if os.path.exists(settings_src):
        try:
            shutil.copy2(settings_src, settings_dst)
            if denoise_setting is not None:
                set_settings_value(settings_dst, "denoise", denoise_setting)
            print(f"[Dispatch] Copied settings.txt to temp folder.")
        except Exception as e:
            print(f"[Dispatch] Warning: Failed to copy settings.txt: {e}")
    else:
        print(f"[Dispatch] Warning: settings.txt not found at {settings_src}")

    ntfy_settings = load_script_settings(settings_src)
        
    # Extract dispatcher-only options and worker count for logic checks
    worker_count = None
    selected_fork = "essential"
    avx512 = False
    passthrough_args = []
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "--workers" and idx + 1 < len(args):
            try:
                worker_count = int(args[idx + 1])
            except ValueError:
                pass
            passthrough_args.extend([arg, args[idx + 1]])
            idx += 2
        elif arg == "--fork" and idx + 1 < len(args):
            selected_fork = args[idx + 1]
            idx += 2
        elif arg == "--avx512":
            if idx + 1 < len(args) and not args[idx + 1].startswith("--"):
                avx512 = parse_bool_setting(args[idx + 1])
                idx += 2
            else:
                avx512 = True
                idx += 1
        else:
            passthrough_args.append(arg)
            idx += 1
    args = passthrough_args

    # --- Optimized worker overrides from the generating .bat (optional) ---
    # Written by the one-time benchmark (workercount.py / ssimu2-workercount.py
    # --optimize-bat). When absent, everything proceeds exactly as before.
    bat_opt = read_bat_optimize_settings(tools_dir, root_dir)
    if bat_opt.get("optimize-workers", "").strip().lower() in ("true", "1", "yes", "on"):
        def _override_flag_value(flag, value):
            for i in range(len(args)):
                if args[i] == flag and i + 1 < len(args):
                    args[i + 1] = value
                    return
            args.extend([flag, value])

        custom_enc = bat_opt.get("custom-av1an-workers", "").strip()
        if custom_enc.isdigit() and int(custom_enc) > 0:
            worker_count = int(custom_enc)
            _override_flag_value("--workers", custom_enc)
            print(f"\033[94m[Dispatch] Using optimized av1an worker count from bat: {custom_enc}\033[0m")

        custom_ssimu2_tool = bat_opt.get("custom-ssim2-tool", "").strip()
        if custom_ssimu2_tool:
            _override_flag_value("--ssimu2", custom_ssimu2_tool.replace(" ", "-"))
            print(f"\033[94m[Dispatch] Using optimized SSIMU2 tool from bat: {custom_ssimu2_tool}\033[0m")

        custom_ssimu2 = bat_opt.get("custom-ssim2-workers", "").strip()
        if custom_ssimu2.isdigit() and int(custom_ssimu2) > 0:
            _override_flag_value("--ssimu2-cpu-workers", custom_ssimu2)
            print(f"\033[94m[Dispatch] Using optimized SSIMU2 worker/stream count from bat: {custom_ssimu2}\033[0m")

    setup_svt_av1_fork(tools_dir, selected_fork, avx512=avx512, verbose=True)

    # --- Worker Safety Check ---
    strip_lp_3 = False
    if worker_count is not None and worker_count in (1, 2):
        print("\033[93m[Dispatch] 1-2 workers detected, setting --lp mode to default auto parallelism\033[0m")
        strip_lp_3 = True

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
        
        # Final destination for the encoded file
        final_output_path = os.path.join(video_output_dir, basename + "-output.mkv")
        
        print("\n" + "="*80)
        print(f"Processing: {filename}")
        print("="*80)
        
        if os.path.exists(final_output_path):
            print(f"[Dispatch] Output file already exists: {final_output_path}")
            print("[Dispatch] Skipping...")
            continue

        try:
            # 1. Scene Detection
            json_file = f"{basename}_scenedetect.json"
            json_abspath = os.path.join(temp_dir, json_file)
            
            if os.path.exists(json_abspath):
                print(f"[Dispatch] Skipping scene detection (JSON exists in temp): {json_file}")
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
                    print("[Dispatch] Scene detection failed.")
            
            # 2. Color Space Detection
            is_bt709 = False
            is_bt601 = False
            f_prim_709 = f_trans_709 = f_mat_709 = False
            f_prim_601 = f_trans_601 = f_mat_601 = False
            
            if os.path.exists(mediainfo_exe):
                try:
                    mi_cmd = [mediainfo_exe, input_abspath_origin]
                    res = subprocess.run(mi_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                    if res.returncode == 0:
                        for line in res.stdout.splitlines():
                            if ":" in line:
                                k, v = line.split(":", 1)
                                k, v = k.strip(), v.strip()
                                if k == "Color primaries":
                                    if v == "BT.709": f_prim_709 = True
                                    elif "BT.601" in v: f_prim_601 = True
                                elif k == "Transfer characteristics":
                                    if v == "BT.709": f_trans_709 = True
                                    elif "BT.601" in v: f_trans_601 = True
                                elif k == "Matrix coefficients":
                                    if v == "BT.709": f_mat_709 = True
                                    elif "BT.601" in v: f_mat_601 = True
                        
                        if f_prim_709 and f_trans_709 and f_mat_709:
                            is_bt709 = True
                            print("[Dispatch] MediaInfo confirmed full BT.709 source.")
                        elif f_prim_601 and f_trans_601 and f_mat_601:
                            is_bt601 = True
                            print("[Dispatch] MediaInfo confirmed full BT.601 source.")
                except Exception:
                    pass

            # 3. Encoding
            final_cmd = [
                sys.executable,
                av1an_script,
                "--fork", selected_fork,
                "-i", input_abspath_origin,
                "--scenes", json_file,
            ]
            if avx512:
                final_cmd.append("--avx512")
            
            bt709_flags = " --color-primaries 1 --transfer-characteristics 1 --matrix-coefficients 1"
            bt601_flags = " --color-primaries 6 --transfer-characteristics 6 --matrix-coefficients 6"
            current_color_flags = ""
            if is_bt709: current_color_flags = bt709_flags
            elif is_bt601: current_color_flags = bt601_flags
            
            skip_next = False
            for i, a in enumerate(args):
                if skip_next:
                    skip_next = False
                    continue
                if a in ("-i", "--input"):
                    skip_next = True
                    continue
                if a in ("--fast-params", "--final-params"):
                    final_cmd.append(a)
                    if i + 1 < len(args):
                        param_str = args[i + 1]
                        if strip_lp_3:
                            param_str = param_str.replace("--lp 3", "")
                        if current_color_flags:
                            param_str += current_color_flags
                        final_cmd.append(param_str)
                        skip_next = True
                    else:
                        final_cmd.append("")
                else:
                    final_cmd.append(a)
            
            print(f"[Dispatch] Processing {filename}...")
            print("[Dispatch] Starting Encoding...")
            print(f"svt-av1 fork: {svt_fork_display_name(selected_fork)}")
            try:
                with keep.running():
                    subprocess.check_call(final_cmd, cwd=temp_dir)
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

            # 4. Move Av1an Artifacts from video-input to Temp
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

            # 5. Tagging
            print("[Dispatch] Applying Tags...")
            try:
                subprocess.check_call([sys.executable, tag_script], cwd=temp_dir)
            except subprocess.CalledProcessError:
                print("[Dispatch] Warning: Tagging reported an error.")

            # 6. Muxing
            print("[Dispatch] Muxing...")
            try:
                subprocess.check_call([sys.executable, mux_script], cwd=temp_dir)
            except subprocess.CalledProcessError:
                print("[Dispatch] Muxing failed.")
                continue
                
            # 7. Move Output
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
    print("Dispatch Batch Complete.")
    print("="*80)

if __name__ == "__main__":
    main()