import sys
import os
import glob
import re
import subprocess

def main():
    # --- 1. Find the Source File ---
    mkv_files = glob.glob("*.mkv")
    
    if not mkv_files:
        print("[Filter-Preview] No .mkv files found in the filter folder.")
        return

    mkv_files.sort()
    source_filename = mkv_files[0]
    # Escape backslashes for Python string safety
    source_path_escaped = os.path.abspath(source_filename).replace("\\", "/")
    
    print(f"[Filter-Preview] Loading: {source_filename}")

    # --- 2. Read Template ---
    template_path = "template.py"
    if not os.path.exists(template_path):
        print("[Filter-Preview] Error: template.py not found.")
        return

    with open(template_path, "r", encoding="utf-8") as f:
        template_content = f.read()

    # --- 3. Modify Template Content ---
    
    # A. Replace filename
    modified_template = template_content.replace("replace.mkv", source_path_escaped)

    # B. Define Style (Alignment 7 = Top Left)
    # We insert this definition right after 'core = vs.core' to ensure valid context
    ass_style_def = "ass_style = 'Arial,24,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,7,10,10,10,1'"
    
    if "core = vs.core" in modified_template:
        modified_template = modified_template.replace("core = vs.core", f"core = vs.core\n{ass_style_def}")
    else:
        # Fallback if specific line isn't found, insert at top (but after imports is safer)
        modified_template = f"{ass_style_def}\n{modified_template}"

    # C. Hijack 'final.set_output(0)' for the Filter Label
    # We look for any variable setting output 0 and apply the Filter label
    def filter_hijack(match):
        indent = match.group(1)
        var_name = match.group(2)
        return (f"{indent}{var_name} = core.sub.Subtitle({var_name}, text=['Filter'], style=ass_style)\n"
                f"{indent}{var_name}.set_output(0)")

    modified_template = re.sub(r"(?m)^(\s*)(\w+)\.set_output\(0\)", filter_hijack, modified_template)

    # D. Append Source Output Logic (Output 1)
    # We append this to the end to ensure 'src' exists and we don't conflict with commented lines
    source_logic = (
        "\n\n# --- Generated Source Output ---\n"
        "try:\n"
        "    # Check if 'src' variable exists from the template\n"
        "    if 'src' in locals():\n"
        "        # Label it 'Source' (Top-Left) and set to Output 1\n"
        "        src_labeled = core.sub.Subtitle(src, text=['Source'], style=ass_style)\n"
        "        src_labeled.set_output(1)\n"
        "except Exception as e:\n"
        "    print(f'Warning: Could not set Source output: {e}')\n"
    )

    final_script_content = modified_template + source_logic

    # --- 4. Write preview.vpy ---
    vpy_filename = "preview.vpy"
    with open(vpy_filename, "w", encoding="utf-8") as f:
        f.write(final_script_content)

    # --- 5. Launch vspreview ---
    print(f"[Filter-Preview] Launching vspreview with {vpy_filename}...")
    try:
        subprocess.run([sys.executable, "-m", "vspreview", vpy_filename], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running vspreview: {e}")
    except KeyboardInterrupt:
        pass

    # --- 6. Cleanup ---
    if os.path.exists(vpy_filename):
        try:
            os.remove(vpy_filename)
        except:
            pass
    
    # Clean up VS index files
    for f in glob.glob("*.ffindex"):
        try: os.remove(f)
        except: pass

if __name__ == "__main__":
    main()