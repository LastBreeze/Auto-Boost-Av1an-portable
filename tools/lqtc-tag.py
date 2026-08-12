import os
import glob
import re
import subprocess
import tempfile

# Runs in 'temp', tools are in ../tools
TOOLS_DIR = os.path.join("..", "tools")

# Settings read out of the active lqtc .bat. These mirror the "set" lines that
# lqtc-builder.py writes, so the MKV tag describes the encode truthfully even
# after the user hand-edits the .bat.
BAT_SETTINGS_KEYS = (
    "lqtc_params",
    "FORK",
    "BACKEND",
    "METRIC",
    "TARGET",
    "CRF_RANGE",
    "DISPLAY_FILE",
)


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
        except Exception:
            pass
    return version


def svt_fork_tag_name(fork):
    """Fork name as it appears inside the [brackets] of the tag."""
    fork_key = (fork or "essential").strip().lower()
    if fork_key in ("svt-av1-essential", "essential"):
        return "svt-av1-essential"
    if fork_key in ("svt-av1-hdr", "hdr"):
        return "svt-av1-hdr"
    return (fork or "essential").strip() or "svt-av1-essential"


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


def parse_lqtc_batch(batch_name):
    """
    Parses the lqtc batch format.
    Handles 'set "VAR=VAL"' and 'set VAR=VAL' correctly.
    """
    batch_path = os.path.join("..", f"{batch_name}.bat")

    settings = {
        "lqtc_params": "",
        "FORK": "essential",
        "BACKEND": "cuda",
        "METRIC": "cvvdp",
        "TARGET": "",
        "CRF_RANGE": "",
        "DISPLAY_FILE": "display.json",
    }

    if not os.path.exists(batch_path):
        return settings

    # Case-insensitive lookup, because cmd.exe variables are case-insensitive.
    key_lookup = {key.lower(): key for key in BAT_SETTINGS_KEYS}

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
                    if "=" in clean_line:
                        parts = clean_line.split("=", 1)
                        key = parts[0].lstrip('"').strip()
                        val = parts[1].strip()
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

                if key and key.lower() in key_lookup:
                    settings[key_lookup[key.lower()]] = val

    except Exception:
        pass

    return settings


def uses_cvvdp(settings):
    """CVVDP is what needs the -d display file in the tag.

    The .bat records METRIC, but the encoder actually picks the metric from the
    numeric target: below 8 is Butteraugli, 8-10 is CVVDP, above 10 is
    SSIMULACRA2. Trust the target when it parses, so a hand-edited TARGET still
    tags correctly.
    """
    target = (settings.get("TARGET") or "").strip()
    match = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*-", target)
    if match:
        try:
            low = float(match.group(1))
            return 8.0 < low <= 10.0
        except ValueError:
            pass
    return (settings.get("METRIC") or "").strip().lower() == "cvvdp"


def build_settings_string(config):
    """Rebuild the LQTC command line that describes this encode.

    Deliberately omits the parts that are machine-specific or constant:
    the executable, input/output paths, -w (worker count), -e svt-av1,
    -v (metric workers) and -m (metric stat).
    """
    parts = []

    target = (config.get("TARGET") or "").strip()
    if target:
        parts.append(f"-t {target}")

    if uses_cvvdp(config):
        # Bare filename only: dispatch passes an absolute path, which would
        # bake a machine-specific location into the tag.
        display_file = (config.get("DISPLAY_FILE") or "display.json").strip().strip('"')
        display_file = re.split(r"[\\/]", display_file)[-1] or "display.json"
        parts.append(f"-d {display_file}")

    crf_range = (config.get("CRF_RANGE") or "").strip()
    if crf_range:
        parts.append(f"-f {crf_range}")

    parts.append("--keep")

    params = (config.get("lqtc_params") or "").strip()
    if len(params) >= 2 and params.startswith('"') and params.endswith('"'):
        params = params[1:-1]
    # The encoder params are quoted as a group. The closing quote is supplied by
    # the quote that closes the whole settings block in main().
    parts.append(f'-p "{params}')

    return " ".join(parts)


def apply_tag_to_file(filepath, encoding_settings):
    xml_template = f"""<?xml version="1.0"?>
<Tags>
  <Tag>
    <Targets>
      <TrackUID>1</TrackUID>
    </Targets>
    <Simple>
      <Name>Encoded_Library_Settings</Name>
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
    if not batch_name:
        return

    config = parse_lqtc_batch(batch_name)
    script_version = get_script_version()
    fork_name = svt_fork_tag_name(config.get("FORK"))

    settings_str = build_settings_string(config)

    full_string = (
        f"Auto-Boost-Av1an {script_version} quality target mode "
        f'[{fork_name}] settings: "{settings_str}"'
    )

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
