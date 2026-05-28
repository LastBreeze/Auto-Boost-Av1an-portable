# Auto-Boost-Av1an-Portable

A fully automated AV1 encoding workflow for Windows. **One double-click** takes your raw video files, encodes them to AV1 with consistent visual quality, and remuxes everything back together with the original audio and subtitles. No command line, no manual setup, no merging — just drop, click, relax.

Built on [Av1an](https://github.com/master-of-zen/Av1an), [SVT-AV1-PSY](https://github.com/gianni-rosato/svt-av1-psy), and [VapourSynth](https://www.vapoursynth.com/).

Linux fork: [Auto-Boost-Av1an-Linux](https://github.com/abdalrahmanx9/Auto-Boost-Av1an-Linux)

---

## ✨ Features

- **Zero configuration** — fully portable, no installation required
- **Bat Builder** — a guided wizard that generates a ready-to-run `.bat` tailored to your content and hardware
- **Two encoding modes** — Auto-Boost (two-pass, metric-guided) and Av1an Direct (single-pass)
- **Multiple encoder forks** — tuned presets for anime, live action, HDR, and custom use cases
- **Auto-muxing** — recombines the new AV1 video with your original audio and subtitle tracks
- **Auto-renaming** — safely prepares files for processing before encoding begins
- **Resume support** — interruptions are handled gracefully; re-run the `.bat` to continue
- **First-run hardware benchmarking** — automatically determines the optimal worker count and SSIMU2 configuration for your CPU and GPU
- **Automatic bt709/bt601 color space detection** to prevent color shifts on HD and DVD sources
- **Auto-crop detection** — removes black bars from widescreen content
- **AVX-512 support** — optional faster encoding on supported Intel and AMD CPUs
- **Zones support** — per-scene encoding overrides using a `zones.txt` file

---

## 🚀 Quick Start

### Option A — Bat Builder (recommended for new users)

1. **Double-click** `bat-builder.bat` in the root folder.
2. **Answer** five short questions about your content type, encoder fork, quality target, and speed.
3. **A `.bat` script is generated** and saved to the root folder.
4. **Drop** your `.mkv`, `.mp4`, or `.m2ts` files into the `video-input` folder.
5. **Double-click** your generated `.bat` file and wait.
6. **Finished files** appear in the `video-output` folder.

### Option B — Pre-made batch files

Pre-built batch files for common scenarios are included. See the table below, drop your files into `video-input`, and double-click.

---

## 📁 Which `.bat` should I use?

### Anime
| File | Method | Quality |
|------|--------|---------|
| `autoboost-anime-crf30.bat` | Auto-Boost | Balanced — recommended starting point |
| `av1an-batch-anime-crf30.bat` | Av1an Direct | Balanced, faster single-pass |

### Live Action / Movies / TV
| File | Method | Quality |
|------|--------|---------|
| `autoboost-liveaction-crf30.bat` | Auto-Boost | Balanced — recommended starting point |
| `av1an-batch-liveaction-crf30.bat` | Av1an Direct | Balanced, faster single-pass |

**Not sure which to pick?** Start with `autoboost-anime-crf30.bat` for animation, or `autoboost-liveaction-crf30.bat` for everything else.

---

## ⚡ Auto-Boost vs Av1an Direct — what's the difference?

**Auto-Boost** uses a two-pass system. The first pass is a fast preview scan that measures the visual quality of each scene using the SSIMU2 perceptual metric. The second pass uses those measurements to automatically fine-tune the encode — spending more bits where the video needs it most. This produces better and more consistent results, especially on content with widely varying scene complexity.

**Av1an Direct** skips the quality measurement pass and encodes everything in a single pass using SVT-AV1-PSY's built-in perceptual tuning. With features like `--lineart-psy-bias` and `--texture-psy-bias`, the quality is excellent on its own and is a great choice for faster turnaround.

---

## 🎚️ CRF Quality Guide

**CRF** (Constant Rate Factor) is the main setting controlling the balance between visual quality and file size. Lower numbers = higher quality + larger files.

| CRF | Quality | File Size | Use Case |
|-----|---------|-----------|----------|
| 20 | Very high | Large | Archival, preservation |
| 25 | High | Medium | High-quality releases |
| 30 | Balanced | Smaller | Casual viewing — *recommended starting point* |
| 35 | Lower | Smallest | Fast-motion content like sports |

**Start with CRF 30.** If quality isn't sufficient, try CRF 25. There is no single right value — it depends on your source and how much space you're willing to use.

---

## 🔀 Choosing an encoder fork

A **fork** is a version of the SVT-AV1 encoder compiled with specific optimizations for different types of content. Think of them as pre-configured profiles. Bat Builder will ask you to choose one, or you can set `fork=` manually in any `.bat` file.

| Fork | Best For | Notes |
|------|----------|-------|
| `5fish` | Anime | Tuned for sharp lines and subtle textures in animation. Denoise enabled by default. |
| `essential` | Anime or live action | Well-rounded, works on both types. Includes scalable detail retention via `--distortion-bias-preset`. |
| `hdr` | HDR or SDR live action | Designed to retain real-world detail and film grain. |
| `custom` | Advanced users | Place your own `SvtAv1EncApp.exe` in `tools\av1an\svt-av1 forks\custom`. |

---

## 🔁 Resume Support

If a batch script is interrupted, just re-run the `.bat` and it will pick up where it left off.

Note: The final encoding pass itself does **not** support mid-pass resuming. If the final pass is interrupted, that file's final pass restarts from the beginning — but all other files resume cleanly.

---

## 🖥️ First Run: Hardware Benchmarking

The first time you run any batch file, one or two automatic benchmarks run before encoding starts.

**Worker count benchmark** — Measures your CPU's RAM usage and thread count to calculate the safest and fastest number of parallel encoding workers for your system. Results are saved to `tools\workercount-config.txt`. Delete this file if you want to re-run the benchmark.

**SSIMU2 benchmark** *(Auto-Boost only)* — Tests whether your GPU supports hardware-accelerated quality scoring via `vs-hip`, and determines how many workers to use. Results are saved to `tools\workercount-ssimu2.txt`. Delete this file to re-run it.

> **Note:** Task Manager is not accurate for displaying CPU usage during encoding — use [HWiNFO](https://www.hwinfo.com/) instead. Not enough CPU being used? Increase the worker count in `workercount-config.txt`. PC becomes unresponsive or you get out-of-memory errors? Decrease it.

---

## 🗺️ Zones (per-scene overrides)

Zones let you override encoding settings for specific frame ranges — useful when one part of a video has different characteristics (e.g., a grainy flashback or a high-motion action scene in an otherwise calm episode).

Zones follow av1an's `zones.txt` layout with one exception: **adjacent frame numbers do not need to overlap**.

```
[start-frame] [end-frame] [encoder] [settings to override]
```

Example:
```
0 2157 svt-av1 --photon-noise 8 --crf 30 --psy-rd 0.6 --enable-variance-boost 1
2158 4316 svt-av1 --photon-noise 8 --crf 28 --psy-rd 0.6 --enable-variance-boost 1
```

**Automatic zones matching** — Name your zones file using season/episode notation and it will be matched to the correct input file automatically:

```
s01e01-zones.txt  →  anime.s01e01.1080p.something.mkv
```

The input filename just needs to contain `sXXeXX` anywhere — everything before and after it is ignored.

**Manual zones** — To use a zones file with any batch script, make a copy of your preferred `.bat` and add `--zones yourfile-zones.txt` to the dispatch command, before `--resume`.

---

## 🧰 Extras

Located in the `extras\` folder:

- **`lossless-intermediary.bat`** — Converts a problematic source into a clean lossless intermediate for stable encoding. Place your `.mkv` in the `tools` folder before running.
- **`encode-opus.audio.bat`** — Extracts audio from MKV files and re-encodes to high-quality, space-saving Opus using all CPU threads.
- **`photon-noise-test.bat`** — Preview how various photon-noise levels (2, 4, 6, 8, 10) will look in your AV1 encode before committing.
- **`compare.bat`** — Auto-generates a [slow.pics](https://slow.pics) link to compare two MKV files. Uses oxipng lossless compression to speed up uploads.
- **`forced-aspect-remux.bat`** — Copies forced aspect ratio metadata from the source to the AV1 output after encoding.
- **`create-sample.bat`** — Creates a 90-second sample clip from an MKV for testing settings before a full encode.
- **`simple-remux.bat`** — Remuxes an MKV, MP4, or M2TS into a clean MKV if your source is being problematic.
- **`add-subtitles.bat`** — Adds subtitle tracks to any MKV file.
- **`compress-folders.bat`** — On Windows 10/11, NTFS-compresses the VapourSynth and tools folders, saving roughly 60% disk space.

The `prefilter\` folder contains scripts for sources that need denoising, debanding, or downscaling before encoding.

---

## 🛠️ Troubleshooting

**"Unsupported compression method" during extraction** → Update your 7-Zip to the latest version.

**Encode crashes or refuses to start on a specific file** → Run `extras\lossless-intermediary.bat` to create a clean intermediate, then encode from that.

**Poor CPU utilization during encoding** → Task Manager is not accurate for this workload. Check HWiNFO. If utilization is low, open `tools\workercount-config.txt` and increase the worker count.

**Out of memory errors or PC becomes unresponsive during encoding** → Open `tools\workercount-config.txt` and decrease the worker count.

**SSIMU2 benchmark freezes** → The benchmark has an automatic timeout that will kill stalled processes and continue.

**Color looks washed out or shifted** → The scripts include automatic BT.709 and BT.601 detection. For DVD sources where color shift persists, use the color space tools in `extras\`.

**Source file has unusual chroma subsampling (4:2:2, 4:4:4, etc.)** → Make a copy of your preferred `.bat` and add `--convert-to-YUV420P10` to the dispatch command.

---

## 💡 Tips for new users

- **Start with Bat Builder.** It asks plain-English questions and handles all settings for you. You can always hand-edit the generated `.bat` file later in Notepad++.
- **CRF 30 is the recommended starting point.** Test on a short clip with `extras\create-sample.bat` before committing to a full encode.
- **Notepad++** is strongly recommended for editing `.bat` files. Windows Notepad can cause issues with line endings.
- **Never add film-grain or noise parameters to fast pass settings** in Auto-Boost batch files — this will break the SSIMU2 metric system.
