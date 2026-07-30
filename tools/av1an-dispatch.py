import sys
import subprocess
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glob
import shutil
import shlex
import re
import time
import threading
import collections
import json
import urllib.parse
import urllib.request
from pathlib import Path
import unicodedata
from wakepy import keep
from svt_fork_setup import setup_svt_av1_fork

BLUE = "\033[94m"
RED = "\033[91m"
RESET = "\033[0m"

DISPLAY_USERNAME = "av1enjoyer"
_WINDOWS_USER_PATH_RE = re.compile(
    r"([\\/]+users[\\/]+)[A-Za-z0-9._-]+",
    re.IGNORECASE,
)


def anonymize_user_paths(text):
    """Hide the real Windows profile name in user-facing console output."""
    if not isinstance(text, str):
        return text
    return _WINDOWS_USER_PATH_RE.sub(
        lambda match: f"{match.group(1)}{DISPLAY_USERNAME}",
        text,
    )


class AnonymizedTextStream:
    """Proxy a text stream while anonymizing C:\\Users\\<name> paths."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        return self._stream.write(anonymize_user_paths(text))

    def writelines(self, lines):
        return self._stream.writelines(anonymize_user_paths(line) for line in lines)

    def __getattr__(self, name):
        return getattr(self._stream, name)


sys.stdout = AnonymizedTextStream(sys.stdout)
sys.stderr = AnonymizedTextStream(sys.stderr)


def format_elapsed_hhmmss(seconds):
    """Format elapsed seconds as hh:mm:ss, allowing totals longer than 24 hours."""
    total_seconds = max(0, int(float(seconds) + 0.5))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def print_av1an_timing_report(report):
    print("\n" + "-" * 80)
    print(f"Av1an time report for: {report['filename']}")
    print("Time format legend: hh:mm:ss = hours:minutes:seconds")
    print(f"Av1an encoding time: {format_elapsed_hhmmss(report['av1an_encoding'])}")
    print("-" * 80)

def scene_detection_env():
    """Environment for scene detection subprocesses.

    Forces unbuffered Python output so live progress lines from
    Progressive-Scene-Detection.py are visible in the parent console.
    """
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["AUTOBOOST_SCENE_X264_PROGRESS"] = "1"
    return env

# =========================================================================
# Simple-mode (non --verbose) progress display
#
# When the generated .bat does not pass --verbose, the noisy phases of the
# workflow are shown as Auto-Boost-Essential style progress bars with a
# short beginner-friendly explanation underneath. The explanation for a
# phase disappears as soon as that phase finishes.
# =========================================================================

SIMPLE_EXPLANATION_SCENE_DETECTION = (
    "Using VapourSynth and x264 for scene detection to break the video into chunks for\n"
    "visual metrics quality measuring and parallel encoding for increased encoding speed."
)
SIMPLE_EXPLANATION_MUXING = (
    "Packaging the finished video together with the original audio, subtitles, chapters,\n"
    "etc, into your final MKV file in the video-output folder."
)

# All simple-mode bars pad their description to this width so every progress
# bar in the workflow starts at the same column and stays aligned.
SIMPLE_DESC_WIDTH = 42


def simple_description(text):
    return "[green]" + text.ljust(SIMPLE_DESC_WIDTH)


try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.text import Text
    from rich.progress import (
        Progress,
        ProgressColumn,
        TextColumn,
        BarColumn,
        SpinnerColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )

    class SimpleFPSColumn(ProgressColumn):
        """fps readout on the right side of the bar (default color), fed via
        task.fields['fps']. Renders fixed-width so bars stay aligned."""

        def render(self, task):
            fps = task.fields.get("fps")
            if fps is None:
                return Text(" " * 12)
            return Text(f"{fps:>8.2f} fps")

    class PlainTimeElapsedColumn(TimeElapsedColumn):
        """Elapsed time in the default color instead of rich's cyan."""

        def render(self, task):
            text = super().render(task)
            text.style = ""
            return text

    class PlainTimeRemainingColumn(TimeRemainingColumn):
        """Remaining time in the default color instead of rich's cyan."""

        def render(self, task):
            text = super().render(task)
            text.style = ""
            return text

    class PhaseRenderable:
        """A progress display plus an explanation line that can be hidden."""

        def __init__(self, progress, explanation):
            self.progress = progress
            self.explanation = explanation
            self.show_explanation = explanation is not None

        def __rich__(self):
            if self.show_explanation:
                return Group(self.progress, Text(self.explanation, style="dim"))
            return self.progress

    RICH_AVAILABLE = True
except ImportError:
    # Without rich we cannot draw the simple interface; every phase falls
    # back to the verbose behaviour instead of failing.
    RICH_AVAILABLE = False

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
SCENE_PROGRESS_RE = re.compile(
    r"Frame\s+(\d+)\s*/\s*([\d.]+)%\s*/\s*(VapourSynth|x264) based scene detection"
    r"(?:\s+\w+)?\s*/\s*([\d.]+)\s*fps"
)
MUX_PROGRESS_RE = re.compile(r"[Pp]rogress:\s*(\d+)\s*%")


def essential_style_progress(console):
    """Progress bar with the same appearance Auto-Boost-Essential uses.
    Percentage, fps and time readouts use the default (white) color, and the
    fps column is fixed-width so all bars in the workflow align."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        "{task.percentage:>3.0f}%",
        SimpleFPSColumn(),
        PlainTimeElapsedColumn(),
        PlainTimeRemainingColumn(),
        console=console,
    )


def stream_subprocess_lines(proc, on_line):
    """Read a subprocess's merged output, splitting on \r and \n so live
    carriage-return progress updates are seen as individual lines."""
    buf = b""
    stream = proc.stdout
    while True:
        chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(1)
        if not chunk:
            break
        buf += chunk
        parts = re.split(b"[\r\n]", buf)
        buf = parts.pop()
        for raw in parts:
            if not raw:
                continue
            line = ANSI_ESCAPE_RE.sub("", raw.decode("utf-8", "replace")).strip()
            if line:
                on_line(line)
    if buf:
        line = ANSI_ESCAPE_RE.sub("", buf.decode("utf-8", "replace")).strip()
        if line:
            on_line(line)


def print_captured_tail(label, lines):
    """Show the tail of a quiet subprocess's output after a failure."""
    if not lines:
        return
    print(f"{RED}[Dispatch] {label} (last {len(lines)} output lines):{RESET}")
    for line in lines:
        print(f"  {line}")


def run_scene_detection_simple(cmd, cwd, env):
    """Run Progressive-Scene-Detection.py behind two Essential-style progress
    bars (VapourSynth + x264) with a short explanation underneath.

    Returns the subprocess return code."""
    console = Console()
    progress = essential_style_progress(console)
    vs_task = progress.add_task(simple_description("VapourSynth scene detection"),
                                total=100.0, fps=None)
    x264_task = progress.add_task(simple_description("x264 scene detection"),
                                  total=100.0, fps=None)
    renderable = PhaseRenderable(progress, SIMPLE_EXPLANATION_SCENE_DETECTION)
    other_lines = collections.deque(maxlen=40)

    def on_line(line):
        match = SCENE_PROGRESS_RE.search(line)
        if match:
            percent = min(100.0, float(match.group(2)))
            fps = float(match.group(4))
            task = vs_task if match.group(3) == "VapourSynth" else x264_task
            progress.update(task, completed=percent, fps=fps)
        else:
            other_lines.append(line)

    proc = subprocess.Popen(cmd, cwd=cwd, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        with Live(renderable, console=console, refresh_per_second=8) as live:
            try:
                stream_subprocess_lines(proc, on_line)
                returncode = proc.wait()
                if returncode == 0:
                    progress.update(vs_task, completed=100.0)
                    progress.update(x264_task, completed=100.0)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                renderable.show_explanation = False
                live.refresh()
    except KeyboardInterrupt:
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        raise
    if returncode != 0:
        print_captured_tail("Scene detection failed", list(other_lines))
    return returncode


def run_with_mux_progress(cmd, cwd, description):
    """Run a muxing helper behind a single Essential-style progress bar,
    driven by mkvmerge's 'Progress: N%' output.

    Returns the subprocess return code."""
    console = Console()
    progress = essential_style_progress(console)
    task = progress.add_task(simple_description(description), total=100.0, fps=None)
    renderable = PhaseRenderable(progress, SIMPLE_EXPLANATION_MUXING)
    other_lines = collections.deque(maxlen=40)

    def on_line(line):
        match = MUX_PROGRESS_RE.search(line)
        if match:
            progress.update(task, completed=min(100.0, float(match.group(1))))
        else:
            other_lines.append(line)

    proc = subprocess.Popen(cmd, cwd=cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        with Live(renderable, console=console, refresh_per_second=8) as live:
            try:
                stream_subprocess_lines(proc, on_line)
                returncode = proc.wait()
                if returncode == 0:
                    progress.update(task, completed=100.0)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                renderable.show_explanation = False
                live.refresh()
    except KeyboardInterrupt:
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        raise
    if returncode != 0:
        print_captured_tail("Muxing output", list(other_lines))
    return returncode


def run_quiet(cmd, cwd, label):
    """Run a helper silently; on failure print the tail of its output.

    Returns the subprocess return code."""
    proc = subprocess.run(cmd, cwd=cwd,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0 and proc.stdout:
        lines = [ANSI_ESCAPE_RE.sub("", raw).rstrip() for raw in
                 proc.stdout.decode("utf-8", "replace").splitlines() if raw.strip()]
        print_captured_tail(label, lines[-40:])
    return proc.returncode


SIMPLE_EXPLANATION_ENCODING = (
    "Encoding your video in a single pass at your chosen quality level. Each chunk is\n"
    "encoded in parallel across your worker count for maximum speed."
)



def find_av1an_done_json(search_dir, min_mtime):
    """Find av1an's done.json in search_dir or one directory level below it,
    ignoring stale files from earlier runs (mtime older than min_mtime)."""
    candidates = []
    direct = os.path.join(search_dir, "done.json")
    if os.path.isfile(direct):
        candidates.append(direct)
    try:
        names = os.listdir(search_dir)
    except OSError:
        names = []
    for name in names:
        candidate = os.path.join(search_dir, name, "done.json")
        if os.path.isfile(candidate):
            candidates.append(candidate)

    def _mtime(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0.0

    fresh = [path for path in candidates if _mtime(path) >= min_mtime]
    if not fresh:
        return None
    return max(fresh, key=_mtime)


def read_av1an_done_json(path):
    """Return (total_frames or None, completed_frames) from av1an's done.json.
    Handles both old (int) and new (dict) per-chunk formats, and returns None
    if the file is mid-write or unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    total = data.get("frames")
    if not isinstance(total, (int, float)) or total <= 0:
        total = None
    completed = 0
    done = data.get("done", {})
    if isinstance(done, dict):
        for value in done.values():
            if isinstance(value, dict):
                try:
                    completed += int(value.get("frames", 0))
                except (TypeError, ValueError):
                    pass
            elif isinstance(value, (int, float)):
                completed += int(value)
    return total, completed


def run_av1an_simple(cmd, cwd, description, explanation, temp_search_dir):
    """Run av1an behind a single Essential-style progress bar with a short
    explanation underneath. Progress advances as av1an chunks complete, read
    from av1an's done.json inside its temporary folder, with a rolling fps
    readout on the right side of the bar.

    Returns the subprocess return code."""
    console = Console()
    progress = essential_style_progress(console)
    task = progress.add_task(simple_description(description), total=None, fps=None)
    renderable = PhaseRenderable(progress, explanation)
    other_lines = collections.deque(maxlen=40)
    stop_event = threading.Event()
    started_wall_time = time.time()

    def watch_done_json():
        samples = collections.deque()
        done_path = None
        while not stop_event.wait(1.0):
            if done_path is None or not os.path.isfile(done_path):
                done_path = find_av1an_done_json(temp_search_dir, started_wall_time - 1.0)
                if done_path is None:
                    continue
            info = read_av1an_done_json(done_path)
            if info is None:
                continue
            total, completed = info
            now = time.monotonic()
            samples.append((now, completed))
            while samples and now - samples[0][0] > 120.0:
                samples.popleft()
            fps = None
            if len(samples) >= 2:
                elapsed = samples[-1][0] - samples[0][0]
                frames = samples[-1][1] - samples[0][1]
                if elapsed > 0 and frames > 0:
                    fps = frames / elapsed
            progress.update(task, total=total, completed=completed, fps=fps)

    proc = subprocess.Popen(cmd, cwd=cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    reader = threading.Thread(target=stream_subprocess_lines,
                              args=(proc, other_lines.append), daemon=True)
    watcher = threading.Thread(target=watch_done_json, daemon=True)
    try:
        with Live(renderable, console=console, refresh_per_second=8) as live:
            reader.start()
            watcher.start()
            try:
                returncode = proc.wait()
                if returncode == 0:
                    final_total = progress.tasks[0].total
                    if final_total:
                        progress.update(task, completed=final_total)
                    else:
                        progress.update(task, total=1, completed=1)
            finally:
                stop_event.set()
                watcher.join(timeout=3)
                reader.join(timeout=3)
                renderable.show_explanation = False
                live.refresh()
    except KeyboardInterrupt:
        stop_event.set()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        raise
    if returncode != 0:
        print_captured_tail("Av1an output", list(other_lines))
    return returncode


def parse_settings_lines(lines):
    """Parse settings.txt lines into a case-insensitive key/value dict."""
    settings = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith(("#", ";", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        settings[key.strip().lower()] = value.strip()
    return settings


def set_settings_value(settings_path, key, value):
    """Set key=value in settings.txt, preserving the rest of the file, and return parsed settings."""
    key_l = key.lower()
    lines = []
    found = False
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";", "[")) or "=" not in line:
            continue
        k, _ = line.split("=", 1)
        if k.strip().lower() == key_l:
            lines[idx] = f"{k.strip()}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    with open(settings_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return parse_settings_lines(lines)

# --- Optimized worker settings (read from the generating .bat file) ---
_BAT_SET_RE = re.compile(r'^set\s+"?([^=\s"]+)\s*=(.*?)"?\s*$', re.IGNORECASE)


def find_active_bat_file(tools_dir, root_dir):
    """Locate the .bat that launched this run via the tools/bat-used-*.txt marker."""
    markers = glob.glob(os.path.join(tools_dir, "bat-used-*.txt"))
    markers.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for marker in markers:
        name = os.path.basename(marker)
        if not (name.startswith("bat-used-") and name.endswith(".txt")):
            continue
        bat_name = name[len("bat-used-"):-len(".txt")]
        bat_path = os.path.join(root_dir, bat_name)
        if os.path.isfile(bat_path):
            return bat_path
    return None


def read_and_repair_workercount_config(tools_dir):
    """Read tools\\workercount-config.txt tolerantly and repair it in place.

    Users hand-edit this file, and Notepad likes to re-save it as UTF-16 or
    UTF-8-with-BOM. Strict UTF-8 readers downstream (the Rust tools) then
    fail with "stream did not contain valid UTF-8", and the .bat reads
    garbage for the worker value. This reader accepts any common Windows
    encoding, extracts the worker count, and - if the file was malformed -
    rewrites it as plain ASCII 'workers=N'. Returns the worker count int,
    or None if the file does not exist."""
    path = os.path.join(tools_dir, "workercount-config.txt")
    try:
        with open(path, "rb") as f:
            blob = f.read()
    except OSError:
        return None
    text = None
    for enc in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            text = blob.decode(enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if text is None:
        text = blob.decode("latin-1", errors="replace")
    text = text.replace("\ufeff", "").replace("\x00", "")
    m = re.search(r"workers\s*=\s*(\d+)", text, re.IGNORECASE)
    if not m:
        # Tolerate a file that is just a bare number
        m = re.search(r"^\s*(\d+)\s*$", text, re.MULTILINE)
    if m:
        workers = max(1, int(m.group(1)))
        broken = False
    else:
        workers = 1  # unreadable/garbage: safe default
        broken = True
    # Rewrite only if the on-disk bytes are not already the clean canonical
    # form (either newline style counts as clean).
    canonical = {f"workers={workers}\n".encode("ascii"),
                 f"workers={workers}\r\n".encode("ascii")}
    if blob not in canonical:
        try:
            with open(path, "w", encoding="ascii") as f:
                f.write(f"workers={workers}\n")
            reason = ("no readable worker count found - reset to the safe default"
                      if broken else "re-saved as plain text (was UTF-16/BOM/malformed)")
            print(f"\033[93m[Dispatch] Repaired workercount-config.txt -> "
                  f"workers={workers} ({reason})\033[0m")
        except OSError:
            pass
    return workers


def sanitize_worker_value(raw, fallback):
    """Return a clean positive-integer worker string from a possibly mangled
    value (BOM/null/UTF-16 junk leaking out of a hand-edited config file via
    the .bat). Returns `fallback` when no digits can be recovered."""
    if raw is None:
        return fallback
    cleaned = str(raw).replace("\ufeff", "").replace("\x00", "").strip()
    m = re.search(r"\d+", cleaned)
    if not m:
        return fallback
    return str(max(1, int(m.group(0))))


def read_bat_optimize_settings(tools_dir, root_dir):
    """Parse optimize-workers, custom av1an workers, and custom SSIMU2
    tool/worker settings from the active .bat. Returns an empty dict when the settings are absent, so
    callers proceed exactly as before."""
    bat_path = find_active_bat_file(tools_dir, root_dir)
    if not bat_path:
        return {}
    wanted = {"optimize-workers", "custom-av1an-workers", "custom-ssim2-workers", "custom-ssim2-tool"}
    settings = {}
    try:
        with open(bat_path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f.read().splitlines():
                line = raw.strip()
                if not line or line.startswith("::") or line.lower().startswith("rem "):
                    continue
                m = _BAT_SET_RE.match(line)
                key = value = None
                if m:
                    key, value = m.group(1).lower(), m.group(2).strip()
                elif "=" in line and " " not in line.split("=", 1)[0] and "%" not in line.split("=", 1)[0]:
                    k, v = line.split("=", 1)
                    key, value = k.strip().lower(), v.strip()
                if key in wanted:
                    settings[key] = value
    except Exception:
        return {}
    return settings


def svt_fork_display_name(fork):
    fork_key = (fork or "essential").strip().lower()
    if fork_key in ("svt-av1-essential", "essential"):
        return "Essential"
    if fork_key in ("svt-av1-hdr", "hdr"):
        return "HDR"
    if fork_key in ("5fish", "svt-av1-psy", "psy"):
        return "psy 5fish"
    if fork_key == "custom":
        return "custom"
    return (fork or "essential").strip() or "Essential"


def parse_bool_setting(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def is_hdr_fork(fork):
    return (fork or "").strip().lower() in ("svt-av1-hdr", "hdr")


def parse_mediainfo_color_metadata(mediainfo_text):
    """Return detected color metadata from MediaInfo text."""
    metadata = {
        "primaries": "",
        "transfer": "",
        "matrix": "",
        "hdr_format": "",
        "chroma_position": "",
        "color_range_full": False,
        "mastering_primaries": "",
        "mastering_luminance": "",
        "max_cll": "",
        "max_fall": "",
        "is_bt709": False,
        "is_bt601": False,
        "is_hdr": False,
    }
    for line in mediainfo_text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key_l = key.strip().lower()
        value = value.strip()
        value_l = value.lower()
        if key_l == "color primaries":
            metadata["primaries"] = value
        elif key_l == "transfer characteristics":
            metadata["transfer"] = value
        elif key_l == "matrix coefficients":
            metadata["matrix"] = value
        elif key_l == "hdr format":
            metadata["hdr_format"] = value
        elif key_l == "chroma subsampling":
            type_match = re.search(r"type\s*(\d)", value_l)
            if type_match:
                metadata["chroma_position"] = type_match.group(1)
        elif key_l == "color range":
            metadata["color_range_full"] = value_l == "full"
        elif key_l == "mastering display color primaries":
            metadata["mastering_primaries"] = value
        elif key_l == "mastering display luminance":
            metadata["mastering_luminance"] = value
        elif key_l == "maximum content light level":
            metadata["max_cll"] = value
        elif key_l == "maximum frame-average light level":
            metadata["max_fall"] = value

    prim_l = metadata["primaries"].lower()
    trans_l = metadata["transfer"].lower()
    mat_l = metadata["matrix"].lower()
    hdr_format_l = metadata["hdr_format"].lower()
    metadata["is_bt709"] = (
        metadata["primaries"] == "BT.709"
        and metadata["transfer"] == "BT.709"
        and metadata["matrix"] == "BT.709"
    )
    metadata["is_bt601"] = "bt.601" in prim_l and "bt.601" in trans_l and "bt.601" in mat_l
    hdr_markers = (
        "hdr", "dolby vision", "smpte st 2084", "st 2084", "pq",
        "hlg", "arib std-b67", "bt.2020", "bt2020", "smpte 2086"
    )
    metadata["is_hdr"] = any(marker in hdr_format_l for marker in hdr_markers) or any(
        marker in text for text in (prim_l, trans_l, mat_l) for marker in hdr_markers
    )
    return metadata


# --- MediaInfo -> SVT-AV1-HDR color flag mapping (Appendix A.2 of the SVT-AV1 User Guide) ---

# CIE 1931 G/B/R coordinates for common mastering display primaries (white point D65).
KNOWN_MASTERING_PRIMARIES = {
    "display p3": "G(0.265,0.690)B(0.15,0.06)R(0.68,0.32)",
    "p3 d65": "G(0.265,0.690)B(0.15,0.06)R(0.68,0.32)",
    "dci p3": "G(0.265,0.690)B(0.15,0.06)R(0.68,0.32)",
    "p3": "G(0.265,0.690)B(0.15,0.06)R(0.68,0.32)",
    "bt.2020": "G(0.17,0.797)B(0.131,0.046)R(0.708,0.292)",
    "bt.2100": "G(0.17,0.797)B(0.131,0.046)R(0.708,0.292)",
    "bt.709": "G(0.30,0.60)B(0.15,0.06)R(0.64,0.33)",
}


def _format_nits(value):
    """4000.0 -> '4000', 0.0050 -> '0.005', 0.0001 -> '0.0001' (matches StaxRip-style output)."""
    return f"{value:g}"


def map_color_primaries_code(value):
    v = (value or "").lower()
    if "bt.2020" in v or "bt.2100" in v:
        return "9"
    if "bt.709" in v:
        return "1"
    if "display p3" in v or "p3 d65" in v or "smpte 432" in v or "smpte eg 432" in v:
        return "12"
    if "dci p3" in v or "p3 dci" in v or "smpte 431" in v or "smpte rp 431" in v:
        return "11"
    if "bt.601" in v:
        return "6"
    if "bt.470 system m" in v:
        return "4"
    if "bt.470" in v:
        return "5"
    if "smpte 240" in v:
        return "7"
    if "xyz" in v or "smpte 428" in v:
        return "10"
    if "ebu" in v:
        return "22"
    return None


def map_transfer_code(value):
    v = (value or "").lower()
    if "pq" in v or "2084" in v:
        return "16"
    if "hlg" in v or "b67" in v:
        return "18"
    if "bt.2020" in v:
        return "15" if "12" in v else "14"
    if "bt.709" in v:
        return "1"
    if "bt.601" in v:
        return "6"
    if "srgb" in v or "sycc" in v:
        return "13"
    if "smpte 428" in v or "st 428" in v:
        return "17"
    if "linear" in v:
        return "8"
    if "smpte 240" in v:
        return "7"
    if "bt.470 system m" in v:
        return "4"
    if "bt.470" in v:
        return "5"
    return None


def map_matrix_code(value):
    v = (value or "").lower()
    if "ictcp" in v:
        return "14"
    if "bt.2020" in v and "constant" in v and "non" not in v:
        return "10"
    if "bt.2020" in v or "bt.2100" in v:
        return "9"
    if "bt.709" in v:
        return "1"
    if "bt.601" in v:
        return "6"
    if "ycgco" in v:
        return "8"
    if "smpte 240" in v:
        return "7"
    if "fcc" in v:
        return "4"
    if "bt.470" in v:
        return "5"
    if "identity" in v:
        return "0"
    return None


def build_mastering_display_value(metadata):
    """Build the --mastering-display G(x,y)B(x,y)R(x,y)WP(x,y)L(max,min) value from MediaInfo text."""
    prim_text = (metadata.get("mastering_primaries") or "").strip()
    lum_text = (metadata.get("mastering_luminance") or "").strip()
    if not prim_text or not lum_text:
        return None

    gbr_wp = None
    # Coordinate form: "R: x=0.680000 y=0.320000, G: ..., B: ..., White point: x=... y=..."
    coords = re.findall(
        r"(R|G|B|White point)\s*:?\s*x\s*=?\s*([0-9.]+)[ ,;]+y\s*=?\s*([0-9.]+)",
        prim_text,
        re.IGNORECASE,
    )
    coord_map = {name.lower(): (x, y) for name, x, y in coords}
    if all(k in coord_map for k in ("g", "b", "r")):
        wp = coord_map.get("white point", ("0.3127", "0.329"))
        gbr_wp = (
            f"G({coord_map['g'][0]},{coord_map['g'][1]})"
            f"B({coord_map['b'][0]},{coord_map['b'][1]})"
            f"R({coord_map['r'][0]},{coord_map['r'][1]})"
            f"WP({wp[0]},{wp[1]})"
        )
    else:
        # Named form: "Display P3", "BT.2020", etc.
        prim_l = prim_text.lower()
        for name, value in KNOWN_MASTERING_PRIMARIES.items():
            if name in prim_l:
                gbr_wp = value + "WP(0.3127,0.329)"
                break
    if not gbr_wp:
        return None

    min_match = re.search(r"min\s*:\s*([0-9.]+)", lum_text, re.IGNORECASE)
    max_match = re.search(r"max\s*:\s*([0-9.]+)", lum_text, re.IGNORECASE)
    if not (min_match and max_match):
        return None
    try:
        l_max = _format_nits(float(max_match.group(1)))
        l_min = _format_nits(float(min_match.group(1)))
    except ValueError:
        return None
    return f"{gbr_wp}L({l_max},{l_min})"


def build_content_light_value(metadata):
    """Build the --content-light max_cll,max_fall value from MediaInfo text like '1 264 cd/m2'."""
    def _int_of(text):
        if not text:
            return None
        head = re.split(r"cd", text, flags=re.IGNORECASE)[0]
        digits = re.sub(r"[^\d]", "", head)
        return digits or None

    max_cll = _int_of(metadata.get("max_cll", ""))
    max_fall = _int_of(metadata.get("max_fall", ""))
    if max_cll and max_fall:
        return f"{max_cll},{max_fall}"
    return None


def build_hdr_color_flags(metadata):
    """Return the SVT-AV1-HDR color flag string for an HDR source, or None if
    the primaries/transfer/matrix could not be mapped. Values never contain
    spaces so they survive param-string whitespace splitting."""
    primaries_code = map_color_primaries_code(metadata.get("primaries", ""))
    transfer_code = map_transfer_code(metadata.get("transfer", ""))
    matrix_code = map_matrix_code(metadata.get("matrix", ""))
    if not (primaries_code and transfer_code and matrix_code):
        return None

    flags = (
        f" --color-primaries {primaries_code}"
        f" --transfer-characteristics {transfer_code}"
        f" --matrix-coefficients {matrix_code}"
    )
    if metadata.get("chroma_position") in ("1", "2"):
        flags += f" --chroma-sample-position {metadata['chroma_position']}"
    if metadata.get("color_range_full"):
        flags += " --color-range 1"
    mastering_display = build_mastering_display_value(metadata)
    if mastering_display:
        flags += f" --mastering-display {mastering_display}"
    content_light = build_content_light_value(metadata)
    if content_light:
        flags += f" --content-light {content_light}"
    return flags


def detect_color_metadata(input_path, mediainfo_exe):
    if not os.path.exists(mediainfo_exe):
        return None
    try:
        res = subprocess.run(
            [mediainfo_exe, input_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception as e:
        print(f"[Dispatch] Warning: MediaInfo color detection failed: {e}")
        return None
    if res.returncode != 0:
        print(f"[Dispatch] Warning: MediaInfo color detection failed with exit code {res.returncode}.")
        return None
    return parse_mediainfo_color_metadata(res.stdout)


def pause_for_hdr_color_settings(input_path, color_metadata):
    print("\n" + "=" * 80)
    print(f"{RED}[Dispatch] ERROR: HDR color settings are detected in the input file, but they could not be auto-mapped.{RESET}")
    print(f"{RED}[Dispatch] Input: {os.path.basename(input_path)}{RESET}")
    print(f"{RED}[Dispatch] You need to manually edit the color settings for your .bat file before using the SVT-AV1-HDR fork,{RESET}")
    print(f"{RED}[Dispatch] or set tonemap=True in the .bat to tonemap HDR to SDR.{RESET}")
    print(f"{RED}[Dispatch] Detected color settings:{RESET}")
    print(f"{RED}[Dispatch]   Color primaries: {color_metadata.get('primaries') or 'unknown'}{RESET}")
    print(f"{RED}[Dispatch]   Transfer characteristics: {color_metadata.get('transfer') or 'unknown'}{RESET}")
    print(f"{RED}[Dispatch]   Matrix coefficients: {color_metadata.get('matrix') or 'unknown'}{RESET}")
    if color_metadata.get("hdr_format"):
        print(f"{RED}[Dispatch]   HDR format: {color_metadata['hdr_format']}{RESET}")
    print("=" * 80)
    try:
        input("Press Enter to exit...")
    except EOFError:
        pass
    sys.exit(1)


def resolve_configured_path(configured_path, root_dir, tools_dir, default_filename="ntfy.txt"):
    configured_path = (configured_path or "").strip().strip('"')
    if not configured_path:
        return os.path.join(tools_dir, default_filename)

    if re.match(r"^[A-Za-z]:[\\/]", configured_path):
        if os.name != "nt":
            drive = configured_path[0].lower()
            rest = configured_path[2:].lstrip("\\/").replace("\\", "/")
            return os.path.join("/mnt", drive, rest)
        return configured_path

    if os.path.isabs(configured_path):
        return configured_path

    if os.name != "nt":
        configured_path = configured_path.replace("\\", "/")

    return os.path.join(root_dir, configured_path)


def read_ntfy_config(settings, root_dir, tools_dir):
    ntfy_path_setting = (settings or {}).get("ntfy", "").strip()
    if ntfy_path_setting.lower() in ("", "false", "off", "none", "disabled"):
        if not ntfy_path_setting:
            ntfy_path_setting = os.path.join(tools_dir, "ntfy.txt")
        else:
            return {}, None
    ntfy_path = resolve_configured_path(ntfy_path_setting, root_dir, tools_dir)
    if not os.path.exists(ntfy_path):
        return {}, ntfy_path

    config = {}
    try:
        with open(ntfy_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith(("#", ";")):
                    continue
                if "=" in stripped:
                    key, value = stripped.split("=", 1)
                    config[key.strip().lower()] = value.strip()
                elif "secretword" not in config:
                    # Backward compatibility with older one-line ntfy.txt files.
                    config["secretword"] = stripped
    except Exception as e:
        print(f"[Dispatch] Warning: Could not read ntfy settings from {ntfy_path}: {e}")
    return config, ntfy_path


def send_ntfy_notification(settings, root_dir, tools_dir, title, message):
    ntfy_config, ntfy_path = read_ntfy_config(settings, root_dir, tools_dir)
    secret_word = ntfy_config.get("secretword", "").strip()
    pc_name = ntfy_config.get("pcname", "").strip() or "this PC"
    if not secret_word:
        if ntfy_path:
            print(f"[Dispatch] ntfy not sent; secretword missing or empty in: {ntfy_path}")
        return False

    body = f"{message}\nPC: {pc_name}"
    topic = urllib.parse.quote(secret_word, safe="")
    request = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=body.encode("utf-8"),
        headers={
            "Title": title,
            "Tags": "movie_camera",
            "Priority": "default",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        print("[Dispatch] ntfy notification sent.")
        return True
    except Exception as e:
        print(f"[Dispatch] Warning: Failed to send ntfy notification: {e}")
        return False

WINDOWS_MAX_PATH = 260


def display_path_for_length(path):
    """Return the Windows-style path users see, so length warnings match Windows tools."""
    abs_path = os.path.abspath(path)
    normalized = abs_path.replace("/", "\\")
    lower = normalized.lower()
    if lower.startswith("\\mnt\\") and len(normalized) > 6 and normalized[5].isalpha() and normalized[6:7] == "\\":
        return f"{normalized[5].upper()}:\\{normalized[7:]}"
    return normalized


def pause_for_long_paths(long_paths):
    print("\n" + "=" * 80)
    print("[Dispatch] ERROR: One or more backend file paths exceed the Windows 260-character limit.")
    print("[Dispatch] Processing has been paused/stopped before encoding to avoid tool failures.")
    print("[Dispatch] The full filename + folder path is too long for Windows tools.")
    print("[Dispatch] Please rename your input filenames to be shorter and/or move the")
    print("[Dispatch] Auto-Boost-Av1an-portable folder to a lower drive path, then run this again.")
    print("-" * 80)
    for path in long_paths:
        print(f"[Dispatch] {len(path)} characters: {path}")
    print("=" * 80)
    try:
        input("Press Enter to exit...")
    except EOFError:
        pass
    sys.exit(1)


def warn_and_pause_if_paths_too_long(input_files, video_output_dir, temp_dir):
    long_paths = []
    for input_path in input_files:
        filename = os.path.basename(input_path)
        basename = os.path.splitext(filename)[0]
        video_input_dir = os.path.dirname(input_path)
        backend_artifact_dir = os.path.join(video_input_dir, basename)
        paths_to_check = [
            input_path,
            os.path.join(video_output_dir, basename + "-output.mkv"),
            os.path.join(temp_dir, f"{basename}.vpy"),
            os.path.join(temp_dir, f"{basename}.ffindex"),
            os.path.join(temp_dir, f"{basename}_scenedetect.json"),
            os.path.join(temp_dir, f"{basename}-output.mkv"),
            os.path.join(video_input_dir, f"{basename}-av1.mkv"),
            backend_artifact_dir,
            os.path.join(backend_artifact_dir, f"{basename}.vpy"),
            os.path.join(backend_artifact_dir, f"{basename}.ffindex"),
            os.path.join(backend_artifact_dir, f"{basename}-av1.mkv"),
        ]
        for path in paths_to_check:
            display_path = display_path_for_length(path)
            if len(display_path) > WINDOWS_MAX_PATH:
                long_paths.append(display_path)

    if long_paths:
        seen = set()
        unique_long_paths = []
        for path in long_paths:
            if path not in seen:
                seen.add(path)
                unique_long_paths.append(path)
        pause_for_long_paths(unique_long_paths)


# --- Python-safe source filename normalization ---
# Every source video is renamed before anything else runs so that its filename
# contains ONLY "." , a-z, A-Z and 0-9. Characters outside that set are folded
# to their closest plain-ASCII equivalent first (o-with-macron -> o, sharp s ->
# ss, ae-ligature -> ae, Cyrillic and Greek letters transliterated) and are
# dropped when no equivalent exists (CJK, emoji, punctuation, brackets, spaces).
# Doing this up front means ffmpeg, ffms2/VapourSynth, x264, av1an,
# SvtAv1EncApp, MediaInfo and mkvmerge only ever see a plain ASCII path.
FILENAME_ALLOWED_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "."
)

# What replaces spaces and every other kind of whitespace. "" deletes them,
# which is the strictest and safest choice because no downstream command line
# then needs quoting. Set this to "." instead if you would rather keep the word
# boundaries readable in the renamed files.
FILENAME_SPACE_REPLACEMENT = ""

# Used when sanitizing leaves nothing behind (for example a fully CJK name).
FILENAME_FALLBACK_STEM = "video"

# Case-sensitive folds that must not go through the lowercase table below.
_FILENAME_ASCII_FOLD_EXACT = {
    "\u1e9e": "SS",   # capital sharp s
    "\u0130": "I",    # capital I with dot above
    "\u0131": "i",    # dotless i
    "\u00b5": "u",    # micro sign (not the Greek letter mu)
}

# Lowercase-keyed folds for characters that Unicode decomposition alone cannot
# reduce to ASCII. Capital letters reuse these entries and get re-capitalized.
_FILENAME_ASCII_FOLD = {
    # Latin
    "\u00df": "ss", "\u00e6": "ae", "\u0153": "oe", "\u00f8": "o",
    "\u0111": "d", "\u00f0": "d", "\u00fe": "th", "\u0142": "l",
    "\u0127": "h", "\u014b": "ng", "\u0167": "t", "\u0138": "k",
    "\u2116": "No",
    # Cyrillic
    "\u0430": "a", "\u0431": "b", "\u0432": "v", "\u0433": "g", "\u0434": "d",
    "\u0435": "e", "\u0451": "e", "\u0436": "zh", "\u0437": "z", "\u0438": "i",
    "\u0439": "y", "\u043a": "k", "\u043b": "l", "\u043c": "m", "\u043d": "n",
    "\u043e": "o", "\u043f": "p", "\u0440": "r", "\u0441": "s", "\u0442": "t",
    "\u0443": "u", "\u0444": "f", "\u0445": "kh", "\u0446": "ts", "\u0447": "ch",
    "\u0448": "sh", "\u0449": "shch", "\u044a": "", "\u044b": "y", "\u044c": "",
    "\u044d": "e", "\u044e": "yu", "\u044f": "ya",
    "\u0454": "ye", "\u0456": "i", "\u0457": "yi", "\u0491": "g", "\u045e": "u",
    # Greek
    "\u03b1": "a", "\u03b2": "v", "\u03b3": "g", "\u03b4": "d", "\u03b5": "e",
    "\u03b6": "z", "\u03b7": "i", "\u03b8": "th", "\u03b9": "i", "\u03ba": "k",
    "\u03bb": "l", "\u03bc": "m", "\u03bd": "n", "\u03be": "x", "\u03bf": "o",
    "\u03c0": "p", "\u03c1": "r", "\u03c2": "s", "\u03c3": "s", "\u03c4": "t",
    "\u03c5": "y", "\u03c6": "f", "\u03c7": "ch", "\u03c8": "ps", "\u03c9": "o",
}

_FILENAME_LATIN_LETTER_RE = re.compile(r"^LATIN (SMALL|CAPITAL) LETTER ([A-Z])\b")


def fold_char_to_ascii(ch):
    """Return the closest plain-ASCII spelling of one character, or "" if none."""
    if ch in _FILENAME_ASCII_FOLD_EXACT:
        return _FILENAME_ASCII_FOLD_EXACT[ch]

    lowered = ch.lower()
    if lowered in _FILENAME_ASCII_FOLD:
        folded = _FILENAME_ASCII_FOLD[lowered]
        if folded and ch != lowered:
            # Preserve the original capitalization: sharp-sh -> "Sh", not "SH".
            folded = folded[0].upper() + folded[1:]
        return folded

    # Strip diacritics: o-with-macron decomposes to "o" + a combining macron.
    kept = "".join(
        c for c in unicodedata.normalize("NFKD", ch)
        if c in FILENAME_ALLOWED_CHARS and not unicodedata.combining(c)
    )
    if kept:
        return kept

    # Accented Cyrillic/Greek letters decompose to a base letter that is still
    # non-ASCII, so fold that base letter through the tables above.
    base = unicodedata.normalize("NFKD", ch)[:1]
    if base and base != ch:
        return fold_char_to_ascii(base)

    # Last resort: read the base letter out of the Unicode character name,
    # e.g. "LATIN SMALL LETTER O WITH STROKE" -> "o".
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return ""
    match = _FILENAME_LATIN_LETTER_RE.match(name)
    if not match:
        return ""
    return match.group(2).lower() if match.group(1) == "SMALL" else match.group(2)


def sanitize_filename_stem(stem):
    """Reduce a filename stem to "." , a-z, A-Z and 0-9 only."""
    pieces = []
    for ch in stem:
        if ch in FILENAME_ALLOWED_CHARS:
            pieces.append(ch)
        elif ch.isspace():
            pieces.append(FILENAME_SPACE_REPLACEMENT)
        else:
            pieces.append(fold_char_to_ascii(ch))
    safe = "".join(pieces)
    # A leading dot hides the file, Windows silently drops a trailing dot, and
    # runs of dots confuse extension parsing - normalize all three.
    safe = re.sub(r"\.{2,}", ".", safe).strip(".")
    return safe or FILENAME_FALLBACK_STEM


def sanitize_filename_extension(ext):
    """Return a lowercase extension built only from a-z and 0-9."""
    body = "".join(c for c in ext.lower() if c in FILENAME_ALLOWED_CHARS and c != ".")
    return f".{body}" if body else ""


def safe_input_filename(filename):
    """Full Python-safe filename for a source video."""
    stem, ext = os.path.splitext(filename)
    safe_ext = sanitize_filename_extension(ext) or ext.lower()
    return f"{sanitize_filename_stem(stem)}{safe_ext}"


def _blocked_by_other_file(dst_path, src_path):
    """True when dst_path already exists as a *different* file than src_path.

    A case-only rename ("Movie.MKV" -> "Movie.mkv") makes os.path.exists()
    report True on Windows even though it is the same file, and renaming a file
    onto itself is exactly what we want in that case.
    """
    if not os.path.exists(dst_path):
        return False
    try:
        return not os.path.samefile(dst_path, src_path)
    except OSError:
        return True


def sanitize_input_filenames(video_input_dir, extensions):
    """Rename every source video so its name holds only "." , a-z, A-Z and 0-9.

    This is the first step that touches the input files - it runs before scene
    detection, encoding, tagging and muxing - so no downstream tool ever has to
    cope with a non-ASCII path. "Dead End no Boken.mkv" (with a macron on the o)
    becomes "DeadEndnoBoken.mkv".
    """
    supported_exts = {pattern[1:].lower() for pattern in extensions if pattern.startswith("*")}
    renamed = 0
    try:
        entries = sorted(os.listdir(video_input_dir))
    except OSError as e:
        print(f"{RED}[Dispatch] ERROR: could not list {video_input_dir}: {e}{RESET}")
        return 0

    for filename in entries:
        src_path = os.path.join(video_input_dir, filename)
        if not os.path.isfile(src_path):
            continue
        ext = os.path.splitext(filename)[1]
        if ext.lower() not in supported_exts:
            continue

        safe_name = safe_input_filename(filename)
        if safe_name == filename:
            continue

        safe_stem, safe_ext = os.path.splitext(safe_name)
        dst_path = os.path.join(video_input_dir, safe_name)
        suffix = 1
        while _blocked_by_other_file(dst_path, src_path):
            dst_path = os.path.join(video_input_dir, f"{safe_stem}{suffix}{safe_ext}")
            suffix += 1

        try:
            os.rename(src_path, dst_path)
        except OSError as e:
            print(f"{RED}[Dispatch] ERROR: could not rename {filename} -> "
                  f"{os.path.basename(dst_path)}: {e}{RESET}")
            print(f"{RED}[Dispatch]        Close anything using that file, or rename it by hand "
                  f"so it only contains '.', a-z and 0-9, then run this again.{RESET}")
            continue

        renamed += 1
        print(f"{BLUE}[Dispatch] Renamed source file to a fully safe name: {filename} -> "
              f"{os.path.basename(dst_path)}{RESET}")

    return renamed



def gather_input_files(video_input_dir, extensions):
    input_files = []
    for ext in extensions:
        input_files.extend(sorted(glob.glob(os.path.join(video_input_dir, ext))))
    return input_files


def scan_for_new_input_files(video_input_dir, extensions, known_input_files):
    """Rescan video-input between encodes and queue files added after startup."""
    sanitize_input_filenames(video_input_dir, extensions)
    current_files = gather_input_files(video_input_dir, extensions)
    new_files = [path for path in current_files if path not in known_input_files]
    if new_files:
        print(f"{BLUE}[Dispatch] New input file(s) detected in video-input; adding to queue:{RESET}")
        for path in new_files:
            print(f"{BLUE}{os.path.basename(path)}{RESET}")
        known_input_files.update(new_files)
    return new_files

def load_script_settings(settings_path):
    """Read settings.txt once into a case-insensitive key/value dict."""
    if not os.path.exists(settings_path):
        return {}
    try:
        with open(settings_path, "r", encoding="utf-8", errors="replace") as f:
            return parse_settings_lines(f.read().splitlines())
    except Exception:
        return {}


def get_script_setting(settings, key_name, default_value):
    """Return a setting from a dict loaded by load_script_settings()."""
    return settings.get(key_name.lower(), default_value)


def setting_is_true(settings, key_name, default_value="False"):
    return get_script_setting(settings, key_name, default_value).strip().lower() in ("1", "true", "yes", "y", "on")


def read_crop_int(value, key_name):
    try:
        crop_value = int(value)
    except (TypeError, ValueError):
        print(f"[Dispatch] Warning: Invalid manual crop {key_name}={value!r}; using 0.")
        return 0
    if crop_value < 0:
        print(f"[Dispatch] Warning: Invalid manual crop {key_name}={crop_value}; using 0.")
        return 0
    if crop_value % 2 != 0:
        adjusted = crop_value - 1
        print(f"[Dispatch] Warning: Manual crop {key_name}={crop_value} is not mod2; using {adjusted}.")
        return adjusted
    return crop_value


def report_crop_status(mode, top, bottom, left, right):
    normalized_mode = (mode or "off").lower()
    active = any((top, bottom, left, right))
    if normalized_mode == "off":
        print(f"{BLUE}[Dispatch] Crop: off{RESET}")
    elif active:
        print(f"{BLUE}[Dispatch] Crop: {normalized_mode} active (top={top}, bottom={bottom}, left={left}, right={right}){RESET}")
    else:
        print(f"{BLUE}[Dispatch] Crop: {normalized_mode} selected, no crop values active{RESET}")


def report_filter_status(do_downscale, target_res, kernel, do_denoise, denoise_setting, do_deband, deband_setting):
    active_filters = []
    if do_downscale:
        active_filters.append(f"downscale: target_resolution={target_res}, kernel_type={kernel}")
    if do_denoise:
        active_filters.append(f"denoise: denoise_setting={denoise_setting or 'enabled'}")
    if do_deband:
        active_filters.append(f"deband: deband_setting={deband_setting or 'enabled'}")

    if not active_filters:
        print(f"{BLUE}[Dispatch] Filters active:{RESET} none")
        return

    for filter_status in active_filters:
        print(f"{BLUE}[Dispatch] Filter active:{RESET} {filter_status}")


def parse_crop_values_from_vpy(vpy_path):
    if not os.path.exists(vpy_path):
        return None
    try:
        with open(vpy_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return None
    match = re.search(r"std\.Crop\(([^)]*)\)", text)
    if not match:
        return 0, 0, 0, 0
    values = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    for key, value in re.findall(r"(top|bottom|left|right)\s*=\s*(-?\d+)", match.group(1)):
        values[key] = int(value)
    return values["top"], values["bottom"], values["left"], values["right"]


def detect_crop_values(source_path, tools_dir):
    """Use tools/cropdetect.py to detect crop values, matching Auto-Boost-Av1an.py behavior."""
    cropdetect_script = os.path.join(tools_dir, "cropdetect.py")
    print("[Dispatch] Detecting crop values via cropdetect.py...")
    print(f"[Dispatch] Source: {os.path.basename(source_path)}")
    if not os.path.exists(cropdetect_script):
        print(f"[Dispatch] Warning: cropdetect.py not found at {cropdetect_script}. Proceeding with 0 crop.")
        return 0, 0, 0, 0

    csv_output = os.path.join(os.path.dirname(source_path), f"{Path(source_path).stem}_crop.csv")

    def run_crop_process(aggressive_mode):
        cmd = [sys.executable, cropdetect_script, source_path, "--out", csv_output, "--samples", "3", "--progress-mode"]
        mode_label = "Aggressive" if aggressive_mode else "Standard"
        if aggressive_mode:
            cmd.append("--aggressive")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if line.startswith("PROGRESS:"):
                    print(f"[Dispatch] Cropdetect ({mode_label}): {line.split(':', 1)[1]}%", end="\r")
                elif line:
                    print(f"[Dispatch] Cropdetect ({mode_label}): {line}")
            print(" " * 80, end="\r")
            return proc.wait() == 0
        except Exception as e:
            print(f"[Dispatch] Warning: Error during crop detection: {e}")
            return False

    def parse_csv_result():
        if not os.path.exists(csv_output):
            print("[Dispatch] Warning: Crop CSV not found after execution.")
            return 0, 0, 0, 0, ""
        import csv
        try:
            with open(csv_output, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            if not rows:
                return 0, 0, 0, 0, ""
            row = rows[0]
            orig_w = int(row.get("width", "0"))
            orig_h = int(row["height"])
            c_w = int(row.get("crop_w", orig_w))
            c_h = int(row["crop_h"])
            c_x = int(row.get("crop_x", "0"))
            c_y = int(row["crop_y"])
            top = c_y
            bottom = orig_h - (c_y + c_h)
            left = c_x
            right = orig_w - (c_x + c_w) if orig_w else 0
            top, bottom, left, right = [v - 1 if v % 2 else v for v in (top, bottom, left, right)]
            return top, bottom, left, right, row.get("crop", "")
        except Exception as e:
            print(f"[Dispatch] Warning: Failed to parse crop CSV: {e}")
            return 0, 0, 0, 0, ""

    if not run_crop_process(aggressive_mode=False):
        return 0, 0, 0, 0
    top, bottom, left, right, crop_str = parse_csv_result()
    if top == 0 and bottom == 0 and left == 0 and right == 0:
        print("[Dispatch] No crop found. Retrying with --aggressive mode...")
        if run_crop_process(aggressive_mode=True):
            top, bottom, left, right, crop_str = parse_csv_result()
    if any((top, bottom, left, right)):
        print(f"[Dispatch] Crop Found: Top={top}, Bottom={bottom}, Left={left}, Right={right} (Based on {crop_str})")
    else:
        print("[Dispatch] No crop detected (0 on all sides).")
    return top, bottom, left, right


def build_vapoursynth_script(source_path, temp_dir, tools_dir, settings, autocrop, convert_yuv420p10=False, tonemap=False):
    """Build the per-input .vpy script used as av1an input."""
    basename = Path(source_path).stem
    vpy_file = os.path.join(temp_dir, f"{basename}.vpy")
    cache_file = os.path.join(temp_dir, f"{basename}.ffindex")

    s_crop_mode = get_script_setting(settings, "crop", "auto")
    s_crop_top = get_script_setting(settings, "top", "0")
    s_crop_bottom = get_script_setting(settings, "bottom", "0")
    s_crop_left = get_script_setting(settings, "left", "0")
    s_crop_right = get_script_setting(settings, "right", "0")
    do_downscale = setting_is_true(settings, "downscale", "False")
    target_res = get_script_setting(settings, "target_resolution", "1920x1080")
    kernel = get_script_setting(settings, "kernel_type", "Hermite")
    do_denoise = setting_is_true(settings, "denoise", "False")
    denoise_setting = get_script_setting(settings, "denoise_setting", "")
    do_deband = setting_is_true(settings, "deband", "False")
    deband_setting = get_script_setting(settings, "deband_setting", "")

    requested_crop_mode = s_crop_mode.strip().lower()
    if not autocrop:
        crop_mode = "off"
    elif requested_crop_mode in ("auto", "manual", "off"):
        crop_mode = requested_crop_mode
    else:
        print(f"[Dispatch] Warning: Unknown crop mode {s_crop_mode!r}; using auto.")
        crop_mode = "auto"

    rebuild_vpy = not os.path.exists(vpy_file)
    if not rebuild_vpy:
        try:
            with open(vpy_file, "r", encoding="utf-8", errors="replace") as f:
                existing_vpy_text = f.read()
            if r'\"' in existing_vpy_text:
                print(f"[Dispatch] Existing VapourSynth script has legacy escaped quotes; rebuilding: {vpy_file}")
                rebuild_vpy = True
            elif ("do_tonemap = True" in existing_vpy_text) != bool(tonemap):
                print(f"[Dispatch] Existing VapourSynth script tonemap state differs; rebuilding: {vpy_file}")
                rebuild_vpy = True
        except Exception as e:
            print(f"[Dispatch] Warning: Could not inspect existing VapourSynth script ({e}); rebuilding: {vpy_file}")
            rebuild_vpy = True

    if rebuild_vpy:
        crop_top = crop_bottom = crop_left = crop_right = 0
        if crop_mode == "auto":
            crop_top, crop_bottom, crop_left, crop_right = detect_crop_values(source_path, tools_dir)
        elif crop_mode == "manual":
            crop_top = read_crop_int(s_crop_top, "top")
            crop_bottom = read_crop_int(s_crop_bottom, "bottom")
            crop_left = read_crop_int(s_crop_left, "left")
            crop_right = read_crop_int(s_crop_right, "right")
        report_crop_status(crop_mode, crop_top, crop_bottom, crop_left, crop_right)
        report_filter_status(do_downscale, target_res, kernel, do_denoise, denoise_setting, do_deband, deband_setting)

        denoise_line = denoise_setting if do_denoise and denoise_setting else ""
        deband_line = deband_setting if do_deband and deband_setting else ""

        vpy_template = """
from vstools import vs, core, initialize_clip, finalize_clip
try:
    from vsdenoise import DFTTest
except Exception:
    DFTTest = None
core.max_cache_size = 1024

# Load Source
src = core.ffms2.Source(source=r"{source}", cachefile=r"{cache}")

# Conversion
if {convert}:
    src = src.resize.Bicubic(format=vs.YUV420P10)

# Initialize (Fixes Placebo bitdepth error by ensuring 16-bit)
src = initialize_clip(src)

# Tonemap HDR -> SDR (libplacebo; libvs_placebo.dll autoloads from the plugins directory)
do_tonemap = {tonemap}
if do_tonemap:
    src = core.fmtc.bitdepth(src, bits=16)
    src = core.placebo.Tonemap(src, src_csp=1, dst_csp=0, dynamic_peak_detection=1, gamut_mapping=1, tone_mapping_function=1, metadata=0, contrast_recovery=0.0, smoothing_period=20.0, percentile=100.0)
    # Tonemap returns RGB or 4:4:4 output; SVT-AV1 only supports 4:2:0, so convert
    # back to YUV420P16 here. finalize_clip then produces the same 10-bit
    # YUV420P10 output as the non-tonemap pipeline.
    if src.format.color_family == vs.RGB:
        src = src.resize.Bicubic(format=vs.YUV420P16, matrix_s="709")
    elif src.format.id != vs.YUV420P16:
        src = src.resize.Bicubic(format=vs.YUV420P16)
    src = src.std.SetFrameProps(_Matrix=1, _Transfer=1, _Primaries=1)

# Optional settings.txt denoise/deband hooks
{denoise_line}
{deband_line}

# 1. CROP
if {ct} > 0 or {cb} > 0 or {cl} > 0 or {cr} > 0:
    src = src.std.Crop(top={ct}, bottom={cb}, left={cl}, right={cr})

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
            target_h = int(target_w * src.height / src.width)
            if target_h % 2 != 0:
                target_h -= 1
        if target_w % 2 != 0:
            target_w -= 1
        if target_w < src.width or target_h < src.height:
            src = core.placebo.Resample(src, target_w, target_h, filter=pl_filter)

# Finalize (Sets 10-bit output)
final = finalize_clip(src)
final.set_output(0)
"""
        with open(vpy_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(vpy_template.format(
                source=source_path,
                cache=cache_file,
                ct=crop_top,
                cb=crop_bottom,
                cl=crop_left,
                cr=crop_right,
                downscale=str(do_downscale),
                target_res=target_res,
                kernel=kernel,
                convert=str(convert_yuv420p10),
                tonemap=str(bool(tonemap)),
                denoise_line=denoise_line,
                deband_line=deband_line,
            ))
        if tonemap:
            print(f"{BLUE}[Dispatch] Filter active:{RESET} tonemap HDR -> SDR (BT.709) via libplacebo")
        print(f"[Dispatch] Built VapourSynth script: {vpy_file}")
    else:
        existing_crop_values = parse_crop_values_from_vpy(vpy_file) or (0, 0, 0, 0)
        report_crop_status(crop_mode, *existing_crop_values)
        report_filter_status(do_downscale, target_res, kernel, do_denoise, denoise_setting, do_deband, deband_setting)
        print(f"[Dispatch] Reusing existing VapourSynth script: {vpy_file}")

    return vpy_file


def resolve_fgs_table_path(param_str, root_dir, tools_dir=None):
    """Rewrite any relative '--fgs-table <path>' in an encoder params string
    to an absolute path so av1an worker processes (which run in their own
    working directories) can find the table file.

    Relative paths are resolved against the portable package root first,
    then the tools directory, then the current working directory. The
    resolved path uses forward slashes (accepted by Windows and safe for
    av1an's shell-style splitting of --video-params) and is double-quoted
    only when it contains whitespace.
    """
    if not param_str or "--fgs-table" not in param_str:
        return param_str

    pattern = re.compile(r'(--fgs-table[ \t]+)("([^"]*)"|\'([^\']*)\'|(\S+))')

    def _repl(match):
        raw = match.group(3) or match.group(4) or match.group(5) or ""
        if not raw:
            return match.group(0)
        if os.path.isabs(raw):
            resolved = os.path.abspath(raw)
        else:
            candidates = [os.path.join(root_dir, raw)]
            if tools_dir:
                candidates.append(os.path.join(tools_dir, raw))
            candidates.append(os.path.abspath(raw))
            resolved = next((c for c in candidates if os.path.isfile(c)), candidates[0])
            resolved = os.path.abspath(resolved)
        if not os.path.isfile(resolved):
            print(f"{RED}[Dispatch] WARNING: film grain table not found: {resolved}{RESET}")
            print(f"{RED}[Dispatch]          Place '{raw}' in the package root next to the .bat file.{RESET}")
        resolved = resolved.replace("\\", "/")
        if any(ch.isspace() for ch in resolved):
            resolved = f'"{resolved}"'
        print(f"[Dispatch] Resolved film grain table path: {resolved}")
        return match.group(1) + resolved

    return pattern.sub(_repl, param_str)


def main():
    # --- Configuration ---
    script_path = os.path.abspath(__file__)
    tools_dir = os.path.dirname(script_path)
    root_dir = os.path.dirname(tools_dir)

    # Read (and if hand-edited/mis-encoded, repair) the shared worker-count
    # config up front, so every later consumer sees a clean file and value.
    cfg_workers = read_and_repair_workercount_config(tools_dir)
    
    video_input_dir = os.path.join(root_dir, "video-input")
    video_output_dir = os.path.join(root_dir, "video-output")
    temp_dir = os.path.join(root_dir, "temp")
    
    # Scripts & Tools
    av1an_exe = os.path.join(tools_dir, "av1an", "av1an.exe")
    scene_detect_script = os.path.join(tools_dir, "Progressive-Scene-Detection.py")
    mediainfo_exe = os.path.join(tools_dir, "MediaInfo_CLI", "MediaInfo.exe")
    
    # UPDATED: Use the specific av1an- versions of tag and mux
    tag_script = os.path.join(tools_dir, "av1an-tag.py")
    mux_script = os.path.join(tools_dir, "av1an-mux.py")
    
    # --- Ensure Directories Exist ---
    if not os.path.exists(video_input_dir):
        os.makedirs(video_input_dir)
        print(f"[Dispatch] Created missing input directory: {video_input_dir}")
        sys.exit(0)
    if not os.path.exists(video_output_dir):
        os.makedirs(video_output_dir)
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    # --- Rename Source Files To Python-Safe Names (must be the first step) ---
    # Do this before argument parsing, scene detection or anything else touches
    # the files, so every later stage only ever sees ".", a-z, A-Z and 0-9.
    extensions = ("*.mkv", "*.mp4", "*.m2ts")
    sanitize_input_filenames(video_input_dir, extensions)
        
    # --- Argument Parsing ---
    args = sys.argv[1:]
    
    crf = "30"
    workers = "1"
    photon_noise = "0"
    final_speed = "4"
    final_params = ""
    resume = False
    selected_fork = "essential"
    avx512 = False
    denoise_setting = None
    autocrop = False
    convert_yuv420p10 = False
    tonemap_enabled = False
    # --verbose (verbose mode) shows everything the way it used to be shown.
    # Without it (default mode), the noisy phases are drawn as simple progress
    # bars with explanations. --no-verbose is the .bat's VERBOSE= placeholder.
    verbose_mode = False
    
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--tonemap":
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                tonemap_enabled = parse_bool_setting(args[i + 1])
                i += 2
            else:
                tonemap_enabled = True
                i += 1
        elif arg == "--fork" and i + 1 < len(args):
            selected_fork = args[i+1]
            i += 2
        elif arg == "--avx512":
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                avx512 = parse_bool_setting(args[i + 1])
                i += 2
            else:
                avx512 = True
                i += 1
        elif arg == "--denoise" and i + 1 < len(args):
            val = args[i+1].strip().lower()
            denoise_setting = "True" if val in ("1", "true", "yes", "y", "on") else "False"
            i += 2
        elif arg == "--autocrop":
            autocrop = True
            i += 1
        elif arg == "--convert-to-YUV420P10":
            convert_yuv420p10 = True
            i += 1
        elif arg in ("--crf", "--quality") and i + 1 < len(args):
            crf = args[i+1]
            i += 2
        elif arg == "--workers" and i + 1 < len(args):
            workers = args[i+1]
            i += 2
        elif arg == "--photon-noise" and i + 1 < len(args):
            photon_noise = args[i+1]
            i += 2
        elif arg == "--final-speed" and i + 1 < len(args):
            final_speed = args[i+1]
            i += 2
        elif arg == "--final-params" and i + 1 < len(args):
            # This captures the 'av1an_settings' string passed from batch
            final_params = args[i+1]
            i += 2
        elif arg == "--resume":
            resume = True
            i += 1
        elif arg == "--verbose":
            verbose_mode = True
            i += 1
        elif arg == "--no-verbose":
            i += 1
        else:
            i += 1

    simple_mode = RICH_AVAILABLE and not verbose_mode
    if not RICH_AVAILABLE and not verbose_mode:
        print("[Dispatch] rich is unavailable; falling back to verbose output.")

    # Rewrite relative --fgs-table paths in the encoder params to absolute
    # paths anchored at the package root, so SvtAv1EncApp can open the table
    # regardless of the working directory av1an spawns its workers in.
    final_params = resolve_fgs_table_path(final_params, root_dir, tools_dir)

    # --- Optimized worker override from the generating .bat (optional) ---
    # Written by the one-time benchmark (workercount.py --optimize-bat).
    # When absent, everything proceeds exactly as before.
    bat_opt = read_bat_optimize_settings(tools_dir, root_dir)
    if bat_opt.get("optimize-workers", "").strip().lower() in ("true", "1", "yes", "on"):
        custom_enc = bat_opt.get("custom-av1an-workers", "").strip()
        if custom_enc.isdigit() and int(custom_enc) > 0:
            workers = custom_enc
            print(f"{BLUE}[Dispatch] Using optimized av1an worker count from bat: {workers}{RESET}")

    # --- Worker Safety Check ---
    # The workers value can arrive mangled if a hand-edited (UTF-16/BOM)
    # config file was read by the .bat - recover the number or substitute
    # the repaired config value so av1an's -w always gets a clean integer.
    raw_workers = workers
    workers = sanitize_worker_value(
        raw_workers, str(cfg_workers) if cfg_workers else "1")
    if workers != str(raw_workers).strip():
        print(f"\033[93m[Dispatch] --workers value {raw_workers!r} was "
              f"invalid - using {workers} instead\033[0m")
    # If tools\workercount-config.txt says workers=1 (e.g. the benchmark
    # failed and wrote the safe fallback), do NOT pass --lp 3 to the encoder:
    # with a single av1an worker, --lp 3 would cap SVT-AV1's threading and
    # leave most of the CPU idle. Same rule when the effective worker count
    # being passed to av1an is 1.
    try:
        _effective_workers = int(workers)
    except (TypeError, ValueError):
        _effective_workers = None
    if (cfg_workers == 1 or _effective_workers == 1) \
            and "--lp 3" in final_params:
        final_params = " ".join(final_params.replace("--lp 3", "").split())
        print("\033[93m[Dispatch] 1 worker detected, setting --lp mode to "
              "default auto parallelism\033[0m")

    settings_path = os.path.join(root_dir, "settings.txt")
    settings = None
    if denoise_setting is not None:
        try:
            settings = set_settings_value(settings_path, "denoise", denoise_setting)
            print(f"[Dispatch] Set settings.txt denoise={denoise_setting}")
        except Exception as e:
            print(f"[Dispatch] Warning: Failed to update settings.txt denoise: {e}")
    if settings is None:
        settings = load_script_settings(settings_path)
    ntfy_settings = settings

    setup_svt_av1_fork(tools_dir, selected_fork, avx512=avx512, verbose=verbose_mode)
            
    # --- Gather Input Files ---
    input_files = gather_input_files(video_input_dir, extensions)
    known_input_files = set(input_files)
    
    if not input_files:
        print(f"[Dispatch] No video files found in {video_input_dir}")
        sys.exit(0)

    warn_and_pause_if_paths_too_long(input_files, video_output_dir, temp_dir)
        
    if not simple_mode:
        print(f"[Dispatch] Found {len(input_files)} files to process.")

    # --- Main Processing Loop ---
    timing_reports = []
    batch_started_at = time.monotonic()
    input_index = 0
    while input_index < len(input_files):
        input_abspath_origin = input_files[input_index]
        input_index += 1
        filename = os.path.basename(input_abspath_origin)
        basename = os.path.splitext(filename)[0]
        
        final_output_path = os.path.join(video_output_dir, basename + "-output.mkv")
        
        print("\n" + "="*80)
        print(f"Processing: {filename}")
        print("="*80)
        
        if os.path.exists(final_output_path):
            print(f"[Dispatch] Output file already exists: {final_output_path}")
            continue

        try:
            # Note: We are NO LONGER moving the file to temp. 
            # We read directly from input_abspath_origin.
            
            # 1. Scene Detection
            # We run this in temp_dir so the JSON appears there
            json_file = f"{basename}_scenedetect.json"
            json_abspath = os.path.join(temp_dir, json_file)
            
            if os.path.exists(json_abspath):
                print(f"[Dispatch] Skipping scene detection (JSON exists).")
            else:
                print("[Dispatch] Running Scene Detection...")
                cmd_scene = [
                    sys.executable,
                    scene_detect_script,
                    "-i", input_abspath_origin,
                    "-o", json_file 
                ]
                try:
                    if simple_mode:
                        scene_rc = run_scene_detection_simple(
                            cmd_scene, cwd=temp_dir, env=scene_detection_env())
                        if scene_rc != 0:
                            raise subprocess.CalledProcessError(scene_rc, cmd_scene)
                    else:
                        subprocess.check_call(cmd_scene, cwd=temp_dir, env=scene_detection_env())
                except subprocess.CalledProcessError:
                    print("[Dispatch] Scene detection failed. Proceeding anyway.")

            # 2. Color Space Detection / HDR handling
            color_metadata = detect_color_metadata(input_abspath_origin, mediainfo_exe)
            is_bt709 = bool(color_metadata and color_metadata["is_bt709"])
            is_bt601 = bool(color_metadata and color_metadata["is_bt601"])
            is_hdr_source = bool(color_metadata and color_metadata["is_hdr"])
            tonemap_this_file = tonemap_enabled and is_hdr_source

            bt709_flags = " --color-primaries 1 --transfer-characteristics 1 --matrix-coefficients 1"
            bt601_flags = " --color-primaries 6 --transfer-characteristics 6 --matrix-coefficients 6"
            current_color_flags = ""
            if tonemap_this_file:
                # Tonemapped output is SDR BT.709.
                current_color_flags = bt709_flags
                print(f"{BLUE}[Dispatch] HDR source detected; tonemapping HDR to SDR (BT.709) via libplacebo.{RESET}")
            elif is_hdr_source and is_hdr_fork(selected_fork):
                # Auto detect: build SVT-AV1-HDR color settings from MediaInfo.
                hdr_flags = build_hdr_color_flags(color_metadata)
                if hdr_flags:
                    current_color_flags = hdr_flags
                    print(f"{BLUE}[Dispatch] HDR source detected; auto-applying SVT-AV1-HDR color settings:{RESET}")
                    print(f"{BLUE}[Dispatch]  {hdr_flags.strip()}{RESET}")
                else:
                    pause_for_hdr_color_settings(input_abspath_origin, color_metadata)
            elif is_hdr_source:
                print(f"{BLUE}[Dispatch] HDR source detected. This fork encodes it as-is (set tonemap=True in the .bat to tonemap to SDR).{RESET}")
            elif is_bt709:
                current_color_flags = bt709_flags
                if simple_mode:
                    pass
                elif is_hdr_fork(selected_fork):
                    print("[Dispatch] MediaInfo confirmed full BT.709 source; copying BT.709 color settings for SVT-AV1-HDR fork.")
                else:
                    print("[Dispatch] MediaInfo confirmed full BT.709 source.")
            elif is_bt601:
                current_color_flags = bt601_flags
                if not simple_mode:
                    print("[Dispatch] MediaInfo confirmed full BT.601 source.")

            # 3. Build VapourSynth input script from settings.txt
            vpy_abspath = build_vapoursynth_script(
                input_abspath_origin,
                temp_dir,
                tools_dir,
                settings,
                autocrop=autocrop,
                convert_yuv420p10=convert_yuv420p10,
                tonemap=tonemap_this_file,
            )

            # 3. Encoding (Direct Av1an Call)
            av1_output = f"{basename}-av1.mkv"
            
            # Construct Encoder Parameters (-v)
            # Combine CRF, preset, and the batch settings
            encoder_params = f"--crf {crf} --preset {final_speed} {final_params}"
            if current_color_flags:
                encoder_params += current_color_flags
            
            # Clean up double spaces if any
            encoder_params = " ".join(encoder_params.split())

            # We run Av1an in video_input_dir, so artifacts appear there (and we can resume if needed).
            # We pass json_abspath because the json is in temp.
            cmd_av1an = [
                av1an_exe,
                "-i", vpy_abspath,
                "-e", "svt-av1",
                "--no-defaults",
                "--photon-noise", photon_noise,
                "-w", workers,
                "-s", json_abspath,
                "-o", av1_output,
                "-v", encoder_params,
                "--keep"
            ]
            
            if resume:
                cmd_av1an.append("--resume")
                
            if not simple_mode:
                print(f"[Dispatch] Starting Av1an Encoding...")
            print(f"svt-av1 fork: {svt_fork_display_name(selected_fork)}")
            av1an_started_at = time.monotonic()
            
            try:
                with keep.running():
                    # Run in video_input_dir so temp folders created by av1an stay with source until done
                    if simple_mode:
                        enc_rc = run_av1an_simple(
                            cmd_av1an,
                            cwd=video_input_dir,
                            description="Encoding",
                            explanation=SIMPLE_EXPLANATION_ENCODING,
                            temp_search_dir=video_input_dir,
                        )
                        if enc_rc != 0:
                            raise subprocess.CalledProcessError(enc_rc, cmd_av1an)
                    else:
                        subprocess.check_call(cmd_av1an, cwd=video_input_dir)
            except subprocess.CalledProcessError:
                print("[Dispatch] Encoding failed.")
                send_ntfy_notification(
                    ntfy_settings,
                    root_dir,
                    tools_dir,
                    "Auto-Boost encode failed",
                    "An encode failed.",
                )
                continue

            av1an_elapsed = time.monotonic() - av1an_started_at

            # 3. Move Av1an Artifacts from video-input to Temp
            # Artifacts are: {basename}-av1.mkv and {basename} (folder)
            av1_file_src = os.path.join(video_input_dir, f"{basename}-av1.mkv")
            av1_folder_src = os.path.join(video_input_dir, basename)
            
            av1_file_dst = os.path.join(temp_dir, f"{basename}-av1.mkv")
            av1_folder_dst = os.path.join(temp_dir, basename)
            
            if not simple_mode:
                print("[Dispatch] Moving encoding artifacts to temp folder...")
            
            # Move the folder
            if os.path.exists(av1_folder_src):
                if os.path.exists(av1_folder_dst):
                    try:
                        shutil.rmtree(av1_folder_dst)
                    except Exception as e:
                        print(f"[Dispatch] Warning: Failed to clean destination folder {av1_folder_dst}: {e}")
                try:
                    shutil.move(av1_folder_src, av1_folder_dst)
                    if not simple_mode:
                        print(f"[Dispatch] Moved folder: {av1_folder_src} -> {av1_folder_dst}")
                except Exception as e:
                    print(f"[Dispatch] Error moving folder: {e}")
            else:
                print(f"[Dispatch] Warning: Expected temp folder not found at {av1_folder_src}")
                
            # Move the file
            if os.path.exists(av1_file_src):
                if os.path.exists(av1_file_dst):
                    try:
                        os.remove(av1_file_dst)
                    except Exception as e:
                        print(f"[Dispatch] Warning: Failed to clean destination file {av1_file_dst}: {e}")
                try:
                    shutil.move(av1_file_src, av1_file_dst)
                    if not simple_mode:
                        print(f"[Dispatch] Moved file: {av1_file_src} -> {av1_file_dst}")
                except Exception as e:
                    print(f"[Dispatch] Error moving encoded file: {e}")
            else:
                print(f"[Dispatch] Warning: Expected encoded file not found at {av1_file_src}")

            # 4. Tagging (using av1an-tag.py)
            if not simple_mode:
                print("[Dispatch] Applying Tags...")
            try:
                if simple_mode:
                    tag_rc = run_quiet([sys.executable, tag_script], cwd=temp_dir,
                                       label="Tagging output")
                    if tag_rc != 0:
                        raise subprocess.CalledProcessError(tag_rc, tag_script)
                else:
                    subprocess.check_call([sys.executable, tag_script], cwd=temp_dir)
            except subprocess.CalledProcessError:
                print("[Dispatch] Warning: Tagging reported an error.")

            # 5. Muxing (using av1an-mux.py)
            if not simple_mode:
                print("[Dispatch] Muxing...")
            try:
                if simple_mode:
                    mux_rc = run_with_mux_progress(
                        [sys.executable, mux_script], cwd=temp_dir,
                        description="Muxing")
                    if mux_rc != 0:
                        raise subprocess.CalledProcessError(mux_rc, mux_script)
                else:
                    subprocess.check_call([sys.executable, mux_script], cwd=temp_dir)
            except subprocess.CalledProcessError:
                print("[Dispatch] Muxing failed.")
                continue
                
            # 6. Move Final Output
            temp_output_mkv = os.path.join(temp_dir, f"{basename}-output.mkv")
            
            output_moved = False
            if os.path.exists(temp_output_mkv):
                if not simple_mode:
                    print(f"[Dispatch] Moving final file to: {final_output_path}")
                try:
                    shutil.move(temp_output_mkv, final_output_path)
                    output_moved = True
                except Exception as e:
                    print(f"[Dispatch] Error moving output file: {e}")
            else:
                print(f"[Dispatch] Error: Expected output file not found: {temp_output_mkv}")

            if output_moved:
                timing_report = {
                    "filename": filename,
                    "av1an_encoding": av1an_elapsed,
                }
                timing_reports.append(timing_report)
                print_av1an_timing_report(timing_report)

                newly_detected_files = scan_for_new_input_files(video_input_dir, extensions, known_input_files)
                if newly_detected_files:
                    warn_and_pause_if_paths_too_long(newly_detected_files, video_output_dir, temp_dir)
                    input_files.extend(newly_detected_files)
        
        except Exception as e:
            print(f"[Dispatch] Critical Error during processing: {e}")
            send_ntfy_notification(
                ntfy_settings,
                root_dir,
                tools_dir,
                "Auto-Boost encode failed",
                "An encode failed.",
            )

    batch_elapsed = time.monotonic() - batch_started_at

    send_ntfy_notification(
        ntfy_settings,
        root_dir,
        tools_dir,
        "Auto-Boost encode complete",
        "All queued encodes are complete.",
    )

    print("\n" + "="*80)
    print("Av1an Direct Batch Complete.")
    print("="*80)

    if timing_reports:
        print("\nFinal Av1an time reports:")
        for timing_report in timing_reports:
            print_av1an_timing_report(timing_report)

    print("\nTime format legend: hh:mm:ss = hours:minutes:seconds")
    print(f"Total time for all files: {format_elapsed_hhmmss(batch_elapsed)}")

if __name__ == "__main__":
    main()