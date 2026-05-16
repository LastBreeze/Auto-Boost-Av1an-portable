import sys
import subprocess
import os
import glob
import shutil
import shlex
from wakepy import keep

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
            # This captures the 'av1an_settings' string passed from batch
            final_params = args[i+1]
            i += 2
        elif arg == "--resume":
            resume = True
            i += 1
        else:
            i += 1
            
    # --- Gather Input Files ---
    extensions = ("*.mkv", "*.mp4", "*.m2ts")
    input_files = []
    for ext in extensions:
        input_files.extend(glob.glob(os.path.join(video_input_dir, ext)))
    
    if not input_files:
        print(f"[Dispatch] No video files found in {video_input_dir}")
        sys.exit(0)
        
    print(f"[Dispatch] Found {len(input_files)} files to process.")

    # --- Main Processing Loop ---
    for input_abspath_origin in input_files:
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
                    subprocess.check_call(cmd_scene, cwd=temp_dir)
                except subprocess.CalledProcessError:
                    print("[Dispatch] Scene detection failed. Proceeding anyway.")

            # 2. Encoding (Direct Av1an Call)
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
                "-i", filename, # filename is sufficient as cwd will be video_input_dir
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
            
            try:
                with keep.running():
                    # Run in video_input_dir so temp folders created by av1an stay with source until done
                    subprocess.check_call(cmd_av1an, cwd=video_input_dir)
            except subprocess.CalledProcessError:
                print("[Dispatch] Encoding failed.")
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
            
            if os.path.exists(temp_output_mkv):
                print(f"[Dispatch] Moving final file to: {final_output_path}")
                try:
                    shutil.move(temp_output_mkv, final_output_path)
                except Exception as e:
                    print(f"[Dispatch] Error moving output file: {e}")
            else:
                print(f"[Dispatch] Error: Expected output file not found: {temp_output_mkv}")
        
        except Exception as e:
            print(f"[Dispatch] Critical Error during processing: {e}")

    print("\n" + "="*80)
    print("Av1an Direct Batch Complete.")
    print("="*80)

if __name__ == "__main__":
    main()