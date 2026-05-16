import os

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def main():
    clear_screen()
    print("================================================")
    print("       Auto-Boost / Av1an Batch Builder         ")
    print("================================================\n")
    print("This tool will create a batch script to encode your videos")
    print("Just answer the questions below and your script will be ready to run.")
    print("SVT-AV1-HDR fork requires manually editing the output .bat file for color settings.\n")    

    # --- 1. Pass Type ---
    print("--------------------------------------------------------")
    print("STEP 1 OF 5: Choose an Encoding Method")
    print("--------------------------------------------------------")
    print("How should the encoder approach your video?\n")
    print("  1: Auto-Boost")
    print("     Two pass encoding with visual metrics. The first pass is a fast-speed")
    print("     preview to measure quality. The second pass uses those")
    print("     measurements to fine-tune the final encode automatically.")
    print("     Takes longer, but can potentially produce better results.\n")
    print("  2: Av1an Single Pass")
    print("     Encodes the video once, straight through.")
    print("     Good if you want faster turnaround.\n")
    mode_choice = input("Select [1/2]: ").strip()
    mode = "autoboost" if mode_choice == "1" else "av1an"

    # --- 2. Fork ---
    print("\n--------------------------------------------------------")
    print("STEP 2 OF 5: Choose an Encoder Preset (Fork)")
    print("--------------------------------------------------------")
    print("Different forks are tuned for different types of video.")
    print("Think of these like pre-configured settings profiles:\n")
    print("  1: 5fish       -- Best for: Anime")
    print("                    Tuned for animation's sharp lines and")
    print("                    subtle detailed textures.\n")
    print("  2: essential   -- Best for: Anime or Live Action")
    print("                    A well-rounded profile that works great on")
    print("                    both animated and real-world footage.")
    print("                    User scalable detail retention.\n")
    print("  3: hdr         -- Best for: HDR or SDR Live Action")
    print("                    Specifically designed to retain live action")
    print("                    detail and grain.\n")
    print("  4: custom      -- For advanced users only.")
    print("                    Use your own custom encoder binary.")
    print("                    Place SvtAv1EncApp.exe in:")
    print("                    tools\\av1an\\svt-av1 forks\\custom\n")
    fork_choice = input("Select [1-4]: ").strip()
    fork_map = {"1": "5fish", "2": "essential", "3": "hdr", "4": "custom"}
    fork = fork_map.get(fork_choice, "essential")

    # --- 3. CRF ---
    print("\n--------------------------------------------------------")
    print("STEP 3 OF 5: Choose a Quality Level (CRF)")
    print("--------------------------------------------------------")
    print("CRF controls the balance between file size and visual quality.")
    print("Lower numbers = higher quality + larger file size.")
    print("Higher numbers = lower quality + smaller file size.\n")
    print("  Recommended starting points:")
    print("    20 -- Very high quality, large files")
    print("    25 -- Good quality, medium files (most people use this range)")
    print("    30 -- Lower quality, small files\n")
    print("If you are unsure, start with 30 and adjust from there.")
    print("You can always re-run this tool to generate a new script.\n")
    crf = input("Enter a CRF value (Press Enter to use the default of 30): ").strip()
    if not crf:
        crf = "30"

    # --- 4. Special Parameters based on Fork ---
    dist_preset = ""
    if fork == "essential":
        print("\n--------------------------------------------------------")
        print("STEP 4 OF 5: Fidelity / Detail Preservation (essential fork)")
        print("--------------------------------------------------------")
        print("This setting controls how aggressively the encoder preserves")
        print("fine detail vs. smoothing things out to save space.\n")
        print("  0 -- Default. Balanced. Good for most content. Start here.")
        print("  1 -- Slightly more detail preserved.")
        print("  2 -- Noticeably more detail (may increase file size a bit).")
        print("  3 -- High fidelity. Good for very detailed scenes.")
        print("  4 -- Maximum fidelity. Can significantly increase file size.\n")
        print("Tip: Start at 0. If textures or fine lines look soft or blurry,")
        print("try bumping this up by 1 and compare.\n")
        val = input("Select a fidelity level [0-4] (Press Enter for 0): ").strip()
        if val and val != "0":
            dist_preset = f" --distortion-bias-preset {val}"

    hdr_noise = ""
    if fork == "hdr":
        print("\n--------------------------------------------------------")
        print("STEP 4 OF 5: Film Grain / Noise Handling (hdr fork)")
        print("--------------------------------------------------------")
        print("Real-world video (especially film) contains natural grain/noise.")
        print("This setting tells the encoder how to handle it:\n")
        print("  1: Clean / Low Noise")
        print("     Best for: Modern digital footage, clean CGI, animation.")
        print("     The encoder will smooth out noise rather than preserve it.\n")
        print("  2: Film Grain Mode")
        print("     Best for: Film-sourced content, older movies, grainy footage.")
        print("     Preserves the natural film grain in your source video.\n")
        noise_choice = input("Select mode [1/2]: ").strip()
        if noise_choice == "2":
            hdr_noise = " --tune 5 --film-grain 10"
        else:
            hdr_noise = " --tune 0 --noise 4"

    # --- 5. Preset Speed ---
    print("\n--------------------------------------------------------")
    print("STEP 5 OF 5: Encoding Speed")
    print("--------------------------------------------------------")
    print("This controls how much time and CPU power the encoder uses.")
    print("Slower speeds = better compression and quality at the same file size.")
    print("Faster speeds = quicker encode, but slightly less efficient.\n")

    if fork == "hdr":
        print("  Recommended speeds for the HDR fork:")
        print("  0 -- Slowest. Best possible quality. Use if you have time.")
        print("  2 -- DEFAULT. Ideal balance of quality and speed for HDR.")
        print("       Highly recommended -- preserves grain and detail well.")
        print("  4 -- Faster. Minimum recommended speed. Only use if your")
        print("       CPU is too slow for preset 2.\n")
        print("  WARNING: Do not go faster than preset 4. Speeds above 4 skip")
        print("  too many quality-preserving tools and will hurt your output.\n")
        default_speed = "2"
    else:
        print("  Recommended speeds for this fork:")
        print("  0 -- Slowest. Maximum quality. Great if you can wait.")
        print("  2 -- Excellent quality. Still slow, but worth it for important encodes.")
        print("  4 -- DEFAULT. Fastest recommended speed. Good quality/speed tradeoff.")
        print("       Use this if you have a slower CPU or need faster results.\n")
        print("  WARNING: Do not go faster than preset 4. Speeds above 4 skip")
        print("  too many quality-preserving tools and will hurt your output.\n")
        default_speed = "4"

    speed = input(f"Enter a preset speed (Press Enter for the recommended default of {default_speed}): ").strip()
    if not speed:
        speed = default_speed

    # --- Build Parameter Strings ---
    fast_params = ""
    final_params = ""
    has_rename = True
    film_grain_note = ""

    if fork == "5fish":
        fast_params = "--lineart-psy-bias 4 --texture-psy-bias 2 --hbd-mds 0 --keyint 305 --noise-level-thr 16000 --tune 0 --filtering-noise-detection 4"
        final_params = "--lineart-psy-bias 4 --texture-psy-bias 2 --hbd-mds 1 --keyint 305 --noise-level-thr 16000 --tune 0 --filtering-noise-detection 4 --lp 3 --photon-noise 200"
        has_rename = False
    elif fork == "essential":
        if mode == "autoboost":
            fast_params = f"--ac-bias 1.0 --tx-bias 3 --luminance-qp-bias 20 --enable-alt-dlf 1 --qp-scale-compress-strength 3 --complex-hvs 1{dist_preset}"
            final_params = f"--ac-bias 1.0 --tx-bias 3 --luminance-qp-bias 20 --enable-alt-dlf 1 --qp-scale-compress-strength 3 --complex-hvs 1 --photon-noise 200{dist_preset}"
        else: # av1an mode
            fast_params = f"--ac-bias 1.0 --tx-bias 3 --luminance-qp-bias 20 --enable-alt-dlf 1 --complex-hvs 1{dist_preset}"
            final_params = f"--ac-bias 1.0 --tx-bias 3 --luminance-qp-bias 20 --enable-alt-dlf 1 --complex-hvs 1 --photon-noise 200{dist_preset}"
        film_grain_note = ":: If you'd like to use --film-grain, then --photon-noise must be set to 0, do not remove the setting.\n"
    elif fork == "hdr":
        # Keep base clean for HDR, apply tuning/noise based on user input
        fast_params = "--tune 0" if "tune 0" in hdr_noise else "--tune 5"
        final_params = f"{hdr_noise.strip()}"
    elif fork == "custom":
        fast_params = ""
        final_params = ""

    autocrop_flag = " --autocrop" if fork != "5fish" else ""

    # --- Construct Script Content ---
    output_filename = f"batbuilder-{mode}-{fork}-crf{crf}-p{speed}.bat"
    
    script = "@echo off\n"
    
    if mode == "autoboost":
        script += ":: Notepad++ is suggested for editing this file. Never add noise/grain to fast params, this will break metrics.\n"
        script += f'set "FAST_PARAMS={fast_params}"\n'
        script += f'set "FINAL_PARAMS={final_params}"\n'
    else:
        script += ":: Notepad++ is suggested for editing this file.\n"
        script += ":: This batch file uses av1an-dispatch.py to call av1an.exe directly.\n"
        script += f'set "av1an_settings={final_params}"\n'

    script += f'set "FINAL_SPEED={speed}"\n'
    script += f'set "QUALITY={crf}"\n'
    script += ":: Set photon noise to 0 if using film-grain\n"
    script += f'set "fork={fork}"\n'
    script += ":: example forks: 5fish, essential, hdr, custom\n\n"
    
    script += "del tools\\bat*.txt\n"
    script += "move *.mkv video-input\nmove *.mp4 video-input\nmove *.m2ts video-input\n"
    script += "cls\nsetlocal enableextensions disabledelayedexpansion\n\n"
    script += ":: Set the current working directory\ncd /d \"%~dp0\"\n\n"
    
    script += ":: --- STEP 0A: CREATE BATCH MARKER ---\necho.\ntype NUL > \"tools\\bat-used-%~nx0.txt\"\n\n"
    script += ":: --- STEP 0B: SET TEMP PATH ---\nset \"PATH=%~dp0VapourSynth;%~dp0tools\\av1an;%~dp0tools\\MKVToolNix;%PATH%\"\n\n"

    # Worker Check Encoding
    script += ":: --- STEP 1A: WORKER COUNT CHECK (ENCODE) ---\n" if mode == "autoboost" else ":: --- STEP 1: WORKER COUNT CHECK ---\n"
    script += "if exist \"tools\\workercount-config.txt\" (\n"
    if mode == "autoboost":
        script += "    REM Read the worker count from the config file\n"
    script += "    for /f \"usebackq tokens=2 delims==\" %%a in (\"tools\\workercount-config.txt\") do set WORKER_COUNT=%%a\n"
    script += ") else (\n"
    script += "    echo.\n    echo -------------------------------------------------------------------------------\n"
    script += "    echo First Run Detected: Calculating optimal encode worker count...\n"
    script += "    echo -------------------------------------------------------------------------------\n"
    script += "    \"VapourSynth\\python.exe\" \"tools\\workercount.py\"\n"
    if mode == "autoboost":
        script += "    \n    REM Reload config after generation\n"
    script += "    for /f \"usebackq tokens=2 delims==\" %%a in (\"tools\\workercount-config.txt\") do set WORKER_COUNT=%%a\n"
    if mode == "autoboost":
        script += "    \n    REM Pause so user can see the calculation results, then continue\n"
    script += "    echo.\n    echo Encode worker count calculated.\n"
    if mode == "autoboost":
        script += ")\n\n"
    else:
        script += ")\n\n"

    # Worker Check SSIMU2 (Autoboost Only)
    if mode == "autoboost":
        script += ":: --- STEP 1B: WORKER COUNT CHECK (SSIMU2) ---\n"
        script += "if exist \"tools\\workercount-ssimu2.txt\" (\n"
        script += "    REM Read config\n"
        script += "    for /f \"usebackq tokens=2 delims==\" %%a in (\"tools\\workercount-ssimu2.txt\") do (\n"
        script += "        if \"%%a\" NEQ \"\" (\n"
        script += "            if not defined SSIMU2_TOOL (\n"
        script += "                set \"SSIMU2_TOOL=%%a\"\n"
        script += "            ) else (\n"
        script += "                set \"SSIMU2_WORKERS=%%a\"\n"
        script += "            )\n        )\n    )\n) else (\n"
        script += "    echo.\n    echo -------------------------------------------------------------------------------\n"
        script += "    echo First Run Detected: Calculating optimal SSIMU2 settings...\n"
        script += "    echo -------------------------------------------------------------------------------\n"
        script += "    echo Checking GPU support ^(vs-hip^) and CPU benchmarks...\n"
        script += "    \"VapourSynth\\python.exe\" \"tools\\ssimu2-workercount.py\"\n    \n"
        script += "    REM Read config after generation\n"
        script += "    for /f \"usebackq tokens=2 delims==\" %%a in (\"tools\\workercount-ssimu2.txt\") do (\n"
        script += "        if \"%%a\" NEQ \"\" (\n"
        script += "            if not defined SSIMU2_TOOL (\n"
        script += "                set \"SSIMU2_TOOL=%%a\"\n"
        script += "            ) else (\n"
        script += "                set \"SSIMU2_WORKERS=%%a\"\n"
        script += "            )\n        )\n    )\n  \n"
        script += "    REM Pause so user can see benchmark results, then continue\n"
        script += "    echo.\n    echo av1an worker count and SSIMU2 benchmark complete.\n"
        script += "    echo You may edit workercount-config.txt and workercount-ssimu2.txt, or delete these .txt files if you want to run the\n"
        script += "\techo benchmark again.\n"
        script += "    echo Task Manager is not accurate for displaying CPU percent used, use hwinfo. Not enough cpu%% being\n"
        script += "\techo used? increase worker count.\n"
        script += "    echo CPU oversaturated and PC is unusable during encoding or out of ram errors?\n"
        script += "\techo Decrease worker count.\n"
        script += "    pause\n)\n\n"

    step_num = 2

    # Renaming
    if has_rename:
        script += f":: --- STEP {step_num}: RENAMING ---\n"
        script += "echo Starting Renaming Process...\n"
        script += "\"VapourSynth\\python.exe\" \"tools\\rename.py\"\n\n"
        step_num += 1

    # Dispatch
    if mode == "autoboost":
        script += f":: --- STEP {step_num}: HANDOFF TO DISPATCH ---\n"
        script += "echo Starting Auto-Boost-Av1an Dispatcher...\n"
    else:
        script += f":: --- STEP {step_num}: DISPATCH ---\n"
        script += "echo Starting Av1an Direct Dispatcher...\n"
    
    script += "echo Encoding inputs from: video-input\necho Outputs will go to:   video-output\necho.\n"
    
    if film_grain_note:
        script += film_grain_note
        
    if mode == "autoboost":
        script += f"\"VapourSynth\\python.exe\" \"tools\\dispatch.py\" --quality %QUALITY%{autocrop_flag} --ssimu2 %SSIMU2_TOOL% --verbose --ssimu2-cpu-workers %SSIMU2_WORKERS% --resume --fast-speed 8 --final-speed %FINAL_SPEED% --workers %WORKER_COUNT% --fast-params \"%FAST_PARAMS%\" --final-params \"%FINAL_PARAMS%\"\n\n"
    else:
        script += f"\"VapourSynth\\python.exe\" \"tools\\av1an-dispatch.py\"{autocrop_flag} --quality %QUALITY% --workers %WORKER_COUNT% --final-speed %FINAL_SPEED% --final-params \"%av1an_settings%\"\n\n"

    script += "echo.\necho All tasks finished.\npause\n\n"
    step_num += 1

    # Cleanup
    script += f":: --- STEP {step_num}: CLEANUP ---\n"
    script += "echo Cleaning up temporary files and folders...\n"
    script += "\"VapourSynth\\python.exe\" \"tools\\cleanup.py\"\n"

    # --- Write to Output ---
    # Put it in the root folder (one directory up from tools)
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(root_dir, output_filename)
    
    with open(file_path, 'w') as f:
        f.write(script)

    print("\n-------------------------------------------------------------------------------")
    print(f"Success! Your batch script has been generated:")
    print(f"File: {output_filename}")
    print("-------------------------------------------------------------------------------")
    print("Drop your video files into the 'video-input' folder, then double-click")
    print("the .bat file to start encoding. Encoded files will appear in 'video-output'.")
    print("")
    print("Want to tweak the settings manually? Open the .bat file in Notepad++.")
    print("-------------------------------------------------------------------------------")
    os.system('pause')

if __name__ == "__main__":
    main()
