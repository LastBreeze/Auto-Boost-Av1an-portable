r"""
You'll need:
- VapourSynth (https://github.com/vapoursynth/vapoursynth/releases)
- "pip install anitopy pyperclip requests requests_toolbelt natsort vstools rich colorama psutil" in terminal (without quotes)
- "vsrepo install fpng lsmas sub" in terminal (without quotes) or the following installed to your usual VapourSynth plugins folder:
    - https://github.com/Mikewando/vsfpng
    - https://github.com/AkarinVS/L-SMASH-Works/releases/latest
    - https://github.com/vapoursynth/subtext/releases/latest
    - Note: plugins folder is typically found in "%AppData%\Roaming\VapourSynth\plugins64" or "C:\Program Files\VapourSynth\plugins"
- Optional: If using FFmpeg, it must be installed and in PATH.

How to use:
- Drop comp.py into a folder with the video files you want to compare.
- (Recommended) Rename your files to have the typical [Group] Show - Ep.mkv naming, since the script will try to parse the group and show name.
  e.g. [JPBD] Youjo Senki - 01.m2ts; [Vodes] Youjo Senki - 01.mkv.
- Change variables below.
- Run comp.py.

This script has been modified to run oxipng lossless compression before uploading.
"""

# Ram limit (in MB)
ram_limit = 8000

# Number of dark, bright, and high motion frames to algorithmically select.
frame_count_dark = 8
frame_count_bright = 6
frame_count_motion = 8
# Number of still frames (scenes with little to no motion) to algorithmically select.
frame_count_still = 5
# Choose your own frames to export. Does not decrease the number of algorithmically selected frames.
user_frames = []
# Number of frames to choose randomly. Completely separate from frame_count_bright, frame_count_dark, and save_frames. Will change every time you run the script.
random_frames = 8

# Save the brightness data in a text file so it doesn't have to be reanalysed next time the script is run. Frames will be reanalysed if show/movie name or episode numbers change.
# Does not save user_frames or random_frames.
save_frames = False

# Print frame info on screenshots.
frame_info = True
# Upscale videos to make the clips match the highest found res.
upscale = True
# Scale all videos to one vertical resolution. Set to 0 to disable, otherwise input the desired vertical res.
single_res = 0
# Use FFmpeg as the image renderer. If false, fpng is used instead
ffmpeg = False
# Compression level. For FFmpeg, range is 0-100. For fpng, 0 is fast, 1 is slow, 2 is uncompressed.
compression = 2

# Automatically upload to slow.pics.
slowpics = True
# Flags to toggle for slowpics settings.
hentai_flag = False
public_flag = False
# TMDB ID of show or movie being comped. Should be in the format "TV_XXXXXX" or "MOVIE_XXXXXX".
tmdbID = ""
# Remove the comparison after this many days. Set to 0 to disable.
remove_after = 0
# Number of images to upload to slow.pics in parallel. Set to 1 to upload one at a time.
upload_threads = 4
# Output slow.pics link to discord webhook. Disabled if empty.
webhook_url = r""
# Automatically open slow.pics url in default browser
browser_open = True
# Create a URL shortcut for each comparison uploaded.
url_shortcut = True
# Automatically delete the screenshot directory after uploading to slow.pics.
delete_screen_dir = False

"""
Used to trim clips, or add blank frames to the beginning of a clip.
Clips are taken in alphabetical order of the filenames.
First input can be the filename, group name, or index of the file. Second input must be an integer.

Example:
trim_dict = {0: 1000, "Vodes": 1046, 3:-50}
trim_dict_end = {"Youjo Senki - 01.mkv": 9251, 4: -12}
First clip will start at frame 1000.
Clip with group name "Vodes" will start at frame 1046.
Clip with filename "Youjo Senki - 01.mkv" will end at frame 9251.
Fourth clip will have 50 blank frames appended to its start.
Fifth clip will end 12 frames early.

Note:
If multiple files have the same group name, the trim will be applied to all of them.
"""
trim_dict = {}
trim_dict_end = {}

"""
Actively adjusts a clip's fps to a target. Useful for sources which incorrectly convert 23.976fps to 24fps.
First input can be the filename, group name, or index of the file. 
Second input must be a fraction split into a list. Numerator comes first, denominator comes second.
Second input can also be the string "set". This will make all other files, if unspecified fps, use the set file's fps.

Example:
change_fps = {0: [24, 1], 1: [24000, 1001]}
First clip will have its fps adjusted to 24
Second clip will have its fps adjusted to 23.976

Example 2:
change_fps = {0: [24, 1], "MTBB": "set"}
First clip will have its fps adjusted to 24
Every other clip will have its fps adjusted to match MTBB's

Note:
If multiple files have the same group name, the specified fps will be applied to all of them.
"""
change_fps = {}

"""
Specify which clip will be analyzed for frame selection algorithm.
Input can be the filename, group name, or index of the file.
By default will select the file which can be accessed the fastest.
"""
analyze_clip = ""

##### Advanced Settings #####

# Random seed to use in frame selection algorithm. May change selected frames. Recommended to leave as default
random_seed = 20202020
# Filename of the text file in which the brightness data will be stored. Recommended to leave as default.
frame_filename = "generated.compframes"
# Directory in which the screenshots will be kept
screen_dirname = "screens"
# Minimum time between dark, light, and random frames, in seconds. Motion frames use a quarter of this value
screen_separation = 6
# Number of frames in each direction over which the motion data will be averaged out. So a radius of 4 would take the average of 9 frames, the frame in the middle, and 4 in each direction.
# Higher value will make it less likely scene changes get picked up as motion, but may lead to less precise results.
motion_diff_radius = 4
# Ratio over the local median frame difference above which a frame is counted as a scene change.
# Scene changes are excluded from motion and still frame selection. Lower = more aggressive detection.
scene_change_sensitivity = 4.0
# Minimum luma range (brightest minus darkest pixel, 0-1) a frame needs to qualify as dark, light, or still.
# Filters out flat, empty, or single-color frames. Set to 0 to disable.
detail_thr = 0.08
# Brightness bounds for still frames, so pure black/white frames aren't selected.
still_brightness_range = [0.035, 0.850]
# Vertical resolution the frame analysis is run at. Greatly speeds up analysis of high res sources
# with near identical results. Set to 0 to analyze at full resolution.
analysis_res = 480

### Not recommended to change stuff below
import os, sys, time, textwrap, re, uuid, random, pathlib, requests, vstools, webbrowser, colorama, shutil, fractions, subprocess, statistics
import psutil, concurrent.futures
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
from rich.table import Column
from natsort import os_sorted
import anitopy as ani
import pyperclip as pc
import vapoursynth as vs
from requests import Session
from functools import partial
from collections import deque
from requests_toolbelt import MultipartEncoder
from typing import Any, Dict, List, Optional, BinaryIO, Union, Callable, TypeVar, Sequence, cast
RenderCallback = Callable[[int, vs.VideoFrame], None]
VideoProp = Union[int, Sequence[int],float, Sequence[float],str, Sequence[str],vs.VideoNode, Sequence[vs.VideoNode],vs.VideoFrame, Sequence[vs.VideoFrame],Callable[..., Any], Sequence[Callable[..., Any]]]
T = TypeVar("T", bound=VideoProp)
vs.core.max_cache_size = ram_limit
colorama.init()

#cache of opened video sources, so the same file isn't opened and indexed multiple times
source_cache = {}

def get_source(file: str) -> vs.VideoNode:
    """
    Opens a video file with LWLibavSource, reusing already opened sources.
    """

    if file not in source_cache:
        source_cache[file] = vs.core.lsmas.LWLibavSource(file)

    return source_cache[file]

#width of the description column of every progress bar. descriptions longer than this get ellipsized
progress_desc_width = 36

def get_progress() -> Progress:
    """
    Creates a progress bar with the shared layout. The description column has a fixed width
    and the bar itself a fixed width, so the bars of every progress display line up perfectly.
    """

    return Progress(
        TextColumn("{task.description}", table_column=Column(width=progress_desc_width, no_wrap=True, overflow="ellipsis")),
        BarColumn(bar_width=40),
        TextColumn("{task.completed}/{task.total}"),
        TextColumn("{task.percentage:>3.02f}%"),
        TimeRemainingColumn()
    )

def FrameInfo(clip: vs.VideoNode,
              title: str,
              style: str = "sans-serif,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,""0,0,0,0,100,100,0,0,1,2,0,7,10,10,10,1",
              newlines: int = 3,
              pad_info: bool = False) -> vs.VideoNode:
    """
    FrameInfo function stolen from awsmfunc, implemented by LibreSneed
    Prints the frame number and a title on the clip.
    Picture Type display has been removed.
    """

    def FrameProps(n: int, f: vs.VideoFrame, clip: vs.VideoNode, padding: Optional[str]) -> vs.VideoNode:
        info = f"Frame {n} of {clip.num_frames}"

        if pad_info and padding:
            info_text = [padding + info]
        else:
            info_text = [info]

        clip = vs.core.sub.Subtitle(clip, text=info_text, style=style)

        return clip

    padding_info: Optional[str] = None

    if pad_info:
        padding_info = " " + "".join(['\n'] * newlines)
        padding_title = " " + "".join(['\n'] * (newlines + 4))
    else:
        padding_title = " " + "".join(['\n'] * newlines)

    clip = vs.core.std.FrameEval(clip, partial(FrameProps, clip=clip, padding=padding_info), prop_src=clip)
    clip = vs.core.sub.Subtitle(clip, text=[padding_title + title], style=style)

    return clip

def dedupe(clip: vs.VideoNode, framelist: list, framecount: int, diff_thr: int, selected_frames: list = [], seed: int = None, motion: bool = False):
    """
    Selects frames from a list as long as they aren't too close together.
    
    :param framelist:     Detailed list of frames that has to be cut down.
    :param framecount:    Number of frames to select.
    :param seed:          Seed for `random.sample()`.
    :param diff_thr:      Minimum distance between each frame (in seconds).
    :param motion:        If enabled, the frames will be put in an ordered list, not selected randomly.

    :return:              Deduped framelist
    """

    random.seed(seed)
    thr = round(clip.fps_num / clip.fps_den * diff_thr)
    initial_length = len(selected_frames)

    while (len(selected_frames) - initial_length) < framecount and len(framelist) > 0:
        dupe = False

        #get random frame from framelist with removal. if motion, get first frame     
        if motion:
            rand = framelist.pop(0)
        else:
            rand = framelist.pop(random.randint(0, len(framelist) - 1))

        #check if it's too close to an already selected frame
        for selected_frame in selected_frames:
            if abs(selected_frame - rand) < thr:
                dupe = True
                break

        if not dupe:
            selected_frames.append(rand)

    selected_frames.sort()
    
    return selected_frames

def analyze_stats(clip: vs.VideoNode, collect_motion: bool = True, message: str = "Analyzing video"):
    """
    Analyzes a clip in a single pass, collecting per-frame statistics.

    :param clip:              Input clip.
    :param collect_motion:    Whether to also collect inter-frame motion data.
    :param message:           Progress bar message.

    :return:                  Tuple of per-frame lists: (average, minimum, maximum, motion diff).
    """

    avg_list = [0.0] * clip.num_frames
    min_list = [0.0] * clip.num_frames
    max_list = [0.0] * clip.num_frames
    diff_list = [0.0] * clip.num_frames


    #analysis runs on the luma plane only (PlaneStats already only looked at plane 0),
    #downscaled to analysis_res, which greatly cuts filter cost with near identical stats
    gray = vstools.get_y(clip)

    if analysis_res > 0 and gray.height > analysis_res:
        scaled_width = max(2, round(gray.width * analysis_res / gray.height / 2) * 2)
        gray = gray.resize.Bilinear(scaled_width, analysis_res)

    #PlaneStatsMin/Max are in the clip's native range, so normalize them to 0-1
    if gray.format.sample_type == vs.INTEGER:
        peak = (1 << gray.format.bits_per_sample) - 1
    else:
        peak = 1

    s_clip = gray.std.PlaneStats()
    prop_src = [s_clip]

    if collect_motion:
        gray_last = (vs.core.std.BlankClip(gray)[0] + gray)[:gray.num_frames]

        #make diff between frame and last frame, with prewitt (difference is white on black background)
        diff_clip = vs.core.std.MakeDiff(gray_last, gray)
        diff_clip = vs.core.std.Prewitt(diff_clip).std.PlaneStats()
        prop_src.append(diff_clip)

    #the whole filter graph is built once and stats are pulled from frame props in a single
    #async render, instead of rebuilding the graph and calling get_frame() for every frame.
    #progress is tracked manually with the shared layout, so all bars stay aligned
    with get_progress() as progress:
        task = progress.add_task(message, total=clip.num_frames)

        def collect(n, f, clip):
            stat_frames = f if isinstance(f, (list, tuple)) else [f]
            avg_list[n] = stat_frames[0].props["PlaneStatsAverage"]
            min_list[n] = stat_frames[0].props["PlaneStatsMin"] / peak
            max_list[n] = stat_frames[0].props["PlaneStatsMax"] / peak

            if collect_motion:
                diff_list[n] = stat_frames[1].props["PlaneStatsAverage"]

            progress.update(task, advance=1)

            return clip

        #render the small stats clip instead of the full res clip, so the render doesn't pass around full size frames
        eval_frames = vs.core.std.FrameEval(gray, partial(collect, clip=s_clip), prop_src=prop_src)
        vstools.clip_async_render(eval_frames)

    return avg_list, min_list, max_list, diff_list

def find_scene_changes(diff_list: list, radius: int, sensitivity: float):
    """
    Flags frames which are likely scene changes, based on how much their difference value
    spikes above the local median. Keeps cuts from being mistaken for motion, and keeps
    frames right on a cut out of the still frame pool.

    :param diff_list:      Per-frame motion difference values.
    :param radius:         Number of neighbouring frames (each direction) used for the local median.
    :param sensitivity:    Ratio over the local median above which a frame counts as a scene change.

    :return:               List of booleans, True for likely scene changes.
    """

    length = len(diff_list)
    scene = [False] * length

    for i in range(length):
        lo = max(0, i - radius)
        hi = min(length, i + radius + 1)
        neighbours = diff_list[lo:i] + diff_list[i+1:hi]

        if not neighbours:
            continue

        med = statistics.median(neighbours)

        #both a relative and a small absolute threshold, so quiet scenes don't get false positives
        if diff_list[i] > max(med * sensitivity, med + 0.01):
            scene[i] = True

    #first frame is diffed against a blank clip, so it always looks like a scene change
    if length > 0:
        scene[0] = True

    return scene

def lazylist(clip: vs.VideoNode, dark_frames: int = 25, light_frames: int = 15, motion_frames: int = 0, still_frames: int = 0,
             selected_frames: list = [], seed: int = random_seed, diff_thr: int = screen_separation, diff_radius: int = motion_diff_radius,
             stats: tuple = None, save_frames: bool = False, file: str = None, files: list = None, files_info: list = None):
    """
    Generates a list of frames for comparison purposes.

    :param clip:             Input clip.
    :param dark_frames:      Number of dark frames.
    :param light_frames:     Number of light frames.
    :param motion_frames:    Number of frames with high level of motion.
    :param still_frames:     Number of frames with little to no motion.
    :param seed:             Seed for `random.sample()`.
    :param diff_thr:         Minimum distance between each frame (in seconds).
    :param diff_radius:      Number of frames to take into account when finding high motion frames.
    :param stats:            Pre-existing analysis data tuple (avg, min, max, diff), skips reanalysis.
    :param save_frames:      If true, also returns the analysis data so it can be stored.
    :param file:             File being analyzed.
    :param files:            List of files in directory.
    :param files_info:       Information for each file in directory.

    :return:                 List of dark, light, motion, and still frames.
    """

    #if no frames were requested, return empty list before running algorithm
    if dark_frames + light_frames + motion_frames + still_frames == 0:
        if save_frames:
            return [], ([], [], [], [])
        return []

    #motion data is always collected when saving, so still/motion counts can be raised later without reanalysis
    need_motion = (motion_frames + still_frames) > 0 or save_frames

    if stats is None:

        #if group name is present, display only it and color it cyan. if group name isnt present, display file name and color it yellow.
        message = "Analyzing video"
        if file is not None and files is not None and files_info is not None:
            findex = files.index(file)
            suffix = files_info[findex].get('suffix')

            if files_info[findex].get("suffix_color") == "yellow":
                message = f'Analyzing video: [yellow]{suffix.strip()}'

            elif files_info[findex].get("suffix_color") == "cyan":
                message = f"Analyzing video: [cyan]{suffix.strip()}"

        stats = analyze_stats(clip, collect_motion=need_motion, message=message)

    avg_list, min_list, max_list, diff_list = stats
    length = min(clip.num_frames, len(avg_list), len(min_list), len(max_list))

    #flag likely scene changes so they don't contaminate motion/still selection or get picked as blended dark/light frames
    if need_motion and any(diff_list):
        scene = find_scene_changes(diff_list, diff_radius, scene_change_sensitivity)
    else:
        scene = [False] * length

    if len(scene) < length:
        scene = scene + [False] * (length - len(scene))

    def brightness_candidates(bounds: tuple, thr: float):
        cand = []
        for i in range(length):
            if scene[i]:
                continue
            if bounds[0] <= avg_list[i] <= bounds[1] and (max_list[i] - min_list[i]) >= thr:
                cand.append(i)
        return cand

    #dark and light candidates now also require some luma range, so flat, washed out, or near-empty
    #frames (fades, credits, solid backgrounds) don't get selected as representative dark/light frames
    dark = brightness_candidates((0.062746, 0.380000), detail_thr)
    light = brightness_candidates((0.450000, 0.800000), detail_thr)

    #if the detail filter leaves too few candidates, fall back to the old behavior
    if len(dark) < dark_frames * 3:
        dark = brightness_candidates((0.062746, 0.380000), 0)
    if len(light) < light_frames * 3:
        light = brightness_candidates((0.450000, 0.800000), 0)

    #remove frames that are within diff_thr seconds of other frames. for dark and light, select random frames as well
    selected_frames = dedupe(clip, dark, dark_frames, diff_thr, selected_frames, seed)
    selected_frames = dedupe(clip, light, light_frames, diff_thr, selected_frames, seed)

    #average the motion data over diff_radius frames in each direction, ignoring scene change spikes,
    #so a single cut can no longer masquerade as sustained motion
    scores = {}
    if motion_frames > 0 or still_frames > 0:
        for i in range(diff_radius, length - diff_radius):
            if scene[i]:
                continue

            window = [diff_list[j] for j in range(i - diff_radius, i + diff_radius + 1) if not scene[j]]

            if window:
                scores[i] = sum(window) / len(window)

    #find frames with most motion
    if motion_frames > 0:
        motion = [i for i, s in sorted(scores.items(), key=lambda x: x[1], reverse=True)]

        #remove frames that are too close to other frames. uses lower diff_thr because high motion frames will be different from one another
        selected_frames = dedupe(clip, motion, motion_frames, round(diff_thr/4), selected_frames, seed, motion=True)

    #find frames with little to no motion
    if still_frames > 0:

        #still frames must contain actual content: not too dark, not blown out, and with some luma range,
        #otherwise the "most still" frames end up being black screens or solid color cards
        still_cand = [i for i in scores
                      if still_brightness_range[0] <= avg_list[i] <= still_brightness_range[1]
                      and (max_list[i] - min_list[i]) >= detail_thr]

        #if the filters leave too few candidates, only require the frame not be pure black
        if len(still_cand) < still_frames * 3:
            still_cand = [i for i in scores if avg_list[i] >= still_brightness_range[0]]

        still = sorted(still_cand, key=lambda i: scores[i])

        #still frames use the full separation, since frames from the same static scene are near identical
        selected_frames = dedupe(clip, still, still_frames, diff_thr, selected_frames, seed, motion=True)

    print()

    if save_frames:
        return selected_frames, (avg_list, min_list, max_list, diff_list)
    else:
        return selected_frames

def _get_slowpics_header(content_length: str, content_type: str, sess: Session) -> Dict[str, str]:
    """
    Stolen from vardefunc, fixed by Jimbo.
    """

    return {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-US,en;q=0.9",
        "Access-Control-Allow-Origin": "*",
        "Content-Length": content_length,
        "Content-Type": content_type,
        "Origin": "https://slow.pics/",
        "Referer": "https://slow.pics/comparison",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
        "X-XSRF-TOKEN": sess.cookies.get_dict()["XSRF-TOKEN"]
    }

def get_highest_res(files: List[str]) -> int:
    """
    Finds the video source with the highest resolution from a list of files.

    :param files:    The list of files in question.

    :return:         The width, height, and filename of the highest resolution video.
    """

    height = 0
    width = 0
    filenum = -1
    for f in files:
        filenum+=1
        video = get_source(f)
        if height < video.height:
            height = video.height
            width = video.width
            max_res_file = filenum

    return width, height, max_res_file

def estimate_analysis_time(file, read_len: int=15):
    """
    Estimates the time it would take to analyze a video source.

    :param read_len:    How many frames to read from the video.
    """

    clip = get_source(file)

    #safeguard for if there arent enough frames in clip
    while clip.num_frames / 3 + 1 < read_len:
        read_len -= 1

    clip1 = clip[int(clip.num_frames / 3) : int(clip.num_frames / 3) + read_len]
    clip2 = clip[int(clip.num_frames * 2 / 3) : int(clip.num_frames * 2 / 3) + read_len]

    def checkclip(n, f, clip):
        avg = f.props["PlaneStatsAverage"]
        return clip

    start_time = time.time()
    vstools.clip_async_render(vs.core.std.FrameEval(clip1, partial(checkclip, clip=clip1.std.PlaneStats()), prop_src=clip1.std.PlaneStats()))
    elapsed_time = time.time() - start_time

    start_time = time.time()
    vstools.clip_async_render(vs.core.std.FrameEval(clip2, partial(checkclip, clip=clip2.std.PlaneStats()), prop_src=clip2.std.PlaneStats()))
    elapsed_time = (elapsed_time + time.time() - start_time)/2

    return elapsed_time

def evaluate_analyze_clip(analyze_clip, files, files_info):
    """
    Determines which file should be analyzed by lazylist.
    """

    file_analysis_default = False

    #check if analyze_clip is an int or string with just an int in it
    if (isinstance(analyze_clip, int) and analyze_clip >= 0) or (isinstance(analyze_clip, str) and analyze_clip.isdigit() and int(analyze_clip) >= 0):
        first_file = files[int(analyze_clip)]

    #check if analyze_clip is a group or file name
    elif isinstance(analyze_clip, str) and analyze_clip != "":
        matches = 0
        for dict in files_info:
            if analyze_clip == dict.get("release_group") or analyze_clip == dict.get("file_name") or analyze_clip in dict.get("file_name"):
                matches+=1
                first_file = files[files_info.index(dict)]

        #if no matches found, use default
        if matches == 0:
            printwrap('No file matching the "analyze_clip" parameter has been found. Using default.')
            file_analysis_default = True
        if matches > 1:
            printwrap('Too many files match the "analyze_clip" parameter. Using default.')

    #if no clip specified, use default
    else:
        file_analysis_default = True

    #default: pick file with smallest read time
    if file_analysis_default:
        printwrap("Determining which file to analyze...\n")
        estimated_times = [estimate_analysis_time(file) for file in files]
        first_file = files[estimated_times.index(min(estimated_times))]
    
    return first_file

def init_clip(file: str, files: list, trim_dict: dict, trim_dict_end: dict, change_fps: dict = {}, 
              analyze_clip: str = None, files_info: list = None, return_file: bool = False):
    """
    Gets trimmed and fps modified clip from video file.
    """

    #evaluate analyze_clip if it hasn't been already
    if analyze_clip is not None and file is None and first_file is None:
        file = evaluate_analyze_clip(analyze_clip, files, files_info)

    findex = files.index(file)
    clip = get_source(file)

    if trim_dict.get(findex) is not None:

        if trim_dict.get(findex) > 0:
            clip = clip[trim_dict.get(findex):]

        elif trim_dict.get(findex) < 0:
            #append blank clip to beginning of source to "extend" it
            clip = vs.core.std.BlankClip(clip)[:(trim_dict.get(findex) * -1)] + clip
            #keep count of how many blank frames were appended
            extended = trim_dict.get(findex) * -1

    if trim_dict_end.get(findex) is not None:
            clip = clip[:trim_dict_end.get(findex)]

    if change_fps.get(findex) is not None:
        clip = vstools.change_fps(clip, fractions.Fraction(numerator=change_fps.get(findex)[0], denominator=change_fps.get(findex)[1]))

    if return_file:
        return clip, file
    else:
        return clip

def get_suffixes(files_info: list, first_display: bool = False):
    """
    Gets display name ('suffix') and its color for every file based on its release group and filename.

    :param files_info:       List of dictionaries generated by anitopy for every file.
    :param first_display:    Whether or not the suffixes are being generated for the program's initial display of found files.

    :return:                 List of dictionaries for every file with 'suffix' and 'suffix_color' updated.
    """

    #if group name exists use it, otherwise use file name
    for i in range(0, len(files_info)):

        if files_info[i].get('release_group') is not None:
            files_info[i]['suffix'] = str(files_info[i].get('release_group'))
            files_info[i]['suffix_color'] = "cyan"

        else:
            files_info[i]['suffix'] = files_info[i].get('file_name')
            files_info[i]['suffix_color'] = "yellow"

    #check for duplicates
    for i in range(0, len(files_info)):
        matches = [i]

        for f in range(i + 1, len(files_info)):
            if files_info[i].get('suffix') == files_info[f].get('suffix'):
                matches.append(f)

        #if duplicates found, check whether they have version number in file name and put it in suffix
        if len(matches) > 1:
            for f in (matches):

                #don't want to rely on anitopy cause i don't know what regex it uses
                '''if files_info[f].get('release_version') != None:
                    files_info[f]['suffix'] = files_info[f].get('suffix') + " " + files_info[f].get('release_version')
                    files_info[f]['suffix_color'] = "cyan"'''

                for pos, letter in enumerate(files_info[f].get('file_name')):
                    x = 0

                    if letter.lower() == "v":
                        while files_info[f].get('file_name')[pos+1:pos+x+2].isdigit() and pos+x+2 <= len(files_info[f].get('file_name')):
                            x += 1

                        #if they do, add " vXX" to suffix
                        #also check that the match for "vXX" not in the file extension
                        if x > 0 and files_info[f].get('file_name')[pos+1:pos+x+2] not in os.path.splitext(files_info[f].get('file_name'))[1]:
                            files_info[f]['suffix'] = files_info[f].get('suffix') + " " + files_info[f].get('file_name')[pos:pos+x+1]
                            files_info[f]['suffix_color'] = "cyan"
                            break

    #check for duplicates again and just set filename this time
    for i in range(0, len(files_info)):
        matches = [i]

        for f in range(i + 1, len(files_info)):
            if files_info[i].get('suffix') == files_info[f].get('suffix'):
                matches.append(f)

        if len(matches) > 1:
            for f in (matches):
                files_info[f]['suffix'] = files_info[f].get('file_name')
                files_info[f]['suffix_color'] = "yellow"

    #if it's not the first display, only show file name up until there's a difference with another file name
    if not first_display:
        for i in range(0, len(files_info)):
            highest = 0
            highest_file = 0
            filename = files_info[i].get('file_name')

            if files_info[i].get('suffix') == filename:
                for f in range(0, len(files_info)):
                    pos = 0

                    if i == f:
                        continue

                    while files_info[i].get('file_name')[pos] == files_info[f].get('file_name')[pos]:
                        pos += 1

                    if pos > highest:
                        highest = pos
                        highest_file = f

                #progress bar should take up about half the screen, at least 2/5 of that will be used, max all of it
                #original: l_bound = 20, h_bound = 45
                consolesize = os.get_terminal_size().columns
                progress = min(round(consolesize / 2), 68)
                l_bound = round((consolesize - progress) * 2/5)
                h_bound = consolesize - progress

                #show whole filename if it fits within limit
                if len(filename) < (h_bound):
                    pass

                #put "..." at the end if the different part appears within limit
                elif highest < h_bound-3:
                    files_info[i]['suffix'] = filename[:h_bound-3].strip() + "..."

                #if section thats different starts less than "l_bound" chars away from end, put "..." in middle of name, with diff following it
                elif len(filename[highest+1:]) <= l_bound:
                    files_info[i]['suffix'] = filename[:h_bound-3-len(filename[highest+1:])].strip() + "..." + filename[highest+1:].strip()

                #if section thats different starts more than "l_bound" chars away from end, put "..." then diff in parentheses
                else:

                    for pos, letter in enumerate(filename):
                        if pos >= len(files_info[highest_file].get('file_name')):
                            break

                        if letter != files_info[highest_file].get('file_name')[pos]:
                            last_diff_pos = pos
                        
                    if last_diff_pos + 1 == len(files_info[highest_file].get('file_name')):
                        diff = filename[highest:]
                    else:
                        diff = filename[highest:last_diff_pos+1]

                    #if all of the diff fits
                    if len(diff) < (h_bound-l_bound-6):
                        files_info[i]['suffix'] = filename[:l_bound].strip() + "... (" + diff.strip() + ")"

                    #if only some of the diff fits
                    else:
                        files_info[i]['suffix'] = filename[:l_bound].strip() + "... (" + diff[:h_bound-l_bound-6].strip() + ")"

    return files_info

def str_to_number(string: str):
    """
    Converts a string to a float or int if possible.
    """

    try:
        float(string)
        try:
            int(string)
            return int(string)
        except:
            return float(string)
    except:
        return string
    
def extend_clip(clip: vs.VideoNode, frames: list):
    """
    If a clip is shorter than the largest frame that needs to be rendered, extend it.
    """

    if clip.num_frames < frames[-1]:
        clip = clip + (vs.core.std.BlankClip(clip)[0] * (frames[-1] - clip.num_frames + 1))

    return clip

def printwrap(text: str, width: int=os.get_terminal_size().columns, end: str="\n", *args, **kwargs):
    """
    Prints text with smart wrapping using textwrap.fill().

    :param text:     Text to wrap and display.
    :param width:    Width of wrapping area, based on the terminal's size by default.
    :param end:      Standard param passed on to print().

    Also passes along extra args to textwrap.fill().
    """

    print(textwrap.fill(text, width, *args, **kwargs), end=end)



def run_comparison():
    #START_TIME = time.time()

    global first_file
    first_file = None
    #first file is only determined by analyze_clip if it is called 

    supported_extensions = ('.mkv', '.m2ts', '.mp4', '.webm', '.ogm', '.mpg', '.vob', '.iso', '.ts', '.mts', '.mov', '.qv', '.yuv',
                            '.flv', '.avi', '.rm', '.rmvb', '.m2v', '.m4v', '.mp2', '.mpeg', '.mpe', '.mpv', '.wmv', '.avc', '.hevc',
                            '.264', '.265', '.av1')

    #find video files in the current directory, and exit if there are fewer than two
    files = [file for file in os.listdir('.') if file.lower().endswith(supported_extensions)]
    files = os_sorted(files)
    file_count = len(files)
    if file_count < 2:
        sys.exit("Error: Fewer than 2 video files found in directory.")

    #use anitopy library to get dictionary of show name, episode number, episode title, release group, etc
    files_info = []
    for file in files:
        files_info.append(ani.parse(file))

    anime_title = ""
    anime_episode_number = ""
    anime_episode_title = ""

    #get anime title, episode number, and episode title
    for dict in files_info:
        if dict.get('anime_title') is not None and anime_title == "":
            anime_title = dict.get('anime_title')

        if dict.get('episode_number') is not None and anime_episode_number == "":
            anime_episode_number = dict.get('episode_number')

        if dict.get('episode_title') is not None and anime_episode_title == "":
            anime_episode_title = dict.get('episode_title')

    #what to name slow.pics collection
    if anime_title != "" and anime_episode_number != "":
        collection_name = anime_title.strip() + " - " + anime_episode_number.strip()
    elif anime_title != "":
        collection_name = anime_title.strip()
    elif anime_episode_title != "":
        collection_name = anime_episode_title.strip()
    else:
        collection_name = files_info[0].get('file_name')
        collection_name = re.sub(r"\[.*?\]|\(.*?\}|\{.*?\}|\.[^.]+$", "", collection_name).strip()
    
    #if anime title still isn't found, give it collection name
    if anime_title == "":
        anime_title = collection_name

    #replace group or file names in trim_dict with file index
    for d in [trim_dict, trim_dict_end, change_fps]:
        for i in list(d):
            if isinstance(i, str):
                found = False

                for dict in files_info:
                    if i == dict.get("release_group") or i == dict.get("file_name"): # or i in dict.get("file_name")
                        d[files_info.index(dict)] = d[i]
                        found = True

                if found:
                    d.pop(i)

    #detects and sets up change_fps "set" feature
    if (list(change_fps.values())).count("set") > 0:
        if (list(change_fps.values())).count("set") > 1:
            sys.exit('Error: More than one change_fps file using "set".')
        
        #if "set" is found, get the index of its file, get its fps, and set every other unspecified file to that fps
        findex = list(change_fps.keys())[list(change_fps.values()).index("set")]
        del change_fps[findex]
        file = files[findex]
        temp_clip = get_source(file)
        fps = [temp_clip.fps_num, temp_clip.fps_den]

        for i in range(0, len(files)):
            if i not in change_fps:
                change_fps[i] = fps

    #if file is already set to certain fps, remove it from change_fps
    #only checked when change_fps has entries, so every file doesn't get opened this early
    if change_fps:
        for findex, file in enumerate(files):
            temp_clip = init_clip(file, files, trim_dict, trim_dict_end)
            if change_fps.get(findex) is not None:
                if not isinstance(change_fps.get(findex), list):
                    sys.exit("Error: change_fps parameter only accepts lists as input")
                if temp_clip.fps_num / temp_clip.fps_den == change_fps.get(findex)[0] / change_fps.get(findex)[1]:
                    del change_fps[findex]

    #get display version of suffixes
    get_suffixes(files_info, first_display=True)

    #print list of files
    print('\nFiles found: ')
    for findex, file in enumerate(files):

        groupname = files_info[findex].get("suffix")

        if files_info[findex].get("release_group") != None:
            #if group name is found, highlight
            if groupname == files_info[findex].get("release_group"):
                filename = files_info[findex].get("file_name").split(groupname)
                filename = filename[0] + colorama.Fore.CYAN + groupname + colorama.Fore.YELLOW + filename[1]

            #if group name with version number is found, highlight both group and version
            elif (files_info[findex].get("release_group") + " v") in groupname:
                v = groupname.rindex("v")
                filename = files_info[findex].get("file_name").split(groupname[:v - 1])
                filename = filename[0] + colorama.Fore.CYAN + groupname[:v - 1] + colorama.Fore.YELLOW + filename[1]
                filename = filename.split(groupname[v:])
                filename = filename[0] + colorama.Fore.CYAN + groupname[v:] + colorama.Fore.YELLOW + filename[1]
            
            #if suffix is filename but group name found, still highlight
            elif files_info[findex].get("release_group") in groupname:
                filename = files_info[findex].get("file_name").split(files_info[findex].get("release_group"))
                filename = filename[0] + colorama.Fore.CYAN + files_info[findex].get("release_group") + colorama.Fore.YELLOW + filename[1]

        #if no group name is found, dont highlight
        else:
            filename = groupname

        #output filenames
        printwrap(colorama.Fore.YELLOW + " - " + filename + colorama.Style.RESET_ALL, subsequent_indent="   ")

        #output which files will be trimmed
        if trim_dict.get(findex) is not None:
            if trim_dict.get(findex) >= 0:
                printwrap(f"     - Trimmed to start at frame {trim_dict.get(findex)}", subsequent_indent="       ")
            elif trim_dict.get(findex) < 0:
                printwrap(f"     - {(trim_dict.get(findex) * -1)} frame(s) appended at start", subsequent_indent="       ")
        if trim_dict_end.get(findex) is not None:
            if trim_dict_end.get(findex) >= 0:
                printwrap(f"     - Trimmed to end at frame {trim_dict_end.get(findex)}", subsequent_indent="       ")
            elif trim_dict_end.get(findex) < 0:
                printwrap(f"     - Trimmed to end {trim_dict_end.get(findex) * -1} frame(s) early", subsequent_indent="       ")
            
        if change_fps.get(findex) is not None:
            printwrap(f"     - FPS changed to {change_fps.get(findex)[0]}/{change_fps.get(findex)[1]}", subsequent_indent="       ")
            
    print()

    #get version of suffixes that will be used in the rest of the file
    get_suffixes(files_info, first_display=False)

    #check if conflicting options are enabled
    if (upscale and single_res > 0):
        sys.exit("Error: Can't use 'upscale' and 'single_res' functions at the same time.")

    
    
    frames = []

    #add user specified frames to list
    frames.extend(user_frames)

    #analysis data of the most recently analyzed clip, used to filter the random frame pool
    last_stats = None

    #if save_frames is enabled, store generated analysis data in a text file, so it doesn't have to be analyzed again
    if save_frames and (frame_count_dark + frame_count_bright + frame_count_motion + frame_count_still) > 0:
        mismatch = False
        saved_stats = None
        #if frame file exists, read from it
        if os.path.exists(frame_filename) and os.stat(frame_filename).st_size > 0:

            printwrap(f'Reading data from "{frame_filename}"...')
            with open(frame_filename) as frame_file:
                generated_frames = frame_file.readlines()

            #turn numbers into floats or ints, and get rid of newlines
            for i, v in enumerate(generated_frames):
                v = v.strip()
                generated_frames[i] = str_to_number(v)

            #check the data file version. older versions don't store the stats the new algorithm needs
            if "version:" not in generated_frames or generated_frames[generated_frames.index("version:") + 1] != 2:
                printwrap("Saved frame data is from an older version of the script.")
                mismatch = True
            else:
                avg_list = generated_frames[generated_frames.index("brightness:")+1:generated_frames.index("brightness_min:")]
                min_list = generated_frames[generated_frames.index("brightness_min:")+1:generated_frames.index("brightness_max:")]
                max_list = generated_frames[generated_frames.index("brightness_max:")+1:generated_frames.index("motion:")]
                diff_list = generated_frames[generated_frames.index("motion:")+1:]
                saved_stats = (avg_list, min_list, max_list, diff_list)

                analyzed_file = generated_frames[generated_frames.index("analyzed_file:") + 1]
                analyzed_group = ani.parse(str(analyzed_file)).get("release_group")
                file_trim = generated_frames[generated_frames.index("analyzed_file_trim:") + 1]
                file_trim_end = generated_frames[generated_frames.index("analyzed_file_trim:") + 2]
                file_fps_num = generated_frames[generated_frames.index("analyzed_file_fps:") + 1]
                file_fps_den = generated_frames[generated_frames.index("analyzed_file_fps:") + 2]

                #check if a file with the same group name as the analyzed file is present in our current directory
                group_found = False
                for i, dict in enumerate(files_info):
                    if dict.get("release_group") is not None and analyzed_group is not None:
                        if dict.get("release_group").lower() == analyzed_group.lower():
                            group_found = True
                            group_file_index = files.index(dict.get("file_name"))

                #if file wasn't found but group name was, set file with the same group name
                if analyzed_file not in files and group_found is True:
                    analyzed_file = files[group_file_index]

                #check if show name, episode number, or the release which was analyzed has changed
                if (generated_frames[generated_frames.index("show_name:") + 1] != anime_title
                    or generated_frames[generated_frames.index("episode_num:") + 1] != int(anime_episode_number)
                    or analyzed_file not in files):

                    mismatch = True

                #check if trim for analyzed file has changed
                if mismatch == False:
                    found_trim = 0
                    found_trim_end = 0
                    if files.index(analyzed_file) in trim_dict:
                        found_trim = trim_dict.get(files.index(analyzed_file))
                    if files.index(analyzed_file) in trim_dict_end:
                        found_trim_end = trim_dict_end.get(files.index(analyzed_file))

                    if (file_trim != found_trim
                        or file_trim_end != found_trim_end):
                        mismatch = True

                #check if fps of analyzed file has changed
                if mismatch == False:
                    temp_clip = init_clip(analyzed_file, files, trim_dict, trim_dict_end, change_fps)
                    if file_fps_num / file_fps_den != temp_clip.fps_num / temp_clip.fps_den:
                        mismatch = True


            #if mismatch is detected, re-analyze frames
            if mismatch:
                printwrap("\nParameters have changed. Will re-analyze brightness and motion data.\n")
                os.remove(frame_filename)
                saved_stats = None

            #only spend time processing lazylist if we need to
            elif (frame_count_dark + frame_count_bright + frame_count_motion + frame_count_still) > 0:
                clip = init_clip(files[0], files, trim_dict, trim_dict_end, change_fps, analyze_clip, files_info)
                frames.extend(lazylist(clip, frame_count_dark, frame_count_bright, frame_count_motion, frame_count_still, frames, stats=saved_stats, file=files[0], files=files, files_info=files_info))
                last_stats = saved_stats

        #if frame file does not exist or has less frames than specified, write to it
        if not os.path.exists(frame_filename) or os.stat(frame_filename).st_size == 0 or mismatch:

            #if this is the first time first_file is being called, it will be evaluated. if not, it will already be known, since it's a global variable
            first, first_file = init_clip(first_file, files, trim_dict, trim_dict_end, change_fps, analyze_clip, files_info, return_file=True)

            #get the trim
            first_trim = 0
            first_trim_end = 0
            if files.index(first_file) in trim_dict:
                first_trim = trim_dict[files.index(first_file)]
            if files.index(first_file) in trim_dict_end:
                first_trim_end = trim_dict_end[files.index(first_file)]


            frames_temp, saved_stats = lazylist(first, frame_count_dark, frame_count_bright, frame_count_motion, frame_count_still, frames, save_frames=True, file=first_file, files=files, files_info=files_info)
            frames.extend(frames_temp)
            last_stats = saved_stats
            avg_list, min_list, max_list, diff_list = saved_stats

            with open(frame_filename, 'w') as frame_file:

                frame_file.write(f"version:\n2\nshow_name:\n{anime_title}\nepisode_num:\n{anime_episode_number}\nanalyzed_file:\n{first_file}\nanalyzed_file_trim:\n{first_trim}\n{first_trim_end}\nanalyzed_file_fps:\n{first.fps_num}\n{first.fps_den}\nbrightness:\n")
                for val in avg_list:
                    frame_file.write(f"{val:.6f}\n")

                frame_file.write("brightness_min:\n")
                for val in min_list:
                    frame_file.write(f"{val:.6f}\n")

                frame_file.write("brightness_max:\n")
                for val in max_list:
                    frame_file.write(f"{val:.6f}\n")

                frame_file.write("motion:\n")
                for val in diff_list:
                    frame_file.write(f"{val:.8f}\n")

    #if save_frames isn't enabled, run lazylist
    elif (frame_count_dark + frame_count_bright + frame_count_motion + frame_count_still) > 0:
        first, first_file = init_clip(first_file, files, trim_dict, trim_dict_end, change_fps, analyze_clip, files_info, return_file=True)
        frames_temp, last_stats = lazylist(first, frame_count_dark, frame_count_bright, frame_count_motion, frame_count_still, frames, save_frames=True, file=first_file, files=files, files_info=files_info)
        frames.extend(frames_temp)

    if random_frames > 0:

        print("Getting dark, bright, motion, still, random frames...\n")

        rand_clip = init_clip(files[0], files, trim_dict, trim_dict_end, change_fps)

        #get list of all frames in clip
        frame_ranges = list(range(0, rand_clip.num_frames))

        #if analysis data matching this clip is available, keep solid black frames out of the random pool
        if last_stats is not None and len(last_stats[0]) == rand_clip.num_frames:
            filtered = [i for i in frame_ranges if last_stats[0][i] >= 0.015]
            if len(filtered) >= random_frames:
                frame_ranges = filtered

        #randomly selects frames at least screen_separation seconds apart
        frame_ranges = dedupe(rand_clip, frame_ranges, random_frames, screen_separation, frames)

        frames.extend(frame_ranges)

    #remove dupes and sort
    frames = [*set(frames)]
    frames.sort()

    #if no frames selected, terminate program
    if len(frames) == 0:
        sys.exit("Error: No frames have been selected, unable to proceed.")

    #print comma separated list of which frames have been selected
    print(f"Selected {len(frames)} frames:")
    first = True
    message = ""
    for f in frames:
        if not first:
            message+=", "
        first = False
        message+=str(f)

    printwrap(message, end="\n\n")



    if upscale:
        max_width, max_height, max_res_file = get_highest_res(files)

    #create screenshot directory, if one already exists delete it first
    screen_dir = pathlib.Path("./" + screen_dirname + "/")
    if os.path.isdir(screen_dir):
        shutil.rmtree(screen_dir)
    os.mkdir(screen_dir)

    #check if ffmpeg is available. if not, run script with ffmpeg disabled
    global ffmpeg
    if ffmpeg:
        try:
            subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            ffmpeg = False
            printwrap("FFmpeg was not found. Continuing to generate screens without it.")

    print("Generating screenshots:")
    #all progress bars share the same fixed layout from get_progress(), so they align
    with get_progress() as progress:

        total_gen_progress = progress.add_task("[green]Total", total=len(frames) * len(files))
        file_gen_progress = progress.add_task("", total=len(frames), visible=0)

        for file in files:
            findex = files.index(file)

            clip = init_clip(file, files, trim_dict, trim_dict_end, change_fps)

            #extend clip if a frame is out of range
            clip = extend_clip(clip, frames)

            #get release group or filename of file
            suffix = files_info[findex].get('suffix')
            #remove any characters not suited for filepath
            suffix = suffix.replace("[\\/:\"*?<>|]+", "").strip()

            if files_info[findex].get("suffix_color") == "yellow":
                message = f'[yellow]{suffix}'

            elif files_info[findex].get("suffix_color") == "cyan":
                message = f'[cyan]{suffix}'

            else:
                message = suffix

            progress.reset(file_gen_progress, description=message, visible=1)
                
            #get matrix of clip, account for black clips added to the beginning due to negative trim
            if trim_dict.get(findex) is not None and trim_dict.get(findex) < 0:
                matrix = clip.get_frame(trim_dict.get(findex) * -1).props._Matrix
            else:
                matrix = clip.get_frame(0).props._Matrix

            #if matrix is unspecified, change it to 709
            if matrix == 2:
                matrix = 1

            #upscale depending on options selected. if none are, just convert to rgb
            if single_res > 0 and clip.height != single_res:
                clip = clip.resize.Lanczos(int(round(clip.width * (single_res / clip.height), 0)), single_res, filter_param_a=3, format=vs.RGB24, matrix_in=matrix, dither_type="error_diffusion")
            elif upscale and clip.height != max_height:
                clip = clip.resize.Lanczos(int(round(clip.width * (max_height / clip.height), 0)), max_height, filter_param_a=3, format=vs.RGB24, matrix_in=matrix, dither_type="error_diffusion")
            else:
                clip = clip.resize.Lanczos(filter_param_a=3, format=vs.RGB24, matrix_in=matrix, dither_type="error_diffusion")

            #if frame_info option selected, print frame info to screen
            if frame_info:
                clip = FrameInfo(clip, title=suffix)
            
            #generate screens
            if ffmpeg:
                for frame in frames:

                    filename = f"{screen_dir}/{frame} - {suffix}.png"

                    ffmpeg_line = f"ffmpeg -y -hide_banner -loglevel error -f rawvideo -video_size {clip.width}x{clip.height} -pixel_format gbrp -framerate {str(clip.fps)} -i pipe: -pred mixed -compression_level {compression} \"{filename}\""
                    try:
                        with subprocess.Popen(ffmpeg_line, stdin=subprocess.PIPE) as process:
                            #ffmpeg needs these planes to be shuffled so they are in gbrp pixel_format (the p is important, rgb24 format doesnt work)
                            clip[frame].std.ShufflePlanes([1, 2, 0], vs.RGB).output(cast(BinaryIO, process.stdin), y4m=False)
                    except:
                        None

                    progress.update(total_gen_progress, advance=1)
                    progress.update(file_gen_progress, advance=1)

            else:
                #keep several frame requests in flight at once, so decoding, resizing and png
                #encoding of different frames overlap instead of running strictly one at a time
                max_requests = max(1, min(vs.core.num_threads, 8))
                pending = deque()

                def finish_one():
                    pending.popleft().result()
                    progress.update(total_gen_progress, advance=1)
                    progress.update(file_gen_progress, advance=1)

                for frame in frames:
                    filename = f"{screen_dir}/{frame} - {suffix}.png"
                    writer = vs.core.fpng.Write(clip[frame], filename, compression=compression, overwrite=True)
                    pending.append(writer.get_frame_async(0))

                    while len(pending) >= max_requests:
                        finish_one()

                while pending:
                    finish_one()

    print()
    #print(time.time() - START_TIME)

    # Oxipng integration with progress bar and stats
    script_path = pathlib.Path(__file__).resolve()
    oxipng_path = script_path.parent.parent / "tools" / "oxipng" / "oxipng.exe"

    if oxipng_path.exists():
        png_files = sorted([f for f in screen_dir.iterdir() if f.suffix.lower() == '.png'])
        if png_files:
            total_size_before = sum(f.stat().st_size for f in png_files)
            
            # Detect CPU threads for parallel execution, using half of available
            oxipng_workers = max(1, psutil.cpu_count(logical=True) // 2)

            def optimize_worker(file_path):
                subprocess.run(
                    [str(oxipng_path), '-o', '4', '--strip', 'safe', '--quiet', str(file_path)],
                    check=False,
                    stderr=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL
                )

            with get_progress() as progress:
                task = progress.add_task(f"Optimizing with oxipng ({oxipng_workers} threads)", total=len(png_files))
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=oxipng_workers) as executor:
                    futures = [executor.submit(optimize_worker, png_file) for png_file in png_files]
                    for _ in concurrent.futures.as_completed(futures):
                        progress.update(task, advance=1)

            total_size_after = sum(f.stat().st_size for f in png_files)
            
            def format_size(size_bytes):
                return f"{size_bytes / (1024 * 1024):.2f}MB"

            print(f"Before: {format_size(total_size_before)}")
            print(f"After: {format_size(total_size_after)}\n")
    else:
        print(f"oxipng not found at {oxipng_path}. Skipping optimization.\n")

    if slowpics:
        #time.sleep(0.5)

        browserId = str(uuid.uuid4())
        fields: Dict[str, Any] = {
            'collectionName': collection_name,
            'hentai': str(hentai_flag).lower(),
            'optimize-images': 'true',
            'browserId': browserId,
            'public': str(public_flag).lower()
        }

        if tmdbID != "":
            fields |= {'tmdbId': str(tmdbID)}
        if remove_after != "" and remove_after != 0:
            fields |= {'removeAfter': str(remove_after)}

        all_image_files = os_sorted([f for f in os.listdir(screen_dir) if f.endswith('.png')])

        #check if all image files are present before uploading. if not, wait a bit and check again. if still not, exit program
        if len(all_image_files) < len(frames) * len(files):
            time.sleep(5)
            all_image_files = os_sorted([f for f in os.listdir(screen_dir) if f.endswith('.png')])

            if len(all_image_files) < len(frames) * len(files):
                sys.exit(f'Error: Number of screenshots in "{screen_dirname}" folder does not match expected value.')
        
        for x in range(0, len(frames)):
            #current_comp is list of image files for this frame
            current_comp = [f for f in all_image_files if f.startswith(str(frames[x]) + " - ")]

            #add field for comparison name. after every comparison name there needs to be as many image names as there are comped video files
            fields[f'comparisons[{x}].name'] = str(frames[x])
            
            #iterate over the image files for this frame
            for imageName in current_comp:
                i = current_comp.index(imageName)
                image = pathlib.Path(f"{screen_dir}/{imageName}")
                fields[f'comparisons[{x}].imageNames[{i}]'] = os.path.basename(image.name).split(' - ', 1)[1].replace(".png", "")

                #this would upload the images all at once, but that wouldnt let us get progress
                #fields[f'comparisons[{x}].images[{i}].file'] = (image.name.split(' - ', 1)[1].replace(".png", ""), image.read_bytes(), 'image/png')

        with Session() as sess:
            sess.get('https://slow.pics/comparison')

            files = MultipartEncoder(fields, str(uuid.uuid4()))

            comp_req = sess.post(
                'https://slow.pics/upload/comparison', data=files.to_string(),
                headers=_get_slowpics_header(str(files.len), files.content_type, sess)
            )

            # Error handling for the API response
            try:
                comp_response = comp_req.json()
            except Exception as e:
                print(f"Error parsing server response: {e}")
                print(f"Status code: {comp_req.status_code}")
                return

            if comp_response.get("images") is None:
                print("\nError: Slow.pics failed to initialize the comparison. Please try again later.")
                print(f"Server Response: {comp_response}")
                return

            collection = comp_response["collectionUuid"]
            key = comp_response["key"]

            #build the list of uploads. each image is tied to its uuid, so upload order doesn't matter
            upload_jobs = []
            for index, image_section in enumerate(comp_response["images"]):
                base = index * file_count
                for image_index, image_id in enumerate(image_section):
                    upload_jobs.append((image_id, all_image_files[base + image_index]))

            def upload_image(image_id, image_file):
                for attempt in range(3):
                    upload_info = {
                        "collectionUuid": collection,
                        "imageUuid": image_id,
                        "file": (image_file, pathlib.Path(f"{screen_dir}/{image_file}").read_bytes(), 'image/png'),
                        'browserId': browserId,
                    }
                    upload_info = MultipartEncoder(upload_info, str(uuid.uuid4()))
                    upload_response = sess.post(
                        'https://slow.pics/upload/image', data=upload_info.to_string(),
                        headers=_get_slowpics_header(str(upload_info.len), upload_info.content_type, sess)
                    )

                    if upload_response.status_code == 200 and upload_response.content.decode() == "OK":
                        return

                    #back off a little before retrying, in case of rate limiting
                    time.sleep(1 + attempt * 2)

                raise Exception(f'Failed to upload "{image_file}" after 3 attempts (status {upload_response.status_code}).')

            with get_progress() as progress:
                upload_progress = progress.add_task("[bright_magenta]Uploading to Slowpoke Pics", total=len(all_image_files))

                with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, upload_threads)) as executor:
                    upload_futures = [executor.submit(upload_image, image_id, image_file) for image_id, image_file in upload_jobs]

                    for future in concurrent.futures.as_completed(upload_futures):
                        future.result()
                        progress.update(upload_progress, advance=1)

        slowpics_url = f'https://slow.pics/c/{key}'
        print(f'\nSlowpoke Pics url: {slowpics_url}', end='')
        pc.copy(slowpics_url)

        if browser_open:
            webbrowser.open(slowpics_url)

        if webhook_url:
            data = {"content": slowpics_url}
            if requests.post(webhook_url, data).status_code < 300:
                print('Posted to webhook.')
            else:
                print('Failed to post on webhook!')

        if url_shortcut:
            #datetime.datetime.now().strftime("%Y.%m.%d") + " - " + 
            shortcut_path = os.path.join("Comparisons", collection_name + " - " + key + ".url")

            if not os.path.exists(os.path.dirname(shortcut_path)):
                os.mkdir(os.path.dirname(shortcut_path))

            with open(shortcut_path, "w", encoding='utf-8') as shortcut:
                shortcut.write(f'[InternetShortcut]\nURL={slowpics_url}')

        if delete_screen_dir and os.path.isdir(screen_dir):
            shutil.rmtree(screen_dir)

        time.sleep(3)

run_comparison()