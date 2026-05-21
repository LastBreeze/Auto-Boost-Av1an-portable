import os
import glob
import re
import subprocess
import tempfile
import shlex

# Since this script runs in 'temp' via dispatch, path to tools is ../tools
TOOLS_DIR = os.path.join("..", "tools")

def get_script_version():
    """Extracts the latest version number from Auto-Boost-Av1an.py."""
    script_path = os.path.join(TOOLS_DIR, "Auto-Boost-Av1an.py")
    version = "Unknown"
    if os.path.exists(script_path):
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                content = f.read()
                # Looks for pattern like: ver_str = "v2.2"
                match = re.search(r'ver_str\s*=\s*["\'](v[0-9\.]+)["\']', content)
                if match:
                    version = match.group(1)
        except Exception as e:
            pass
    return version

def get_svt_av1_version():
    """Executes SvtAv1EncApp.exe to get the precise version and formats it."""
    exe_path = os.path.join(TOOLS_DIR, "av1an", "SvtAv1EncApp.exe")
    if not os.path.exists(exe_path):
        return "SVT-AV1_Unknown"
        
    try:
        # Run the command and capture output
        result = subprocess.run([exe_path, "--version"], capture_output=True, text=True, check=True)
        output = result.stdout.strip() or result.stderr.strip()
        
        if not output:
            return "SVT-AV1_Unknown"
            
        # Get first line and clean off the (release) tag
        line = output.split('\n')[0].strip()
        line = line.replace(" (release)", "").strip()
        
        # Format 1: svt-av1-psy 5fish fork
        if "SVT-AV1-PSY" in line and "5fish" in line:
            match = re.search(r"SVT-AV1-PSY \[5fish.*?\]\s+(v[0-9a-zA-Z\.\-]+)", line)
            if match:
                return f"svt-av1-psy 5fish fork {match.group(1)}"
            # Fallback if pattern slightly differs
            return re.sub(r"SVT-AV1-PSY \[5fish.*?\]", "svt-av1-psy 5fish fork", line).strip()
            
        # Format 2: SVT-AV1-Essential
        if "SVT-AV1-Essential" in line:
            match = re.search(r"(SVT-AV1-Essential)\s+(v[0-9\.]+)", line)
            if match:
                return f"{match.group(1)} {match.group(2)}"
                
        # Format 3: General Catch-all (e.g. SVT-AV1-HDR)
        return line

    except Exception as e:
        print(f"Error fetching SVT-AV1 version: {e}")
        return "SVT-AV1_Unknown"

def get_active_batch_filename():
    """Scans tools/ folder for the marker file created by the .bat script."""
    # Marker is now in TOOLS_DIR
    pattern = os.path.join(TOOLS_DIR, "bat-used-*.txt")
    files = glob.glob(pattern)
    
    if not files:
        print("Error: No active batch marker found in tools/. Cannot determine settings.")
        return None
    
    marker_file = files[0]
    filename = os.path.basename(marker_file)
    batch_name = filename.replace("bat-used-", "").replace(".txt", "")
    
    if batch_name.lower().endswith(".bat"):
        batch_name = batch_name[:-4]
    
    # Do NOT delete the marker yet, as other files in the loop might need it.
    # Cleanup.py should handle it, or we leave it.
    # If dispatch loops, we need this file to persist for all files.
    # Commenting out removal.
    # try:
    #     os.remove(marker_file)
    # except OSError:
    #     pass
        
    return batch_name

def get_dynamic_variables():
    vars_map = {
        "%WORKER_COUNT%": "Unknown",
        "%SSIMU2_TOOL%": "auto",
        "%SSIMU2_WORKERS%": "4"
    }
    
    wc_path = os.path.join(TOOLS_DIR, "workercount-config.txt")
    if os.path.exists(wc_path):
        try:
            with open(wc_path, "r") as f:
                for line in f:
                    if "workers=" in line:
                        val = line.strip().split("=", 1)[1]
                        vars_map["%WORKER_COUNT%"] = val
        except Exception:
            pass

    ss_path = os.path.join(TOOLS_DIR, "workercount-ssimu2.txt")
    if os.path.exists(ss_path):
        try:
            with open(ss_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("tool="):
                        vars_map["%SSIMU2_TOOL%"] = line.split("=", 1)[1]
                    if line.startswith("workercount="):
                        vars_map["%SSIMU2_WORKERS%"] = line.split("=", 1)[1]
        except Exception:
            pass
            
    return vars_map

def parse_batch_line(line, vars_map):
    try:
        parts = shlex.split(line, posix=False)
    except ValueError:
        return [], "", "medium", None

    start_idx = -1
    for i, part in enumerate(parts):
        if "dispatch.py" in part or "Auto-Boost-Av1an.py" in part:
            start_idx = i
            break
            
    if start_idx == -1:
        return [], "", "medium", None

    raw_args = parts[start_idx+1:]
    general_flags = []
    final_params = ""
    quality = "medium"
    final_speed = None

    i = 0
    while i < len(raw_args):
        curr = raw_args[i]
        
        if curr in ["-i", "--scenes", "--workers"]:
            i += 2
            continue
        if curr == "--fast-params":
            i += 2
            continue
        if curr == "--final-params":
            if i + 1 < len(raw_args):
                final_params = raw_args[i+1]
                i += 2
            else:
                i += 1
            continue
        if curr.startswith("-"):
            flag = curr
            val = None
            if i + 1 < len(raw_args):
                next_token = raw_args[i+1]
                if not next_token.startswith("-") or (next_token.startswith("-") and len(next_token) > 1 and next_token[1].isdigit()):
                    val = next_token
                    i += 2
                else:
                    i += 1
            else:
                i += 1
            if flag == "--quality" and val: quality = val
            if flag == "--final-speed" and val: final_speed = val
            if val: general_flags.append(f"{flag} {val}")
            else: general_flags.append(flag)
        else:
            i += 1

    return general_flags, final_params, quality, final_speed

def get_crf_string(quality):
    q = str(quality).lower().strip()
    if q == "high": return "--crf 25(variable)"
    if q == "low": return "--crf 35(variable)"
    if q == "medium": return "--crf 30(variable)"
    try:
        return f"--crf {q}(variable)"
    except ValueError:
        return "--crf 30(variable)"

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
    
    # Path to mkvpropedit is in ../tools/MKVToolNix/
    mkvpropedit = os.path.join(TOOLS_DIR, "MKVToolNix", "mkvpropedit.exe")
    
    try:
        print(f"Applying tag to: {filepath}")
        subprocess.run(
            [mkvpropedit, filepath, "--tags", "track:v1:" + tmp_path],
            check=True,
            capture_output=True 
        )
        print("Success.")
    except subprocess.CalledProcessError as e:
        print(f"Error tagging {filepath}: {e}")
    except FileNotFoundError:
        print(f"Error: mkvpropedit.exe not found at {mkvpropedit}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def main():
    print("Tagging output files...")
    
    batch_file = get_active_batch_filename()
    if not batch_file: return 

    cmd_line = ""
    batch_vars = {}
    
    # The batch file is in root, which is ..
    real_batch_path = os.path.join("..", f"{batch_file}.bat")
    
    if os.path.exists(real_batch_path):
        try:
            with open(real_batch_path, "r", encoding="utf-8") as f:
                for line in f:
                    strip = line.strip()
                    if re.match(r'^set\s+', strip, re.IGNORECASE):
                        rest = re.sub(r'^set\s+', '', strip, flags=re.IGNORECASE).strip()
                        m = re.match(r'^"?([^"=]+)"?=(.*)', rest)
                        if m:
                            key = m.group(1).strip()
                            val = m.group(2).strip()
                            if rest.startswith('"') and val.endswith('"'):
                                val = val[:-1]
                            batch_vars[f"%{key}%"] = val

                    if (not strip.lower().startswith("rem") and not strip.startswith("::")) and \
                       ("dispatch.py" in strip.lower() or "auto-boost-av1an.py" in strip.lower()):
                        cmd_line = strip
        except Exception as e:
            print(f"Error reading batch file: {e}")
            return
    else:
        print(f"Error: Could not find original batch file: {real_batch_path}")
        return

    vars_map = batch_vars.copy()
    dynamic_vars = get_dynamic_variables()
    vars_map.update(dynamic_vars) 

    if cmd_line:
        for key, val in vars_map.items():
            cmd_line = cmd_line.replace(key, val)

    general_flags, final_params, quality, final_speed = parse_batch_line(cmd_line, vars_map)
    script_version = get_script_version()
    svt_version = get_svt_av1_version()
    
    info_parts = [f"Auto-Boost-Av1an {script_version}"]
    info_parts.extend(general_flags)
    info_parts.append(svt_version)
    
    settings_content = []
    if final_speed: settings_content.append(f"--preset {final_speed}")
    settings_content.append(get_crf_string(quality))
    
    if final_params:
        clean_params = final_params.strip()
        if len(clean_params) >= 2 and clean_params.startswith('"') and clean_params.endswith('"'):
            clean_params = clean_params[1:-1]
        settings_content.append(clean_params)

    combined_settings_str = " ".join(settings_content)
    full_string = " ".join(info_parts) + f' settings: "{combined_settings_str}"'
    
    print("-------------------------------------------------------------------------------")
    print(f"Scanned: {batch_file}.bat")
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