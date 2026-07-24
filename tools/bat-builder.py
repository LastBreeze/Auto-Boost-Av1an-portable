import os

BLUE = "\033[94m"
RED = "\033[91m"
RESET = "\033[0m"

def enable_ansi_colors():
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def main():
    enable_ansi_colors()
    clear_screen()
    print("================================================")
    print("       Auto-Boost / Av1an Batch Builder         ")
    print("================================================\n")
    print("This tool will create a batch script to encode your videos")
    print("Just answer the questions below and your script will be ready to run.")
    print("HDR sources: the SVT-AV1-HDR fork can auto-detect HDR and apply matching color")
    print("settings, or any fork can tonemap HDR content down to SDR (BT.709) via libplacebo.\n")

    # --- 1. Pass Type ---
    print("--------------------------------------------------------")
    print("STEP 1 OF 5: Choose an Encoding Method")
    print("--------------------------------------------------------")
    print("How should the encoder approach your video?\n")
    print("  1: Auto-Boost")
    print("     Two pass encoding with visual metrics. The first pass is")
    print("     a fast-speed preview to measure quality. The second pass")
    print("     uses those measurements to fine-tune the final encode")
    print("     automatically. Can potentially produce better results.\n")
    print("  2: Av1an Single Pass")
    print("     Encodes the video once, straight through.")
    print("     Good if you want faster turnaround.\n")
    print("")
    print("  NOTE: If your video has a lot of grain, pick Av1an Single Pass. Auto-Boost can")
    print("  mistake the grain for fine detail and try to preserve it, which wastes bits")
    print("  and makes your final file much larger than it needs to be.\n")
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

    avx512_value = "False"
    if fork in ("5fish", "essential"):
        print("\n--------------------------------------------------------")
        print("AVX-512 CPU Support")
        print("--------------------------------------------------------")
        print("Some 5fish/essential SVT-AV1 builds have an AVX-512 optimized exe.")
        print("Only select Yes if you are sure your CPU supports AVX-512.")
        print("If you are not sure, press Enter for the default: No.\n")
        print("  1: Yes -- Use the AVX-512 optimized encoder executable")
        print("  2: No  -- Use the standard encoder executable\n")
        avx_choice = input("Does your CPU support AVX-512? [1 Yes / 2 No] (Press Enter for No): ").strip()
        if avx_choice == "1":
            avx512_value = "True"

    # --- HDR Handling (SVT-AV1-HDR fork only; other forks are asked at the end) ---
    tonemap_value = "False"
    if fork == "hdr":
        print("\n--------------------------------------------------------")
        print("HDR Handling (SVT-AV1-HDR fork)")
        print("--------------------------------------------------------")
        print("How should HDR source content be handled?\n")
        print("  1: Auto detect SDR/HDR content")
        print("     MediaInfo detects each source. SDR sources get standard")
        print("     BT.709/BT.601 color settings. HDR sources automatically get")
        print("     matching SVT-AV1-HDR color settings (primaries, transfer,")
        print("     matrix, mastering display, content light) -- HDR stays HDR.\n")
        print("  2: Tonemap HDR to SDR")
        print("     HDR sources are converted to SDR (BT.709) via libplacebo")
        print("     inside the VapourSynth script. Uses GPU. SDR sources are")
        print("     encoded normally.\n")
        hdr_handling_choice = input("Select [1/2] (Press Enter for 1): ").strip()
        if hdr_handling_choice == "2":
            tonemap_value = "True"

    denoise_value = "True" if fork == "5fish" else "False"
    if fork == "5fish":
        print(f"\n{BLUE}--------------------------------------------------------")
        print("5fish Denoise Recommendation")
        print(f"--------------------------------------------------------{RESET}")
        print("For 5fish, denoise=True will be enabled in settings.txt.")
        print("The .bat scripts have the ability to edit denoise= in settings.txt")
        print("This is highly recommended with:")
        print("denoise_setting=src = DFTTest().denoise(src, {0.00:0.30, 0.40:0.30, 0.60:0.60, 0.80:1.50, 1.00:2.00}, planes=[0, 1, 2])\n")
    else:
        print("\nDenoise will be set to False in settings.txt for this generated batch file.")

    # --- 3. CRF ---
    print("\n--------------------------------------------------------")
    print("STEP 3 OF 5: Choose a Quality Level (CRF)")
    print("--------------------------------------------------------")
    print("CRF controls the balance between file size and visual quality.")
    print("Lower numbers = higher quality + larger file size.")
    print("Higher numbers = lower quality + smaller file size.\n")
    print("  Recommended starting points:")
    print("    20 -- Very high quality, large files")
    print("    25 -- Good quality, medium files")
    print("    30 -- Lower quality, small files\n")
    print("If you are unsure, start with 30 and adjust from there.")
    print("You can always re-run this tool to generate a new script.\n")
    crf = input("Enter a CRF value (Press Enter to use the default of 30): ").strip()
    if not crf:
        crf = "30"

    # --- 4. Special Parameters based on Fork ---
    dist_preset = ""
    dist_filename_suffix = ""
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
        print("  4 -- Maximum fidelity. Can significantly increase file size.")
        print("       Mimics SVT-AV1-HDR's tune grain for absolute grain")
        print("       retention with no regard to distortion at all.\n")
        print("Tip: Start at 0. If textures or fine lines look soft or blurry,")
        print("try bumping this up by 1 and compare.\n")
        val = input("Select a fidelity level [0-4] (Press Enter for 0): ").strip()
        if val not in ("0", "1", "2", "3", "4"):
            val = "0"
        dist_filename_suffix = f"-d{val}"
        if val != "0":
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
            if mode == "autoboost":
                print(f"\n{RED}WARNING: Auto-Boost mode is NOT recommended for high grain content.")
                print("Visual metrics can mistake grain for detail, which can lead")
                print("to excessive boosting. For grainy SVT-AV1-HDR content, use")
                print(f"Av1an Single Pass mode instead.{RESET}\n")
            hdr_noise = " --tune 5 --film-grain 10"
        else:
            hdr_noise = " --tune 0 --noise 4"

    # --- 5. Preset Speed ---
    print("\n--------------------------------------------------------")
    print("STEP 5 OF 5: Encoding Speed (Preset)")
    print("--------------------------------------------------------")
    print("This controls how much time and CPU power the encoder spends")
    print("searching for efficient ways to store your video.")
    print("Slower presets = more effort, which usually means better")
    print("quality for the file size (results vary by video).")
    print("Faster presets = quicker encodes, but possibly less efficient")
    print("and less quality.\n")

    print("  Recommended presets for this fork:")
    print("  0 -- Slowest. Maximum effort. Great if you can wait.")
    if fork == "hdr":
        print("  1 -- Improves on preset 2, especially for grainy")
        print("       video. Handles grain better and cleans up some")
        print("       artifacts that other presets can leave behind.")
        print("       With tune grain, it can bring extra quality")
        print("       improvements.")
    else:
        print("  1 -- Possible slight improvement over preset 2,")
        print("       at the cost of extra encode time.")
    print("  2 -- Very high effort. Still slow, but a good choice")
    print("       for encodes you care about.")
    print("  3 -- Not useful at this time. Offers no significant")
    print("       measurable advantage over preset 4.")
    print("  4 -- DEFAULT. Fastest recommended preset. A solid")
    print("       balance of speed and efficiency. Use this if you")
    print("       have a slower CPU or need results sooner.\n")
    print("  WARNING: Presets faster than 4 are not recommended.")
    print("  They skip many of the tools designed to preserve")
    print("  quality while staying efficient, so output quality")
    print("  will suffer.\n")

    default_speed = "4"
    speed = input(f"Enter a preset speed (Press Enter for the recommended default of {default_speed}): ").strip()
    if not speed:
        speed = default_speed

    # --- Dark Scene Quality Boost ---
    print("\n--------------------------------------------------------")
    print("Dark Scene Quality Boost")
    print("--------------------------------------------------------")
    print("By default, AV1 treats dark/low-light scenes as less important")
    print("and gives them less detail. This can cause banding or")
    print("blocking or detail loss in shadows and night scenes.")
    print("--luminance-qp-bias counteracts that by boosting quality in")
    print("those darker frames. How strong do you want that boost?\n")
    print("  20 -- Light: a gentle correction, minimal impact on file size, start here")
    print("  40 -- Balanced: solid improvement for most videos")
    print("  60 -- Higher detail: more significant boosting for dark scenes, higher impact on file size\n")
    luminance_qp_bias = input("Enter luminance QP bias (Press Enter for 20): ").strip()
    if luminance_qp_bias not in ("20", "40", "60"):
        luminance_qp_bias = "20"
    luminance_param = f" --luminance-qp-bias {luminance_qp_bias}"

    # --- Build Parameter Strings ---
    fast_params = ""
    final_params = ""
    has_rename = True
    film_grain_note = ""

    if fork == "5fish":
        fast_params = f"--lineart-psy-bias 3 --texture-psy-bias 3 --hbd-mds 0{luminance_param}"
        final_params = f"--lineart-psy-bias 3 --texture-psy-bias 3 --hbd-mds 1{luminance_param} --lp 3 --photon-noise 200"
        has_rename = False
    elif fork == "essential":
        fast_params = f"--scd 0 --enable-dlf 3{dist_preset}{luminance_param}"
        final_params = f"--scd 0 --enable-dlf 3{dist_preset}{luminance_param} --lp 3 --photon-noise 200"
        film_grain_note = ":: If you'd like to use --film-grain, then --photon-noise must be set to 0, do not remove the setting.\n"
    elif fork == "hdr":
        # Keep base clean for HDR, apply tuning/noise based on user input
        fast_params = ("--tune 0" if "tune 0" in hdr_noise else "--tune 5") + luminance_param
        final_params = f"{hdr_noise.strip()}{luminance_param} --lp 3"
    elif fork == "custom":
        fast_params = luminance_param.strip()
        final_params = f"{luminance_param.strip()} --lp 3 --photon-noise 200"

    # --- Auto Crop ---
    print("\n--------------------------------------------------------")
    print("Auto Crop")
    print("--------------------------------------------------------")
    print("Most movies and TV shows have black bars on the top and bottom")
    print("(letterboxing). Auto crop automatically detects and removes them,")
    print("which saves file space and avoids wasting encoding bits on black areas.\n")
    print("  1: Yes -- Automatically detect and crop black bars")
    print("  2: No  -- Keep the video as-is, no cropping\n")
    print("Tip: If auto crop removes too much or too little, you can open")
    print("settings.txt in Notepad++ and switch to manual crop mode instead.\n")
    autocrop_input = input("Enable auto crop? [1 Yes / 2 No] (Press Enter for No): ").strip()
    use_autocrop = autocrop_input == "1"

    autocrop_flag = " --autocrop" if use_autocrop else ""

    # --- One-Time Worker Optimization ---
    print("\n--------------------------------------------------------")
    print("One-Time Worker Optimization Benchmark")
    print("--------------------------------------------------------")
    print("Optimize av1an svt-av1 and ssim2 worker count for this bat")
    print("script with one-time benchmark? This will target proper cpu")
    print("and gpu saturation for your svt-av1 preset and any filtering.\n")
    print("  1: Yes -- On first launch, this .bat runs a one-time benchmark")
    print("            using YOUR chosen encoder preset/params and any")
    print("            settings.txt filtering. The tuned worker counts are")
    print("            saved inside this .bat and reused on every run.")
    print("  2: No  -- Use the standard shared worker calculation\n")
    optimize_input = input("Select [1 Yes / 2 No] (Press Enter for No): ").strip()
    optimize_workers = optimize_input == "1"

    # --- HDR Handling (non-HDR forks, asked last) ---
    if fork != "hdr":
        print("\n--------------------------------------------------------")
        print("HDR Handling")
        print("--------------------------------------------------------")
        print("This fork is intended for SDR output. If an HDR source is")
        print("dropped into video-input, how should it be handled?\n")
        print("  1: SDR encoding")
        print("     Sources are encoded as-is. SDR sources get standard")
        print("     BT.709/BT.601 color settings when detected.\n")
        print("  2: Tonemap HDR to SDR")
        print("     HDR sources are converted to SDR (BT.709) via libplacebo")
        print("     inside the VapourSynth script. Uses GPU. SDR sources are")
        print("     encoded normally.\n")
        sdr_handling_choice = input("Select [1/2] (Press Enter for the default of 1): ").strip()
        if sdr_handling_choice == "2":
            tonemap_value = "True"

    # --- Construct Script Content ---
    autocrop_suffix = "-autocrop" if use_autocrop else ""
    tonemap_suffix = "-tonemap" if tonemap_value == "True" else ""
    output_filename = f"batbuilder-{mode}-{fork}{dist_filename_suffix}-crf{crf}-p{speed}{autocrop_suffix}{tonemap_suffix}.bat"
    
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
    script += f'set "CRF={crf}"\n'
    script += f'set "fork={fork}"\n'
    script += ":: example forks: 5fish, essential, hdr, custom\n"
    script += f'set "DENOISE={denoise_value}"\n'
    script += ":: DENOISE updates denoise=True/False in settings.txt before dispatch. 5fish defaults to True; all other forks default to False.\n"
    script += f'set "AVX512={avx512_value}"\n'
    script += ":: Set AVX512=True only if your CPU supports AVX-512 and the fork has an AVX-512 build.\n"
    script += f'set "tonemap={tonemap_value}"\n'
    script += ":: tonemap=True converts HDR sources to SDR (BT.709) via libplacebo inside the VapourSynth script (uses GPU).\n"
    script += ":: tonemap=False: the hdr fork auto-detects HDR sources and applies matching SVT-AV1-HDR color settings; other forks encode as-is.\n\n"

    if optimize_workers:
        script += 'set "optimize-workers=true"\n'
        script += 'set "custom-av1an-workers="' + " " * 8 + "\n"
        script += 'set "custom-ssim2-workers="' + " " * 8 + "\n"
        script += 'set "custom-ssim2-tool="' + " " * 16 + "\n"
        script += ":: The one-time optimized benchmark fills in the custom worker/stream values and SSIMU2 tool above.\n"
        script += ":: custom-ssim2-tool values: vs-hip nvidia, vs-hip vulkan, ffvship nvidia, ffvship vulkan, vs-zip.\n"
        script += ":: The trailing spaces after the closing quotes are RESERVED so the benchmark can edit this\n"
        script += ":: running .bat in-place without shifting cmd.exe's byte offsets - do not delete them.\n"
        script += ":: To re-run a benchmark, clear the custom value between = and the closing quote.\n"
        script += ":: To disable optimized workers, set optimize-workers=false.\n\n"
    
    script += "del tools\\bat*.txt\n"
    script += "move *.mkv video-input\nmove *.mp4 video-input\nmove *.m2ts video-input\n"
    script += "cls\nsetlocal enableextensions disabledelayedexpansion\n\n"
    script += ":: Set the current working directory\ncd /d \"%~dp0\"\n\n"
    
    script += ":: --- STEP 0A: CREATE BATCH MARKER ---\necho.\ntype NUL > \"tools\\bat-used-%~nx0.txt\"\n\n"
    script += ":: --- STEP 0B: SET TEMP PATH ---\nset \"PATH=%~dp0VapourSynth;%~dp0tools\\av1an;%~dp0tools\\MKVToolNix;%PATH%\"\n\n"

    # Optimized One-Time Benchmark (encode workers)
    if optimize_workers:
        script += ":: --- STEP 1-OPT: ONE-TIME OPTIMIZED WORKER BENCHMARK (ENCODE) ---\n"
        script += "\"VapourSynth\\python.exe\" \"tools\\workercount.py\" --optimize-bat \"%~f0\"\n"
        script += "if defined custom-av1an-workers set \"WORKER_COUNT=%custom-av1an-workers%\"\n\n"

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

    # Optimized One-Time Benchmark (SSIMU2 vs-zip workers, Autoboost Only)
    if mode == "autoboost" and optimize_workers:
        script += ":: --- STEP 1B-OPT: ONE-TIME OPTIMIZED SSIMU2 BENCHMARK ---\n"
        script += "\"VapourSynth\\python.exe\" \"tools\\ssimu2-workercount.py\" --optimize-bat \"%~f0\"\n"
        script += "if defined custom-ssim2-tool set \"SSIMU2_TOOL=%custom-ssim2-tool%\"\n"
        script += "if defined custom-ssim2-workers set \"SSIMU2_WORKERS=%custom-ssim2-workers%\"\n\n"

    # Worker Check SSIMU2 (Autoboost Only)
    if mode == "autoboost":
        script += ":: --- STEP 1B: WORKER COUNT CHECK (SSIMU2) ---\n"
        script += "if exist \"tools\\workercount-ssimu2.txt\" (\n"
        script += "    REM Read config\n"
        script += "    for /f \"usebackq tokens=1,2 delims==\" %%a in (\"tools\\workercount-ssimu2.txt\") do (\n"
        script += "        if /I \"%%a\"==\"tool\" set \"SSIMU2_TOOL=%%b\"\n"
        script += "        if /I \"%%a\"==\"workercount\" set \"SSIMU2_WORKERS=%%b\"\n"
        script += "    )\n) else (\n"
        script += "    echo.\n    echo -------------------------------------------------------------------------------\n"
        script += "    echo First Run Detected: Calculating optimal SSIMU2 settings...\n"
        script += "    echo -------------------------------------------------------------------------------\n"
        script += "    echo Checking GPU support ^(vs-hip^) and CPU benchmarks...\n"
        script += "    \"VapourSynth\\python.exe\" \"tools\\ssimu2-workercount.py\"\n    \n"
        script += "    REM Read config after generation\n"
        script += "    for /f \"usebackq tokens=1,2 delims==\" %%a in (\"tools\\workercount-ssimu2.txt\") do (\n"
        script += "        if /I \"%%a\"==\"tool\" set \"SSIMU2_TOOL=%%b\"\n"
        script += "        if /I \"%%a\"==\"workercount\" set \"SSIMU2_WORKERS=%%b\"\n"
        script += "    )\n  \n"
        script += "    REM Pause so user can see benchmark results, then continue\n"
        script += "    echo.\n    echo av1an worker count and SSIMU2 benchmark complete.\n"
        script += "    echo You may edit workercount-config.txt and workercount-ssimu2.txt, or delete these .txt files if you want to run the\n"
        script += "\techo benchmark again.\n"
        script += "    echo Task Manager is not accurate for displaying CPU percent used, use hwinfo. Not enough cpu%% being\n"
        script += "\techo used? increase worker count.\n"
        script += "    echo CPU oversaturated and PC is unusable during encoding or out of ram errors?\n"
        script += "\techo Decrease worker count.\n"
        script += "    pause\n)\n\n"

    if optimize_workers:
        script += "if defined custom-av1an-workers set \"WORKER_COUNT=%custom-av1an-workers%\"\n"

    if mode == "autoboost":
        if optimize_workers:
            script += "if defined custom-ssim2-tool set \"SSIMU2_TOOL=%custom-ssim2-tool%\"\n"
            script += "if defined custom-ssim2-workers set \"SSIMU2_WORKERS=%custom-ssim2-workers%\"\n"
        script += "if not defined SSIMU2_TOOL set \"SSIMU2_TOOL=vs-hip\"\n"
        script += "if not defined SSIMU2_WORKERS set \"SSIMU2_WORKERS=1\"\n\n"

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
        script += f"\"VapourSynth\\python.exe\" \"tools\\dispatch.py\" --fork %fork% --avx512 %AVX512% --denoise %DENOISE% --tonemap %tonemap% --crf %CRF%{autocrop_flag} --ssimu2 \"%SSIMU2_TOOL%\" --verbose --ssimu2-cpu-workers %SSIMU2_WORKERS% --resume --fast-speed 8 --final-speed %FINAL_SPEED% --workers %WORKER_COUNT% --fast-params \"%FAST_PARAMS%\" --final-params \"%FINAL_PARAMS%\"\n\n"
    else:
        script += f"\"VapourSynth\\python.exe\" \"tools\\av1an-dispatch.py\" --resume --fork %fork% --avx512 %AVX512% --denoise %DENOISE% --tonemap %tonemap%{autocrop_flag} --crf %CRF% --workers %WORKER_COUNT% --final-speed %FINAL_SPEED% --final-params \"%av1an_settings%\"\n\n"

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
