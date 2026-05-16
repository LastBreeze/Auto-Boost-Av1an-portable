import sys
import subprocess
import os
import glob
import shutil
import re
from wakepy import keep

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
    av1an_dir = os.path.join(tools_dir, "av1an")
    forks_dir = os.path.join(av1an_dir, "svt-av1 forks")
    
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

    # --- Copy settings.txt to Temp ---
    # Auto-Boost-Av1an.py searches CWD (temp) for settings.txt
    settings_src = os.path.join(root_dir, "settings.txt")
    settings_dst = os.path.join(temp_dir, "settings.txt")

    if os.path.exists(settings_src):
        try:
            shutil.copy2(settings_src, settings_dst)
            print(f"[Dispatch] Copied settings.txt to temp folder.")
        except Exception as e:
            print(f"[Dispatch] Warning: Failed to copy settings.txt: {e}")
    else:
        print(f"[Dispatch] Warning: settings.txt not found at {settings_src}")

    # --- Fork Selection & AVX-512 Check ---
    print("\n[Dispatch] Checking SVT-AV1 fork settings...")
    bat_marker_files = glob.glob(os.path.join(tools_dir, "bat-used-*.txt"))
    selected_fork = None

    if bat_marker_files:
        marker_file = bat_marker_files[0]
        bat_filename = os.path.basename(marker_file).replace("bat-used-", "").replace(".txt", "")
        bat_path = os.path.join(root_dir, bat_filename)

        if os.path.exists(bat_path):
            try:
                with open(bat_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    match = re.search(r'set\s+"fork=([^"]+)"', content, re.IGNORECASE)
                    if match:
                        selected_fork = match.group(1).lower().strip()
                        print(f"[Dispatch] Found fork '{selected_fork}' configured in {bat_filename}")

                        # --- HDR Fork Color Space Warning ---
                        if "hdr" in selected_fork:
                            has_primaries = "--color-primaries" in content
                            has_transfer = "--transfer-characteristics" in content
                            has_matrix = "--matrix-coefficients" in content

                            if not (has_primaries and has_transfer and has_matrix):
                                print("\n\033[93m[WARNING] Missing color space settings for HDR fork!\033[0m")
                                print("With the svt-av1-hdr fork, color settings must be set manually in your bat file.")
                                print("It is up to you to choose SDR or HDR specific settings.")
                                print("Please ensure these parameters are set manually in your bat file:")
                                print("  --color-primaries --transfer-characteristics --matrix-coefficients\n")
                                print(r'If you want a guide, you can goto "tools\av1an\svt-av1 forks" and do "SvtAv1EncApp.exe --color-help"')
                                print("")
                                os.system("pause")

            except Exception as e:
                print(f"[Dispatch] Error reading batch file for fork: {e}")
        else:
            print(f"[Dispatch] Warning: Batch file {bat_path} not found.")
    else:
        print("[Dispatch] Warning: No bat-used-*.txt marker found in tools dir.")

    if selected_fork and os.path.exists(forks_dir):
        # Determine AVX-512 Support
        avx512_supported = False
        try:
            from cpuinfo import get_cpu_info
            info = get_cpu_info()
            if 'avx512f' in info.get('flags', []):
                avx512_supported = True
                print("[Dispatch] CPU supports AVX-512.")
            else:
                print("[Dispatch] CPU does not support AVX-512.")
        except ImportError:
            print("[Dispatch] Warning: py-cpuinfo not installed. Assuming no AVX-512 support.")

        # Find matching fork parent directory
        fork_parent = None
        for f in os.listdir(forks_dir):
            if os.path.isdir(os.path.join(forks_dir, f)) and selected_fork in f.lower():
                fork_parent = os.path.join(forks_dir, f)
                break

        if fork_parent:
            target_subfolder = None
            subfolders = [d for d in os.listdir(fork_parent) if os.path.isdir(os.path.join(fork_parent, d))]

            if avx512_supported:
                # Look for AVX-512 optimized builds
                for sub in subfolders:
                    sub_lower = sub.lower()
                    if 'icelake' in sub_lower or 'znver5' in sub_lower or 'znver4' in sub_lower:
                        target_subfolder = sub
                        break

            if not target_subfolder:
                # Fallback to x86-64-v3
                for sub in subfolders:
                    if 'x86-64-v3' in sub.lower():
                        target_subfolder = sub
                        break

            if not target_subfolder and subfolders:
                target_subfolder = subfolders[0]  # Fallback to first available

            if target_subfolder:
                src_dir = os.path.join(fork_parent, target_subfolder)
                exe_src = os.path.join(src_dir, "SvtAv1EncApp.exe")
                dll_src = os.path.join(src_dir, "ffms2.dll")
                
                exe_dest = os.path.join(av1an_dir, "SvtAv1EncApp.exe")
                dll_dest = os.path.join(av1an_dir, "ffms2.dll")

                # Clean up existing files in tools/av1an
                try:
                    if os.path.exists(exe_dest):
                        os.remove(exe_dest)
                    if os.path.exists(dll_dest):
                        os.remove(dll_dest)
                except Exception as e:
                    print(f"[Dispatch] Warning: Could not clean up old SVT-AV1 files: {e}")

                # Copy new binaries
                if os.path.exists(exe_src):
                    try:
                        shutil.copy2(exe_src, exe_dest)
                        print(f"[Dispatch] Copied SvtAv1EncApp.exe from {target_subfolder}")
                        
                        # Copy ffms2.dll if fork is "essential"
                        if "essential" in selected_fork and os.path.exists(dll_src):
                            shutil.copy2(dll_src, dll_dest)
                            print(f"[Dispatch] Copied ffms2.dll from {target_subfolder}")
                    except Exception as e:
                        print(f"[Dispatch] Error copying fork files: {e}")
                else:
                    print(f"[Dispatch] Error: SvtAv1EncApp.exe not found in {src_dir}")
        else:
            print(f"[Dispatch] Warning: Could not find a fork directory matching '{selected_fork}'")
            
    print("-" * 80)

    # --- Argument Parsing (Settings only) ---
    args = sys.argv[1:]
    
    # Extract worker count for logic checks
    worker_count = None
    for idx, arg in enumerate(args):
        if arg == "--workers" and idx + 1 < len(args):
            try:
                worker_count = int(args[idx + 1])
            except ValueError:
                pass

    # --- Worker Safety Check ---
    strip_lp_3 = False
    if worker_count is not None and worker_count in (1, 2):
        print("\033[93m[Dispatch] 1-2 workers detected, setting --lp mode to default auto parallelism\033[0m")
        strip_lp_3 = True

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
                    subprocess.check_call(cmd_scene, cwd=temp_dir)
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
            final_cmd = [sys.executable, av1an_script, "-i", input_abspath_origin, "--scenes", json_file]
            
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
            try:
                with keep.running():
                    subprocess.check_call(final_cmd, cwd=temp_dir)
            except subprocess.CalledProcessError:
                print("[Dispatch] Encoding failed.")
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
    print("Dispatch Batch Complete.")
    print("="*80)

if __name__ == "__main__":
    main()