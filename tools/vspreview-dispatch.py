import os
import glob
import sys
import subprocess
import shutil


def repair_vspreview_storage():
    """Repair stale VSPreview storage that crashes on missing WindowSettings.zoom_index."""
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


def cleanup(vpy_file):
    """Cleans up generated VPY files, .vsjet folder, and .ffindex files."""
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

    # Delete .vsjet folder
    if os.path.exists(".vsjet"):
        try:
            shutil.rmtree(".vsjet")
        except OSError:
            pass

    # Delete .ffindex files
    for f in glob.glob("*.ffindex"):
        try:
            os.remove(f)
        except OSError:
            pass

def index_sources(mkv_files):
    """Pre-index sources with ffmsindex so indexing progress is visible.

    core.ffms2.Source has no progress reporting, so a large file looks like a
    hang before the preview window opens. ffmsindex writes the same
    <file>.ffindex that ffms2.Source picks up, and prints a live percentage
    while it works.
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ffmsindex = os.path.join(root_dir, "VapourSynth", "vs-plugins", "ffmsindex.exe")
    if not os.path.exists(ffmsindex):
        return

    for mkv in mkv_files:
        index_path = mkv + ".ffindex"
        if os.path.exists(index_path):
            continue

        print(f"Indexing {os.path.basename(mkv)}")
        try:
            subprocess.run([ffmsindex, mkv, index_path], check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            # ffms2.Source will index it again itself, just without progress.
            print(f"Warning: could not pre-index {mkv}: {exc}")
        print()


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
    
    # Load all sources into arrays inside the VapourSynth script
    for mkv in mkv_files:
        # Escape backslashes for the script string
        mkv_path = mkv.replace("\\", "/")
        file_label = os.path.basename(mkv)
        
        lines.append(f'clips.append(core.ffms2.Source(source="{mkv_path}"))')
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
        "    # Set output. Note: set_output(0) corresponds to pressing '1' in vspreview",
        "    clip.set_output(i)",
        ""
    ])
            
    return vpy_filename, "\n".join(lines)

def main():
    # Repair stale VSPreview global storage and remove local storage before launch.
    # A missing WindowSettings.zoom_index in old storage makes VSPreview fail
    # before the preview window opens.
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

    # 4. Execute vspreview
    cmd = [sys.executable, "-m", "vspreview", vpy_filename]
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error occurred while running vspreview: {e}")
    except KeyboardInterrupt:
        pass
    finally:
        # 5. Cleanup on exit
        print("Cleaning up temporary files...")
        cleanup(vpy_filename)

if __name__ == "__main__":
    main()