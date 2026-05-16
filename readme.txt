Which Batch File Should I Choose?

Pick based on your content type and desired quality:

**ANIME**
**Auto-Boost (Two-Pass System)**
- **autoboost-anime-crf30.bat** — Recommended starting point

**Direct Av1an (Single Pass)**
- **av1an-batch-anime-crf30.bat** — Simpler single-pass encode using svt-av1-psy's new 5fish experimental features for line and texture boosting

**LIVE ACTION / MOVIES / TV SHOWS**
**Auto-Boost (Two-Pass System)**
- **autoboost-liveaction-crf30.bat** — Recommended starting point

**Direct Av1an (Single Pass)**
- **av1an-batch-liveaction-crf30.bat** — Simpler single-pass encode using svt-av1-psy's new 5fish experimental features for line and texture boosting

**SPORTS / FAST MOTION**
- **autoboost-sports-crf33-lowquality.bat** — Optimized for high-motion content

**QUALITY GUIDE (CRF values)**
- **25** = High quality, good balance
- **30** = Balanced quality and efficiency
- **35** = Lower quality, smaller files

TIP: Start with CRF 30. If quality isn't sufficient, try CRF 25. 

## What's the Difference Between Auto-Boost and Direct Av1an?

Auto-Boost scripts use a two-pass system: a fast initial pass followed by a slower, higher-quality final pass that "boosts" areas detected as visually
important. This balances speed and quality.

Direct Av1an scripts skip the boost system and encode everything in one pass using svt-av1-psy's built-in perceptual tuning. With the latest 5fish
experimental features, the line and texture boosting capabilities are excellent on their own, making this a great choice if this fits your needs

--- What is CRF? ---
CRF stands for "Constant Rate Factor." It is the main setting that determines the balance between Video Quality and File Size.

• Lower CRF value (e.g., 18) = Higher Quality, Larger File Size.
• Higher CRF value (e.g., 30) = Lower Quality, Smaller File Size.

In these scripts:
- CRF 30 is used for "Standard" (Good balance for casual viewing).
- CRF 25 is used for "High Quality" (Better detail retention).
- CRF 18 is used for "Archival" (Maximum quality, very large files).

--- What is BT.709? ---
This is the standard color format for most HD (1080p) content.
The script includes "Auto BT.709 Color Detection" to automatically fix washed-out colors on HD content and/or address color shift.

--zones--
Follows av1an zones.txt layout with one exception: adjacent frame numbers do not need to overlap.
[start-frame] [end-frame] [encoder] [photon-noise level] [settings to override]

Example:

0 2157 svt-av1 --photon-noise 8 --crf 30 --psy-rd 0.6 --enable-variance-boost 1 --tf-strength 2
2158 4316 svt-av1 --photon-noise 8 --crf 30 --psy-rd 0.6 --enable-variance-boost 1 --tf-strength 3

zones naming convention:
s01e01-zones.txt
The script will automatically match the zones files using this naming convention. Example of matching pair:
s01e01-zones.txt
anime.s01e01.1080p.something.mkv this can be named anything as long as the filename contains sXXeXX season+episode naming.

zones.txt may be manually specified. Example: if you like using the batch files, make a copy of your perferred batch .bat file.
Insert --zones into the settings, before fast-params. Notepad++ is suggested for editing. Before: --resume
After: --resume --zones example-zones.txt

Notepad++ is suggested for editing batch files.

Changelog

v2.0.1
---------------------------------
• Update Auto-Boost-Av1an.py
  ffvship path fix
• Update av1an-tag.py
  Improve svt-av1 fork version number parsing
• Update bat-builder.py
  Append preset number to output filename, tweak default svt-av1-essential settings.

v2.0
---------------------------------
• fssimu2 replaced with FFVship
• libvship_AMD.dll replaced with libvship_VULKAN.dll until AMD driver updates stop breaking libvship
• bat builder added, bat files can now specify svt-av1 fork
• CPU AVX512 support is detected for apppriate svt-av1 exe auto selection

v1.66
---------------------------------
• Update svt-av1-psy 5fish experimental branch to latest build.
• Input files are no longer moved to a temp folder. Adjusted live action settings for efficency and quality.

v1.65
---------------------------------
• Improve filter folder logic

v1.64
---------------------------------
• Update svt-av1-psy 5fish to latest build.
• Progression Boost has been removed. This advanced script targets specific ssimu2 or butter metric scores per scene and is
  not well-suited for this portable setup because I'm not familiar enough with the script to provide troubleshooting support.
  Users who wish to continue using it may use a previous version, though it will no longer be supported going forward.

v1.63
---------------------------------
• Improved cleanup.py and filter.py logic.
• Fixed bug where ssimu2-workercount.py was not killing stalled benchmarks.

v1.62
---------------------------------
• Add "filter" folder: filters then encodes your source mkv files one by one, automatically. 

v1.61
---------------------------------
• Code cleanup
• Update svt-av1-psy 5fish to even fresherest build

v1.6
---------------------------------
• Update svt-av1-psy to Feb 6 2026 build: introduces --lineart-psy-bias and --texture-psy-bias for improved detail retention.
• Update Vship to 4.1.0, faster performance for GPU based metrics.
• Add input and output folders.

v1.52
---------------------------------
• Split Progression Boost into two batch scripts for anime and live action with appropriate settings for both.
• Implement separate benchmarking script for Progression Boost that uses svt-av1 preset 2 for more suited results.

v1.51
---------------------------------
• Improve auto crop detection by vibeporting Staxrip's autocrop.exe from Visual Basic to Python
• Add 2.1 channel detection for audio encode scripts
• Add Progression-Boost-Basic-SSIMU2 so you can taget a ssimu2 score

v1.5
---------------------------------
• Add setting: --convert-to-YUV420P10. This is only needed if your source is something like 4:2:2, 4:4:4, etc. How to use:
  Make a copy of your preferred batch file, add --convert-to-YUV420P10 to the settings. Example:
  Before: --resume
  After: --resume --convert-to-YUV420P10
• Adjusted crf15 batch files to crf18. After doing a few [Breeze] encodes this season with the new experimental settings,
  some being crf17, some crf19, crf18 should provide more of a "sweet spot" for higher fidelity encodes.

v1.49
---------------------------------
• Fast-pass uses the Progressive-Scene-Detection json to skip av1an scene detection
• Combined all respective nvidia/x265 prefilter scripts.
• extras\add-subtitles.bat add your own subtitles to any mkv file.

v1.48
---------------------------------
• Downscale scripts added to prefilter folder.
• extras\create-sample.bat use this to create a 90 second sample of your mkv file for testing encoding settings.
• extras\simple-remux.bat will remux your mkv/mp4/m2ts file into a mkv if your source file is being problematic.
• Automated downscaling is now supported directly during the encoding process; simply edit settings.txt to enable it.

v1.47
---------------------------------
• Implement manual zones.txt selection using --zones
• Added vspreview to extras folder.
• Added settings.txt for manual crop settings.
• Improve resuming logic if encoding gets interrupted.

v1.46
---------------------------------
• extras\compare.bat: Apply oxipng lossless compression to speedup uploading to slow.pics.
• Added prefilter folder with deband scripts.
• Transfer BT601 color spaces for DVD sources to address color shift.

v1.45
---------------------------------
• Accomodate variable framerate source files.
• Add low quality batch file with extra temporal-filtering-strength for sports because crf30 batch was making input/output same size.

v1.44
---------------------------------
• Added more audio encoding scripts.
• Added wakepy to keep system from sleeping during encoding.

v1.43
---------------------------------
• Added scripts in extras folder for light denoise.
• Improved crop detection for live action scripts.
• Improved opus audio script: let users choose to encode only lossless audio tracks or all audio tracks.

v1.42
---------------------------------
• If benchmarks freeze, end process so benchmarking can continue
• Fast-pass now uses multiple workers

v1.41
---------------------------------
• Multuple ssimu2 worker benchmarking to determine best option for user's system
• Added auto crop to live action batch files

v1.4
---------------------------------
• Added live action batch files.
• Adjusted all batch files to svt-av1 preset 4 for faster general purpose av1 encoding. Users with powerful CPUs and/or powerful amounts of free
  CPU time use may edit batch files to use slower preset if needed. "--final-speed 4" can be changed to 2 or 0. Community testing indicates
  1 and 3 are not suitable and speeds faster than 4 are negative towards quality.

v1.39
---------------------------------
• Upgraded 5fish .exe to experimental branch 5fish-svt-av1-psy_ac-bias+exp2f788d04+_e87a5ae3, added experimental settings to scripts to increase
  quality, including texture and lines.
• Added crf 15 .bat file to make thicc encodes with --aggressive double math. Example: before: script attempts to hit visual metric target,
  lowers crf by a value of 1.5. After: script lowers crf by 3
• Added auto bt709 color detection
• Improved dynamic settings parsing for auto tagging to add settings used to mediainfo

v1.38
---------------------------------
• Made adjustments to file tagging so correct settings list is applied to each output mkv, visible via mediainfo.

v1.37
---------------------------------
• Added tool extras\compress-folders.bat. For Windows 10/11 this will compress the VapourSynth and tools folders, saving over 600MB of space.

v1.36
---------------------------------
• Failsafe: if fssimu2 crashes, fallback to vs-zip.
• Output mkv files are auto tagged with settings used, visible via mediainfo.

v1.35
---------------------------------
• Automated Hardware Optimization: Added a one-time test that runs the first time you start a batch file to ultimately speed up final-pass av1 encoding.
  - It benchmarks your system's actual RAM usage and CPU threads to calculate the safest and fastest "Worker" count for your specific PC.
  - Results are saved to a configuration file (tools\workercount-config.txt) so the test only needs to run once. You may manually edit this txt file if needed.
  - You can safely delete the txt file tools\workercount-config.txt if you want the test to run again.
  - Optimized Threading: Automatically adds --lp 3 to final encoding settings. This improves efficiency and prevents CPU oversaturation when running multiple workers.
• New Troubleshooting Tool: Added extras\lossless-intermediary.bat.
  - Use this if you have a "problematic" video that crashes or refuses to encode properly.
  - It converts your video into a clean, lossless file that you can use as a stable source to ensure smooth encoding. Place your mkv file in the "tools" folder and
	run lossless-intermediary.bat
• New Opus Audio Tool: Added extras\encode-opus.audio.bat for easy audio compression.
  - Automatically extracts audio from your MKV videos and converts it to high-quality, space-saving Opus format.
  - Smartly processes multiple files at once using your CPU's full threads and saves a new video with opus audio to an output folder.
• Add python script to automatically cleanup all temp files and folders

v1.34 (Experimental)
---------------------------------
• Adjusted final muxing to accommodate all steps correctly and properly mux final av1 mkv with source mkv file subs+audio+etc
• Added --workers setting to .bat files. Changing the worker count will increase encoding speed if appropriate for your cpu+ram.
  You can see how much cpu% and ram% final-pass is using on your system with hwinfo. Task Manager is not accurate in displaying cpu%.

v1.33 (Experimental)
---------------------------------
• Improved scene detection logic.
• Added --photon-noise setting to batch files. 
  - Allows users to customize the value or disable it (set to 0) if they prefer to use --film-grain flags.

v1.32 (Experimental)
---------------------------------
• Adjusted script's scene detection mechanism to address issues with keyframe insertion and metric scoring.

v1.31
---------------------------------
• Fixed Portable Environment: Resolved issues where Av1an/VapourSynth would not run correctly on systems without global installations.
• Added extras\compare.bat - compares two .mkv files and generates a slow.pics URL (comparison does not publish to homepage).
• Added bt709 batch files: Assists in transferring bt709 colorspace from sources to AV1 encodes.
• Updated SVT-AV1 binaries (Credit: Miss Ashenlight for compiling):
  - Added znver2 build (Default): Faster speeds for supported Intel/AMD CPUs.
  - Added x86-64-v3 build: For wider hardware compatibility.
  - Manual switch available in tools\av1an\5fish-svt-av1-psy_622fb012.
• Corrected various copy+paste errors in scripts.
