import os
import re
import shutil

BLUE = "\033[94m"
RED = "\033[91m"
RESET = "\033[0m"

# The CPU build menu, and the cputarget= value each option stores in
# tools\workercount-config.txt so the next build can default to it.
ARCH_BY_CHOICE = {"1": "znver2", "2": "x86-64-v3", "3": "avx512"}
CHOICE_BY_ARCH = {arch: choice for choice, arch in ARCH_BY_CHOICE.items()}


def workercount_config_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "workercount-config.txt")


def read_saved_arch():
    """The cputarget= remembered in tools\\workercount-config.txt, or None."""
    try:
        with open(workercount_config_path(), "r", encoding="utf-8",
                  errors="ignore") as handle:
            text = handle.read()
    except OSError:
        return None
    match = re.search(r"^\s*cputarget\s*=\s*(\S+)", text,
                      re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    arch = match.group(1).strip().lower()
    return arch if arch in CHOICE_BY_ARCH else None


def save_arch(arch):
    """Remember the chosen CPU build in tools\\workercount-config.txt.

    cputarget goes on the first line and the existing workers= line stays
    last, because the .bat files read this file with a for/f loop where the
    last line wins. For the same reason a file with no workers= line is left
    alone: the .bats treat the file existing as "the worker benchmark already
    ran", so writing a lone cputarget= would skip the benchmark and hand av1an
    an empty worker count. Once any encode has run, the line is there and the
    setting sticks.
    """
    path = workercount_config_path()
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return
    kept = [line for line in lines
            if line.strip() and not re.match(r"\s*cputarget\s*=", line, re.IGNORECASE)]
    if not any(re.match(r"\s*workers\s*=", line, re.IGNORECASE) for line in kept):
        return
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"cputarget={arch}\n")
            for line in kept:
                handle.write(line.rstrip() + "\n")
    except OSError:
        pass

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

def setup_condor():
    """Copy tools\\condor-builder.bat into the main folder so it can be run from there.

    Returns True if the tool was set up (caller should stop), False to go back
    to the main menu.
    """
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(tools_dir)
    source = os.path.join(tools_dir, "condor-builder.bat")
    dest = os.path.join(root_dir, "condor-builder.bat")

    if not os.path.exists(source):
        print(f"\n{RED}Could not find tools\\condor-builder.bat.")
        print(f"Your install may be incomplete - try re-downloading the package.{RESET}")
        os.system('pause')
        return True

    if os.path.exists(dest):
        print("\ncondor-builder.bat already exists in the main folder.")
        print("Overwriting will discard any edits you made to it.\n")
        overwrite = input("Replace it with a fresh copy? [1 Yes / 2 No] (Press Enter for No): ").strip()
        if overwrite != "1":
            print("\nLeft the existing condor-builder.bat alone. Nothing was changed.")
            os.system('pause')
            return True

    shutil.copy2(source, dest)

    print("\n-------------------------------------------------------------------------------")
    print("Condor is ready.")
    print("File: condor-builder.bat (main folder)")
    print("-------------------------------------------------------------------------------")
    print("Run it from the main folder to build a Condor batch script, which lets you")
    print("set a target quality using CVVDP, SSIM2, butteraugli or XPSNR instead of a")
    print("fixed CRF.")
    print("-------------------------------------------------------------------------------")
    os.system('pause')
    return True

def lqtc_acknowledgement():
    """Show the LQTC "I understand" page.

    Returns True if the user chose to continue, False to go back.
    """
    items = [
        ["I will use the Windows command line to see if LQTC",
         "displays an error for a hardware incompatibility."],
        ["I know how to extract and apply my own AV1 grain synth",
         "tables, and I will edit the grain .bat files in",
         "video-output manually."],
        ["I accept that LQTC might not be compatible with my PC."],
        ["I accept and understand that this package has two target",
         "based encoders, and if one doesn't work, I can use the",
         "other."],
        ["I know what x86-64-v3 / znver2 / avx512 means."],
    ]

    while True:
        clear_screen()
        print("================================================")
        print("      Large Quality Target Collider (LQTC)      ")
        print("================================================\n")
        print("Before setting up LQTC, please read and accept the following:\n")
        for item in items:
            print(f"  I understand: {item[0]}")
            for extra in item[1:]:
                print(f"                {extra}")
            print("")
        print("------------------------------------------------")
        print("  1. Continue -- I understand all of the above")
        print("  2. Go back\n")
        choice = input("Select [1/2] (Press Enter to go back): ").strip()

        if choice == "1":
            return True
        if choice == "2" or choice == "":
            return False

def setup_lqtc():
    """Copy tools\\lqtc-builder.bat into the main folder so it can be run from there.

    Also copies the contents of tools\\grav1synth into video-output, since LQTC
    needs it there.

    Returns True if the tool was set up (caller should stop), False to go back
    to the main menu.
    """
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(tools_dir)
    source = os.path.join(tools_dir, "lqtc-builder.bat")
    dest = os.path.join(root_dir, "lqtc-builder.bat")

    if not os.path.exists(source):
        print(f"\n{RED}Could not find tools\\lqtc-builder.bat.")
        print(f"Your install may be incomplete - try re-downloading the package.{RESET}")
        os.system('pause')
        return True

    if os.path.exists(dest):
        print("\nlqtc-builder.bat already exists in the main folder.")
        print("Overwriting will discard any edits you made to it.\n")
        overwrite = input("Replace it with a fresh copy? [1 Yes / 2 No] (Press Enter for No): ").strip()
        if overwrite != "1":
            print("\nLeft the existing lqtc-builder.bat alone. Nothing was changed.")
            os.system('pause')
            return True

    shutil.copy2(source, dest)

    grav1synth_src = os.path.join(tools_dir, "grav1synth")
    grav1synth_dest = os.path.join(root_dir, "video-output")
    grav1synth_copied = False
    if os.path.isdir(grav1synth_src):
        os.makedirs(grav1synth_dest, exist_ok=True)
        shutil.copytree(grav1synth_src, grav1synth_dest, dirs_exist_ok=True)
        grav1synth_copied = True
    else:
        print(f"\n{RED}Could not find tools\\grav1synth - skipping the grav1synth copy.")
        print(f"Your install may be incomplete - try re-downloading the package.{RESET}")

    print("\n-------------------------------------------------------------------------------")
    print("Large Quality Target Collider is ready.")
    print("File: lqtc-builder.bat (main folder)")
    if grav1synth_copied:
        print("grav1synth files copied into video-output.")
    print("-------------------------------------------------------------------------------")
    print("Run it from the main folder to build an LQTC batch script, which lets you")
    print("set a target quality using CVVDP or SSIM2 instead of a fixed CRF.")
    print("-------------------------------------------------------------------------------")
    os.system('pause')
    return True

def setup_afterzone():
    """Copy tools\\AfterZone.bat into the main folder so it can be run from there.

    Returns True if the tool was set up (caller should stop), False to go back
    to the main menu.
    """
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(tools_dir)
    source = os.path.join(tools_dir, "AfterZone.bat")
    dest = os.path.join(root_dir, "AfterZone.bat")

    if not os.path.exists(source):
        print(f"\n{RED}Could not find tools\\AfterZone.bat.")
        print(f"Your install may be incomplete - try re-downloading the package.{RESET}")
        os.system('pause')
        return True

    if os.path.exists(dest):
        print("\nAfterZone.bat already exists in the main folder.")
        print("Overwriting will discard any edits you made to it.\n")
        overwrite = input("Replace it with a fresh copy? [1 Yes / 2 No] (Press Enter for No): ").strip()
        if overwrite != "1":
            print("\nLeft the existing AfterZone.bat alone. Nothing was changed.")
            os.system('pause')
            return True

    shutil.copy2(source, dest)

    print("\n-------------------------------------------------------------------------------")
    print("AfterZone is ready.")
    print("File: AfterZone.bat (main folder)")
    print("-------------------------------------------------------------------------------")
    print("Before running it:")
    print("  1. Finish a normal encode and leave the temp folder in place")
    print("     (do not run cleanup yet - AfterZone needs temp\\<name>\\.<hash>\\chunks.json).")
    print("  2. Keep the original input in video-input\\<name>.mkv")
    print("  3. Put a zones file next to it: video-input\\<name>.txt")
    print("     See zones-example.txt in the main folder for the format.")
    print("     AfterZone can also auto-generate one from the finished file's bitrate.")
    print("")
    print("Open AfterZone.bat in Notepad++ and copy the av1an_settings, FINAL_SPEED and")
    print("CRF lines from the .bat you originally encoded with, so the MKV tag stays")
    print("truthful. Result: video-output\\<name>-afterzone.mkv (your original output is")
    print("left alone).")
    print("-------------------------------------------------------------------------------")
    os.system('pause')
    return True

def advanced_tools_menu():
    """Advanced tools submenu. Returns True if handled, False to go back."""
    while True:
        clear_screen()
        print("================================================")
        print("               Advanced Tools                   ")
        print("================================================\n")
        print("  1. Setup Condor in the main folder\n")
        print("  2. Setup Large Quality Target Collider in the main folder\n")
        print("  3. Setup AfterZone in the main folder\n")
        print("  4. Go back\n")
        print("  Condor allows you to set a target quality using CVVDP, SSIM2")
        print("  Butteraugli or XPSNR.\n")
        print("  LQTC allows you to set a target quality using CVVDP or SSIM2")
        print("  There is a potential that this Windows build will not work")
        print("  on every system\n")
        print("  AfterZone allows you to reencode frame ranges with different")
        print("  settings after encoding is already completed.\n")
        choice = input("Select [1/2/3/4]: ").strip()

        if choice == "1":
            return setup_condor()
        if choice == "2":
            if lqtc_acknowledgement():
                return setup_lqtc()
            continue
        if choice == "3":
            return setup_afterzone()
        if choice == "4":
            return False

def main():
    enable_ansi_colors()

    # --- 1. Pass Type ---
    while True:
        clear_screen()
        print("================================================")
        print("       Auto-Boost / Av1an Batch Builder")
        print("================================================\n")
        print("This tool will create a batch script to encode your videos.")
        print("Just answer the questions below and your script will be ready to run.\n")
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
        print("     Good if you want faster turnaround.")
        print("     ")
        print("  3: Setup advanced tools\n")
        print("  NOTE: If your video has a lot of grain, pick Av1an Single Pass. Auto-Boost can")
        print("  mistake the grain for fine detail and try to preserve it, which wastes bitrate")
        print("  and makes your final file much larger than it needs to be.\n")
        mode_choice = input("Select [1/2/3]: ").strip()

        if mode_choice == "3":
            if advanced_tools_menu():
                return
            continue

        mode = "autoboost" if mode_choice == "1" else "av1an"
        break

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

    arch_value = "x86-64-v3"
    if fork in ("5fish", "essential"):
        print("\n--------------------------------------------------------")
        print("CPU Build")
        print("--------------------------------------------------------")
        print("The encoder comes in a few versions, each built for a different")
        print("type of processor. They all produce the same video - a matching")
        print("build just encodes it faster.")
        print("")
        print("Picking one your processor cannot run makes the encode stop with")
        print("an error rather than harm anything, so a faster build is worth a")
        print("try. If it will not start, build the bat again and take option 2,")
        print("which works on every modern computer.\n")
        print("  1: znver2    -- Try this one first. It is faster on AMD Ryzen")
        print("                  3000 series and newer, and it runs on Intel")
        print("                  processors too, so Intel users should give it")
        print("                  a go before settling for x86-64-v3.\n")
        print("  2: x86-64-v3 -- Works on any Intel or AMD processor from")
        print("                  roughly 2015 onwards. The safe choice, and")
        print("                  what to use if option 1 or 3 will not run.\n")
        print("  3: AVX-512   -- Fastest, but only on processors that support")
        print("                  AVX-512. That means recent AMD Ryzen (5000")
        print("                  and newer) or certain Intel chips. Only pick")
        print("                  this if you have checked that yours does.\n")
        saved_arch = read_saved_arch()
        default_choice = CHOICE_BY_ARCH.get(saved_arch, "1")
        if saved_arch:
            print(f"Last time you chose {saved_arch} (option {default_choice}).\n")
        arch_choice = input(f"Select [1/2/3] (Press Enter for {default_choice}): ").strip()
        arch_value = ARCH_BY_CHOICE.get(arch_choice, ARCH_BY_CHOICE[default_choice])
        save_arch(arch_value)

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
        print("     encoded normally. GPU/iGPU 2016 or newer required.")
        print("     Not currently compatible with Intel GPUs.\n")
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
    print("Controls how hard the encoder works to compress your video.")
    print("Slower presets: better quality per MB, longer encode times.")
    print("Faster presets: quicker encodes, larger files or slightly lower")
    print("quality. Actual gains vary by source video.\n")

    print("  Recommended presets for this fork:")
    if fork != "5fish":
        print("  0 -- Slowest. Maximum effort. Great if you can wait.")
    if fork == "hdr":
        print("  1 -- Improves on preset 2, especially for grainy")
        print("       video. Handles grain better and cleans up some")
        print("       artifacts that other presets can leave behind.")
        print("       With tune grain, it can bring extra quality")
        print("       improvements.")
    elif fork != "5fish":
        print("  1 -- Possible slight improvement over preset 2,")
        print("       at the cost of extra encode time.")
    print("  2 -- Very high effort. Still slow, but a good choice")
    print("       for encodes you care about.")
    print("  3 -- Not useful at this time.")
    print("  4 -- DEFAULT. Fastest recommended preset. A solid")
    print("       balance of speed and efficiency. Use this if you")
    print("       have a slower CPU or need results sooner.\n")
    print("  WARNING: Presets faster than 4 are not recommended.")
    print("  They skip many of the tools designed to preserve")
    print("  quality while staying efficient, so output quality")
    print("  will suffer.\n")

    if fork == "5fish":
        print("  Quote from 5fish github repo:")
        print("  \"even if you have time to burn, as of right now, we")
        print("  don't recommend --preset 0. --preset 2 has a smart")
        print("  system to filter candidates, while --preset 0 tests")
        print("  through all the candidates. This smart filtering system")
        print("  often outperforms doing the full tests, and for this")
        print("  reason --preset 2 often gives a better result than")
        print("  --preset 0\"\n")

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
        fast_params = "--scd 0 --lineart-psy-bias 3 --texture-psy-bias 3 --hbd-mds 0"
        final_params = "--scd 0 --lineart-psy-bias 3 --texture-psy-bias 3 --hbd-mds 1 --lp 3 --photon-noise 200"
        has_rename = False
    elif fork == "essential":
        fast_params = f"--scd 0 --enable-dlf 3{dist_preset}"
        final_params = f"--scd 0 --enable-dlf 3{dist_preset} --lp 3 --photon-noise 200"
        film_grain_note = ":: If you'd like to use --film-grain, then --photon-noise must be set to 0, do not remove the setting.\n"
    elif fork == "hdr":
        # Keep base clean for HDR, apply tuning/noise based on user input
        fast_params = "--tune 0" if "tune 0" in hdr_noise else "--tune 5"
        final_params = f"{hdr_noise.strip()} --lp 3"
    elif fork == "custom":
        fast_params = ""
        final_params = "--lp 3 --photon-noise 200"

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
        print("     encoded normally.")
        print("     GPU/iGPU 2016 or newer required. Not compatible with Intel GPU\n")
        sdr_handling_choice = input("Select [1/2] (Press Enter for the default of 1): ").strip()
        if sdr_handling_choice == "2":
            tonemap_value = "True"

    # --- Interface Mode (final question) ---
    print("\n--------------------------------------------------------")
    print("Interface Mode")
    print("--------------------------------------------------------")
    print("How much information do you want to see while encoding?\n")
    print("  1: Default mode -- Simple interface with progress bars")
    print("     Each phase of the workflow shows a clean progress bar")
    print("     with a short explanation of what is happening.")
    print("     Recommended for new users.\n")
    print("  2: Verbose mode -- Show me everything")
    print("     Adds --verbose to the generated .bat and displays the")
    print("     full output of every tool during the workflow.\n")
    interface_choice = input("Select [1/2] (Press Enter for the default of 1): ").strip()
    verbose_value = "--verbose" if interface_choice == "2" else "--no-verbose"

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
    script += f'set "ARCH={arch_value}"\n'
    script += ":: ARCH picks the CPU build of the encoder: x86-64-v3 (any modern CPU),\n"
    script += ":: znver2 (AMD Ryzen 3000+), avx512 (only CPUs with AVX-512).\n"
    script += ":: A fork without that build falls back to x86-64-v3. The hdr fork is x86-64-v3 only.\n"
    script += f'set "tonemap={tonemap_value}"\n'
    script += ":: tonemap=True converts HDR sources to SDR (BT.709) via libplacebo inside the VapourSynth script (uses GPU).\n"
    script += ":: tonemap=False: the hdr fork auto-detects HDR sources and applies matching SVT-AV1-HDR color settings; other forks encode as-is.\n"
    script += f'set "VERBOSE={verbose_value}"\n'
    script += ":: VERBOSE=--verbose shows the full output of every tool during the workflow (verbose mode).\n"
    script += ":: VERBOSE=--no-verbose keeps the simple interface with progress bars (default mode).\n\n"

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
    # Only the workers= line is read, so other keys in the file - such as the
    # cputarget= this builder remembers - are ignored rather than overwriting
    # the worker count.
    read_workers = ("    for /f \"usebackq tokens=1,2 delims==\" %%a in (\"tools\\workercount-config.txt\") do (\n"
                    "        if /I \"%%a\"==\"workers\" set \"WORKER_COUNT_CFG=%%b\"\n"
                    "    )\n")
    script += "set \"WORKER_COUNT_CFG=\"\n"
    script += "if exist \"tools\\workercount-config.txt\" (\n"
    if mode == "autoboost":
        script += "    REM Read the worker count from the config file. Only workers= is read, so\n"
        script += "    REM other keys, such as the cputarget= the builders remember, are ignored.\n"
    script += read_workers
    script += ")\n"
    script += "if not defined WORKER_COUNT_CFG (\n"
    script += "    echo.\n    echo -------------------------------------------------------------------------------\n"
    script += "    echo First Run Detected: Calculating optimal encode worker count...\n"
    script += "    echo -------------------------------------------------------------------------------\n"
    script += "    \"VapourSynth\\python.exe\" \"tools\\workercount.py\"\n"
    if mode == "autoboost":
        script += "    \n    REM Reload config after generation\n"
    script += read_workers
    if mode == "autoboost":
        script += "    \n    REM Pause so user can see the calculation results, then continue\n"
    script += "    echo.\n    echo Encode worker count calculated.\n"
    script += ")\n"
    script += "if defined WORKER_COUNT_CFG set \"WORKER_COUNT=%WORKER_COUNT_CFG%\"\n\n"

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
        script += f"\"VapourSynth\\python.exe\" \"tools\\dispatch.py\" --fork %fork% --arch %ARCH% --denoise %DENOISE% --tonemap %tonemap% --crf %CRF%{autocrop_flag} --ssimu2 \"%SSIMU2_TOOL%\" %VERBOSE% --ssimu2-cpu-workers %SSIMU2_WORKERS% --resume --fast-speed 8 --final-speed %FINAL_SPEED% --workers %WORKER_COUNT% --fast-params \"%FAST_PARAMS%\" --final-params \"%FINAL_PARAMS%\"\n\n"
    else:
        script += f"\"VapourSynth\\python.exe\" \"tools\\av1an-dispatch.py\" --resume %VERBOSE% --fork %fork% --arch %ARCH% --denoise %DENOISE% --tonemap %tonemap%{autocrop_flag} --crf %CRF% --workers %WORKER_COUNT% --final-speed %FINAL_SPEED% --final-params \"%av1an_settings%\"\n\n"

    script += "echo.\necho All tasks finished.\necho Ctrl+C to keep temp files and exit.\necho Or, to cleaup temp files:\npause\n\n"
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
