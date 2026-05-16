=== Auto-Boost Filter & Encode Tool ===

This folder allows you to pre-process videos with VapourSynth filters before running your main encode.
It will create one x265 10-bit lossless intermerdiary file at a time, encode it, then remove the intermediary.

HOW TO USE:

1. Put your Source Videos (.mkv) inside this folder.
   (The tool will automatically rename them to remove spaces/brackets and add "-source").

2. Put your Encoding Batch File (.bat) inside this folder.
   - This should be the .bat file of your choice from the main folder.
   - You do not need to edit it; the tool will automatically handle "pauses" and file paths.

3. (Optional) If you have a Zones file (*zones*.txt), put it in here too.

4. Double-click "filter.bat".

filter-vspreview.bat: use this to preview your template.py. before starting encoding.

WHAT HAPPENS:
1. The tool creates a lossless x265 filtered copy of your video using template.py
2. It moves that copy to the video-input folder
3. It runs your chosen encoding batch file
4. After the encode is successful, it deletes the lossless intermediate file
5. It repeats this for every video in the "filter" folder

VapourSynth script writing will not be supported, please feel free to discuss filtering on the
av1 weeb edition discord in the #filtering channel.