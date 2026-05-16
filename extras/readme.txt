===================================================================
                       EXTRAS SCRIPTS README
===================================================================

This folder contains several tools to help you prepare, test, and compare 
your video encodes. Double-click the .bat files to run them.

-------------------------------------------------------------------
                        COMPARISON TOOLS
-------------------------------------------------------------------

compare.bat
  • What it does: Creates a slow.pics comparison link for your videos.
	Not shared on slow.pics homepage.
  • How to use:
    1. Place two MKV files in this folder.
    2. Rename them so the script knows which is which. 
       Example: "source.mkv" and "av1.mkv" OR: Full naming with fake group names:
          [JPBD] Jujutsu Kaisen - S02E01.mkv
          [AV1] Jujutsu Kaisen - S02E01.mkv
    3. Run the script.

vspreview.bat
  • What it does: Opens a local preview window to view video files frame-by-frame.
  • Useful for: Comparing quality locally or finding specific frame numbers for zoning.
  • Controls: 
    - Press 1, 2, 3, etc, to switch between loaded videos.
    - Use Ctrl+MouseWheel to zoom in and out.

-------------------------------------------------------------------
                     FILE FIXING & PREPARATION
-------------------------------------------------------------------

simple-remux.bat
  • What it does: Copies video/audio/etc into a clean MKV container without re-encoding.
  • Use this if: Your encoder is crashing or complaining about headers/container errors.
  • Supported files: .mkv, .mp4, .m2ts.

lossless-intermediary.bat
  • What it does: Converts a troublesome video into a lossless x265 MKV.
  • Use this if: The "simple-remux" didn't fix your issue and the source file is still causing errors.
  • Warning: This creates VERY large files. Suggestion: only process one at a time.

forced-aspect-remux.bat
  • What it does: Copies the aspect ratio from your source file to your encoded file.
    Use this after av1 encoding is complete.
  • Use this if: Your final encode looks stretched or squashed compared to the original.
  
add-subtitles.bat
  • What it does: Muxes subtitles (.ass/.srt) and fonts (.ttf/.otf) into your MKV files.
  • How to use:
    [Single File Mode]
      - Place 1 MKV and your subtitle files in this folder.
      - Name the subtitle file exactly what you want the Track Title to be.
      - Example: "French.ass" -> Track Title: "French", Language: French.
    [Batch Mode (Multiple Episodes)]
      - Ensure your files have SxxExx matching (e.g., S01E01).
      - Example MKV: "Show.Name.S01E01.mkv"
      - Example Sub: "S01E01.English.ass"
    [Fonts]
      - Any .ttf or .otf files in the folder are automatically attached to ALL processed MKVs.
	  
Always choose the right subtitle files to ensure sync.
e.g. Source is JPBD, use subs that are written for JPBD.
Official support will not be provided for subtitle sync but you can still free to discuss subtitle
sync in the discord.

-------------------------------------------------------------------
                        TESTING & EXTRAS
-------------------------------------------------------------------

create-sample.bat
  • What it does: Creates a short 90-second sample from a larger video file.
  • Use this to: Quickly test different encode settings without waiting for a full video to finish.
  • Note: This creates a clip from the 03:00 to 04:30 timestamp.

compress-folders.bat
  • What it does: Compresses the tool folders (VapourSynth/Tools) to save disk space.
  • Note: Safe for Windows 10 and 11. Can save about 60% of the installation size.