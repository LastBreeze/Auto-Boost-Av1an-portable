import sys
import subprocess
import os
import glob
import shutil
import shlex
import csv
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
        
    # --- Settings Parsing ---
    settings_path = os.path.join(root_dir, "settings.txt")
    
    def get_setting(key, default):
        if not os.path.exists(settings_path): return default
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or line.startswith(';'): continue
                    if '=' in line:
                        k, v = line.split('=', 1)
                        if k.strip().lower() == key.lower():
                            return v.strip()
        except: pass
        return default

    s_downscale = get_setting("downscale", "False")
    s_target_res = get_setting("target_resolution", "1920x1080")
    s_kernel = get_setting("kernel_type", "Hermite")
    s_denoise = get_setting("denoise", "False")
    s_denoise_setting = get_setting("denoise_setting", "src = DFTTest().denoise(src, {0.00:0.30, 0.40:0.30, 0.60:0.60, 0.80:1.50, 1.00:2.00}, planes=[0, 1, 2])")
    s_deband = get_setting("deband", "False")
    s_deband_setting = get_setting("deband_setting", "src = core.placebo.Deband(src, threshold=1.5, planes=1)")
    s_crop_mode = get_setting("crop", "auto").lower()
    s_crop_top = int(get_setting("top", "0"))
    s_crop_bottom = int(get_setting("bottom", "0"))

    do_downscale = s_downscale.lower() == "true"
    do_denoise = s_denoise.lower() == "true"
    do_deband = s_deband.lower() == "true"
    do_manual_crop = s_crop_mode == "manual" and (s_crop_top > 0 or s_crop_bottom > 0)

    is_filtering_active = do_downscale or do_denoise or do_deband or do_manual_crop

    # --- Argument Parsing ---
    args = sys.argv[1:]
    
    quality = "30"
    workers = "1"
    photon_noise = "0"
    final_speed = "4"
    final_params = ""
    resume = False
    autocrop = False
    
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
        elif arg == "--autocrop":
            autocrop = True
            is_filtering_active = True
            i += 1
        else:
            i += 1

    # --- Display Active Filters ---
    print("\n" + "="*80)
    print("Active VapourSynth Filters:")
    print("="*80)
    filters_active_display = False

    if do_downscale:
        print(f"- Downscale: True | Target: {s_target_res}, Kernel: {s_kernel}")
        filters_active_display = True
    if do_denoise:
        print(f"- Denoise:   True | Setting: {s_denoise_setting}")
        filters_active_display = True
    if do_deband:
        print(f"- Deband:    True | Setting: {s_deband_setting}")
        filters_active_display = True
    
    if do_manual_crop:
        print(f"- Crop:      True | Mode: manual, Top: {s_crop_top}, Bottom: {s_crop_bottom}")
        filters_active_display = True
    elif autocrop:
        print(f"- Crop:      True | Mode: auto (Detection per file)")
        filters_active_display = True

    if not filters_active_display:
        print("- None")
    print("="*80 + "\n")
            
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

            # 1.5. VapourSynth Generation (If Active)
            av1an_input = filename
            
            crop_t = s_crop_top if do_manual_crop else 0
            crop_b = s_crop_bottom if do_manual_crop else 0
            
            if autocrop:
                cropdetect_script = os.path.join(tools_dir, "cropdetect.py")
                csv_output = os.path.join(video_input_dir, f"{basename}_crop.csv")
                if os.path.exists(cropdetect_script):
                    print("[Dispatch] Detecting crop values via cropdetect.py...")
                    try:
                        subprocess.run([sys.executable, cropdetect_script, input_abspath_origin, "--out", csv_output, "--samples", "3"], check=False)
                        if os.path.exists(csv_output):
                            with open(csv_output, newline='', encoding='utf-8') as f:
                                reader = csv.DictReader(f)
                                rows = list(reader)
                                if rows:
                                    orig_h = int(rows[0]['height'])
                                    c_h = int(rows[0]['crop_h'])
                                    c_y = int(rows[0]['crop_y'])
                                    crop_t = c_y
                                    crop_b = orig_h - (c_y + c_h)
                                    if crop_t % 2 != 0: crop_t -= 1
                                    if crop_b % 2 != 0: crop_b -= 1
                                    print(f"[Dispatch] Autocrop found: Top={crop_t}, Bottom={crop_b}")
                    except Exception as e:
                        print(f"[Dispatch] Autocrop failed: {e}")

            if is_filtering_active:
                vpy_filename = f"{basename}.vpy"
                vpy_abspath = os.path.join(video_input_dir, vpy_filename)
                cache_file_path = os.path.join(temp_dir, f"{basename}.ffindex")
                
                print(f"[Dispatch] VapourSynth filtering active based on settings.txt. Generating {vpy_filename}...")
                
                vpy_template = """from vstools import vs, core, initialize_clip, finalize_clip
core.max_cache_size = 1024

# Load Source
src = core.ffms2.Source(source=r"{source}", cachefile=r"{cache}")

# Initialize (Fixes Placebo bitdepth error by ensuring 16-bit)
src = initialize_clip(src)

# 1. CROP
if {ct} > 0 or {cb} > 0:
    src = src.std.Crop(top={ct}, bottom={cb})

# 2. DOWNSCALE
should_downscale = {downscale}
target_res_str = "{target_res}"
user_kernel = "{kernel}"

if should_downscale:
    # Kernel Map
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

    # Parse Target Resolution
    target_w = 0
    target_h = 0
    
    if "x" in target_res_str.lower():
        try:
            w_str, h_str = target_res_str.lower().split("x")
            target_w = int(w_str)
            target_h = int(h_str)
        except:
            pass
    else:
        try:
            target_w = int(target_res_str)
        except:
            pass
            
    # Calculate Height
    if target_w > 0:
        if target_h == 0:
            target_h = int(target_w * src.height / src.width)
            if target_h % 2 != 0:
                target_h -= 1
        
        if target_w % 2 != 0:
            target_w -= 1
            
        if target_w < src.width or target_h < src.height:
             src = core.placebo.Resample(src, target_w, target_h, filter=pl_filter)

# 3. DENOISE
should_denoise = {denoise_enabled}
if should_denoise:
    from vsdenoise import DFTTest
    {denoise_setting}

# 4. DEBAND
should_deband = {deband_enabled}
if should_deband:
    {deband_setting}

# Finalize (Sets 10-bit output)
final = finalize_clip(src)
final.set_output(0)
"""
                with open(vpy_abspath, "w", encoding="utf-8") as file:
                    file.write(vpy_template.format(
                        source=input_abspath_origin, 
                        cache=cache_file_path, 
                        ct=crop_t, 
                        cb=crop_b,
                        downscale=str(do_downscale),
                        target_res=s_target_res,
                        kernel=s_kernel,
                        denoise_enabled=str(do_denoise),
                        denoise_setting=s_denoise_setting,
                        deband_enabled=str(do_deband),
                        deband_setting=s_deband_setting
                    ))
                
                av1an_input = vpy_filename

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
                "-i", av1an_input, # Could be .mkv or .vpy
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