"""Preview the settings.txt filter chain against the untouched source.

Picks a video out of video-input, rebuilds the same VapourSynth chain that
av1an-dispatch.py feeds to av1an, and opens VSPreview with the source and the
filtered clip as separate outputs so they can be flipped with 1/2/3.

The filter settings are read straight from settings.txt through
av1an-dispatch.py's own readers, so what you see here is what the encode gets.
"""

import contextlib
import glob
import importlib.util
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
ROOT_DIR = TOOLS_DIR.parent
VIDEO_INPUT_DIR = ROOT_DIR / "video-input"
SETTINGS_PATH = ROOT_DIR / "settings.txt"
# Deleted when VSPreview closes. The ".tmp" suffix is the fallback: if the
# preview is killed outright, tools/cleanup.py sweeps the folder up later.
TEMP_DIR = ROOT_DIR / "settings-preview.tmp"
EXTENSIONS = ("*.mkv", "*.mp4", "*.m2ts")

BLUE = "\033[94m"
RED = "\033[91m"
RESET = "\033[0m"

PLUGIN_ENV_VAR = "VAPOURSYNTH_EXTRA_PLUGIN_PATH"


def plugin_dir():
    """Absolute path to the package's vs-plugins folder, or "" if it is gone."""
    candidate = ROOT_DIR / "VapourSynth" / "vs-plugins"
    return str(candidate) if candidate.is_dir() else ""


def ensure_plugin_path():
    """Point VapourSynth at the package's vs-plugins folder.

    VapourSynth used to run in portable mode: a portable.vs marker next to
    python.exe made the core autoload VapourSynth\\vs-plugins, which is where
    this package keeps ffms2, DFTTest, libvs_placebo and vszip. VapourSynth 78
    dropped that and reads VAPOURSYNTH_EXTRA_PLUGIN_PATH instead; without it
    scripts fail with "No attribute with the name ffms2 exists".

    Kept inline rather than in a shared module so this script stays
    self-contained. VSPreview inherits the variable as a child process.
    """
    found = plugin_dir()
    if not found:
        return ""

    existing = [part for part in os.environ.get(PLUGIN_ENV_VAR, "").split(os.pathsep) if part]
    if not existing:
        # Set a single path: valid whether the core reads one path or a list.
        os.environ[PLUGIN_ENV_VAR] = found
    elif not any(os.path.normcase(part) == os.path.normcase(found) for part in existing):
        os.environ[PLUGIN_ENV_VAR] = os.pathsep.join(existing + [found])

    return found


def load_module(module_name, script_path):
    """Import a tools/ script that has a hyphen in its filename."""
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"Could not find {script_path}")
    spec = importlib.util.spec_from_file_location(module_name, str(script_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gather_input_files():
    files = []
    for ext in EXTENSIONS:
        files.extend(glob.glob(str(VIDEO_INPUT_DIR / ext)))
    return sorted(files)


def select_input_file(requested):
    """Return the source to preview, asking the user when video-input holds several."""
    if requested:
        candidate = Path(requested)
        if not candidate.is_absolute():
            candidate = VIDEO_INPUT_DIR / requested
        if not candidate.exists():
            print(f"{RED}[Preview] File not found: {candidate}{RESET}")
            return None
        return str(candidate)

    files = gather_input_files()
    if not files:
        print(f"{RED}[Preview] No .mkv, .mp4 or .m2ts files found in video-input.{RESET}")
        print(f"{RED}[Preview] Put the file you want to test in: {VIDEO_INPUT_DIR}{RESET}")
        return None
    if len(files) == 1:
        return files[0]

    print("Multiple files found in video-input:")
    for index, path in enumerate(files, start=1):
        print(f"  {index}. {os.path.basename(path)}")
    while True:
        choice = input(f"Preview which file? [1-{len(files)}, default 1]: ").strip()
        if not choice:
            return files[0]
        if choice.isdigit() and 1 <= int(choice) <= len(files):
            return files[int(choice) - 1]
        print("Please enter one of the listed numbers.")


def requested_crop_mode(dispatch, settings):
    """Return the [crop] mode from settings.txt, falling back to auto."""
    mode = dispatch.get_script_setting(settings, "crop", "auto").strip().lower()
    if mode not in ("auto", "manual", "off"):
        print(f"[Preview] Warning: Unknown crop mode {mode!r}; using auto.")
        mode = "auto"
    return mode


def ask_autocrop(mode):
    """Ask whether to crop at all.

    This stands in for av1an-dispatch.py's --autocrop switch: the .bat files
    decide it there, so the preview has to ask. Without it, the [crop] section
    of settings.txt is skipped entirely, exactly as dispatch does.
    """
    print()
    print("[Preview] Crop:")
    print("[Preview]   Enter = no crop, preview the source at its full frame")
    if mode == "off":
        print("[Preview]   1     = crop, but settings.txt has crop=off so nothing is cropped")
    else:
        print(f"[Preview]   1     = crop using settings.txt (crop={mode})")
    while True:
        choice = input("Press Enter for no crop, or 1 for auto crop: ").strip()
        if not choice:
            return False
        if choice == "1":
            return True
        print("Please press Enter for no crop, or type 1 for auto crop.")


def resolve_crop(dispatch, settings, source_path, autocrop, requested_mode):
    """Resolve settings.txt [crop] into (mode, top, bottom, left, right)."""
    if not autocrop:
        # Matches dispatch: no autocrop means the whole [crop] section is off.
        return "off", 0, 0, 0, 0

    if requested_mode == "auto":
        print("[Preview] crop=auto: running crop detection (this takes a moment)...")
        top, bottom, left, right = dispatch.detect_crop_values(source_path, str(TOOLS_DIR))
    elif requested_mode == "manual":
        top = dispatch.read_crop_int(dispatch.get_script_setting(settings, "top", "0"), "top")
        bottom = dispatch.read_crop_int(dispatch.get_script_setting(settings, "bottom", "0"), "bottom")
        left = dispatch.read_crop_int(dispatch.get_script_setting(settings, "left", "0"), "left")
        right = dispatch.read_crop_int(dispatch.get_script_setting(settings, "right", "0"), "right")
    else:
        top = bottom = left = right = 0

    return requested_mode, top, bottom, left, right


PREVIEW_TEMPLATE = '''
from vstools import vs, core, initialize_clip, finalize_clip
try:
    from vsdenoise import DFTTest
except Exception:
    DFTTest = None
core.max_cache_size = 1024
{filter_state}

# VapourSynth 78 dropped the portable.vs autoload of the package's vs-plugins
# folder, so ffms2/DFTTest/placebo/vszip are loaded by hand when the core did
# not pick them up on its own. A no-op on installs that still autoload.
import os as _os
_plugin_dir = r"{plugin_dir}"
if _plugin_dir and not hasattr(core, "ffms2") and _os.path.isdir(_plugin_dir):
    for _dll in sorted(_os.listdir(_plugin_dir)):
        if _dll.lower().endswith(".dll"):
            try:
                core.std.LoadPlugin(_os.path.join(_plugin_dir, _dll))
            except Exception:
                pass

# Load Source
src = core.ffms2.Source(source=r"{source}", cachefile=r"{cache}")

# Initialize (Fixes Placebo bitdepth error by ensuring 16-bit)
src = initialize_clip(src)

# Untouched reference, branched off before anything from settings.txt runs.
source_clip = src


# Geometry is shared by the filtered output and the geometry-only output, so it
# lives in a function instead of being written out twice.
def apply_geometry(clip):
    # 1. CROP
    if {ct} > 0 or {cb} > 0 or {cl} > 0 or {cr} > 0:
        clip = clip.std.Crop(top={ct}, bottom={cb}, left={cl}, right={cr})

    # 2. DOWNSCALE
    should_downscale = {downscale}
    target_res_str = "{target_res}"
    user_kernel = "{kernel}"

    if should_downscale:
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
        target_w = 0
        target_h = 0
        if "x" in target_res_str.lower():
            try:
                w_str, h_str = target_res_str.lower().split("x")
                target_w = int(w_str)
                target_h = int(h_str)
            except Exception:
                pass
        else:
            try:
                target_w = int(target_res_str)
            except Exception:
                pass
        if target_w > 0:
            if target_h == 0:
                target_h = int(target_w * clip.height / clip.width)
                if target_h % 2 != 0:
                    target_h -= 1
            if target_w % 2 != 0:
                target_w -= 1
            if target_w < clip.width or target_h < clip.height:
                clip = core.placebo.Resample(clip, target_w, target_h, filter=pl_filter)
    return clip


# DEHALO (settings.txt [dehalo]; always runs before denoise)
do_dehalo = {dehalo}
if do_dehalo:
    import vsdehalo as deh
    dehalo_kwargs = dict(
        lowsens={dh_lowsens},
        highsens={dh_highsens},
        ss={dh_ss},
        darkstr={dh_darkstr},
        brightstr={dh_brightstr},
    )
    if hasattr(deh, "AlphaBlur"):
        # vsjetpack >= 1.0: the rx/ry radius moved into the AlphaBlur blur object.
        src = deh.dehalo_alpha(src, blur=deh.AlphaBlur(rx={dh_rx}, ry={dh_ry}), **dehalo_kwargs)
    else:
        # Older vsdehalo takes rx/ry directly.
        src = deh.dehalo_alpha(src, rx={dh_rx}, ry={dh_ry}, **dehalo_kwargs)

# Optional settings.txt denoise/deband hooks
{denoise_line}
{deband_line}

src = apply_geometry(src)


# Outputs. In VSPreview press 1 / 2 / 3 to switch between them.
def labelled(clip, text):
    return core.text.Text(clip, text, alignment=7)


previews = [
    (finalize_clip(source_clip), "1: SOURCE - settings.txt not applied"),
    (finalize_clip(src), "2: FILTERED - {filter_summary}"),
]

# With crop/downscale on, output 2 no longer lines up with output 1. This third
# clip is the source put through the same geometry and nothing else, so 2 vs 3
# shows the filters alone.
if {geometry_active}:
    previews.append((finalize_clip(apply_geometry(source_clip)), "3: SOURCE + crop/downscale only"))

for preview_index, (preview_clip, preview_text) in enumerate(previews):
    labelled(preview_clip, preview_text).set_output(preview_index)
'''


def build_preview_script(dispatch, source_path, settings, crop_values):
    """Write the temporary .vpy and return (path, geometry_active)."""
    basename = Path(source_path).stem
    vpy_file = TEMP_DIR / f"{basename}-preview.vpy"
    cache_file = TEMP_DIR / f"{basename}.ffindex"

    crop_mode, crop_top, crop_bottom, crop_left, crop_right = crop_values

    do_downscale = dispatch.setting_is_true(settings, "downscale", "False")
    target_res = dispatch.get_script_setting(settings, "target_resolution", "1920x1080")
    kernel = dispatch.get_script_setting(settings, "kernel_type", "Hermite")
    do_dehalo = dispatch.setting_is_true(settings, "dehalo", "False")
    dehalo_values = dispatch.read_dehalo_settings(settings) if do_dehalo else None
    do_denoise = dispatch.setting_is_true(settings, "denoise", "False")
    denoise_setting = dispatch.get_script_setting(settings, "denoise_setting", "")
    do_deband = dispatch.setting_is_true(settings, "deband", "False")
    deband_setting = dispatch.get_script_setting(settings, "deband_setting", "")

    dispatch.report_crop_status(crop_mode, crop_top, crop_bottom, crop_left, crop_right)
    dispatch.report_filter_status(
        do_downscale, target_res, kernel, do_denoise, denoise_setting,
        do_deband, deband_setting, do_dehalo, dehalo_values,
    )

    geometry_active = do_downscale or any((crop_top, crop_bottom, crop_left, crop_right))

    # Kept to plain words: this text is embedded in a quoted string inside the
    # generated script, so it must not carry quotes or braces of its own.
    active_names = []
    if do_dehalo:
        active_names.append("dehalo")
    if do_denoise and denoise_setting:
        active_names.append("denoise")
    if do_deband and deband_setting:
        active_names.append("deband")
    if any((crop_top, crop_bottom, crop_left, crop_right)):
        active_names.append("crop")
    if do_downscale:
        active_names.append("downscale")
    filter_summary = " + ".join(active_names) if active_names else "nothing enabled in settings.txt"

    if not active_names:
        print(f"{RED}[Preview] Nothing is enabled in settings.txt; both outputs will look identical.{RESET}")

    dehalo_args = dehalo_values or dispatch.DEHALO_DEFAULTS

    TEMP_DIR.mkdir(exist_ok=True)
    with open(vpy_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(PREVIEW_TEMPLATE.format(
            source=source_path,
            cache=str(cache_file),
            plugin_dir=plugin_dir(),
            ct=crop_top,
            cb=crop_bottom,
            cl=crop_left,
            cr=crop_right,
            downscale=str(do_downscale),
            target_res=target_res,
            kernel=kernel,
            denoise_line=denoise_setting if do_denoise and denoise_setting else "",
            deband_line=deband_setting if do_deband and deband_setting else "",
            dehalo=str(do_dehalo),
            dh_rx=dehalo_args["rx"],
            dh_ry=dehalo_args["ry"],
            dh_brightstr=dehalo_args["brightstr"],
            dh_darkstr=dehalo_args["darkstr"],
            dh_lowsens=dehalo_args["lowsens"],
            dh_highsens=dehalo_args["highsens"],
            dh_ss=dehalo_args["ss"],
            filter_state=f"# Filter state: dehalo={do_dehalo}, denoise={do_denoise}, deband={do_deband}",
            filter_summary=filter_summary,
            geometry_active=str(bool(geometry_active)),
        ))

    print(f"[Preview] Built VapourSynth script: {vpy_file}")
    return vpy_file, geometry_active


def cleanup(source_path):
    """Remove everything the preview created once VSPreview has closed.

    The whole temp folder goes: the generated .vpy, the ffms2 index, VSPreview's
    own scratch files and its .vsjet cache all live in there.
    """
    try:
        if TEMP_DIR.is_dir():
            shutil.rmtree(TEMP_DIR)
    except OSError:
        pass

    # detect_crop_values drops a CSV next to the source.
    if source_path:
        crop_csv = Path(source_path).with_name(f"{Path(source_path).stem}_crop.csv")
        try:
            if crop_csv.exists():
                os.remove(crop_csv)
        except OSError:
            pass


def main():
    args = [arg for arg in sys.argv[1:] if arg.strip()]

    # Before anything spawns a VapourSynth core.
    ensure_plugin_path()

    if not SETTINGS_PATH.exists():
        print(f"{RED}[Preview] settings.txt not found at {SETTINGS_PATH}{RESET}")
        input("Press Enter to exit...")
        return 1
    if not VIDEO_INPUT_DIR.is_dir():
        print(f"{RED}[Preview] video-input folder not found at {VIDEO_INPUT_DIR}{RESET}")
        input("Press Enter to exit...")
        return 1

    source_path = select_input_file(args[0] if args else None)
    if not source_path:
        input("Press Enter to exit...")
        return 1

    print(f"{BLUE}[Preview] Source: {os.path.basename(source_path)}{RESET}")
    print(f"{BLUE}[Preview] Settings: {SETTINGS_PATH}{RESET}")

    dispatch = load_module("av1an_dispatch_preview", TOOLS_DIR / "av1an-dispatch.py")
    vspreview_dispatch = load_module("vspreview_dispatch_preview", TOOLS_DIR / "vspreview-dispatch.py")

    settings = dispatch.load_script_settings(str(SETTINGS_PATH))
    if not settings:
        print(f"{RED}[Preview] settings.txt could not be read or is empty.{RESET}")
        input("Press Enter to exit...")
        return 1

    crop_mode = requested_crop_mode(dispatch, settings)
    autocrop = ask_autocrop(crop_mode)
    crop_values = resolve_crop(dispatch, settings, source_path, autocrop, crop_mode)

    vpy_file, geometry_active = build_preview_script(dispatch, source_path, settings, crop_values)

    print()
    print("[Preview] In VSPreview:")
    print("[Preview]   1 = source, 2 = filtered" + (", 3 = source with crop/downscale only" if geometry_active else ""))
    print("[Preview]   Ctrl+mousewheel zooms. Close the window to return here.")
    print("[Preview] First frame takes a while: ffms2 has to index the source.")
    print()

    # Stale VSPreview storage missing WindowSettings.zoom_index crashes the
    # launch before the window appears. It repairs storage silently; its own
    # progress output is housekeeping noise here.
    with contextlib.redirect_stdout(io.StringIO()):
        vspreview_dispatch.repair_vspreview_storage()

    exit_code = 0
    try:
        # Run from the temp folder so VSPreview's own scratch files land there.
        subprocess.run([sys.executable, "-m", "vspreview", str(vpy_file)], cwd=str(TEMP_DIR), check=True)
    except subprocess.CalledProcessError as e:
        print(f"{RED}[Preview] vspreview exited with an error: {e}{RESET}")
        exit_code = e.returncode or 1
    except KeyboardInterrupt:
        pass
    finally:
        cleanup(source_path)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
