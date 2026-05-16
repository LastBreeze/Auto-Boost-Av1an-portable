import sys
import subprocess
import os
import glob
import shutil
from wakepy import keep

def main():
    # --- Configuration ---
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
    # Critical: Use filter-mux to merge with original source, not the x265 intermediate
    mux_script = os.path.join(tools_dir, "filter-mux.py")
    
    # Locate MediaInfo
    mediainfo_exe = os.path.join(tools_dir, "MediaInfo_CLI", "MediaInfo.exe")
    
    # --- Ensure Directories Exist ---
    if not os.path.exists(video_input_dir):
        os.makedirs(video_input_dir)
        sys.exit(0)
    if not os.path.exists(video_output_dir):
        os.makedirs(video_output_dir)
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
        
    # --- Argument Parsing ---
    args = sys.argv[1:]
    worker_count = None
    for idx, arg in enumerate(args):
        if arg == "--workers" and idx + 1 < len(args):
            try: worker_count = int(args[idx + 1])
            except ValueError: pass

    strip_lp_3 = False
    if worker_count is not None and worker_count in (1, 2):
        print("\033[93m[Filter-Dispatch] 1-2 workers detected, setting --lp mode to default\033[0m")
        strip_lp_3 = True

    # --- Gather Input Files ---
    extensions = ("*.mkv", "*.mp4", "*.m2ts")
    input_files = []
    for ext in extensions:
        input_files.extend(glob.glob(os.path.join(video_input_dir, ext)))
    
    if not input_files:
        print(f"[Filter-Dispatch] No video files found in {video_input_dir}")
        sys.exit(0)
        
    print(f"[Filter-Dispatch] Found {len(input_files)} files to process.")

    # --- Main Processing Loop ---
    for input_abspath_origin in input_files:
        filename = os.path.basename(input_abspath_origin)
        # Identify the original base name
        basename_raw = os.path.splitext(filename)[0]
        # Remove the intermediate tag if present
        original_basename = basename_raw.replace("-x265-source", "")
        
        # Paths
        source_path = input_abspath_origin # Absolute path to file in video-input
        
        # Final destination
        final_output_name = f"{original_basename}-muxed.mkv"
        final_output_path = os.path.join(video_output_dir, final_output_name)
        
        print("\n" + "="*80)
        print(f"Processing: {filename}")
        print("="*80)
        
        if os.path.exists(final_output_path):
            print(f"[Filter-Dispatch] Output exists: {final_output_path}. Skipping.")
            continue

        try:
            # 1. Scene Detection (Run in temp_dir)
            json_file = f"{basename_raw}_scenedetect.json"
            json_abspath = os.path.join(temp_dir, json_file)
            
            if not os.path.exists(json_abspath):
                print("[Filter-Dispatch] Running Scene Detection...")
                cmd_scene = [
                    sys.executable, 
                    scene_detect_script, 
                    "-i", source_path, 
                    "-o", json_file
                ]
                try: 
                    subprocess.check_call(cmd_scene, cwd=temp_dir)
                except subprocess.CalledProcessError: 
                    print("[Filter-Dispatch] Scene detection failed, continuing...")
            
            # 2. Color Space Check
            is_bt709 = False
            is_bt601 = False
            if os.path.exists(mediainfo_exe):
                try:
                    mi_cmd = [mediainfo_exe, source_path]
                    res = subprocess.run(mi_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                    if "BT.709" in res.stdout: is_bt709 = True
                    elif "BT.601" in res.stdout: is_bt601 = True
                except: pass

            # 3. Encoding (Call Auto-Boost-Av1an)
            final_cmd = [
                sys.executable, av1an_script, 
                "-i", source_path, 
                "-t", temp_dir,
                "--scenes", json_abspath
            ]
            
            # Reconstruct args
            skip_next = False
            for i, a in enumerate(args):
                if skip_next: skip_next = False; continue
                if a in ("-i", "--input", "-t", "--temp", "--scenes"): skip_next = True; continue
                
                if a in ("--fast-params", "--final-params"):
                    final_cmd.append(a)
                    if i + 1 < len(args):
                        param_str = args[i + 1]
                        if strip_lp_3: param_str = param_str.replace("--lp 3", "")
                        if is_bt709: param_str += " --color-primaries 1 --transfer-characteristics 1 --matrix-coefficients 1"
                        elif is_bt601: param_str += " --color-primaries 6 --transfer-characteristics 6 --matrix-coefficients 6"
                        final_cmd.append(param_str)
                        skip_next = True
                    else: final_cmd.append("")
                else: final_cmd.append(a)
            
            print(f"[Filter-Dispatch] Starting Encoding for {filename}...")
            
            try:
                with keep.running():
                    subprocess.check_call(final_cmd, cwd=temp_dir)
            except subprocess.CalledProcessError:
                print("[Filter-Dispatch] Encoding failed.")
                continue 
            
            # 4. Check Output
            generated_av1_list = glob.glob(os.path.join(temp_dir, f"*{basename_raw}*-av1.mkv"))
            
            if not generated_av1_list:
                generated_av1_list = glob.glob(os.path.join(video_input_dir, f"*{basename_raw}*-av1.mkv"))
                if generated_av1_list:
                    print(f"[Filter-Dispatch] Output found in video-input, moving to temp...")
                    shutil.move(generated_av1_list[0], temp_dir)

            # 5. Tagging
            try: subprocess.check_call([sys.executable, tag_script], cwd=temp_dir)
            except: pass

            # 6. Muxing (Calls filter-mux.py)
            print("[Filter-Dispatch] Muxing...")
            try:
                subprocess.check_call([sys.executable, mux_script], cwd=temp_dir)
            except subprocess.CalledProcessError:
                print("[Filter-Dispatch] Muxing failed.")
                continue
                
            # 7. Move Final Output
            # filter-mux.py creates {original_basename}-muxed.mkv in temp
            temp_output_mkv = os.path.join(temp_dir, final_output_name)
            
            if os.path.exists(temp_output_mkv):
                print(f"[Filter-Dispatch] Moving final file to: {final_output_path}")
                shutil.move(temp_output_mkv, final_output_path)
            else:
                print(f"[Filter-Dispatch] Error: Expected output not found: {temp_output_mkv}")
        
        except Exception as e:
            print(f"[Filter-Dispatch] Critical Error: {e}")
            import traceback
            traceback.print_exc()

    print("\n[Filter-Dispatch] Batch Complete.")

if __name__ == "__main__":
    main()