# Plugin-load chatter from VapourSynth children (API3 deprecation notices,
# duplicate plugin DLLs) is dropped back out of any output relayed below.
try:
    import sys as _quiet_sys, os as _quiet_os
    _quiet_dir = _quiet_os.path.dirname(_quiet_os.path.abspath(__file__))
    if _quiet_dir not in _quiet_sys.path:
        _quiet_sys.path.insert(0, _quiet_dir)
    from vs_quiet import is_plugin_noise as _is_plugin_noise
except Exception:
    def _is_plugin_noise(line):
        return False

import os
import glob
import sys
import subprocess
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import source_filter


# Which previewer opens a script. VSPreview is still the default here; a
# launcher that wants vsview - the successor previewer from the same authors,
# bundled in VapourSynth\Lib\site-packages - sets AUTOBOOST_PREVIEWER=vsview in
# its own environment before calling in. All three launchers that go through
# this module do that: settings-preview.bat, video-input\template-preview.bat
# and extras\vspreview.bat. The default is left on VSPreview so that anything
# calling in without setting the variable keeps the behaviour it had.
# photon-test.py is not affected either way - it keeps its own launch line and
# stays on VSPreview.
PREVIEWER_ENV_VAR = "AUTOBOOST_PREVIEWER"
VSVIEW = "vsview"
VSPREVIEW = "vspreview"


def selected_previewer():
    """"vsview" when the environment asks for it, "vspreview" otherwise.

    Anything other than "vsview" is VSPreview, so a typo in the variable falls
    back to the previewer that was always used rather than to an error.
    """
    if os.environ.get(PREVIEWER_ENV_VAR, "").strip().lower() == VSVIEW:
        return VSVIEW
    return VSPREVIEW


def previewer_name():
    """The previewer's name as it is spelled in console output."""
    return "vsview" if selected_previewer() == VSVIEW else "VSPreview"


def repair_vspreview_storage():
    """Repair stale VSPreview storage that crashes on missing WindowSettings.zoom_index."""
    # vsview keeps its own settings elsewhere and never reads this file.
    if selected_previewer() == VSVIEW:
        return

    appdata = os.environ.get("APPDATA")
    if not appdata:
        return

    global_storage = os.path.join(appdata, "vspreview", "global.yml")
    if not os.path.exists(global_storage):
        return

    try:
        with open(global_storage, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError as exc:
        print(f"[VSPreview] Warning: Could not read storage {global_storage}: {exc}")
        return

    changed = False
    in_window_settings = False
    block_start = None
    indent = "        "
    has_zoom_index = False

    for idx, line in enumerate(lines):
        if "!!python/object:vspreview.main.settings.WindowSettings" in line:
            in_window_settings = True
            block_start = idx
            has_zoom_index = False
            leading = line[:len(line) - len(line.lstrip())]
            indent = leading + "    "
            continue

        if not in_window_settings:
            continue

        stripped = line.strip()
        leading_len = len(line) - len(line.lstrip())
        if stripped and leading_len <= len(indent) - 4 and idx > (block_start or 0):
            if not has_zoom_index:
                lines.insert(idx, f"{indent}zoom_index: 1")
                changed = True
            in_window_settings = False
            continue

        if stripped.startswith("zoom_index:"):
            has_zoom_index = True
        elif stripped.startswith(("x_pos:", "y_pos:")) and not has_zoom_index:
            lines.insert(idx, f"{indent}zoom_index: 1")
            changed = True
            has_zoom_index = True
            in_window_settings = False
            break

    if in_window_settings and not has_zoom_index:
        lines.append(f"{indent}zoom_index: 1")
        changed = True

    if changed:
        backup_path = global_storage + ".bak"
        try:
            if not os.path.exists(backup_path):
                shutil.copy2(global_storage, backup_path)
            with open(global_storage, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError as exc:
            print(f"[VSPreview] Warning: Could not repair storage {global_storage}: {exc}")


def launch_command(vpy_file, python_executable=None):
    """The argv that opens one .vpy in the selected previewer.

    Everything that previews a script goes through here rather than building
    its own launch line, so the choice of previewer and the vs-jetpack 2
    compatibility shim in tools\\vspreview_compat.py are applied the same way in
    all of them. See that file for what it bridges and why it is not a patch to
    site-packages.

    vsview is launched as a plain "-m vsview". It is built against vs-jetpack 2
    already, so the shim would only put back names it never asks for.

    For VSPreview the shim is used only when it is actually there; a package
    without it falls back to the plain "-m vspreview" line this used to be, so a
    previewer that no longer needs bridging keeps working after the file is
    deleted.

    Both are started through VapourSynth\\python.exe rather than through the
    Scripts\\vsview.exe and Scripts\\vspreview.exe launchers, because those have
    the build machine's python path written into them and do nothing on anyone
    else's install.
    """
    executable = python_executable or sys.executable

    if selected_previewer() == VSVIEW:
        return [executable, "-m", "vsview", str(vpy_file)]

    shim = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "vspreview_compat.py")
    if os.path.exists(shim):
        return [executable, shim, str(vpy_file)]
    return [executable, "-m", "vspreview", str(vpy_file)]


# Set to 1 to watch VSPreview's console output live instead of having it held
# back. For working out why a preview is behaving oddly when it does still open.
VERBOSE_ENV_VAR = "AUTOBOOST_PREVIEW_VERBOSE"


def run_preview(vpy_file, cwd=None, python_executable=None):
    """Open one .vpy in the selected previewer, showing its console output only
    if it fails.

    A VSPreview that opens normally still says a lot on the way up - API3
    deprecation notices for plugins, a SyntaxWarning from vstools, a builtin
    file-loader plugin that cannot import a name vs-jetpack 2 moved, and a
    parting "Core is still in use" from vsengine. None of it means the preview
    did not work, and printing it under a window that opened fine only teaches
    people to ignore the console - which is where a real failure has to be read.

    So the output is held and thrown away on a clean exit, and printed in full
    when the exit code is non-zero, which is the case where it is the only
    evidence of what went wrong. Set AUTOBOOST_PREVIEW_VERBOSE=1 to let it
    through as it happens instead.

    Raises subprocess.CalledProcessError on a non-zero exit, after printing, so
    callers keep the error handling they already have.
    """
    command = launch_command(vpy_file, python_executable)
    kwargs = {"cwd": str(cwd) if cwd else None}

    if os.environ.get(VERBOSE_ENV_VAR, "").strip() not in ("", "0"):
        subprocess.run(command, check=True, **kwargs)
        return 0

    result = subprocess.run(command, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", **kwargs)
    if result.returncode != 0:
        output = "\n".join(line for line in (result.stdout or "").splitlines()
                           if not _is_plugin_noise(line)).strip()
        if output:
            print(output)
        raise subprocess.CalledProcessError(result.returncode, command,
                                            output=result.stdout)
    return 0


def is_package_storage(path):
    """True for the package's own .vsjet folder.

    A .vsjet folder next to a script is scratch and goes with the rest of the
    cleanup. The one holding ArtCNN's ONNX models is not: they are 35 MB and
    downloaded by hand. It lives in VapourSynth\\.vsjet, the folder the model
    storage preamble in tools/vpy_template.py points rendered scripts at. The
    package root is still checked because that is where installs from before the
    move keep theirs. Everything that sweeps a .vsjet checks here first, because
    a preview started from either folder would otherwise delete the models and
    the next rescale would fail with nothing to explain why.
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.normcase(os.path.abspath(path)) in (
        os.path.normcase(os.path.join(root_dir, "VapourSynth", ".vsjet")),
        os.path.normcase(os.path.join(root_dir, ".vsjet")))


def cleanup(vpy_file):
    """Cleans up generated VPY files, scratch .vsjet folders, and index files."""
    # Delete the generated .vpy file used for the session
    if vpy_file and os.path.exists(vpy_file):
        try:
            os.remove(vpy_file)
        except OSError:
            pass

    # Delete all other .vpy files in the folder (cleanup for stale files)
    for f in glob.glob("*.vpy"):
        try:
            os.remove(f)
        except OSError:
            pass

    # Delete a scratch .vsjet folder, never the package's own
    if os.path.exists(".vsjet") and not is_package_storage(".vsjet"):
        try:
            shutil.rmtree(".vsjet")
        except OSError:
            pass

    # Delete the index files either source filter may have left behind
    for pattern in ("*.ffindex", "*.bsindex"):
        for f in glob.glob(pattern):
            try:
                os.remove(f)
            except OSError:
                pass

def ffmsindex_path():
    """Absolute path to the bundled ffmsindex.exe, or "" when it is missing."""
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    exe = os.path.join(root_dir, "VapourSynth", "vs-plugins", "ffmsindex.exe")
    return exe if os.path.exists(exe) else ""


def index_source(source_path, index_path=None):
    """Pre-build one ffms2 index, printing the percentage while it works.

    core.ffms2.Source has no progress reporting, so a large file looks like a
    hang before the preview window opens. ffmsindex writes the same index
    ffms2.Source goes on to read, and prints a live percentage while building
    it.

    index_path defaults to <source>.ffindex, which is where ffms2.Source looks
    when it is handed no cachefile. A script that does pass one has to hand the
    same path in here, or the index lands somewhere nothing reads it.

    Whether ffms2 is the filter in play is the caller's decision: BestSource
    prints its own progress and keeps its own index, so pre-indexing for it
    would only build a file nothing goes on to read.

    Returns True when an index is in place, False when the caller has to fall
    back on the source filter indexing silently by itself.
    """
    index_path = str(index_path or (str(source_path) + ".ffindex"))
    if os.path.exists(index_path):
        return True

    ffmsindex = ffmsindex_path()
    if not ffmsindex:
        return False

    print(f"Indexing {os.path.basename(str(source_path))}")
    indexed = True
    try:
        subprocess.run([ffmsindex, str(source_path), index_path], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        # ffms2.Source will index it again itself, just without progress.
        print(f"Warning: could not pre-index {source_path}: {exc}")
        indexed = False
    print()
    return indexed


def index_sources(mkv_files):
    """Pre-index the comparison sources so indexing progress is visible.

    BestSource prints its own progress while indexing, so this step is skipped
    when it is the selected source filter - ffmsindex would only build an index
    nothing goes on to read.
    """
    if source_filter.resolve() == source_filter.BESTSOURCE:
        return

    for mkv in mkv_files:
        index_source(mkv)


def create_vpy_script(mkv_files):
    """Generates the .vpy script content based on found MKV files."""
    
    # 1. Header and Style Definition
    lines = [
        "import vapoursynth as vs",
        "core = vs.core",
        "",
        "# Define an ASS-style string with Alignment=7 (top-left)",
        "ass_style = \",\".join([",
        "    \"Arial\", \"24\",",
        "    \"&H00FFFFFF\", \"&H000000FF\", \"&H00000000\", \"&H00000000\",",
        "    \"0\", \"0\", \"0\", \"0\",",
        "    \"100\", \"100\",",
        "    \"0\", \"0\",",
        "    \"1\", \"2\", \"0\", \"7\",",
        "    \"10\", \"10\", \"10\",",
        "    \"1\"",
        "])",
        "",
        "clips = []",
        "labels = []"
    ]

    # 2. Logic to handle one or multiple files
    vpy_filename = "preview.vpy"

    # ffms2 unless tools\source-filter-override.txt says otherwise.
    active_source_filter = source_filter.resolve()

    # Load all sources into arrays inside the VapourSynth script
    for mkv in mkv_files:
        # Escape backslashes for the script string
        mkv_path = mkv.replace("\\", "/")
        file_label = os.path.basename(mkv)

        source_call = source_filter.plain_source_call(active_source_filter, mkv_path)
        lines.append(f'clips.append({source_call})')
        lines.append(f'labels.append("{file_label}")')
        
    lines.extend([
        "",
        "def black_color(clip):",
        "    \"\"\"Border colour that is actually black for this clip's format.\"\"\"",
        "    fmt = clip.format",
        "    if fmt.color_family == vs.YUV:",
        "        if fmt.sample_type == vs.FLOAT:",
        "            return [0.0, 0.0, 0.0]",
        "        neutral = 1 << (fmt.bits_per_sample - 1)",
        "        return [0, neutral, neutral]",
        "    if fmt.sample_type == vs.FLOAT:",
        "        return [0.0] * fmt.num_planes",
        "    return [0] * fmt.num_planes",
        "",
        "",
        "def pad_to_height(clip, target_height):",
        "    \"\"\"Centre the clip in black bars so it reaches target_height.\"\"\"",
        "    pad = target_height - clip.height",
        "    if pad <= 0:",
        "        return clip",
        "    # Borders must be a multiple of the vertical chroma subsampling",
        "    mod = 1 << clip.format.subsampling_h",
        "    pad -= pad % mod",
        "    if pad <= 0:",
        "        return clip",
        "    top = (pad // 2 // mod) * mod",
        "    return core.std.AddBorders(clip, top=top, bottom=pad - top, color=black_color(clip))",
        "",
        "",
        "widths = set(c.width for c in clips)",
        "",
        "if len(widths) == 1:",
        "    # Same width, differing heights (e.g. a cropped encode next to the",
        "    # untouched source): pad with black bars instead of rescaling, so the",
        "    # pixels line up 1:1 for comparison.",
        "    target_height = max(c.height for c in clips)",
        "    clips = [pad_to_height(c, target_height) for c in clips]",
        "else:",
        "    # Differing widths: downscale everything to the smallest height",
        "    min_height = min(c.height for c in clips)",
        "    scaled = []",
        "    for clip in clips:",
        "        if clip.height > min_height:",
        "            # Calculate new width, maintaining aspect ratio and ensuring mod 2 (even number) for chroma subsampling",
        "            new_width = round((clip.width * (min_height / clip.height)) / 2) * 2",
        "            clip = core.resize.Lanczos(clip, width=new_width, height=min_height)",
        "        scaled.append(clip)",
        "    clips = scaled",
        "",
        "for i, clip in enumerate(clips):",
        "    # Add the subtitle with the filename",
        "    clip = core.sub.Subtitle(clip, text=[labels[i]], style=ass_style)",
        "    ",
        "    # Set output. Note: set_output(0) corresponds to pressing '1' in the previewer",
        "    clip.set_output(i)",
        ""
    ])
            
    return vpy_filename, "\n".join(lines)

def main():
    # Repair stale VSPreview global storage and remove local storage before launch.
    # A missing WindowSettings.zoom_index in old storage makes VSPreview fail
    # before the preview window opens. Under vsview the repair is a no-op.
    repair_vspreview_storage()
    cleanup(None)

    # 1. Scan for MKV files in the current directory
    mkv_files = glob.glob("*.mkv")

    if not mkv_files:
        print("No .mkv files found in this folder.")
        print("Please ensure your MKV files are in the 'extras' folder alongside vspreview.bat")
        input("Press Enter to exit...")
        return

    # 2. Index up front so the wait shows a percentage instead of a blank screen
    index_sources(mkv_files)

    # 3. Generate the .vpy script
    vpy_filename, script_content = create_vpy_script(mkv_files)
    
    print(f"Generating script: {vpy_filename} for {len(mkv_files)} file(s)...")
    with open(vpy_filename, "w", encoding="utf-8") as f:
        f.write(script_content)

    # 4. Execute the previewer. Its console output is held back unless it fails.
    try:
        run_preview(vpy_filename)
    except subprocess.CalledProcessError as e:
        print(f"Error occurred while running {previewer_name()}: {e}")
    except KeyboardInterrupt:
        pass
    finally:
        # 5. Cleanup on exit
        print("Cleaning up temporary files...")
        cleanup(vpy_filename)

if __name__ == "__main__":
    main()