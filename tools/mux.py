import os
import subprocess
import glob
import sys
import json

# Paths to executables
# Relative paths work because we run this script via Dispatch inside the 'temp' folder,
# and tools are in ../tools
MKVMERGE = os.path.join("..", "tools", "MKVToolNix", "mkvmerge.exe")
MKVEXTRACT = os.path.join("..", "tools", "MKVToolNix", "mkvextract.exe")
MKVPROPEDIT = os.path.join("..", "tools", "MKVToolNix", "mkvpropedit.exe")
MEDIAINFO = os.path.join("..", "tools", "MediaInfo_CLI", "MediaInfo.exe")

# Define fallback to check absolute paths if relative fails (safety net)
def resolve_tool(path):
    if os.path.exists(path):
        return path
    # Try looking relative to this script file if we aren't running in temp
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Assuming script is in tools/, look inside tools/
    name = os.path.basename(path)
    # Reconstruct path relative to script dir
    # path was like "../tools/MKVToolNix/..." -> remove "../tools/"
    if "MKVToolNix" in path:
        return os.path.join(script_dir, "MKVToolNix", os.path.basename(path))
    if "MediaInfo" in path:
        return os.path.join(script_dir, "MediaInfo_CLI", os.path.basename(path))
    return path

MKVMERGE = resolve_tool(MKVMERGE)
MKVEXTRACT = resolve_tool(MKVEXTRACT)
MKVPROPEDIT = resolve_tool(MKVPROPEDIT)
MEDIAINFO = resolve_tool(MEDIAINFO)

def run_command(cmd, status_label):
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    print(f"{status_label}: Starting...          ", end="\r")
    sys.stdout.flush()
    for line in process.stdout:
        line = line.strip()
        if line.startswith("Progress:"):
            percent = line.split(":")[-1].strip()
            print(f"{status_label}: {percent}          ", end="\r")
            sys.stdout.flush()
    process.wait()
    if process.returncode != 0:
        print(f"\n[ERROR] Command failed: {' '.join(cmd)}")
        raise subprocess.CalledProcessError(process.returncode, cmd)
    print(f"{status_label}: Done.          ")

def force_vfr_metadata(file_path, status_label):
    if not os.path.exists(MKVPROPEDIT):
        print(f"[WARN] mkvpropedit not found. Skipping metadata edit.")
        return
    video_track_count = get_video_track_count(file_path) or 1
    cmd = [MKVPROPEDIT, "--parse-mode", "full", file_path]
    for i in range(1, video_track_count + 1):
        cmd.extend(["--edit", f"track:v{i}", "--delete", "default-duration"])
    print(f"{status_label}: Updating...          ", end="\r")
    sys.stdout.flush()
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print(f"{status_label}: Done.          ")
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Failed to edit properties: {e}")

def get_video_track_id(source_file):
    cmd = [MKVMERGE, "-J", source_file]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        data = json.loads(result.stdout)
        for track in data.get("tracks", []):
            if track.get("type") == "video":
                return track.get("id")
    except Exception as e:
        print(f"[WARN] Failed to get track ID: {e}")
    return None

def get_video_track_count(source_file):
    cmd = [MKVMERGE, "-J", source_file]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        data = json.loads(result.stdout)
        count = 0
        for track in data.get("tracks", []):
            if track.get("type") == "video":
                count += 1
        return count
    except Exception:
        return 1

def check_vfr_mediainfo(source_file):
    if not os.path.exists(MEDIAINFO):
        return False
    cmd = [MEDIAINFO, source_file]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        for line in result.stdout.splitlines():
            if "frame rate mode" in line.lower() and "variable" in line.lower():
                return True
    except Exception:
        pass
    return False

def mux_files():
    # We are running in 'temp', so find av1 files here
    av1_files = glob.glob("*-av1.mkv")

    if not av1_files:
        print("No *-av1.mkv files found in temp to mux.")
        return

    print(f"Found {len(av1_files)} '-av1.mkv' files. Starting muxing process...\n")

    for av1_file in av1_files:
        base_name = av1_file.replace("-av1.mkv", "")

        # Check for matching source file
        # Priority 1: Check ../video-input/ (Standard workflow)
        # Priority 2: Check current dir (Fallback)
        
        possible_sources = [
            os.path.join("..", "video-input", f"{base_name}.mkv"),
            os.path.join("..", "video-input", f"{base_name}.mp4"),
            os.path.join("..", "video-input", f"{base_name}.m2ts"),
            f"{base_name}.mkv",
            f"{base_name}-source.mkv"
        ]
        
        source_mkv = None
        for path in possible_sources:
            if os.path.exists(path):
                source_mkv = path
                break

        if not source_mkv:
            print(f"[SKIP] Source file not found for: {av1_file}")
            print(f"       Checked ../video-input/ and local temp folder.")
            continue

        temp_mkv = f"{base_name}_temp_no_video.mkv"
        final_output = f"{base_name}-output.mkv"
        timestamp_file = f"{base_name}_timestamps.txt"

        try:
            is_vfr = check_vfr_mediainfo(source_mkv)
            timestamps_args = []
            total_steps = 4 if is_vfr else 2
            current_step = 1

            if is_vfr:
                print(f"\033[92mVariable framerate detected, applying timecodes...\033[0m")
                vid_track_id = get_video_track_id(source_mkv) or 0
                cmd_extract_ts = [MKVEXTRACT, source_mkv, "timestamps_v2", f"{vid_track_id}:{timestamp_file}"]
                run_command(cmd_extract_ts, f"[{base_name}] Step {current_step}/{total_steps} (Timecodes)")
                current_step += 1
                if os.path.exists(timestamp_file):
                    av1_track_id = get_video_track_id(av1_file) or 0
                    timestamps_args = ["--timestamps", f"{av1_track_id}:{timestamp_file}"]

            # Step 1: Extract Audio/Subs
            cmd_step1 = [MKVMERGE, "-o", temp_mkv, "--no-video", source_mkv]
            run_command(cmd_step1, f"[{base_name}] Step {current_step}/{total_steps} (Extract)")
            current_step += 1

            # Step 2: Merge
            cmd_step2 = [MKVMERGE, "-o", final_output]
            cmd_step2.extend(timestamps_args)
            cmd_step2.append(av1_file)
            cmd_step2.append(temp_mkv)
            run_command(cmd_step2, f"[{base_name}] Step {current_step}/{total_steps} (Merge)  ")
            current_step += 1

            # Step 3: VFR Metadata Fix
            if is_vfr:
                force_vfr_metadata(final_output, f"[{base_name}] Step {current_step}/{total_steps} (VFR Fix)")

            # Cleanup Temp Files
            if os.path.exists(temp_mkv): os.remove(temp_mkv)
            if os.path.exists(timestamp_file): os.remove(timestamp_file)
            
            # --- NEW: Delete the intermediate AV1 file if output exists ---
            if os.path.exists(final_output):
                print(f"Deleting intermediate file: {av1_file}")
                try:
                    os.remove(av1_file)
                except OSError as e:
                    print(f"[WARN] Failed to delete {av1_file}: {e}")

        except subprocess.CalledProcessError:
            print(f"\n[FAIL] Could not process {base_name}. Skipping.")

if __name__ == "__main__":
    mux_files()