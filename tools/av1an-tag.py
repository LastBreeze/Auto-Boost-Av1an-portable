import os
import glob
import re
import subprocess
import tempfile
import shlex

# Runs in 'temp', tools are in ../tools
TOOLS_DIR = os.path.join("..", "tools")

def get_5fish_folder():
    """Finds the 5fish folder name in tools/av1an."""
    base_path = os.path.join(TOOLS_DIR, "av1an")
    pattern = os.path.join(base_path, "5fish-svt-av1-psy*")
    folders = glob.glob(pattern)
    if folders:
        return os.path.basename(folders[0])
    return "5fish-svt-av1-psy_Unknown"

def get_active_batch_filename():
    """Scans tools/ for the marker file."""
    pattern = os.path.join(TOOLS_DIR, "bat-used-*.txt")
    files = glob.glob(pattern)
    
    if not files:
        print("Error: No active batch marker found.")
        return None
    
    # Pick the newest marker if multiple exist
    marker_file = max(files, key=os.path.getctime)
    filename = os.path.basename(marker_file)
    batch_name = filename.replace("bat-used-", "").replace(".txt", "")
    
    if batch_name.lower().endswith(".bat"):
        batch_name = batch_name[:-4]
        
    return batch_name

def parse_av1an_batch(batch_name):
    """
    Parses the new batch format which defines av1an_settings.
    Handles 'set "VAR=VAL"' and 'set VAR=VAL' correctly.
    """
    batch_path = os.path.join("..", f"{batch_name}.bat")
    
    settings = {
        "av1an_settings": "",
        "FINAL_SPEED": "4",
        "QUALITY": "30",
        "PHOTON_NOISE": "0"
    }

    if not os.path.exists(batch_path):
        return settings

    try:
        with open(batch_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.lower().startswith("set"):
                    continue
                
                # Remove 'set ' prefix
                clean_line = re.sub(r"^set\s+", "", line, flags=re.IGNORECASE).strip()
                
                key = None
                val = None

                # Check for set "VAR=VAL" syntax (Starts with quote)
                if clean_line.startswith('"'):
                    # Find the first equals sign
                    if "=" in clean_line:
                        parts = clean_line.split("=", 1)
                        # Remove leading quote from key
                        key = parts[0].lstrip('"').strip()
                        val = parts[1].strip()
                        # Remove trailing quote from value if it exists (standard batch syntax)
                        if val.endswith('"'):
                            val = val[:-1]
                else:
                    # Standard set VAR=VAL
                    if "=" in clean_line:
                        parts = clean_line.split("=", 1)
                        key = parts[0].strip()
                        val = parts[1].strip()
                        # Handle set VAR="VAL" (explicit quotes in value)
                        if val.startswith('"') and val.endswith('"'):
                            val = val[1:-1]
                
                if key and key in settings:
                    settings[key] = val

    except Exception:
        pass
        
    return settings

def get_crf_string(quality):
    return f"--crf {quality}"

def apply_tag_to_file(filepath, encoding_settings):
    xml_template = f"""<?xml version="1.0"?>
<Tags>
  <Tag>
    <Targets>
      <TrackUID>1</TrackUID>
    </Targets>
    <Simple>
      <Name>ENCODING_SETTINGS</Name>
      <String>{encoding_settings}</String>
    </Simple>
  </Tag>
</Tags>
"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode="w", encoding="utf-8") as tmp:
        tmp.write(xml_template)
        tmp_path = tmp.name
    
    mkvpropedit = os.path.join(TOOLS_DIR, "MKVToolNix", "mkvpropedit.exe")
    
    try:
        print(f"Applying tag to: {filepath}")
        subprocess.run(
            [mkvpropedit, filepath, "--tags", "track:v1:" + tmp_path],
            check=True,
            capture_output=True 
        )
        print("Success.")
    except Exception as e:
        print(f"Error tagging {filepath}: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def main():
    print("Tagging output files...")
    
    batch_name = get_active_batch_filename()
    if not batch_name: return 

    config = parse_av1an_batch(batch_name)
    fish_version = get_5fish_folder()
    
    # Construct info string
    # Format: Av1an [Flags] 5fish... settings: "..."
    
    # 1. Prefix
    info_parts = ["Av1an"]
    
    # 2. Photon Noise (if > 0)
    if config["PHOTON_NOISE"] and config["PHOTON_NOISE"] != "0":
        info_parts.append(f"--photon-noise {config['PHOTON_NOISE']}")
        
    # 3. 5fish version
    info_parts.append(fish_version)
    
    # 4. Settings Block
    settings_content = []
    settings_content.append(f"--preset {config['FINAL_SPEED']}")
    settings_content.append(get_crf_string(config['QUALITY']))
    
    if config['av1an_settings']:
        clean_params = config['av1an_settings'].strip()
        # Safety check: strip external quotes if they somehow remain
        if len(clean_params) >= 2 and clean_params.startswith('"') and clean_params.endswith('"'):
            clean_params = clean_params[1:-1]
        settings_content.append(clean_params)

    combined_settings_str = " ".join(settings_content)
    
    # Final String Assembly
    full_string = " ".join(info_parts) + f' settings: "{combined_settings_str}"'
    
    print("-------------------------------------------------------------------------------")
    print(f"Scanned: {batch_name}.bat")
    print(f"Generated Tag: \n{full_string}")
    print("-------------------------------------------------------------------------------")

    # Only tag files in temp that have been encoded
    found = False
    target_files = glob.glob("*-av1.mkv")
    
    for f in target_files:
        found = True
        apply_tag_to_file(f, full_string)
    
    if not found:
        print("No output MKV files found to tag.")

if __name__ == "__main__":
    main()