import importlib.util
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import source_filter
import vpy_template

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
    print("set a target quality using CVVDP, SSIM2, butteraugli instead of a")
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

def current_source_filter_label():
    """What the source filter menu entry shows for the current setting."""
    override = source_filter.read_override()
    if override is None:
        return f"{source_filter.DEFAULT_FILTER} (default, no override file)"
    return f"{override} (set in tools\\{source_filter.OVERRIDE_FILENAME})"


def setup_source_filter():
    """Pick the VapourSynth source filter used by the generated .vpy scripts.

    The choice is stored in tools\\source-filter-override.txt, which Auto-Boost,
    Av1an single pass and Condor read when they build a filtering script. With
    no file there they use ffms2, exactly as they always have, so option 3
    (delete the file) restores the original behaviour.

    Returns False so the caller stays in the advanced tools menu: this only
    writes a setting, it does not build anything.
    """
    while True:
        clear_screen()
        print("================================================")
        print("          VapourSynth Source Filter             ")
        print("================================================\n")
        print("The source filter is the plugin that opens your video inside the")
        print("VapourSynth filtering script (crop, downscale, denoise, deband,")
        print("dehalo, tonemap). It decides how frames are decoded, not how they")
        print("are encoded.\n")
        print(f"Currently: {current_source_filter_label()}\n")
        print("  1: ffms2 (default)")
        print("     Fast to index and light on disk. Seek based, so on a few")
        print("     awkward sources - open-GOP HDR/BT.2020 in particular - it can")
        print("     return the wrong frames or stop short of the real end.\n")
        print("  2: BestSource")
        print("     Decodes linearly and is frame exact, so it is the safer pick")
        print("     when ffms2 gives you a frame count mismatch, a truncated")
        print("     encode or scenes that drift out of sync. Indexing takes")
        print("     noticeably longer, especially on long files.\n")
        print("  3: Remove the override (go back to the built-in default)\n")
        print("  4: Go back without changing anything\n")
        print("This applies to Auto-Boost, Av1an single pass and Condor. LQTC does")
        print("its own decoding without VapourSynth, so it ignores this setting.")
        print("Existing .vpy scripts in a leftover temp folder are rebuilt on the")
        print("next run, so a change takes effect straight away.\n")
        choice = input("Select [1/2/3/4]: ").strip()

        if choice in ("1", "2"):
            picked = source_filter.FFMS2 if choice == "1" else source_filter.BESTSOURCE
            try:
                path = source_filter.write_override(picked)
            except (OSError, ValueError) as e:
                print(f"\n{RED}Could not write the override file: {e}{RESET}")
                os.system('pause')
                continue
            print("\n-------------------------------------------------------------------------------")
            print(f"Source filter set to: {picked}")
            print(f"File: tools\\{os.path.basename(path)}")
            print("-------------------------------------------------------------------------------")
            print("Every .bat you have already generated picks this up as well - the")
            print("dispatchers read the file at the start of each run.")
            print("-------------------------------------------------------------------------------")
            os.system('pause')
            return False
        if choice == "3":
            if source_filter.clear_override():
                print(f"\nRemoved tools\\{source_filter.OVERRIDE_FILENAME}.")
                print(f"The scripts are back to their built-in default ({source_filter.DEFAULT_FILTER}).")
            else:
                print(f"\nThere was no tools\\{source_filter.OVERRIDE_FILENAME} to remove.")
                print(f"The scripts are already using the built-in default ({source_filter.DEFAULT_FILTER}).")
            os.system('pause')
            return False
        if choice == "4" or choice == "":
            return False


def load_av1an_dispatch():
    """Import tools\\av1an-dispatch.py as a module.

    The template writer reuses the dispatcher's settings.txt readers so the file
    it writes is exactly what the dispatcher would have generated - a second copy
    of the dehalo/fine_dehalo validation here would drift from it. The hyphen in
    the filename is why this needs importlib. Loaded on demand, since nothing
    else in the batch builder needs it.

    Returns (module, reason). Exactly one of the two is set: reason is the line
    to show the user when the import did not work. It carries the real exception
    rather than a generic "something is wrong", because everything that goes
    wrong here goes wrong the same way - one import inside the dispatcher fails -
    and the name of the missing piece is the whole of the fix.
    """
    module = sys.modules.get("av1an_dispatch")
    if module is not None:
        return module, None

    tools_dir = os.path.dirname(os.path.abspath(__file__))
    module_path = os.path.join(tools_dir, "av1an-dispatch.py")
    if not os.path.exists(module_path):
        return None, "tools\\av1an-dispatch.py is not there."

    try:
        spec = importlib.util.spec_from_file_location("av1an_dispatch", module_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["av1an_dispatch"] = module
        spec.loader.exec_module(module)
    except Exception as e:
        sys.modules.pop("av1an_dispatch", None)
        return None, f"{type(e).__name__}: {e}"
    return module, None


def template_status_label():
    """What the template menu entry shows for the current state."""
    path = vpy_template.template_path()
    if os.path.isfile(path):
        return "video-input\\template.vpy is present and in use"
    return "not written (scripts are generated from settings.txt)"


TEMPLATE_PREVIEW_BAT = "template-preview.bat"


def copy_template_preview_bat():
    """Put template-preview.bat in video-input, next to the template.

    Returns (copied, message). The template is the thing that matters, so a
    failure here is reported and otherwise ignored rather than being allowed to
    undo a template that was written successfully.
    """
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    source = os.path.join(tools_dir, TEMPLATE_PREVIEW_BAT)
    dest = os.path.join(os.path.dirname(vpy_template.template_path()), TEMPLATE_PREVIEW_BAT)

    if not os.path.exists(source):
        return False, (f"Could not find tools\\{TEMPLATE_PREVIEW_BAT}, so the preview "
                       f"launcher was not written.")
    try:
        shutil.copy2(source, dest)
    except OSError as e:
        return False, f"Could not write video-input\\{TEMPLATE_PREVIEW_BAT}: {e}"
    return True, f"video-input\\{TEMPLATE_PREVIEW_BAT}"


def delete_template_preview_bat():
    """Remove video-input\\template-preview.bat. True if one was there."""
    try:
        os.remove(os.path.join(os.path.dirname(vpy_template.template_path()),
                               TEMPLATE_PREVIEW_BAT))
        return True
    except OSError:
        return False


def confirm_template_overwrite():
    """Ask before replacing an existing template.vpy. True to go ahead."""
    if not os.path.isfile(vpy_template.template_path()):
        return True
    print("\nvideo-input\\template.vpy already exists.")
    print("Overwriting will discard any edits you made to it.\n")
    if input("Replace it? [1 Yes / 2 No] (Press Enter for No): ").strip() == "1":
        return True
    print("\nLeft the existing template.vpy alone. Nothing was changed.")
    os.system('pause')
    return False


def perform_template_write(rescale=None):
    """Write video-input\\template.vpy from settings.txt. True when it went out.

    The file is the filter chain the dispatchers would have generated, laid out
    for hand editing. While it exists, Auto-Boost, Av1an single pass and Condor
    render it instead of generating a script, so settings.txt is not read at all
    - its crop, downscale, dehalo, denoise and deband keys stop applying.

    rescale is None for the standard template, which has no rescale in it at
    all, or the name of a vpy_template.LIVE_RESCALE_BACKENDS entry, which goes
    in switched on.
    """
    dispatch, reason = load_av1an_dispatch()
    if dispatch is None:
        print(f"\n{RED}Could not load tools\\av1an-dispatch.py, which the template is")
        print(f"built from.")
        print("")
        print(f"  {reason}")
        print("")
        if "ModuleNotFoundError" in (reason or ""):
            missing = (reason or "").rsplit("'", 2)
            package = missing[1] if len(missing) == 3 else "the missing module"
            print(f"That is a Python package the dispatcher needs and this install")
            print(f"does not have. Install it into the package's own Python with:")
            print(f"  VapourSynth\\python.exe -m pip install {package}")
        else:
            print(f"Your install may be incomplete - try re-downloading the package.")
        print(f"{RESET}")
        os.system('pause')
        return False

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    settings = dispatch.load_script_settings(os.path.join(root_dir, "settings.txt"))
    if not settings:
        print(f"\n{RED}Could not read settings.txt in the main folder, so there is")
        print(f"nothing to build the template from.{RESET}")
        os.system('pause')
        return False

    # The crop line is seeded here and hand-edited from then on: nothing rewrites
    # it per input, because the template is the user's script. crop=auto has no
    # numbers to copy - detection needs a video - so an auto user gets a zeroed
    # line and a note below telling them to fill it in.
    crop_mode = dispatch.get_script_setting(settings, "crop", "auto").strip().lower()
    if crop_mode == "manual":
        crop_values = (
            dispatch.read_crop_int(dispatch.get_script_setting(settings, "top", "0"), "top"),
            dispatch.read_crop_int(dispatch.get_script_setting(settings, "bottom", "0"), "bottom"),
            dispatch.read_crop_int(dispatch.get_script_setting(settings, "left", "0"), "left"),
            dispatch.read_crop_int(dispatch.get_script_setting(settings, "right", "0"), "right"),
        )
    else:
        crop_values = (0, 0, 0, 0)

    try:
        text = vpy_template.build_template_text(
            settings,
            dispatch.read_dehalo_settings(settings),
            dispatch.read_fine_dehalo_settings(settings),
            crop_values,
            source_filter.resolve(),
            rescale=rescale,
        )
        written = vpy_template.write_template(text)
    except (OSError, ValueError, KeyError) as e:
        print(f"\n{RED}Could not write the template: {e}{RESET}")
        os.system('pause')
        return False

    preview_copied, preview_message = copy_template_preview_bat()

    print("\n-------------------------------------------------------------------------------")
    print("Template written.")
    print(f"File: video-input\\{os.path.basename(written)}")
    if preview_copied:
        print(f"File: {preview_message}")
    print("-------------------------------------------------------------------------------")
    print("Every .bat you have already generated picks this up - the dispatchers")
    print("look for the file at the start of each input. While it is there,")
    print("settings.txt is ignored completely: this file is the filter chain now.")
    print("")
    print("Edit the file freely. Delete it to go back to scripts generated from")
    print("settings.txt.")
    print("")
    if crop_mode == "manual":
        print(f"Crop: the std.Crop line was filled in from settings.txt (top={crop_values[0]},")
        print(f"bottom={crop_values[1]}, left={crop_values[2]}, right={crop_values[3]}). Change the crop in the template")
        print("from now on - settings.txt [crop] and the auto crop question in the .bat")
        print("builder no longer do anything while the file is there.")
    elif crop_mode == "auto":
        print(f"{RED}Crop: settings.txt has crop=auto, but a template cannot detect a crop -")
        print("it is one script for every video, and auto crop needs to look at each")
        print("one. The std.Crop line went out as all zeros, which crops nothing. Put")
        print(f"your own numbers in it and check them with {TEMPLATE_PREVIEW_BAT}.{RESET}")
    else:
        print("Crop: the std.Crop line went out as all zeros, which crops nothing. Put")
        print("numbers in it to crop - settings.txt [crop] is no longer read while the")
        print("file is there.")
    print("")
    if rescale:
        label = vpy_template.LIVE_RESCALE_BACKENDS[rescale][0]
        print(f"Rescale: the {label} block is switched ON in")
        print("the file. Open it and set new_height to the resolution the show was")
        print("drawn at, and the descale kernel to the one it was scaled with - what")
        print("is in there now is a starting point, not an answer.")
    else:
        print("Rescale: this template was written without one. Come back to this page")
        print("and pick option 2 or 3 if you want a rescale in it.")
    if preview_copied:
        print("")
        print(f"Run video-input\\{TEMPLATE_PREVIEW_BAT} to see what your template does to")
        print("a video in video-input before you spend hours encoding with it. It opens")
        print("vspreview with the untouched source on 1 and the template applied on 2.")
    else:
        print("")
        print(f"{RED}{preview_message}{RESET}")
    print("-------------------------------------------------------------------------------")
    os.system('pause')
    return True


def write_vpy_template():
    """The template.vpy page: write it, with or without a rescale, or delete it.

    Option 1 writes the filter chain settings.txt describes and nothing else.
    Options 2 and 3 write that same chain with one rescale block in it, switched
    on.

    Returns False so the caller stays in the advanced tools menu.
    """
    rescale_by_choice = {"1": None, "2": "DirectML", "3": "NVIDIA"}

    while True:
        clear_screen()
        print("================================================")
        print("        VapourSynth Filtering Template          ")
        print("================================================\n")
        print("Only one thing is filled in for each file encoded: replace.mkv in")
        print("the source line becomes the file being encoded. Everything else runs")
        print("exactly as written, the std.Crop line included - the crop in the")
        print("template is the only crop, and settings.txt [crop] and auto crop stop")
        print("applying. Do not change the frame count (no trimming), or else scene")
        print("detection will break.\n")
        print(f"Currently: {template_status_label()}\n")
        print("  1: Standard template.vpy\n")
        print("  2: DirectML rescale (Nvidia, AMD, Intel)\n")
        print("  3: Nvidia TRT Engine Rescale (Nvidia only) PLACEHOLDER, NOT WORKING\n")
        print("  4: Delete template.vpy (go back to settings.txt auto scripts)\n")
        print("  5: Go back without changing anything\n")
        print("  6: Exit\n")
        print("Notepad++ is suggested for editing the file afterwards.")
        print("LQTC decodes without VapourSynth, so it ignores the template.\n")
        choice = input("Select [1/2/3/4/5/6]: ").strip()

        if choice in ("1", "2", "3"):
            if not confirm_template_overwrite():
                continue

            perform_template_write(rescale_by_choice[choice])
            return False
        if choice == "4":
            removed_template = vpy_template.delete_template()
            # The launcher goes with it: on its own it would only ever report a
            # missing template.
            removed_preview = delete_template_preview_bat()
            if removed_template:
                print("\nRemoved video-input\\template.vpy.")
                print("The encoders are back to generating their script from settings.txt.")
            else:
                print("\nThere was no video-input\\template.vpy to remove.")
                print("The encoders already generate their script from settings.txt.")
            if removed_preview:
                print(f"Removed video-input\\{TEMPLATE_PREVIEW_BAT} as well.")
            os.system('pause')
            return False
        if choice == "5" or choice == "":
            return False
        if choice == "6":
            sys.exit(0)


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
        print(f"  4. VapourSynth source filter -- currently {current_source_filter_label()}\n")
        print("  5. Write template.vpy based off settings.txt to video-input folder\n")
        print("  6. Go back\n")
        print("  7. Exit\n")
        print("  Condor allows you to set a target quality using CVVDP, SSIM2")
        print("  or Butteraugli.\n")
        print("  LQTC allows you to set a target quality using CVVDP or SSIM2")
        print("  There is a potential that this Windows build will not work")
        print("  on every system\n")
        print("  AfterZone allows you to reencode frame ranges with different")
        print("  settings after encoding is already completed.\n")
        print("  Source filter picks the plugin that opens your video inside the")
        print("  VapourSynth filtering script: ffms2 (fast) or BestSource (frame")
        print("  exact, better on awkward HDR sources).\n")
        choice = input("Select [1/2/3/4/5/6/7]: ").strip()

        if choice == "1":
            return setup_condor()
        if choice == "2":
            if lqtc_acknowledgement():
                return setup_lqtc()
            continue
        if choice == "3":
            return setup_afterzone()
        if choice == "4":
            setup_source_filter()
            continue
        if choice == "5":
            write_vpy_template()
            continue
        if choice == "6":
            return False
        if choice == "7":
            sys.exit(0)

# --- The generated .bat, from one settings dict -----------------------------
#
# Both front ends - the numbered questions in main() and the GUI page - fill in
# the same dict and hand it to build_script(), so the two cannot drift apart.
# The keys are the raw answers, not the flags built from them:
#
#   mode              "autoboost" | "av1an"
#   fork              "5fish" | "essential" | "hdr" | "custom"
#   arch              "znver2" | "x86-64-v3" | "avx512"
#   crf               CRF as typed, e.g. "30"
#   speed             final preset as typed, e.g. "4"
#   fidelity          "0".."4"      essential fork only, ignored otherwise
#   grain             "clean"|"film"  hdr fork only, ignored otherwise
#   tonemap           "True" | "False"
#   autocrop          bool
#   optimize_workers  bool
#   verbose           "--verbose" | "--no-verbose"
#   denoise           optional; derived from the fork when absent


def output_filename_for(cfg):
    """The .bat name a settings dict produces, so the GUI can preview it."""
    fork = cfg["fork"]
    dist_suffix = f"-d{cfg.get('fidelity', '0')}" if fork == "essential" else ""
    autocrop_suffix = "-autocrop" if cfg.get("autocrop") else ""
    tonemap_suffix = "-tonemap" if cfg.get("tonemap") == "True" else ""
    return (f"batbuilder-{cfg['mode']}-{fork}{dist_suffix}-crf{cfg['crf']}"
            f"-p{cfg['speed']}{autocrop_suffix}{tonemap_suffix}.bat")


def build_script(cfg):
    """Write the .bat described by cfg into the main folder.

    Returns (output_filename, file_path).
    """
    mode = cfg["mode"]
    fork = cfg["fork"]
    arch_value = cfg["arch"]
    crf = cfg["crf"]
    speed = cfg["speed"]
    tonemap_value = cfg["tonemap"]
    use_autocrop = bool(cfg.get("autocrop"))
    optimize_workers = bool(cfg.get("optimize_workers"))
    verbose_value = cfg.get("verbose", "--no-verbose")
    # 5fish is the one fork the package turns denoising on for; the front ends
    # do not ask, they report what the fork implies.
    denoise_value = cfg.get("denoise") or ("True" if fork == "5fish" else "False")

    # Fidelity only exists on the essential fork, grain only on hdr. Anything
    # left over in cfg from a fork the user switched away from is ignored here
    # rather than leaking into another fork's parameters.
    dist_preset = ""
    if fork == "essential":
        fidelity = str(cfg.get("fidelity", "0"))
        if fidelity != "0":
            dist_preset = f" --distortion-bias-preset {fidelity}"

    hdr_noise = ""
    if fork == "hdr":
        hdr_noise = (" --tune 5 --film-grain 10" if cfg.get("grain") == "film"
                     else " --tune 0 --noise 4")

    autocrop_flag = " --autocrop" if use_autocrop else ""

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
    output_filename = output_filename_for(cfg)
    
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
        script += ":: custom-ssim2-tool values: vs-hip nvidia, vs-hip amd, vs-hip vulkan, ffvship nvidia,\n"
        script += "::                            ffvship amd, ffvship vulkan, vs-zip.\n"
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

    script += "echo.\necho All tasks finished.\necho Ctrl+C to keep temp files and exit.\necho Or, to cleanup temp files:\npause\n\n"
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
    return output_filename, file_path


# --- GUI (experimental) -----------------------------------------------------
#
# The GUI is tkinter. tkinter is in the standard library, but it is the one
# part of it that is not pure Python - it is the compiled _tkinter plus the Tcl
# and Tk runtimes, built against one exact interpreter - and python.org leaves
# all of it out of the embeddable build. So this package carries its own copy,
# taken from python.org's tcltk.msi for the version of Python in VapourSynth\:
#
#     _tkinter.pyd, tcl86t.dll, tk86t.dll, zlib1.dll   VapourSynth#     Lib\site-packages	kinter\                       the Python half
#     tcl	cl8.6, tcl	k8.6, tcl	cl8                  the Tcl and Tk libraries
#
# about 9 MB, and it travels with the package to any PC it is copied to.
#
# has_tkinter() is still checked before the page opens, because those files can
# go missing - and because replacing VapourSynth\python.exe with a different
# Python version leaves them in place but unloadable. Either way the answer is
# the same: this is part of the package, so a package that has lost it should
# be downloaded again.

def gui_module_dir():
    return os.path.dirname(os.path.abspath(__file__))


def has_tkinter():
    """Whether the interpreter running this file can open a Tk window.

    tkinter is two halves: the pure Python package, and the compiled _tkinter
    that binds Tcl and Tk. Looking for the package alone is not enough - it
    would be found on its own and report yes while the import fails - so the
    compiled half is imported for real. That is a DLL load and nothing more,
    and it is the half that goes missing, or stops matching, if the portable
    Python is ever replaced with a different version.
    """
    try:
        import _tkinter  # noqa: F401  - imported to prove it loads
    except Exception:
        return False
    try:
        return importlib.util.find_spec("tkinter") is not None
    except (ImportError, ValueError):
        return False


def gui_build(cfg):
    """What the GUI's Generate button calls. Same builder the questions use."""
    if cfg["fork"] in ("5fish", "essential"):
        save_arch(cfg["arch"])
    return build_script(cfg)


def launch_gui():
    """Open the one-page GUI. Returns True when the caller should stop.

    False sends the user back to the questions, which is what happens when the
    Tk files this package ships with are not there any more.
    """
    if not has_tkinter():
        clear_screen()
        print("================================================")
        print("            GUI (experimental)                  ")
        print("================================================\n")
        print(f"{RED}Tk is missing from this package, so the GUI cannot open.{RESET}\n")
        print("The GUI is tkinter, and this package carries its own copy of it")
        print("in the VapourSynth folder: _tkinter.pyd, tcl86t.dll, tk86t.dll,")
        print("zlib1.dll, Lib\\site-packages\\tkinter and the tcl folder. At least")
        print("one of those is gone, or VapourSynth\\python.exe has been replaced")
        print("with a different version of Python, which leaves the files there")
        print("but unloadable.\n")
        print("Re-download the package to put it back. Nothing else needs those")
        print("files - encoding is unaffected, and options 1 and 2 ask the same")
        print("questions and build exactly the same .bat.\n")
        os.system('pause')
        return False

    sys.path.insert(0, gui_module_dir())
    try:
        import batbuilder_gui
    except Exception as e:
        print(f"\n{RED}Could not load tools\\batbuilder_gui.py: {e}")
        print(f"Your install may be incomplete - try re-downloading the package.{RESET}")
        os.system('pause')
        return False

    try:
        batbuilder_gui.run(gui_build, output_filename_for,
                           defaults={"arch": read_saved_arch() or "znver2"})
    except Exception as e:
        print(f"\n{RED}The GUI stopped with an error: {e}{RESET}")
        os.system('pause')
    return True


def main():
    enable_ansi_colors()

    # --gui opens the page straight away, for a shortcut that skips the menu.
    if "--gui" in sys.argv[1:]:
        launch_gui()
        return

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
        print("  0: GUI")
        print("     The same questions as 1 and 2, on one page, with every")
        print("     option visible at once. It builds exactly the same .bat.\n")
        print("  NOTE: If your video has a lot of grain, pick Av1an Single Pass. Auto-Boost can")
        print("  mistake the grain for fine detail and try to preserve it, which wastes bitrate")
        print("  and makes your final file much larger than it needs to be.\n")
        mode_choice = input("Select [1/2/3/0]: ").strip()

        if mode_choice == "0":
            if launch_gui():
                return
            continue

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
    fidelity_value = "0"
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
        fidelity_value = val

    grain_value = "clean"
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
            grain_value = "film"

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
    cfg = {
        "mode": mode,
        "fork": fork,
        "arch": arch_value,
        "crf": crf,
        "speed": speed,
        "fidelity": fidelity_value,
        "grain": grain_value,
        "tonemap": tonemap_value,
        "denoise": denoise_value,
        "autocrop": use_autocrop,
        "optimize_workers": optimize_workers,
        "verbose": verbose_value,
    }
    output_filename, _path = build_script(cfg)

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
