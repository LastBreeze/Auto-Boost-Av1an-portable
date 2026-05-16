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
    
    # Executable & Scripts
    av1an_exe = os.path.join(tools_dir, "av1an", "av1an.exe")
    scene_detect_script = os.path.join(tools_dir, "Progressive-Scene-Detection.py")
    tag_script = os.path.join(tools_dir, "av1an-tag.py")
    
    # Critical: Use filter-mux to merge with original source in ../filter
    mux_script = os.path.join(tools_dir, "filter-mux.py")
    
    # --- Ensure Directories Exist ---
    if not os.path.exists(video_input_dir):
        os.makedirs(video_input_dir)
        sys.exit(0)
    if not os.path.exists(video_output_dir):
        os.makedirs(video_output_dir)
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
        
    # --- Argument Parsing ---
    # Matches arguments passed by av1an-batch files
    args = sys.argv[1:]
    
    quality = "30"
    workers = "1"
    photon_noise = "0"
    final_speed = "4"
    final_params = ""
    resume = False
    
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--quality":
            quality = args[i+1]
            i += 2
        elif arg == "--workers":
            workers = args[i+1]
            i += 2
        elif arg == "--photon-noise":
            photon_noise = args[i+1]
            i += 2
        elif arg == "--final-speed":
            final_speed = args[i+1]
            i += 2
        elif arg == "--final-params":
            final_params = args[i+1]
            i += 2
        elif arg == "--resume":
            resume = True
            i += 1
        else:
            i += 1
            
    # --- Gather Input Files ---
    # In filter mode, these are the *-x265-source.mkv files created by filter.py
    extensions = ("*.mkv", "*.mp4", "*.m2ts")
    input_files = []
    for ext in extensions:
        input_files.extend(glob.glob(os.path.join(video_input_dir, ext)))
    
    if not input_files:
        print(f"[Filter-Av1an-Dispatch] No video files found in {video_input_dir}")
        sys.exit(0)
        
    print(f"[Filter-Av1an-Dispatch] Found {len(input_files)} files to process.")

    # --- Main Processing Loop ---
    for input_abspath_origin in input_files:
        filename = os.path.basename(input_abspath_origin)
        # filename ex: "Show-source-x265-source.mkv"
        basename = os.path.splitext(filename)[0]
        # basename ex: "Show-source-x265-source"
        
        # Calculate expected final output name for skipping
        # filter-mux produces: {original_base}-muxed.mkv
        original_base = basename.replace("-x265-source", "")
        final_output_name = f"{original_base}-muxed.mkv"
        final_output_path = os.path.join(video_output_dir, final_output_name)
        
        print("\n" + "="*80)
        print(f"Processing: {filename}")
        print("="*80)
        
        if os.path.exists(final_output_path):
            print(f"[Filter-Av1an-Dispatch] Output exists: {final_output_path}. Skipping.")
            continue

        # Temporary path for source file during processing
        source_in_temp = os.path.join(temp_dir, filename)

        try:
            # 1. Move Source to Temp
            print(f"[Filter-Av1an-Dispatch] Moving {filename} to temp folder...")
            if not os.path.exists(source_in_temp):
                try:
                    shutil.move(input_abspath_origin, source_in_temp)
                except IOError as e:
                    print(f"[Filter-Av1an-Dispatch] Error moving input file: {e}")
                    continue
            
            # 2. Scene Detection
            json_file = f"{basename}_scenedetect.json"
            json_abspath = os.path.join(temp_dir, json_file)
            
            if os.path.exists(json_abspath):
                print(f"[Filter-Av1an-Dispatch] Skipping scene detection (JSON exists).")
            else:
                print("[Filter-Av1an-Dispatch] Running Scene Detection...")
                cmd_scene = [
                    sys.executable,
                    scene_detect_script,
                    "-i", source_in_temp,
                    "-o", json_file 
                ]
                try:
                    subprocess.check_call(cmd_scene, cwd=temp_dir)
                except subprocess.CalledProcessError:
                    print("[Filter-Av1an-Dispatch] Scene detection failed. Proceeding anyway.")

            # 3. Encoding (Direct Av1an Call)
            # We must output *-av1.mkv so filter-mux.py detects it
            av1_output = f"{basename}-av1.mkv"
            
            encoder_params = f"--crf {quality} --preset {final_speed} {final_params}"
            encoder_params = " ".join(encoder_params.split()) # cleanup spaces

            cmd_av1an = [
                av1an_exe,
                "-i", source_in_temp,
                "-e", "svt-av1",
                "--no-defaults",
                "--photon-noise", photon_noise,
                "-w", workers,
                "-s", json_file,
                "-o", av1_output,
                "-v", encoder_params
            ]
            
            if resume:
                cmd_av1an.append("--resume")
                
            print(f"[Filter-Av1an-Dispatch] Starting Av1an Encoding...")
            
            try:
                with keep.running():
                    subprocess.check_call(cmd_av1an, cwd=temp_dir)
            except subprocess.CalledProcessError:
                print("[Filter-Av1an-Dispatch] Encoding failed.")
                continue

            # 4. Tagging
            # Uses av1an-tag.py which reads the BAT file to apply encoding settings tags
            print("[Filter-Av1an-Dispatch] Applying Tags...")
            try:
                subprocess.check_call([sys.executable, tag_script], cwd=temp_dir)
            except subprocess.CalledProcessError:
                print("[Filter-Av1an-Dispatch] Warning: Tagging reported an error.")

            # 5. Muxing
            # Calls filter-mux.py (which muxes with the original source in ../filter)
            print("[Filter-Av1an-Dispatch] Muxing...")
            try:
                subprocess.check_call([sys.executable, mux_script], cwd=temp_dir)
            except subprocess.CalledProcessError:
                print("[Filter-Av1an-Dispatch] Muxing failed.")
                continue
                
            # 6. Move Final Output
            # filter-mux.py output: {original_base}-muxed.mkv in temp
            temp_output_mkv = os.path.join(temp_dir, final_output_name)
            
            if os.path.exists(temp_output_mkv):
                print(f"[Filter-Av1an-Dispatch] Moving final file to: {final_output_path}")
                try:
                    shutil.move(temp_output_mkv, final_output_path)
                except Exception as e:
                    print(f"[Filter-Av1an-Dispatch] Error moving output file: {e}")
            else:
                print(f"[Filter-Av1an-Dispatch] Error: Expected output file not found: {temp_output_mkv}")
        
        except Exception as e:
            print(f"[Filter-Av1an-Dispatch] Critical Error: {e}")
            import traceback
            traceback.print_exc()
            
        finally:
            # 7. Move Input Back
            # Always return the intermediate file to video-input (filter.py handles final deletion)
            if os.path.exists(source_in_temp):
                print(f"[Filter-Av1an-Dispatch] Moving {filename} back to video-input...")
                try:
                    shutil.move(source_in_temp, input_abspath_origin)
                except IOError as e:
                    print(f"[Filter-Av1an-Dispatch] Error moving input file back: {e}")

    print("\n" + "="*80)
    print("Filter Av1an Batch Complete.")
    print("="*80)

if __name__ == "__main__":
    main()