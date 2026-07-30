#!/usr/bin/env python3
"""AfterZone - apply a zones.txt to an encode that has ALREADY finished.

Normally --zones has to be decided before av1an starts. AfterZone lets you
decide afterwards: you watch the finished file, note the scenes you are not
happy with, write a zones.txt, and AfterZone re-encodes only those parts.

How it works
------------
When av1an runs with --keep, its working folder survives:

    .<hash>\\chunks.json   one entry per chunk, each with its own start_frame /
                           end_frame and video_params
    .<hash>\\done.json     {"frames":N,"done":{"00003":{...}},...}
    .<hash>\\encode\\*.ivf every finished chunk

That .<hash> folder ends up in one of two places, because av1an names it after
a hash of the input path and creates it in whatever folder it was run from:

    temp\\<name>\\.<hash>     Auto-Boost .bat files. Auto-Boost-Av1an.py runs
                             av1an in video-input\\<name>\\, and dispatch.py
                             moves that whole folder to temp\\<name>\\ afterwards.
                             The .vpy sits next to it in temp\\<name>\\.
    video-input\\.<hash>      av1an-only .bat files. av1an-dispatch.py runs
                             av1an in video-input itself, so the folder is
                             created there and is never moved. The .vpy for
                             these lives in temp\\<name>.vpy.

Both are searched. The folder name is a hash, so a loose .<hash> in video-input
is matched to its input file by the .vpy path recorded in its chunks.json.

On --resume, av1an reads chunks.json, throws away every chunk whose name is a
key in done.json, and encodes the rest with the video_params stored in
chunks.json.  It performs no freshness check on either file, and the final
concat simply reads whatever .ivf files are in encode\\.

So AfterZone does exactly this, per chunk that a zone touches:
  1. rewrite that chunk's video_params in chunks.json with the zone's params
  2. delete its done.json entry
  3. move its encode\\NNNNN.ivf out of the way
then re-runs av1an with --resume.  Untouched chunks are never re-encoded.

A zone edge that lands inside a chunk splits that chunk in two, which is what
av1an itself does with --zones during a fresh encode: chunks.json is just a
list, so the entry is replaced by one entry per piece, each with its own
start_frame/end_frame, its own frame range in source_cmd, and its own
video_params.  A zone covering frames 300-500 of a 100-500 chunk therefore
gives frames 100-300 the original parameters and 300-500 the zone's.

Both pieces still have to be encoded, because the existing .ivf covers the
whole original chunk and cannot be cut, so splitting costs the same encode
time as re-encoding the chunk whole -- what it buys is the parameters being
right per piece.  It also puts a keyframe at the split, exactly as a fresh
--zones encode would.

Inserting entries renumbers every chunk after the split, because a chunk's
name is "{index:05}" and all three of av1an's concat methods depend on that
numbering being contiguous from zero.  AfterZone therefore also renames the
encoded .ivf files and re-keys done.json, and writes a rename-map json into
afterzone-backup\\ before it touches anything.

Chunks that cannot be split fall back to taking the zone across their whole
range: multi-pass chunks (both pieces would share one --stats file) and
chunks whose source_cmd has no frame range AfterZone recognizes.  Either way
it prints exactly which frames are affected before it changes anything.

zones.txt format (one zone per line, blank lines and #-comments ignored):

    start_frame end_frame encoder [reset] encoder_params
    0 2157 svt-av1 --crf 28 --psy-rd 0.6
    31769 -1 svt-av1 --crf 30 --tf-strength 3

end_frame is exclusive; -1 means "to the end of the video".  Without the
optional `reset` keyword the zone's params are MERGED onto the params that
chunk was originally encoded with (matching flags are replaced, new flags are
appended), so you only need to list what you want to change.  With `reset`,
the zone's params replace the chunk's params completely.  Every parameter is
passed to the encoder, which is how the .bat files in this package already
handle things like --photon-noise.

Output goes to video-output\\<name>-afterzone.mkv.  The original
video-output\\<name>-output.mkv is never touched, so you can compare them.

Run this via AfterZone.bat (it sets PATH and the encoder-settings tag).
"""

import copy
import glob
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape as xml_escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from wakepy import keep as wakepy_keep
except Exception:  # pragma: no cover - wakepy is bundled, but never hard-fail
    wakepy_keep = None

BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

VIDEO_EXTS = (".mkv", ".mp4", ".m2ts")

# Default starting threshold for auto-generation, as a multiple of the typical
# bitrate (the median of the 1 second rolling average). The user can change it
# interactively, so this is only where the search starts.
BITRATE_ZONE_THRESHOLD = 1.25

# A zone edge that lands inside a chunk splits that chunk in two, the same way
# --zones would have split it during a fresh encode. Splitting at an arbitrary
# frame can leave a sliver of a chunk behind, which wastes a keyframe on a
# handful of frames, so an edge closer than this to a chunk boundary is pushed
# out to the boundary instead (the zone absorbs the sliver).
MIN_SPLIT_SEGMENT = 12

DISPLAY_USERNAME = "av1enjoyer"
_WINDOWS_USER_PATH_RE = re.compile(r"([\\/]+users[\\/]+)[A-Za-z0-9._-]+", re.IGNORECASE)


def anonymize_user_paths(text):
    """Hide the real Windows profile name in user-facing console output."""
    if not isinstance(text, str):
        return text
    return _WINDOWS_USER_PATH_RE.sub(lambda m: f"{m.group(1)}{DISPLAY_USERNAME}", text)


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

try:
    import colorama

    colorama.just_fix_windows_console()
except Exception:
    pass


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def hr():
    print("-" * 79)


def die(message):
    print(f"{RED}[AfterZone] {message}{RESET}")
    sys.exit(1)


def ask(prompt, valid):
    """Prompt until the user types one of `valid` (case-insensitive)."""
    while True:
        try:
            answer = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        if answer in valid:
            return answer
        print(f"{YELLOW}Please enter one of: {', '.join(valid)}{RESET}")


def ask_percentage(prompt):
    """Read a percentage above 100. Blank input means 'give up'."""
    while True:
        try:
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        if not raw:
            return None
        try:
            value = float(raw.rstrip("%").strip())
        except ValueError:
            print(f"{YELLOW}Enter a number above 100 (for example 115), or press "
                  f"Enter to give up.{RESET}")
            continue
        if value <= 100:
            print(f"{YELLOW}The value has to be above 100. At 100% the threshold is "
                  f"the median bitrate itself, which would select roughly half the "
                  f"video.{RESET}")
            continue
        return value


def human_bytes(size):
    step = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if step < 1024.0 or unit == "TiB":
            return f"{step:.1f} {unit}" if unit != "B" else f"{int(step)} B"
        step /= 1024.0
    return f"{step:.1f} TiB"


def frames_to_timecode(frame, fps):
    if not fps or fps <= 0:
        return "??:??:??"
    total = frame / fps
    hours, rem = divmod(int(total), 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}"


def read_worker_count(tools_dir):
    """Read workers=N from tools/workercount-config.txt (same file the .bats use)."""
    config = os.path.join(tools_dir, "workercount-config.txt")
    try:
        with open(config, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if "=" in line and line.split("=", 1)[0].strip().lower() == "workers":
                    value = int(line.split("=", 1)[1].strip())
                    if value > 0:
                        return value
    except Exception:
        pass
    return 4


def svt_av1_version(tools_dir):
    """Report the fork currently installed as tools/av1an/SvtAv1EncApp.exe."""
    exe = os.path.join(tools_dir, "av1an", "SvtAv1EncApp.exe")
    if not os.path.exists(exe):
        return "SvtAv1EncApp.exe not found"
    try:
        result = subprocess.run([exe, "--version"], capture_output=True, text=True)
        output = (result.stdout or result.stderr or "").strip()
        if output:
            return output.splitlines()[0].replace(" (release)", "").strip()
    except Exception as exc:
        return f"unknown ({exc})"
    return "unknown"


# ---------------------------------------------------------------------------
# encoder parameter parsing / merging
# ---------------------------------------------------------------------------


def _is_flag(token):
    """True for '--crf' / '-q', False for values including negatives like '-1'."""
    return bool(re.match(r"^--?[A-Za-z]", token))


def parse_params(tokens):
    """['--crf','30','--hbd-mds','1'] -> [['--crf','30'], ['--hbd-mds','1']]."""
    parsed = []
    index = 0
    while index < len(tokens):
        token = str(tokens[index])
        if _is_flag(token):
            if "=" in token:
                flag, value = token.split("=", 1)
                parsed.append([flag, value])
                index += 1
            elif index + 1 < len(tokens) and not _is_flag(str(tokens[index + 1])):
                parsed.append([token, str(tokens[index + 1])])
                index += 2
            else:
                parsed.append([token, None])
                index += 1
        else:
            # Stray value with no flag in front of it; keep it so nothing is lost.
            parsed.append([token, None])
            index += 1
    return parsed


def flatten_params(parsed):
    flat = []
    for flag, value in parsed:
        flat.append(flag)
        if value is not None:
            flat.append(value)
    return flat


def merge_params(base_tokens, zone_tokens):
    """Override matching flags in place, append flags the base does not have."""
    merged = parse_params(base_tokens)
    for flag, value in parse_params(zone_tokens):
        for entry in merged:
            if entry[0] == flag:
                entry[1] = value
                break
        else:
            merged.append([flag, value])
    return flatten_params(merged)


def params_summary(base_tokens, new_tokens):
    """Describe what actually changed, for the confirmation screen."""
    before = {flag: value for flag, value in parse_params(base_tokens)}
    after = {flag: value for flag, value in parse_params(new_tokens)}
    changes = []
    for flag, value in after.items():
        if flag not in before:
            changes.append(f"+{flag} {value}" if value is not None else f"+{flag}")
        elif before[flag] != value:
            changes.append(f"{flag} {before[flag]} -> {value}")
    for flag in before:
        if flag not in after:
            changes.append(f"-{flag}")
    return ", ".join(changes) if changes else "no change"


# ---------------------------------------------------------------------------
# zones.txt
# ---------------------------------------------------------------------------


class Zone:
    def __init__(self, line_number, start, end, encoder, reset, params):
        self.line_number = line_number
        self.start = start
        self.end = end
        self.encoder = encoder
        self.reset = reset
        self.params = params

    def overlaps(self, chunk_start, chunk_end):
        return chunk_start < self.end and chunk_end > self.start


def parse_zones_file(path, total_frames):
    """Parse `start end encoder [reset] params` lines. Blank / #-comments skipped."""
    zones = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                tokens = shlex.split(line, posix=False)
            except ValueError:
                tokens = line.split()
            if len(tokens) < 3:
                print(f"{YELLOW}[AfterZone] Line {line_number}: need at least "
                      f"'start end encoder', skipping: {line}{RESET}")
                continue
            try:
                start = int(tokens[0])
                end = int(tokens[1])
            except ValueError:
                print(f"{YELLOW}[AfterZone] Line {line_number}: frame numbers are not "
                      f"integers, skipping: {line}{RESET}")
                continue

            encoder = tokens[2]
            rest = tokens[3:]
            reset = bool(rest) and rest[0].lower() == "reset"
            if reset:
                rest = rest[1:]

            if end < 0:
                end = total_frames
            if start >= total_frames:
                print(f"{YELLOW}[AfterZone] Line {line_number}: starts at frame {start} "
                      f"but the video is only {total_frames} frames, skipping.{RESET}")
                continue
            start = max(0, start)
            end = min(end, total_frames)
            if end <= start:
                print(f"{YELLOW}[AfterZone] Line {line_number}: empty range "
                      f"({start}-{end}), skipping.{RESET}")
                continue
            if not rest:
                print(f"{YELLOW}[AfterZone] Line {line_number}: no encoder parameters, "
                      f"skipping.{RESET}")
                continue
            zones.append(Zone(line_number, start, end, encoder, reset, rest))
    return zones


# ---------------------------------------------------------------------------
# locating the av1an working folder
# ---------------------------------------------------------------------------


class Job:
    """One input video plus the av1an working folder that produced it."""

    def __init__(self, source, work_dir, hash_dir, chunks, done):
        self.source = source                  # video-input\name.mkv
        # av1an's cwd for the original run, and the cwd AfterZone re-runs it in:
        #   temp\name      for Auto-Boost .bat files
        #   video-input    for av1an-only .bat files
        self.stem = Path(source).stem
        self.work_dir = work_dir
        self.hash_dir = hash_dir              # work_dir\.3926ad3 (av1an's --temp)
        self.chunks_path = chunks
        self.done_path = done


def hash_dirs_in(directory):
    """Every av1an working folder sitting directly inside `directory`."""
    found = []
    try:
        entries = sorted(os.scandir(directory), key=lambda e: e.name)
    except OSError:
        return found
    for entry in entries:
        if not entry.is_dir():
            continue
        chunks = os.path.join(entry.path, "chunks.json")
        done = os.path.join(entry.path, "done.json")
        if os.path.exists(chunks) and os.path.exists(done):
            found.append(entry.path)
    return found


def find_hash_dir(work_dir):
    """av1an names its temp folder '.<hash of input filename>'. Find it by content."""
    candidates = hash_dirs_in(work_dir)
    if not candidates:
        return None
    if len(candidates) > 1:
        # Prefer the dotted hash folder, then the most recently written one.
        dotted = [c for c in candidates if os.path.basename(c).startswith(".")]
        candidates = dotted or candidates
        candidates.sort(key=lambda p: os.path.getmtime(os.path.join(p, "done.json")),
                        reverse=True)
        print(f"{YELLOW}[AfterZone] Multiple av1an temp folders found; using "
              f"{os.path.basename(candidates[0])}{RESET}")
    return candidates[0]


_SOURCE_CMD_TEXT = {}


def hash_dir_source_text(hash_dir):
    """The first chunk's source_cmd as one lowercased string, for identification.

    A loose .<hash> folder in video-input is named after a hash of the input
    path, so the folder name says nothing about which video it belongs to. The
    chunk commands do: every one of them names the .vpy av1an was given.
    """
    if hash_dir in _SOURCE_CMD_TEXT:
        return _SOURCE_CMD_TEXT[hash_dir]
    text = ""
    try:
        with open(os.path.join(hash_dir, "chunks.json"), "r",
                  encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            parts = [osstring_decode(item)
                     for item in (data[0].get("source_cmd") or [])]
            text = " ".join(part for part in parts if part).lower()
    except (OSError, ValueError, TypeError, AttributeError):
        text = ""
    _SOURCE_CMD_TEXT[hash_dir] = text
    return text


def hash_dir_matches(hash_dir, stem):
    """True when this folder's chunks decode frames from `stem`'s script.

    The extension is required to be right after the stem so that 'foo' does not
    claim the folder belonging to 'foobar'.
    """
    text = hash_dir_source_text(hash_dir)
    if not text:
        return False
    needle = stem.lower()
    return (f"{needle}.vpy" in text
            or f"\\{needle}." in text
            or f"/{needle}." in text)


def discover_jobs(video_input_dir, temp_dir):
    """Pair every input video with the av1an working folder that produced it.

    Three shapes are recognized, in this order of preference:

        temp\\<name>\\.<hash>    Auto-Boost .bat, after dispatch.py moved it
        video-input\\<name>\\.<hash>
                                the same run, interrupted before the move
        video-input\\.<hash>     av1an-only .bat, which never has its folder
                                moved because av1an-dispatch.py runs av1an in
                                video-input itself

    If a stem somehow has folders in more than one place, the one whose
    done.json was written last wins: that is the encode the mkv in video-output
    came from.
    """
    jobs = []
    sources = []
    for ext in VIDEO_EXTS:
        sources.extend(sorted(glob.glob(os.path.join(video_input_dir, f"*{ext}"))))

    loose = hash_dirs_in(video_input_dir)     # av1an-only .bat files land here
    claimed = set()

    for source in sources:
        stem = Path(source).stem
        candidates = []
        for base in (temp_dir, video_input_dir):
            work_dir = os.path.join(base, stem)
            if not os.path.isdir(work_dir):
                continue
            hash_dir = find_hash_dir(work_dir)
            if hash_dir:
                candidates.append((work_dir, hash_dir))
        for hash_dir in loose:
            if hash_dir_matches(hash_dir, stem):
                candidates.append((video_input_dir, hash_dir))

        # A loose folder whose chunks.json could not be read identifies nothing,
        # so fall back to it only when there is exactly one of each and no
        # other candidate: then there is nothing it could be confused with.
        if not candidates and len(sources) == 1 and len(loose) == 1:
            candidates.append((video_input_dir, loose[0]))

        if not candidates:
            continue
        if len(candidates) > 1:
            candidates.sort(key=lambda pair: os.path.getmtime(
                os.path.join(pair[1], "done.json")), reverse=True)
            print(f"{YELLOW}[AfterZone] {stem}: found {len(candidates)} av1an "
                  f"folders; using the most recently written one, "
                  f"{candidates[0][1]}{RESET}")

        work_dir, hash_dir = candidates[0]
        claimed.add(hash_dir)
        jobs.append(Job(source, work_dir, hash_dir,
                        os.path.join(hash_dir, "chunks.json"),
                        os.path.join(hash_dir, "done.json")))

    orphans = [hash_dir for hash_dir in loose if hash_dir not in claimed]
    return jobs, sources, orphans


# ---------------------------------------------------------------------------
# bitrate analysis + zones.txt auto-generation
# ---------------------------------------------------------------------------


def find_encoded_output(video_output_dir, stem):
    """Locate the finished encode to analyse (prefer <stem>-output.mkv)."""
    for suffix in ("-output.mkv", "-afterzone.mkv", "-av1.mkv"):
        candidate = os.path.join(video_output_dir, f"{stem}{suffix}")
        if os.path.exists(candidate):
            return candidate
    matches = sorted(glob.glob(os.path.join(video_output_dir, f"{stem}*.mkv")))
    return matches[0] if matches else None


def probe_frame_sizes(ffprobe, path):
    """Return per-frame compressed sizes in presentation order, via ffprobe packets."""
    cmd = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "packet=pts_time,size", "-of", "csv=p=0", path,
    ]
    packets = []
    unordered = 0
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace")
    last_report = time.monotonic()
    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        fields = line.split(",")
        if len(fields) < 2:
            continue
        try:
            size = int(fields[-1])
        except ValueError:
            continue
        try:
            pts = float(fields[0])
        except ValueError:
            pts = None
            unordered += 1
        packets.append((pts, size))
        now = time.monotonic()
        if now - last_report > 0.5:
            print(f"  Read {len(packets):,} video frames...", end="\r", flush=True)
            last_report = now
    stderr = process.stderr.read()
    process.wait()
    print(" " * 60, end="\r")
    if process.returncode != 0:
        die(f"ffprobe failed:\n{stderr.strip()}")
    if not packets:
        die("ffprobe returned no video frames; is the output file valid?")
    if unordered == 0:
        packets.sort(key=lambda item: item[0])
    return [size for _pts, size in packets]


def rolling_mean(values, window):
    """Centred rolling mean, edges handled by shrinking the window."""
    count = len(values)
    if window <= 1 or count == 0:
        return list(values)
    prefix = [0]
    for value in values:
        prefix.append(prefix[-1] + value)
    half = window // 2
    out = []
    for index in range(count):
        low = max(0, index - half)
        high = min(count, index + half + 1)
        out.append((prefix[high] - prefix[low]) / float(high - low))
    return out


def median(values):
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        return 0.0
    middle = count // 2
    if count % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def find_high_bitrate_runs(smoothed, threshold, min_len, merge_gap):
    """Contiguous regions that are *sustainably* above threshold.

    Spike handling is the whole difficulty here. A single huge frame (a
    scene-change keyframe, or a flash/explosion) is smeared by the rolling
    average into a bump exactly one window wide, which looks like a region.
    min_len is therefore set wider than the smoothing window by the caller, so
    a lone spike cannot produce a long enough run to qualify while a genuinely
    expensive scene can.

    Judging the run by raw frame sizes instead does not work: on content with
    many skip/repeat frames the median raw frame size is a couple of bytes even
    inside the most expensive scene, so every region would be rejected.
    """
    runs = []
    start = None
    for index, value in enumerate(smoothed):
        if value >= threshold:
            if start is None:
                start = index
        elif start is not None:
            runs.append([start, index])
            start = None
    if start is not None:
        runs.append([start, len(smoothed)])

    merged = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = run[1]
        else:
            merged.append(run)

    return [run for run in merged if run[1] - run[0] >= min_len]


def rank_chunks_by_bitrate(chunks, sizes, frame_scale):
    """Every chunk with its mean bytes-per-frame, most expensive first.

    av1an chunks are scene based, so this ranks scenes. Used for the top-N
    fallback when threshold detection finds nothing worth zoning.
    """
    count = len(sizes)
    ranked = []
    for chunk in chunks:
        low = int(round(chunk["start_frame"] / frame_scale))
        high = int(round(chunk["end_frame"] / frame_scale))
        low = max(0, min(count, low))
        high = max(low + 1, min(count, high))
        window = sizes[low:high]
        if not window:
            continue
        ranked.append((sum(window) / float(len(window)), chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def top_scene_spans(ranked, count):
    """Frame spans for the N most expensive chunks, adjacent ones merged."""
    picked = sorted([chunk["start_frame"], chunk["end_frame"]]
                    for _mean, chunk in ranked[:count])
    merged = []
    for span in picked:
        if merged and span[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], span[1])
        else:
            merged.append(span)
    return merged


def print_scene_map(ranked, reference, fps, to_kbps, limit=12):
    """List the most expensive scenes with the frame range each one occupies.

    This is the table you need to hand-write a zones.txt. Ranges that line up
    with these boundaries re-encode exactly one scene each; ranges that do not
    split the chunks they land in, which costs the rest of those chunks a
    re-encode at their original parameters.
    """
    if not ranked:
        return
    shown = ranked[:limit]
    print(f"{BOLD}Most expensive scenes (av1an chunks){RESET}")
    print(f"{'chunk':>6}  {'frames':>15}  {'timecode':>19}  {'bitrate':>11}  vs typical")
    for mean_size, chunk in shown:
        start, end = chunk["start_frame"], chunk["end_frame"]
        print(f"{chunk['index']:05d}   {f'{start}-{end}':>15}  "
              f"{frames_to_timecode(start, fps) + ' - ' + frames_to_timecode(end, fps):>19}  "
              f"{mean_size * to_kbps:>8,.0f} kbps  {mean_size / reference:>6.1f}x")
    if len(ranked) > limit:
        print(f"       ... and {len(ranked) - limit} more scene(s), lower bitrate.")
    print()
    print("Ranges that match the frame numbers above re-encode exactly those scenes.")
    print("Any other range is fine too: the chunks it starts or ends inside are split")
    print("at your frame numbers, and the leftover pieces are re-encoded unchanged.")
    print("You can hand-write zone lines from this table instead of using a threshold.")
    print()


def strongest_sustained_factor(detect, peak_factor):
    """Highest multiple of the median that still selects at least one region.

    Used to suggest a threshold when the user's value found nothing. `detect`
    takes a factor and returns the spans it would select, so this reflects the
    real detector (minimum length, gap stitching and the median-of-run check)
    rather than just the peak of the curve.
    """
    low = 1.0
    if not detect(1.0001):
        return None
    high = max(peak_factor, low)
    if detect(high):
        return high
    for _ in range(24):
        mid = (low + high) / 2.0
        if detect(mid):
            low = mid
        else:
            high = mid
        if high - low < 0.005:
            break
    return low


def scale_runs_to_frames(runs, total_frames, frame_scale):
    """Detector positions to source frame numbers, clamped and merged.

    These stay at the exact frames the bitrate rose and fell. Zone edges no
    longer have to line up with chunk boundaries, because a zone edge inside a
    chunk splits it (see build_plan), so widening here would only re-encode
    frames the user did not ask for.
    """
    spans = []
    for run_start, run_end in runs:
        start = max(0, int(round(run_start * frame_scale)))
        end = min(total_frames, int(round(run_end * frame_scale)))
        if end > start:
            spans.append([start, end])
    spans.sort()
    merged = []
    for span in spans:
        if merged and span[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], span[1])
        else:
            merged.append(span)
    return merged


def ascii_bitrate_plot(smoothed, fps, width=72, height=12):
    """Console bitrate graph so the shape of the file is visible without a viewer."""
    if not smoothed:
        return
    count = len(smoothed)
    columns = []
    for column in range(width):
        low = int(column * count / width)
        high = max(low + 1, int((column + 1) * count / width))
        window = smoothed[low:high]
        columns.append(sum(window) / len(window))
    peak = max(columns) or 1.0
    ramp = " .:-=+*#%@"
    print()
    print(f"  Bitrate shape (0 to {peak * 8 * fps / 1000.0:,.0f} kbps peak, smoothed):")
    for row in range(height, 0, -1):
        line = ""
        for value in columns:
            level = value / peak * height
            line += ramp[-1] if level >= row else (ramp[3] if level >= row - 0.5 else " ")
        print(f"  |{line}|")
    print(f"  +{'-' * width}+")
    print(f"  0{' ' * (width - 12)}{frames_to_timecode(count, fps):>11}")
    print()


def write_bitrate_png(path, smoothed, fps, median_size, threshold, spans, frame_scale,
                      factor=BITRATE_ZONE_THRESHOLD):
    """Optional matplotlib plot; skipped silently if matplotlib is unavailable."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None

    try:
        to_kbps = 8.0 * fps / 1000.0

        # Feature-length files have hundreds of thousands of frames. Decimate to
        # keep rendering quick and the PNG small, using the per-bucket mean so
        # the drawn curve still matches the curve the threshold was applied to.
        max_points = 4000
        count = len(smoothed)
        if count > max_points:
            frames, kbps = [], []
            for bucket in range(max_points):
                low = int(bucket * count / max_points)
                high = max(low + 1, int((bucket + 1) * count / max_points))
                chunk = smoothed[low:high]
                frames.append(low * frame_scale)
                kbps.append(sum(chunk) / len(chunk) * to_kbps)
        else:
            frames = [index * frame_scale for index in range(count)]
            kbps = [value * to_kbps for value in smoothed]

        figure, axes = plt.subplots(figsize=(16, 5), dpi=110)
        axes.plot(frames, kbps, linewidth=0.7, color="#1f77b4", label="bitrate (1s mean)")
        axes.axhline(median_size * to_kbps, color="#2ca02c", linestyle="--", linewidth=1,
                     label=f"typical {median_size * to_kbps:,.0f} kbps")
        # factor is None when the zones came from the top-N scenes rather than
        # from a threshold, in which case there is no threshold line to draw.
        if factor is not None and threshold is not None:
            axes.axhline(threshold * to_kbps, color="#d62728", linestyle=":",
                         linewidth=1,
                         label=f"threshold {threshold * to_kbps:,.0f} kbps "
                               f"({factor * 100:.0f}% of typical)")
        for index, (start, end) in enumerate(spans):
            axes.axvspan(start, end, color="#ff7f0e", alpha=0.25,
                         label="generated zone" if index == 0 else None)
        axes.set_xlabel("frame")
        axes.set_ylabel("kbps")
        axes.set_title(os.path.basename(path).replace("-bitrate.png", "") + " - bitrate")
        axes.margins(x=0)
        axes.grid(alpha=0.25)
        axes.legend(loc="upper right", fontsize="small")
        figure.tight_layout()
        figure.savefig(path)
        plt.close(figure)
        return path
    except Exception as exc:
        print(f"{YELLOW}[AfterZone] Could not write the bitrate plot: {exc}{RESET}")
        return None


def generate_zones_file(job, chunks, total_frames, fps, zones_path,
                        video_output_dir, ffprobe):
    """Analyse the finished encode and write a zones.txt the user can edit."""
    encoded = find_encoded_output(video_output_dir, job.stem)
    if not encoded:
        die(f"No finished encode found in video-output for '{job.stem}'.\n"
            f"            AfterZone needs the encoded file to measure bitrate.\n"
            f"            Expected something like video-output\\{job.stem}-output.mkv")

    hr()
    print(f"{BOLD}Generating a zones.txt from the bitrate of the finished encode{RESET}")
    hr()
    print(f"Analysing: {encoded}")
    print()
    print("What this does:")
    print("  1. Reads the compressed size of every video frame with ffprobe.")
    print("  2. Smooths those sizes over a 1 second window to get local bitrate.")
    print("  3. Takes the median of that curve as 'the majority of the video'.")
    print(f"  4. Marks every region that sustains at least "
          f"{int(BITRATE_ZONE_THRESHOLD * 100)}% of that typical bitrate")
    print(f"     (i.e. {int((BITRATE_ZONE_THRESHOLD - 1) * 100)}% above the majority "
          f"of the video). Regions have to be longer than the")
    print("     smoothing window, so single-frame spikes do not become zones.")
    print("  5. Widens each region out to av1an's chunk boundaries and writes them")
    print("     as zone lines for you to edit.")
    print("  You choose the percentage if the default does not suit the file.")
    print()
    print(f"{YELLOW}This reads the whole file and can take several minutes on a "
          f"feature length encode.{RESET}")
    print("Nothing is deleted or re-encoded during this step.")
    print()

    sizes = probe_frame_sizes(ffprobe, encoded)
    print(f"Read {len(sizes):,} video frames.")

    # The encode should have the same frame count as the chunk list, but stay
    # correct if it does not (VFR sources, stray packets).
    frame_scale = 1.0
    if len(sizes) != total_frames and len(sizes) > 0:
        frame_scale = total_frames / float(len(sizes))
        print(f"{YELLOW}Note: encode has {len(sizes):,} frames but chunks.json covers "
              f"{total_frames:,}; scaling positions by {frame_scale:.4f}.{RESET}")

    window = max(1, int(round(fps)))
    smoothed = rolling_mean(sizes, window)

    # The reference is the median of the *smoothed* curve, i.e. the typical
    # bitrate over time. The median raw frame size is useless for this: content
    # with many skip/repeat frames measures 26 bytes at the median while
    # averaging 7,000, so a percentage of it selects effectively everything.
    reference = median(smoothed)
    if reference <= 0:
        die("Measured bitrate is zero throughout; cannot analyse this file.")

    to_kbps = 8.0 * fps / 1000.0
    peak = max(smoothed) if smoothed else 0.0
    print(f"Typical bitrate: {reference * to_kbps:,.0f} kbps "
          f"(median of the 1 second average)")
    print(f"Peak bitrate:    {peak * to_kbps:,.0f} kbps "
          f"({peak / reference:.1f}x typical)")

    ascii_bitrate_plot(smoothed, fps)

    # Always leave a plot on disk, even if no zones are found or the user gives
    # up, so the bitrate can be reviewed before picking a threshold. It gets
    # rewritten with the zones shaded once a threshold selects something.
    png_path = os.path.join(os.path.dirname(zones_path), f"{job.stem}-bitrate.png")
    png = write_bitrate_png(png_path, smoothed, fps, reference,
                            reference * BITRATE_ZONE_THRESHOLD, [], frame_scale,
                            BITRATE_ZONE_THRESHOLD)
    if png:
        print(f"{GREEN}Bitrate plot saved to:{RESET} {png}")
        print("Open it to see the shape of the encode and where the bitrate peaks.")
    else:
        print(f"{YELLOW}Could not write the bitrate plot image "
              f"(matplotlib unavailable).{RESET}")
    print()

    # A lone spike is smeared by the rolling average into a bump one window
    # wide, so require a run to be half again longer than the window. Anything
    # shorter is not worth a zone of its own once it is split out.
    min_len = max(1, int(round(window * 1.5)))
    merge_gap = max(1, window)                # stitch regions under 1s apart

    def detect(factor):
        runs = find_high_bitrate_runs(smoothed, reference * factor,
                                      min_len, merge_gap)
        return scale_runs_to_frames(runs, total_frames, frame_scale)

    ranked = rank_chunks_by_bitrate(chunks, sizes, frame_scale)
    print_scene_map(ranked, reference, fps, to_kbps)

    def offer_top_scenes(count=3):
        """Fallback that always produces something usable to start from."""
        spans = top_scene_spans(ranked, count)
        print()
        print(f"Top {min(count, len(ranked))} highest-bitrate scene(s):")
        for mean_size, chunk in ranked[:count]:
            print(f"  chunk {chunk['index']:05d}  frames "
                  f"{chunk['start_frame']}-{chunk['end_frame']}  "
                  f"({frames_to_timecode(chunk['start_frame'], fps)} - "
                  f"{frames_to_timecode(chunk['end_frame'], fps)})  "
                  f"{mean_size * to_kbps:,.0f} kbps "
                  f"({mean_size / reference:.1f}x typical)")
        return spans

    peak_factor = (peak / reference) if reference else 1.0
    best_factor = "unknown"          # computed once, on the first failure
    factor = BITRATE_ZONE_THRESHOLD
    spans = None
    source_note = ""

    while spans is None:
        threshold = reference * factor
        print(f"Zone threshold:  {threshold * to_kbps:,.0f} kbps "
              f"({factor * 100:.0f}% of typical)")
        found = detect(factor)

        if found:
            covered = sum(end - start for start, end in found)
            share = covered * 100.0 / max(1, total_frames)
            print(f"Found {len(found)} region(s) covering {covered:,} frames "
                  f"({share:.1f}% of the video).")
            if share <= 50.0:
                spans = found
                source_note = f"{factor * 100:.0f}% of the typical bitrate"
                break

            # Selecting most of the video means re-encoding most of it, which
            # defeats the point of AfterZone. Let the user decide.
            print()
            print(f"{YELLOW}That is over half the video, so this would re-encode "
                  f"most of it.{RESET}")
            print("A higher percentage would target only the most expensive scenes.")
            print()
            print(f"  {BOLD}1{RESET} - Enter a different percentage")
            print(f"  {BOLD}2{RESET} - Use the top 3 highest-bitrate scenes instead")
            print(f"  {BOLD}3{RESET} - Keep these regions anyway")
            print()
            choice = ask("Enter 1, 2 or 3: ", {"1", "2", "3"})
            print()
            if choice == "3":
                spans = found
                source_note = f"{factor * 100:.0f}% of the typical bitrate"
                break
            if choice == "2":
                spans = offer_top_scenes()
                source_note = "the top 3 highest-bitrate scenes"
                factor = None  # no threshold was used
                threshold = None
                break
            answer = ask_percentage("Enter a percentage above 100: ")
            if answer is not None:
                factor = answer / 100.0
            print()
            continue

        # Nothing found at this threshold.
        print()
        print(f"{YELLOW}No region sustains {factor * 100:.0f}% of the typical "
              f"bitrate for longer than {min_len} frames.{RESET}")

        if best_factor == "unknown":
            best_factor = strongest_sustained_factor(detect, peak_factor)

        if best_factor is None:
            print("This encode is very even, so there is no region that stands out")
            print("at any threshold above 100%.")
            print()
            print(f"  {BOLD}1{RESET} - Create zones for the top 3 highest-bitrate "
                  f"scenes anyway")
            print("      They are the most expensive scenes in the file, so they are a")
            print("      reasonable starting point even without a clear peak.")
            print(f"  {BOLD}2{RESET} - Exit without creating a zones file")
            print()
            if ask("Enter 1 or 2: ", {"1", "2"}) == "2":
                print()
                print("No zones file was created.")
                if png:
                    print(f"The bitrate plot is at {png} if you want to read frame "
                          f"ranges off it yourself.")
                print(f"Write {zones_path} by hand to re-encode specific frame ranges.")
                return None
            spans = offer_top_scenes()
            source_note = "the top 3 highest-bitrate scenes"
            factor = None      # no threshold was used
            threshold = None
            break

        suggestion = max(101, int(best_factor * 100))
        print(f"The strongest sustained region is about {best_factor * 100:.0f}% of "
              f"typical ({reference * best_factor * to_kbps:,.0f} kbps), so anything "
              f"up to {suggestion} will find something.")
        print("Lower percentages select more of the video; higher ones select only")
        print("the most expensive scenes.")
        print()
        print(f"  {BOLD}1{RESET} - Enter a different percentage "
              f"(suggested {suggestion})")
        print(f"  {BOLD}2{RESET} - Use the top 3 highest-bitrate scenes instead")
        print(f"  {BOLD}3{RESET} - Exit without creating a zones file")
        print()
        choice = ask("Enter 1, 2 or 3: ", {"1", "2", "3"})
        print()
        if choice == "3":
            print("No zones file was created.")
            if png:
                print(f"The bitrate plot is at {png} if you want to read frame "
                      f"ranges off it yourself.")
            print(f"Write {zones_path} by hand to re-encode specific frame ranges.")
            return None
        if choice == "2":
            spans = offer_top_scenes()
            source_note = "the top 3 highest-bitrate scenes"
            factor = None      # no threshold was used
            threshold = None
            break
        answer = ask_percentage(f"Enter a percentage above 100 "
                                f"(suggested {suggestion}): ")
        if answer is not None:
            factor = answer / 100.0
        print()

    # Redraw with the selected zones shaded, at the threshold that found them.
    png = write_bitrate_png(png_path, smoothed, fps, reference, threshold, spans,
                            frame_scale, factor) or png

    covered = sum(end - start for start, end in spans)
    lines = [
        f"# AfterZone auto-generated zones for {os.path.basename(job.source)}",
        f"# Measured from: {os.path.basename(encoded)}",
        f"# Typical bitrate {reference * to_kbps:,.0f} kbps "
        f"(median of the 1 second average); peak {peak * to_kbps:,.0f} kbps.",
        f"# Ranges below were selected by: {source_note}.",
        "#",
        "# Ranges are the exact frames the bitrate stayed high. end_frame is",
        "# exclusive. A range that starts or ends inside an av1an chunk splits that",
        "# chunk, so only these frames get the parameters below -- but the rest of a",
        "# split chunk is re-encoded too (with its original parameters), because the",
        "# encoded chunk cannot be cut in half.",
        "#",
        "# EDIT THE PARAMETERS BELOW BEFORE RUNNING AfterZone AGAIN.",
        "# Each line currently repeats the settings the range was already encoded",
        "# with, so running as-is would re-encode it to the same thing. Change the",
        "# values you want different, e.g. raise --crf to spend fewer bits here or",
        "# lower it to spend more. You only need to list the flags you are changing;",
        "# anything you leave out keeps its original value.",
        "#",
        "# Delete any line you do not want re-encoded.",
        "",
    ]
    for start, end in spans:
        base = []
        for chunk in chunks:
            if chunk["start_frame"] <= start < chunk["end_frame"]:
                base = [str(token) for token in chunk.get("video_params") or []]
                break
        lines.append(f"# frames {start}-{end}  ({frames_to_timecode(start, fps)} - "
                     f"{frames_to_timecode(end, fps)})")
        lines.append(f"{start} {end} svt-av1 {' '.join(base)}".rstrip())
    lines.append("")

    with open(zones_path, "w", encoding="utf-8", newline="\r\n") as handle:
        handle.write("\n".join(lines))

    hr()
    print(f"{GREEN}Wrote {zones_path}{RESET}")
    print(f"  {len(spans)} zone(s) from {source_note}, covering {covered:,} of "
          f"{total_frames:,} frames "
          f"({covered * 100.0 / max(1, total_frames):.1f}% of the video).")
    if png:
        print(f"{GREEN}Bitrate plot saved to:{RESET} {png}")
        print("  The selected zones are shaded on it, so you can check they line up")
        print("  with the scenes you actually care about.")
    hr()
    print()
    print(f"{BOLD}Next steps:{RESET}")
    if png:
        print(f"  1. Review {png} to see which regions were picked.")
        print(f"  2. Open {zones_path} in a text editor (Notepad++ is suggested).")
        print("  3. Change the encoder parameters on the lines you care about, and")
        print("     delete the lines you do not want re-encoded.")
        print("  4. Run AfterZone again to re-encode just those chunks.")
    else:
        print(f"  1. Open {zones_path} in a text editor (Notepad++ is suggested).")
        print("  2. Change the encoder parameters on the lines you care about, and")
        print("     delete the lines you do not want re-encoded.")
        print("  3. Run AfterZone again to re-encode just those chunks.")
    print()
    return zones_path


# ---------------------------------------------------------------------------
# splitting a chunk at a zone edge
# ---------------------------------------------------------------------------

# av1an serializes every source_cmd argument as a Rust OsString, which json
# encodes as {"Windows": [utf-16 code units]} or {"Unix": [bytes]} depending on
# the platform that wrote the file. Plain strings are accepted as well, in case
# a future av1an changes the representation.

_SELECT_RANGE_RE = re.compile(r"(between\(n\\?,)(\d+)(\\?,)(\d+)(\))")


def osstring_decode(item):
    """The text of one serialized source_cmd argument, or None if unreadable."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict) and len(item) == 1:
        kind, payload = next(iter(item.items()))
        if not isinstance(payload, list):
            return None
        try:
            if kind == "Windows":
                raw = b"".join(struct.pack("<H", int(unit)) for unit in payload)
                return raw.decode("utf-16-le", "surrogatepass")
            if kind == "Unix":
                return bytes(int(byte) for byte in payload).decode("utf-8",
                                                                   "surrogateescape")
        except (TypeError, ValueError, struct.error, UnicodeDecodeError):
            return None
    return None


def osstring_encode(template, text):
    """Re-encode `text` in whatever representation `template` used."""
    if isinstance(template, str):
        return text
    kind = next(iter(template))
    if kind == "Windows":
        raw = text.encode("utf-16-le", "surrogatepass")
        return {"Windows": list(struct.unpack(f"<{len(raw) // 2}H", raw))}
    return {"Unix": list(text.encode("utf-8", "surrogateescape"))}


def retarget_source_cmd(cmd, start, end):
    """A copy of `cmd` that decodes frames [start, end) instead of its own range.

    Two forms exist, and both count frames inclusively at the end, so the last
    frame written is end - 1:

      vspipe ... -s <first> -e <last>          lsmash / ffms2 / dgdecnv /
                                               bestsource, i.e. anything that
                                               goes through a .vpy
      ... select=between(n\\,<first>\\,<last>)   the ffmpeg chunk methods

    Anything else returns None, which makes the caller refuse to split rather
    than write a chunk whose source_cmd disagrees with its start_frame.
    """
    if not isinstance(cmd, list) or not cmd:
        return None
    decoded = [osstring_decode(item) for item in cmd]
    if any(text is None for text in decoded):
        return None

    out = list(cmd)
    has_start = "-s" in decoded
    has_end = "-e" in decoded

    if has_start or has_end:
        # Half a range would silently produce the wrong frames; refuse instead.
        if not (has_start and has_end):
            return None
        for flag, value in (("-s", start), ("-e", end - 1)):
            position = decoded.index(flag)
            if position + 1 >= len(decoded) or not decoded[position + 1].isdigit():
                return None
            out[position + 1] = osstring_encode(cmd[position + 1], str(value))
        return out

    changed = False
    for position, text in enumerate(decoded):
        replaced = _SELECT_RANGE_RE.sub(
            lambda match: f"{match.group(1)}{start}{match.group(3)}{end - 1}"
                          f"{match.group(5)}", text)
        if replaced != text:
            out[position] = osstring_encode(cmd[position], replaced)
            changed = True
    return out if changed else None


def split_blocker(chunk):
    """Why this chunk cannot be split at an interior frame, or None if it can."""
    if int(chunk.get("passes") or 1) > 1:
        return "it is multi-pass, so both pieces would share one --stats file"
    # Even at passes=1 some setups hand a chunk its own stats file; two pieces
    # writing to one file at the same time would corrupt it.
    for token in chunk.get("video_params") or []:
        if str(token).split("=", 1)[0] in ("--stats", "--fpf", "--pass"):
            return f"its parameters include {str(token).split('=', 1)[0]}, which is " \
                   f"per-chunk state the pieces would share"
    if retarget_source_cmd(chunk.get("source_cmd"), 0, 2) is None:
        return "its source_cmd has no frame range AfterZone recognizes"
    if chunk.get("proxy_cmd") is not None and \
            retarget_source_cmd(chunk.get("proxy_cmd"), 0, 2) is None:
        return "its proxy_cmd has no frame range AfterZone recognizes"
    return None


def split_chunk(chunk, start, end):
    """A copy of `chunk` covering frames [start, end) only."""
    piece = copy.deepcopy(chunk)
    piece["start_frame"] = start
    piece["end_frame"] = end
    piece["source_cmd"] = retarget_source_cmd(chunk.get("source_cmd"), start, end)
    if chunk.get("proxy_cmd") is not None:
        piece["proxy_cmd"] = retarget_source_cmd(chunk.get("proxy_cmd"), start, end)
    # A cached per-shot target-quality CQ was probed against the original frame
    # range and does not describe this one, so drop it and let av1an re-probe.
    if "per_shot_target_quality_cq" in piece:
        piece["per_shot_target_quality_cq"] = None
    return piece


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------


class PlanEntry:
    """One chunk of the rewritten chunks.json."""

    def __init__(self, chunk, old_index, zone, base, params, reencode, piece):
        self.chunk = chunk
        self.old_index = old_index    # chunk it came from, for the .ivf rename
        self.zone = zone              # None when no zone covers it
        self.base = base              # params before the zone was applied
        self.params = params
        self.reencode = reencode
        self.piece = piece            # (number, count) when part of a split
        self.new_index = None

    @property
    def is_piece(self):
        return self.piece is not None


class Plan:
    def __init__(self, original_count=0):
        self.entries = []       # every chunk of the new chunks.json, in frame order
        # (original index, start, end, reason) where a zone edge could not split.
        # The index is captured here because build_plan renumbers the chunks it
        # is handed, and this is the number the user saw in the scene map.
        self.blocked = []
        self.original_count = original_count

    @property
    def reencodes(self):
        return [entry for entry in self.entries if entry.reencode]

    @property
    def carried(self):
        return [entry for entry in self.entries if not entry.reencode]

    @property
    def split_indices(self):
        return sorted({entry.old_index for entry in self.entries if entry.is_piece})


def covering_zone(zones, start, end):
    """The last zone in file order overlapping [start, end), or None.

    Later zones win where two overlap, which is how av1an resolves them too.
    """
    found = None
    for zone in zones:
        if zone.overlaps(start, end):
            found = zone
    return found


def cut_points(chunk, zones, min_segment):
    """Zone edges strictly inside this chunk, ignoring ones that leave a sliver.

    An edge within min_segment of a chunk boundary (or of the previous edge) is
    dropped, so the zone absorbs those few frames instead of them becoming a
    chunk of their own with a keyframe all to themselves.
    """
    start, end = chunk["start_frame"], chunk["end_frame"]
    edges = {edge for zone in zones for edge in (zone.start, zone.end)
             if start < edge < end}
    kept = []
    for edge in sorted(edges):
        previous = kept[-1] if kept else start
        if edge - previous < min_segment or end - edge < min_segment:
            continue
        kept.append(edge)
    return kept


def build_plan(chunks, zones, min_segment=MIN_SPLIT_SEGMENT):
    """Map zones onto chunks, splitting chunks at zone edges where possible.

    `chunks` must be sorted by start_frame; the result is the complete new
    chunk list in the same order, renumbered from zero so that av1an's concat
    still finds a contiguous run of encode\\NNNNN files.
    """
    plan = Plan(len(chunks))
    for chunk in chunks:
        start, end = chunk["start_frame"], chunk["end_frame"]
        base = [str(token) for token in chunk.get("video_params") or []]
        cuts = cut_points(chunk, zones, min_segment)

        if cuts:
            reason = split_blocker(chunk)
            if reason:
                plan.blocked.append((chunk["index"], start, end, reason))
                cuts = []

        bounds = [start] + cuts + [end]
        segments = []
        for piece_start, piece_end in zip(bounds, bounds[1:]):
            zone = covering_zone(zones, piece_start, piece_end)
            if zone is None:
                params = base
            elif zone.reset:
                params = list(zone.params)
            else:
                params = merge_params(base, zone.params)

            # Two zones meeting inside a chunk, or a zone that resolves to the
            # parameters the chunk already had, need no split between them --
            # and no keyframe.
            if segments and segments[-1][3] == params:
                previous = segments[-1]
                segments[-1] = (previous[0], piece_end, zone or previous[2], params)
            else:
                segments.append((piece_start, piece_end, zone, params))

        for number, (piece_start, piece_end, zone, params) in enumerate(segments, 1):
            if len(segments) == 1:
                entry_chunk = chunk
                piece = None
                reencode = zone is not None
            else:
                entry_chunk = split_chunk(chunk, piece_start, piece_end)
                piece = (number, len(segments))
                # The encoded chunk file covers the whole original range and
                # cannot be cut, so every piece has to be encoded again --
                # including the pieces no zone touches.
                reencode = True

            # A copy per piece: several pieces of one chunk can resolve to the
            # same list, and they must not end up sharing it in chunks.json.
            entry_chunk["video_params"] = list(params)
            plan.entries.append(PlanEntry(entry_chunk, chunk["index"], zone,
                                          base, list(params), reencode, piece))

    for new_index, entry in enumerate(plan.entries):
        entry.new_index = new_index
        entry.chunk["index"] = new_index
    return plan


def print_plan(job, plan, chunks, done_map, fps, total_frames):
    hr()
    print(f"{BOLD}Plan for {os.path.basename(job.source)}{RESET}")
    hr()
    print(f"av1an folder: {job.hash_dir}")
    print(f"Chunks total: {len(chunks)}   already encoded: {len(done_map)}")
    if plan.split_indices:
        print(f"Chunks split at a zone edge: {len(plan.split_indices)}   "
              f"chunks.json: {plan.original_count} -> {len(plan.entries)} entries")
    if plan.blocked:
        print()
        for index, start, end, reason in plan.blocked:
            print(f"{YELLOW}[AfterZone] Chunk {index:05d} ({start}-{end}) cannot be "
                  f"split because {reason}.{RESET}")
        print(f"{YELLOW}            The zone applies across its whole range "
              f"instead.{RESET}")

    probing = [entry for entry in plan.reencodes
               if (entry.chunk.get("target_quality") or {}).get("target") is not None]
    if probing:
        print()
        print(f"{YELLOW}[AfterZone] Target quality is on for {len(probing)} chunk(s) "
              f"being re-encoded. av1an probes{RESET}")
        print(f"{YELLOW}            for its own CQ, which overrides a --crf set by a "
              f"zone. Split pieces are{RESET}")
        print(f"{YELLOW}            re-probed, because the cached CQ belonged to the "
              f"whole original chunk.{RESET}")
    print()
    print(f"{'chunk':>6}  {'from':>11}  {'frames':>15}  {'timecode':>19}  "
          f"{'size':>10}  changes")

    reencode_frames = 0
    reencode_bytes = 0
    counted = set()
    for entry in plan.reencodes:
        chunk = entry.chunk
        start, end = chunk["start_frame"], chunk["end_frame"]
        old_name = f"{entry.old_index:05d}"
        reencode_frames += end - start

        # done.json sizes are per original chunk, so a split chunk's size is
        # shown once and counted once rather than per piece.
        size = int((done_map.get(old_name) or {}).get("size_bytes") or 0)
        if entry.old_index in counted:
            size_text = ""
        else:
            counted.add(entry.old_index)
            reencode_bytes += size
            size_text = human_bytes(size)

        origin = old_name if entry.piece is None \
            else f"{old_name} {entry.piece[0]}/{entry.piece[1]}"
        if entry.zone is None:
            changes = f"{BLUE}unchanged, re-encoded because of the split{RESET}"
        elif entry.zone.reset:
            changes = "reset (params replaced)"
        else:
            changes = params_summary(entry.base, entry.params)
        timecode = (frames_to_timecode(start, fps) + " - "
                    + frames_to_timecode(end, fps))
        print(f"{entry.new_index:05d}   {origin:>11}  {f'{start}-{end}':>15}  "
              f"{timecode:>19}  {size_text:>10}  {changes}")

    print()
    print(f"Chunks to re-encode: {len(plan.reencodes)} of {len(plan.entries)}")
    print(f"Frames to re-encode: {reencode_frames:,} of {total_frames:,} "
          f"({reencode_frames * 100.0 / max(1, total_frames):.1f}%)")
    print(f"Encoded data being replaced: {human_bytes(reencode_bytes)}")
    if plan.split_indices:
        shifted = sum(1 for entry in plan.carried
                      if entry.old_index != entry.new_index)
        print()
        print(f"{BOLD}Splitting renumbers chunks.{RESET} Pieces marked 'unchanged' "
              f"keep the parameters they")
        print("were encoded with, but still have to be encoded again: the existing "
              "chunk")
        print("file covers the whole original range and cannot be cut in half. A "
              "keyframe")
        print("is placed at each split, exactly as --zones would have during the "
              "first encode.")
        if shifted:
            print(f"{shifted} finished chunk file(s) are renamed to keep the "
                  f"numbering contiguous.")
    print()
    print("Everything else is reused from the existing encode and will not be")
    print("re-encoded. The replaced .ivf chunks are moved to an afterzone-backup")
    print("folder rather than deleted, so nothing is lost if you change your mind.")
    hr()


# ---------------------------------------------------------------------------
# applying the plan
# ---------------------------------------------------------------------------


def apply_plan(job, plan, done_data):
    """Rewrite chunks.json / done.json and move the replaced chunk files aside.

    Order matters. Everything being re-encoded leaves encode\\ first, then the
    surviving files are renamed into their new numbering from the highest index
    down. Splitting only ever inserts chunks, so a chunk's new index is never
    lower than its old one, which makes descending order collision-free.
    """
    backup_dir = os.path.join(job.hash_dir, "afterzone-backup")
    os.makedirs(backup_dir, exist_ok=True)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    for name in ("chunks.json", "done.json"):
        source = os.path.join(job.hash_dir, name)
        if os.path.exists(source):
            shutil.copy2(source, os.path.join(backup_dir, f"{name}.{stamp}.bak"))
    print(f"[AfterZone] Backed up chunks.json and done.json to {backup_dir}")

    encode_dir = os.path.join(job.hash_dir, "encode")
    done_map = done_data.get("done") or {}

    extensions = {}
    for entry in plan.entries:
        extensions.setdefault(entry.old_index, entry.chunk.get("output_ext") or "ivf")

    replaced = sorted({entry.old_index for entry in plan.reencodes})
    renames = [(entry.old_index, entry.new_index, extensions[entry.old_index])
               for entry in plan.carried if entry.old_index != entry.new_index]

    # Written before anything moves, so an interrupted run can be reconstructed
    # by hand: this says what encode\ was supposed to end up looking like.
    journal_path = os.path.join(backup_dir, f"rename-map.{stamp}.json")
    with open(journal_path, "w", encoding="utf-8") as handle:
        json.dump({
            "chunks_before": plan.original_count,
            "chunks_after": len(plan.entries),
            "moved_to_backup": [f"{index:05d}.{extensions[index]}"
                                for index in replaced],
            "renames": [{"from": f"{old:05d}.{ext}", "to": f"{new:05d}.{ext}"}
                        for old, new, ext in renames],
        }, handle, indent=2)
    if renames:
        print(f"[AfterZone] Wrote {os.path.basename(journal_path)} to "
              f"afterzone-backup\\ before renaming anything")

    moved = 0
    missing = 0
    for index in replaced:
        name = f"{index:05d}.{extensions[index]}"
        source = os.path.join(encode_dir, name)
        if os.path.exists(source):
            destination = os.path.join(backup_dir, name)
            if os.path.exists(destination):
                os.remove(destination)
            shutil.move(source, destination)
            moved += 1
        else:
            missing += 1

    print(f"[AfterZone] Moved {moved} encoded chunk(s) out of encode\\ "
          f"into afterzone-backup\\")
    if missing:
        print(f"{YELLOW}[AfterZone] {missing} chunk file(s) were already absent "
              f"from encode\\.{RESET}")

    renamed = 0
    for old_index, new_index, ext in sorted(renames, reverse=True):
        source = os.path.join(encode_dir, f"{old_index:05d}.{ext}")
        destination = os.path.join(encode_dir, f"{new_index:05d}.{ext}")
        if not os.path.exists(source):
            continue                      # never finished in the original encode
        if os.path.exists(destination):
            die(f"encode\\{new_index:05d}.{ext} already exists, so renumbering "
                f"would overwrite it.\n"
                f"            Nothing else has been changed: chunks.json and "
                f"done.json are still the originals.\n"
                f"            Restore encode\\ using {journal_path} and the "
                f"backups in {backup_dir}.")
        os.replace(source, destination)
        renamed += 1
    if renamed:
        print(f"[AfterZone] Renamed {renamed} finished chunk file(s) to keep the "
              f"numbering contiguous")

    # av1an skips a chunk when done.json holds its name, so entries have to
    # follow their chunk to its new number, and re-encoded chunks lose theirs.
    done_data["done"] = {
        f"{entry.new_index:05d}": done_map[f"{entry.old_index:05d}"]
        for entry in plan.carried if f"{entry.old_index:05d}" in done_map
    }

    # Stale concat leftovers from the previous run; av1an regenerates these.
    stale = (glob.glob(os.path.join(job.hash_dir, "group_options_*.json"))
             + glob.glob(os.path.join(job.hash_dir, "group_output_*.mkv"))
             + glob.glob(os.path.join(job.hash_dir, "options.json")))
    for path in stale:
        destination = os.path.join(backup_dir, os.path.basename(path))
        if os.path.exists(destination):
            os.remove(destination)
        shutil.move(path, destination)
    if stale:
        print(f"[AfterZone] Moved {len(stale)} stale concat file(s) aside so av1an "
              f"rebuilds them.")

    with open(job.chunks_path, "w", encoding="utf-8") as handle:
        json.dump([entry.chunk for entry in plan.entries], handle)
    with open(job.done_path, "w", encoding="utf-8") as handle:
        json.dump(done_data, handle)
    print(f"[AfterZone] Rewrote chunks.json ({len(plan.entries)} chunk(s), "
          f"{len(plan.reencodes)} to encode) and done.json "
          f"({len(done_data['done'])} chunk(s) still done).")
    return backup_dir


def repair_vpy_paths(vpy_path, video_input_dir):
    """Fix ffindex/source paths in the .vpy that moved when temp was relocated.

    Auto-Boost moves the working folder out of video-input after encoding,
    which leaves the cachefile= path inside the generated .vpy pointing
    somewhere that no longer exists. Left alone that forces a full re-index (or
    fails outright), so point it at the index file that is actually sitting
    next to the script.
    """
    try:
        with open(vpy_path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return False

    vpy_dir = os.path.dirname(os.path.abspath(vpy_path))
    stem = Path(vpy_path).stem
    original = text

    def strip_prefix(path):
        return path[4:] if path.startswith("\\\\?\\") else path

    def has_prefix(path):
        return path.startswith("\\\\?\\")

    for keyword in ("cachefile", "source"):
        match = re.search(keyword + r'\s*=\s*r"([^"]*)"', text)
        if not match:
            continue
        current = match.group(1)
        plain = strip_prefix(current)
        if os.path.exists(plain):
            continue

        replacement = None
        if keyword == "cachefile":
            for candidate in (os.path.join(vpy_dir, f"{stem}.ffindex"),
                              os.path.join(vpy_dir, os.path.basename(plain))):
                if os.path.exists(candidate):
                    replacement = candidate
                    break
            if replacement is None and os.path.isdir(vpy_dir):
                # No index yet: let ffms2 write one next to the script.
                replacement = os.path.join(vpy_dir, f"{stem}.ffindex")
        else:
            for ext in VIDEO_EXTS:
                candidate = os.path.join(video_input_dir, f"{stem}{ext}")
                if os.path.exists(candidate):
                    replacement = candidate
                    break

        if replacement:
            new_value = ("\\\\?\\" + replacement) if has_prefix(current) else replacement
            text = text.replace(f'{keyword}=r"{current}"', f'{keyword}=r"{new_value}"')
            text = text.replace(f'{keyword} = r"{current}"', f'{keyword} = r"{new_value}"')
            print(f"[AfterZone] Repaired stale {keyword} path in "
                  f"{os.path.basename(vpy_path)}")

    if text != original:
        shutil.copy2(vpy_path, vpy_path + ".afterzone.bak")
        with open(vpy_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        return True
    return False


def baseline_video_params(plan):
    """The commonest params among unzoned chunks: a sane -v for av1an.

    On --resume av1an takes each chunk's params from chunks.json, so this only
    exists so av1an has a coherent global -v to validate and log.
    """
    pool = [tuple(str(token) for token in (entry.chunk.get("video_params") or []))
            for entry in plan.entries if entry.zone is None]
    if not pool:
        pool = [tuple(str(token) for token in (entry.chunk.get("video_params") or []))
                for entry in plan.entries]
    if not pool:
        return []
    return list(Counter(pool).most_common(1)[0][0])


def find_scenes_file(job, temp_dir, video_input_dir):
    """An existing scenes file stops av1an redoing scene detection on resume.

    Auto-Boost writes <name>_scenes.json into the working folder; av1an-only
    .bat files pass av1an a temp\\<name>_scenedetect.json instead, and their
    working folder is video-input, so both roots are searched.
    """
    for candidate in (os.path.join(job.work_dir, f"{job.stem}_scenes.json"),
                      os.path.join(job.work_dir, "scenes.json"),
                      os.path.join(job.hash_dir, "scenes.json"),
                      os.path.join(temp_dir, f"{job.stem}_scenedetect.json"),
                      os.path.join(temp_dir, f"{job.stem}_scenes.json"),
                      os.path.join(video_input_dir, f"{job.stem}_scenedetect.json"),
                      os.path.join(video_input_dir, f"{job.stem}_scenes.json")):
        if os.path.exists(candidate):
            return candidate
    return None


def find_vpy_file(job, temp_dir, video_input_dir):
    """The .vpy av1an was originally given.

    Auto-Boost keeps it in the working folder. av1an-only .bat files leave the
    working folder in video-input but pass av1an an absolute path to a script
    in temp\\, so that is checked too.
    """
    name = f"{job.stem}.vpy"
    for candidate in (os.path.join(job.work_dir, name),
                      os.path.join(temp_dir, name),
                      os.path.join(video_input_dir, name),
                      os.path.join(temp_dir, job.stem, name)):
        if os.path.exists(candidate):
            return candidate
    return None


def run_av1an(job, av1an_exe, temp_dir, video_input_dir, workers, video_params):
    """Re-run av1an with --resume in the original working folder."""
    vpy_name = f"{job.stem}.vpy"
    vpy_path = find_vpy_file(job, temp_dir, video_input_dir)
    if vpy_path is None:
        die(f"VapourSynth script not found: {os.path.join(job.work_dir, vpy_name)}\n"
            f"            av1an needs the same input script it originally used.\n"
            f"            Also looked in {temp_dir}")
    repair_vpy_paths(vpy_path, video_input_dir)

    # av1an resolves -i against its cwd, which is job.work_dir. A script sitting
    # in the working folder is passed by name, because chunks.json's source_cmd
    # is relative in that case too; a script anywhere else is passed absolute,
    # exactly as av1an-dispatch.py does for the av1an-only .bat files.
    if os.path.dirname(os.path.abspath(vpy_path)) == os.path.abspath(job.work_dir):
        input_arg = vpy_name
    else:
        input_arg = os.path.abspath(vpy_path)

    av1_output = f"{job.stem}-av1.mkv"
    stale_output = os.path.join(job.work_dir, av1_output)
    if os.path.exists(stale_output):
        os.remove(stale_output)

    cmd = [
        av1an_exe,
        "-i", input_arg,
        "-e", "svt-av1",
        "--no-defaults",
        "--temp", os.path.basename(job.hash_dir),      # the existing .<hash> folder
        "--resume",                                    # reuse chunks.json / done.json
        "--keep",
        "-y",
        "-x", "0",
        "-w", str(workers),
        "-o", av1_output,
    ]
    if video_params:
        cmd.extend(["-v", " ".join(video_params)])

    scenes = find_scenes_file(job, temp_dir, video_input_dir)
    if scenes:
        cmd.extend(["-s", scenes])
    else:
        print(f"{YELLOW}[AfterZone] No scenes file found; av1an may redo scene "
              f"detection (the chunk list still comes from chunks.json).{RESET}")

    hr()
    print(f"{BOLD}Running av1an{RESET}")
    print(f"Working folder: {job.work_dir}")
    print(f"Command: {' '.join(cmd)}")
    hr()

    started = time.monotonic()
    try:
        if wakepy_keep is not None:
            with wakepy_keep.running():
                subprocess.check_call(cmd, cwd=job.work_dir)
        else:
            subprocess.check_call(cmd, cwd=job.work_dir)
    except subprocess.CalledProcessError as exc:
        die(f"av1an failed with exit code {exc.returncode}.\n"
            f"            Your original chunks are in "
            f"{os.path.join(job.hash_dir, 'afterzone-backup')}")
    elapsed = time.monotonic() - started
    print(f"{GREEN}[AfterZone] av1an finished in "
          f"{int(elapsed // 60)}m {int(elapsed % 60)}s{RESET}")
    return stale_output


def read_encoding_settings_tag(mkv_path, tools_dir):
    """Return the ENCODING_SETTINGS tag of an existing mkv, or None."""
    mkvextract = os.path.join(tools_dir, "MKVToolNix", "mkvextract.exe")
    if not mkv_path or not os.path.exists(mkv_path) or not os.path.exists(mkvextract):
        return None

    xml = b""
    # New syntax first, then the older "mode first" form for good measure.
    for cmd in ([mkvextract, mkv_path, "tags"], [mkvextract, "tags", mkv_path]):
        try:
            result = subprocess.run(cmd, capture_output=True)
        except OSError:
            return None
        if result.returncode == 0 and result.stdout.strip():
            xml = result.stdout
            break
    if not xml.strip():
        return None

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None
    for simple in root.iter("Simple"):
        name = (simple.findtext("Name") or "").strip().upper()
        if name == "ENCODING_SETTINGS":
            value = (simple.findtext("String") or "").strip()
            if value:
                return value
    return None


def apply_encoding_settings_tag(mkv_path, settings, tools_dir):
    """Write settings into the video track's ENCODING_SETTINGS tag. True on success."""
    mkvpropedit = os.path.join(tools_dir, "MKVToolNix", "mkvpropedit.exe")
    if not os.path.exists(mkvpropedit):
        return False

    xml = (
        '<?xml version="1.0"?>\n'
        "<Tags>\n  <Tag>\n    <Targets>\n      <TrackUID>1</TrackUID>\n"
        "    </Targets>\n    <Simple>\n      <Name>ENCODING_SETTINGS</Name>\n"
        f"      <String>{xml_escape(settings)}</String>\n"
        "    </Simple>\n  </Tag>\n</Tags>\n"
    )
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode="w",
                                    encoding="utf-8") as tmp:
        tmp.write(xml)
        tmp_path = tmp.name
    try:
        subprocess.run([mkvpropedit, mkv_path, "--tags", "track:v1:" + tmp_path],
                       check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, OSError):
        return False
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def tag_and_mux(job, av1_path, tools_dir, temp_dir, video_output_dir):
    """Reuse av1an-tag.py and av1an-mux.py exactly as av1an-dispatch.py does."""
    if not os.path.exists(av1_path):
        die(f"av1an did not produce {av1_path}")

    final = os.path.join(video_output_dir, f"{job.stem}-afterzone.mkv")

    # The encoder settings of this encode are the ones from the original run, so
    # inherit the ENCODING_SETTINGS tag from the finished output instead of
    # rebuilding it from whatever .bat happens to be marked as active now.
    reference = find_encoded_output(video_output_dir, job.stem)
    inherited = None
    if reference and os.path.abspath(reference) != os.path.abspath(final):
        inherited = read_encoding_settings_tag(reference, tools_dir)
        if inherited:
            print(f"[AfterZone] Encoder settings taken from "
                  f"{os.path.basename(reference)}")

    # Both helpers run with cwd=temp and glob *-av1.mkv there.
    staged = os.path.join(temp_dir, f"{job.stem}-av1.mkv")
    if os.path.abspath(staged) != os.path.abspath(av1_path):
        if os.path.exists(staged):
            os.remove(staged)
        shutil.move(av1_path, staged)
        print(f"[AfterZone] Moved encode to {staged}")

    tag_script = os.path.join(tools_dir, "av1an-tag.py")
    mux_script = os.path.join(tools_dir, "av1an-mux.py")

    if inherited:
        print("[AfterZone] Applying inherited encoder-settings tag...")
        if not apply_encoding_settings_tag(staged, inherited, tools_dir):
            print(f"{YELLOW}[AfterZone] Warning: could not copy the encoder-settings "
                  f"tag.{RESET}")
            inherited = None
    else:
        print("[AfterZone] Applying encoder-settings tag...")
        try:
            subprocess.check_call([sys.executable, tag_script], cwd=temp_dir)
        except subprocess.CalledProcessError:
            print(f"{YELLOW}[AfterZone] Warning: tagging reported an error.{RESET}")

    print("[AfterZone] Muxing audio, subtitles and chapters back in...")
    try:
        subprocess.check_call([sys.executable, mux_script], cwd=temp_dir)
    except subprocess.CalledProcessError:
        die("Muxing failed.")

    muxed = os.path.join(temp_dir, f"{job.stem}-output.mkv")
    if not os.path.exists(muxed):
        die(f"Expected muxed file not found: {muxed}")

    if os.path.exists(final):
        print(f"{YELLOW}[AfterZone] Replacing existing {final}{RESET}")
        os.remove(final)
    shutil.move(muxed, final)

    # mkvmerge may or may not carry track tags across, so stamp the finished file.
    if inherited and not apply_encoding_settings_tag(final, inherited, tools_dir):
        print(f"{YELLOW}[AfterZone] Warning: could not write the encoder-settings tag "
              f"to {os.path.basename(final)}.{RESET}")
    return final


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def print_intro(fork):
    hr()
    print(f"{BOLD}AfterZone{RESET}")
    hr()
    print("AfterZone will use a zones.txt after your encoding is already finished.")
    print("It will remove encoded chunks from the av1an folder and edit json files so")
    print("av1an only encodes chunks that need new settings.")
    print()
    print("Zone edges do not have to line up with av1an's chunks. An edge inside a")
    print("chunk splits that chunk, the same way --zones would have during a fresh")
    print("encode, so only the frames you name get the new settings. The rest of a")
    print("split chunk is re-encoded unchanged, because a finished chunk cannot be")
    print("cut in half.")
    print()
    print(f"{BLUE}It will use whatever svt-av1 fork was used last:{RESET}")
    print(f"  {fork}")
    print("  (that is tools\\av1an\\SvtAv1EncApp.exe, put there by the last .bat you")
    print("   ran. Run that .bat again first if you want a different fork.)")
    print()
    print("A zones.txt that matches the input video's filename is required, placed")
    print("alongside the input file in the video-input folder.")
    print("  example.mkv  ->  video-input\\example.txt")
    print()
    print("Output is written to video-output as <name>-afterzone.mkv. Your original")
    print("<name>-output.mkv is left alone so you can compare the two.")
    hr()
    print()


def main():
    script_path = os.path.abspath(__file__)
    tools_dir = os.path.dirname(script_path)
    root_dir = os.path.dirname(tools_dir)

    video_input_dir = os.path.join(root_dir, "video-input")
    video_output_dir = os.path.join(root_dir, "video-output")
    temp_dir = os.path.join(root_dir, "temp")

    av1an_exe = os.path.join(tools_dir, "av1an", "av1an.exe")
    ffprobe_exe = os.path.join(tools_dir, "av1an", "ffprobe.exe")

    # Match the PATH the .bat files set, so this also works when run directly.
    for entry in (os.path.join(root_dir, "VapourSynth"),
                  os.path.join(tools_dir, "av1an"),
                  os.path.join(tools_dir, "MKVToolNix")):
        if os.path.isdir(entry):
            os.environ["PATH"] = entry + os.pathsep + os.environ.get("PATH", "")

    if not os.path.exists(av1an_exe):
        die(f"av1an.exe not found at {av1an_exe}")
    for directory in (video_input_dir, video_output_dir):
        if not os.path.isdir(directory):
            short = os.path.join(os.path.basename(root_dir),
                                 os.path.relpath(directory, root_dir))
            die("Required folder is missing, this tool is for reencoding scenes "
                f"after an output mkv and associated temp files already exist: {short}")
    # temp\ holds the av1an folder for Auto-Boost encodes, but for av1an-only
    # ones it may hold nothing AfterZone needs. It is still where tagging and
    # muxing run, so make sure it exists rather than refusing to start.
    os.makedirs(temp_dir, exist_ok=True)

    print_intro(svt_av1_version(tools_dir))

    jobs, sources, orphans = discover_jobs(video_input_dir, temp_dir)
    if not jobs:
        print(f"{RED}[AfterZone] No finished av1an encode found to work with.{RESET}")
        print()
        if not sources:
            print("There is no video in video-input. AfterZone needs the original")
            print("input file still sitting there.")
        else:
            print("Found these inputs but no matching av1an working folder:")
            for source in sources:
                stem = Path(source).stem
                print(f"  {os.path.basename(source)}  ->  looked for "
                      f"temp\\{stem}\\.<hash>\\chunks.json, "
                      f"video-input\\{stem}\\.<hash>\\chunks.json")
                print(f"      and any video-input\\.<hash>\\chunks.json naming "
                      f"{stem}.vpy")
            print()
            print("AfterZone needs the av1an temp folder that the encode left behind,")
            print("which only survives when the encode ran with --keep and cleanup did")
            print("not remove it.")
            if orphans:
                print()
                print(f"{YELLOW}These av1an folders are in video-input but none of "
                      f"them names an input file that is still there:{RESET}")
                for hash_dir in orphans:
                    print(f"  {hash_dir}")
                print("Put the matching source video back in video-input, under the")
                print("name it had when it was encoded.")
        sys.exit(1)

    if orphans:
        print(f"{YELLOW}[AfterZone] Ignoring {len(orphans)} av1an folder(s) in "
              f"video-input with no matching input file:{RESET}")
        for hash_dir in orphans:
            print(f"  {os.path.basename(hash_dir)}")
        print()

    if len(jobs) > 1:
        print(f"Found {len(jobs)} finished encode(s) with av1an folders still present:")
        for job in jobs:
            print(f"  {os.path.basename(job.source)}")
        print()

    workers = read_worker_count(tools_dir)
    processed = []

    for job in jobs:
        hr()
        print(f"{BOLD}{os.path.basename(job.source)}{RESET}")
        hr()

        try:
            with open(job.chunks_path, "r", encoding="utf-8") as handle:
                chunks_data = json.load(handle)
            with open(job.done_path, "r", encoding="utf-8") as handle:
                done_data = json.load(handle)
        except (OSError, ValueError) as exc:
            print(f"{RED}[AfterZone] Could not read av1an's json files: {exc}{RESET}")
            continue

        if not isinstance(chunks_data, list) or not chunks_data:
            print(f"{RED}[AfterZone] chunks.json is empty or not a list; skipping.{RESET}")
            continue

        chunks = sorted(chunks_data, key=lambda c: c.get("start_frame", 0))
        done_map = done_data.get("done") or {}
        total_frames = int(done_data.get("frames") or 0) or max(
            c["end_frame"] for c in chunks)
        fps = float(chunks[0].get("frame_rate") or 24.0)

        pending = [c for c in chunks if f"{c['index']:05d}" not in done_map]
        if pending:
            print(f"{YELLOW}[AfterZone] {len(pending)} chunk(s) were never finished in "
                  f"the original encode.{RESET}")
            print("            They will be encoded too. Zones still apply normally.")

        zones_path = os.path.join(video_input_dir, f"{job.stem}.txt")
        if not os.path.exists(zones_path):
            print(f"{RED}No zones file found: {zones_path}{RESET}")
            print()
            print("AfterZone needs to know which frame ranges to re-encode.")
            print()
            print(f"  {BOLD}1{RESET} - Auto-generate a zones.txt I can edit.")
            print("      AfterZone measures the bitrate of the finished encode and")
            print("      writes zone lines covering every region whose bitrate is at")
            print(f"      least {int((BITRATE_ZONE_THRESHOLD - 1) * 100)}% higher than "
                  f"the majority of the video.")
            print("      This only reads the file. Nothing is deleted or re-encoded.")
            print(f"  {BOLD}2{RESET} - Exit so I can write my own zones.txt.")
            print("      See zones-example.txt in the package root for the format.")
            print()
            choice = ask("Enter 1 or 2: ", {"1", "2"})
            print()
            if choice == "2":
                print("Exiting. Create "
                      f"{os.path.join('video-input', job.stem + '.txt')} "
                      "and run AfterZone again.")
                continue
            generate_zones_file(job, chunks, total_frames, fps, zones_path,
                                video_output_dir, ffprobe_exe)
            continue

        print(f"Zones file: {zones_path}")
        zones = parse_zones_file(zones_path, total_frames)
        if not zones:
            print(f"{RED}[AfterZone] No usable zone lines in {zones_path}; "
                  f"skipping.{RESET}")
            continue
        print(f"Parsed {len(zones)} zone(s), video is {total_frames:,} frames "
              f"at {fps:.3f} fps.")

        for zone in zones:
            normalized = zone.encoder.lower().replace("-", "_")
            chunk_encoder = str(chunks[0].get("encoder") or "").lower()
            if chunk_encoder and normalized != chunk_encoder:
                print(f"{YELLOW}[AfterZone] Line {zone.line_number}: zone encoder "
                      f"'{zone.encoder}' does not match the encode's "
                      f"'{chunk_encoder}'. Continuing; parameters are passed through "
                      f"as written.{RESET}")

        plan = build_plan(chunks, zones)
        if not plan.reencodes:
            print(f"{RED}[AfterZone] No chunk overlaps any zone; nothing to do.{RESET}")
            continue

        print_plan(job, plan, chunks, done_map, fps, total_frames)
        if ask("Proceed and re-encode these chunks? [y/n]: ", {"y", "n"}) != "y":
            print("Nothing was changed. Exiting.")
            continue
        print()

        apply_plan(job, plan, done_data)
        av1_path = run_av1an(job, av1an_exe, temp_dir, video_input_dir, workers,
                             baseline_video_params(plan))
        final = tag_and_mux(job, av1_path, tools_dir, temp_dir, video_output_dir)
        processed.append(final)

        hr()
        print(f"{GREEN}Done: {final}{RESET}")
        print(f"Original encode is untouched at "
              f"{os.path.join(video_output_dir, job.stem + '-output.mkv')}")
        print(f"Replaced chunks are kept in "
              f"{os.path.join(job.hash_dir, 'afterzone-backup')}")
        print("Delete that folder once you are happy with the result.")
        hr()

    if processed:
        print()
        print(f"{GREEN}{BOLD}AfterZone finished.{RESET}")
        for path in processed:
            print(f"  {path}")


if __name__ == "__main__":
    main()
