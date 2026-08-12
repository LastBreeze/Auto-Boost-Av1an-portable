import os
import glob
import re
import subprocess
import tempfile

# Runs in 'temp', tools are in ../tools
TOOLS_DIR = os.path.join("..", "tools")

# Settings read out of the active condor .bat. These mirror the "set" lines that
# condor-builder.py writes, so the MKV tag describes the encode truthfully even
# after the user hand-edits the .bat.
BAT_SETTINGS_KEYS = (
    "condor_params",
    "FINAL_SPEED",
    "fork",
    "METRIC",
    "TARGET",
    "MIN_QUANTIZER",
    "MAX_QUANTIZER",
    "TARGET_PROFILE",
    "DECODER",
)

# Operational helpers that belong on the dispatcher's command line, not in a tag
# that is supposed to describe the encode.
UNTAGGED_OPTIONS = {
    "--avx512": 1,
    "--arch": 1,
    "--denoise": 1,
    "--tonemap": 1,
    "--autocrop": 0,
    "--verbose": 0,
    "--no-verbose": 0,
}


def strip_untagged_options(params):
    """Remove operational helper options that should not be written to MKV tags."""
    if not params:
        return params
    params = params.strip()
    if len(params) >= 2 and params.startswith('"') and params.endswith('"'):
        params = params[1:-1]

    parts = params.split()
    cleaned = []
    i = 0
    while i < len(parts):
        skip_count = UNTAGGED_OPTIONS.get(parts[i])
        if skip_count is not None:
            i += 1 + skip_count
            continue
        cleaned.append(parts[i])
        i += 1
    return " ".join(cleaned)


def normalize_fgs_table_path(params):
    """Reduce any '--fgs-table <path>' value to its bare filename so MKV tags
    stay portable and free of machine-specific absolute paths (the dispatch
    scripts expand the filename to an absolute path at encode time)."""
    if not params or "--fgs-table" not in params:
        return params

    pattern = re.compile(r'(--fgs-table[ \t]+)("([^"]*)"|\'([^\']*)\'|(\S+))')

    def _repl(match):
        raw = match.group(3) or match.group(4) or match.group(5) or ""
        if not raw:
            return match.group(0)
        filename = re.split(r"[\\/]", raw)[-1]
        if any(ch.isspace() for ch in filename):
            filename = f'"{filename}"'
        return match.group(1) + filename

    return pattern.sub(_repl, params)


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


def get_condor_version():
    """Executes condor.exe to get its version string."""
    exe_path = os.path.join(TOOLS_DIR, "av1an", "condor.exe")
    if not os.path.exists(exe_path):
        return "Condor_Unknown"
    try:
        result = subprocess.run([exe_path, "--version"], capture_output=True, text=True, check=True)
        line = (result.stdout.strip() or result.stderr.strip()).split("\n")[0].strip()
        return line or "Condor_Unknown"
    except Exception:
        return "Condor_Unknown"


def get_svt_av1_version():
    """Executes SvtAv1EncApp.exe to get the precise version and formats it."""
    exe_path = os.path.join(TOOLS_DIR, "av1an", "SvtAv1EncApp.exe")
    if not os.path.exists(exe_path):
        return "SVT-AV1_Unknown"

    try:
        result = subprocess.run([exe_path, "--version"], capture_output=True, text=True, check=True)
        output = result.stdout.strip() or result.stderr.strip()
        if not output:
            return "SVT-AV1_Unknown"

        line = output.split("\n")[0].strip().replace(" (release)", "").strip()

        # Format 1: svt-av1-psy 5fish fork
        if "SVT-AV1-PSY" in line and "5fish" in line:
            match = re.search(r"SVT-AV1-PSY \[5fish.*?\]\s+(v[0-9a-zA-Z\.\-]+)", line)
            if match:
                return f"svt-av1-psy 5fish fork {match.group(1)}"
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


def parse_condor_batch(batch_name):
    """
    Parses the condor batch format.
    Handles 'set "VAR=VAL"' and 'set VAR=VAL' correctly.
    """
    batch_path = os.path.join("..", f"{batch_name}.bat")

    settings = {
        "condor_params": "",
        "FINAL_SPEED": "4",
        "fork": "essential",
        "METRIC": "ssimulacra2",
        "TARGET": "",
        "MIN_QUANTIZER": "",
        "MAX_QUANTIZER": "",
        "TARGET_PROFILE": "standard",
        "DECODER": "bestsource",
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
                        if val.startswith('"') and val.endswith('"'):
                            val = val[1:-1]

                if key and key.lower() in key_lookup:
                    settings[key_lookup[key.lower()]] = val

    except Exception:
        pass

    return settings


def svt_fork_tag_name(fork):
    """Fork name as it appears inside the [brackets] of the tag."""
    fork_key = (fork or "essential").strip().lower()
    if fork_key in ("svt-av1-essential", "essential"):
        return "svt-av1-essential"
    if fork_key in ("svt-av1-hdr", "hdr"):
        return "svt-av1-hdr"
    if fork_key in ("5fish", "svt-av1-psy", "psy"):
        return "svt-av1-psy 5fish"
    return (fork or "essential").strip() or "svt-av1-essential"


def build_settings_string(config):
    """Rebuild the settings that describe this encode.

    There is deliberately no --crf: Condor's Target Quality picks a quantizer
    per scene, so a single CRF in the tag would be a lie. The Target Quality
    settings that produced those quantizers are recorded instead.

    Worker count, decoder threads and file paths are left out because they are
    machine-specific and say nothing about the resulting video.
    """
    parts = [f"--preset {(config.get('FINAL_SPEED') or '4').strip()}"]

    params = (config.get("condor_params") or "").strip()
    if len(params) >= 2 and params.startswith('"') and params.endswith('"'):
        params = params[1:-1]
    if params:
        parts.append(normalize_fgs_table_path(strip_untagged_options(params)))

    metric = (config.get("METRIC") or "").strip()
    if metric:
        parts.append(f"--target-metric {metric}")

    target = (config.get("TARGET") or "").strip()
    if target:
        parts.append(f"--target {target}")

    min_q = (config.get("MIN_QUANTIZER") or "").strip()
    if min_q:
        parts.append(f"--minimum-quantizer {min_q}")

    max_q = (config.get("MAX_QUANTIZER") or "").strip()
    if max_q:
        parts.append(f"--maximum-quantizer {max_q}")

    profile = (config.get("TARGET_PROFILE") or "").strip()
    if profile:
        parts.append(f"--target-profile {profile}")

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

    config = parse_condor_batch(batch_name)
    script_version = get_script_version()
    condor_version = get_condor_version()
    svt_version = get_svt_av1_version()
    fork_name = svt_fork_tag_name(config.get("fork"))

    settings_str = build_settings_string(config)

    full_string = (
        f"Auto-Boost-Av1an {script_version} Condor target quality "
        f"[{fork_name}] {condor_version} {svt_version} "
        f'settings: "{settings_str}"'
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
