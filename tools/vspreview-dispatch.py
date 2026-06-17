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
            print(f"[VSPreview] Repaired missing zoom_index in: {global_storage}")
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
        "# Find the smallest height among all loaded clips",
        "min_height = min([c.height for c in clips])",
        "",
        "for i, clip in enumerate(clips):",
        "    if clip.height > min_height:",
        "        # Calculate new width, maintaining aspect ratio and ensuring mod 2 (even number) for chroma subsampling",
        "        new_width = round((clip.width * (min_height / clip.height)) / 2) * 2",
        "        clip = core.resize.Lanczos(clip, width=new_width, height=min_height)",
        "    ",
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

    # 2. Generate the .vpy script
    vpy_filename, script_content = create_vpy_script(mkv_files)
    
    print(f"Generating script: {vpy_filename} for {len(mkv_files)} file(s)...")
    with open(vpy_filename, "w", encoding="utf-8") as f:
        f.write(script_content)

    # 3. Execute vspreview
    cmd = [sys.executable, "-m", "vspreview", vpy_filename]
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error occurred while running vspreview: {e}")
    except KeyboardInterrupt:
        pass
    finally:
        # 4. Cleanup on exit
        print("Cleaning up temporary files...")
        cleanup(vpy_filename)

if __name__ == "__main__":
    main()