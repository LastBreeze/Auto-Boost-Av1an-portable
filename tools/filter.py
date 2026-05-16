import os
import glob
import subprocess
import shutil
import sys

# --- CONFIGURATION & PATHS ---
CWD = os.getcwd()
ROOT_DIR = os.path.dirname(CWD)  # "Auto-Boost-Av1an-portable"
TOOLS_DIR = os.path.join(ROOT_DIR, "tools")
VIDEO_INPUT_DIR = os.path.join(ROOT_DIR, "video-input")
VIDEO_OUTPUT_DIR = os.path.join(ROOT_DIR, "video-output")
VS_DLL_PATH = os.path.abspath(os.path.join(ROOT_DIR, "VapourSynth", "VSScript.dll"))

MKVMERGE_EXE = "mkvmerge.exe"
X265_EXE = "x265.exe"

X265_SETTINGS = [
    "--preset", "superfast",
    "--output-depth", "10",
    "--lossless",
    "--colorprim", "bt709",
    "--colormatrix", "bt709",
    "--transfer", "bt709",
    "--level-idc", "0"
]

VPY_TEMPLATE = """
import vapoursynth as vs
core = vs.core
clip = core.ffms2.Source(source=r"{source_path}")
clip.set_output()
"""

def run_command(cmd_list, shell=False):
    try:
        display_cmd = cmd_list if isinstance(cmd_list, str) else " ".join(cmd_list)
        print(f"Running: {display_cmd}")
        subprocess.run(cmd_list, shell=shell, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}")
        return False

def setup_encoding_batch():
    """
    1. Finds a .bat file in filter folder.
    2. Reads it.
    3. Replaces 'av1an-dispatch.py' with 'filter-av1an-dispatch.py'.
    4. Replaces 'dispatch.py' with 'filter-dispatch.py'.
    5. Removes 'pause'.
    6. Saves as 'FILTER-{filename}' in root.
    """
    bat_files = glob.glob("*.bat")
    valid_bats = [b for b in bat_files if "filter.bat" not in b.lower()]

    if not valid_bats:
        print("Error: No encoding .bat file found in the filter folder.")
        return None

    original_bat = valid_bats[0]
    new_bat_name = f"FILTER-{original_bat}"
    new_bat_path = os.path.join(ROOT_DIR, new_bat_name)

    print(f"Preparing encoding batch file: {original_bat} -> {new_bat_name}")

    try:
        with open(original_bat, 'r') as f_in, open(new_bat_path, 'w') as f_out:
            for line in f_in:
                # 1. Remove pauses
                if "pause" in line.lower().strip():
                    continue
                
                # 2. Modify Dispatch Command
                # Check for av1an-dispatch FIRST because it contains "dispatch.py" substring
                if "av1an-dispatch.py" in line:
                    line = line.replace("av1an-dispatch.py", "filter-av1an-dispatch.py")
                elif "dispatch.py" in line:
                    line = line.replace("dispatch.py", "filter-dispatch.py")
                
                f_out.write(line)
        return new_bat_name
    except IOError as e:
        print(f"Error processing batch file: {e}")
        return None

def copy_zones():
    zone_files = glob.glob("*zones*.txt")
    if zone_files:
        print(f"Found {len(zone_files)} zone file(s). Copying to {VIDEO_INPUT_DIR}...")
        for zf in zone_files:
            try: shutil.copy(zf, VIDEO_INPUT_DIR)
            except: pass

def sanitize_filename(filepath):
    directory, filename = os.path.split(filepath)
    base, ext = os.path.splitext(filename)
    if base.endswith("-source"): return filepath
    exclusions = ("-av1", "-breeze", "-x265", "-sokudo", "-dbms")
    if base.endswith(exclusions): return filepath
    new_base = base.replace("(", "").replace(")", "").replace("[", "").replace("]", "").replace(" ", ".") + "-source"
    new_filename = new_base + ext
    new_full_path = os.path.join(directory, new_filename)
    if new_filename != filename:
        try:
            os.rename(filepath, new_full_path)
            print(f"Renamed: '{filename}' -> '{new_filename}'")
            return new_full_path
        except OSError: return filepath
    return filepath

def main():
    if not os.path.exists(VIDEO_INPUT_DIR): os.makedirs(VIDEO_INPUT_DIR)
    if not os.path.exists(VIDEO_OUTPUT_DIR): os.makedirs(VIDEO_OUTPUT_DIR)

    batch_filename = setup_encoding_batch()
    if not batch_filename:
        input("Press Enter to exit...")
        sys.exit(1)
    
    copy_zones()

    mkv_files = glob.glob("*.mkv")
    if not mkv_files:
        print("No .mkv files found.")
        input("Press Enter to exit...")
        sys.exit(0)

    for raw_path in mkv_files:
        source_path = sanitize_filename(os.path.abspath(raw_path))
        filename = os.path.basename(source_path)
        base_name = os.path.splitext(filename)[0]

        print(f"\n=== Processing Sequence: {filename} ===")

        vpy_file = os.path.join(CWD, f"{base_name}.vpy")
        temp_x265_raw = os.path.join(CWD, f"temp_{base_name}_raw.mkv")
        
        # Intermediate file (Input for Batch)
        intermediary_name = f"{base_name}-x265-source.mkv"
        intermediary_path = os.path.join(VIDEO_INPUT_DIR, intermediary_name)

        # --- Check if intermediary exists ---
        if os.path.exists(intermediary_path):
            print(f"--- [SKIP] Intermediary found in video-input: {intermediary_name}")
            print("--- Skipping x265 generation and proceeding to Batch...")
        else:
            # Step A: Generate VPY & Step B: Encode x265
            try:
                vs_source = source_path.replace("\\", "/")
                with open(vpy_file, "w", encoding="utf-8") as f:
                    f.write(VPY_TEMPLATE.format(source_path=vs_source))
            except IOError: continue

            print("--- [GENERATE] Creating lossless x265 intermediary...")
            x265_cmd = [X265_EXE, "--reader-options", f"library={VS_DLL_PATH}"] + X265_SETTINGS + ["--output", temp_x265_raw, vpy_file]
            if not run_command(x265_cmd): continue
            
            mkv_cmd = [MKVMERGE_EXE, "-o", intermediary_path, temp_x265_raw]
            if not run_command(mkv_cmd): continue
            
            # Cleanup Temps
            if os.path.exists(vpy_file): os.remove(vpy_file)
            if os.path.exists(temp_x265_raw): os.remove(temp_x265_raw)

        # Step C: Run Modified Batch (Runs regardless of whether we skipped generation)
        print(f"--- Starting Modified Batch: {batch_filename} ---")
        batch_full_path = os.path.join(ROOT_DIR, batch_filename)
        try: subprocess.run(batch_full_path, cwd=ROOT_DIR, shell=True, check=True)
        except subprocess.CalledProcessError: print("Batch error (ignoring)")

        # Step D: Verify Output and Cleanup
        # Expected output from filter-mux: "Show-source-muxed.mkv"
        expected_output_name = f"{base_name}-muxed.mkv"
        files_after = os.listdir(VIDEO_OUTPUT_DIR)
        
        if expected_output_name in files_after:
            print(f"Success! Output detected: {expected_output_name}")
            print(f"Deleting intermediate: {intermediary_name}")
            try: os.remove(intermediary_path)
            except: pass
        else:
            print(f"Warning: Expected output {expected_output_name} not found.")

    # Final Batch Cleanup
    final_bat_path = os.path.join(ROOT_DIR, batch_filename)
    if os.path.exists(final_bat_path):
        try: os.remove(final_bat_path)
        except: pass
    print("Done.")

if __name__ == "__main__":
    main()