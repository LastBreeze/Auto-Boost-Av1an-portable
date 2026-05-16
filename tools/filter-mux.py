import os
import glob
import subprocess
import sys

# --- CONFIGURATION ---
# This script runs inside 'temp', so we look one level up for other folders
TOOLS_DIR = os.path.join("..", "tools")
FILTER_DIR = os.path.join("..", "filter")
MKVMERGE = os.path.join(TOOLS_DIR, "MKVToolNix", "mkvmerge.exe")

def main():
    # 1. Find the raw AV1 file in the current (temp) directory
    # Av1an usually outputs files ending in -av1.mkv or just .mkv depending on settings, 
    # but dispatch.py usually ensures we are working with predictable names.
    av1_files = glob.glob("*-av1.mkv")
    
    if not av1_files:
        print("[Filter-Mux] No *-av1.mkv files found in temp.")
        return

    for av1_file in av1_files:
        # av1_file example: "ShowName-source-x265-source-av1.mkv"
        # We need to match this to "ShowName-source.mkv" in the ..\filter folder
        
        print(f"[Filter-Mux] Processing raw encode: {av1_file}")
        
        # Strip suffix to get the intermediate base name
        # "ShowName-source-x265-source-av1.mkv" -> "ShowName-source-x265-source"
        intermediate_base = av1_file.replace("-av1.mkv", "")
        
        # Strip the "-x265-source" tag added by filter.py to find the original source
        # "ShowName-source-x265-source" -> "ShowName-source"
        original_base = intermediate_base.replace("-x265-source", "")
        
        # Construct path to the original source in the filter folder
        source_mkv = os.path.join(FILTER_DIR, f"{original_base}.mkv")
        
        if not os.path.exists(source_mkv):
            print(f"[Filter-Mux] Warning: Original source not found at: {source_mkv}")
            print(f"[Filter-Mux] Cannot mux audio/subs. Skipping {av1_file}")
            continue

        # Define Output Name
        # User requested "-muxed" appended to the end.
        output_mkv = f"{original_base}-muxed.mkv"
        
        print(f"[Filter-Mux] Muxing with source: {os.path.basename(source_mkv)}")
        print(f"[Filter-Mux] Output target: {output_mkv}")
        
        # Mux Command: 
        # Take Video from AV1 file
        # Take Audio, Subs, Chapters, Attachments from Source file
        cmd = [
            MKVMERGE,
            "-o", output_mkv,
            "--no-audio", "--no-subtitles", "--no-chapters", "--no-attachments", "--no-global-tags",
            av1_file, # Video source
            "--no-video",
            source_mkv # Audio/Sub source
        ]
        
        try:
            subprocess.run(cmd, check=True)
            print(f"[Filter-Mux] Successfully created: {output_mkv}")
            
            # Clean up the raw AV1 file to save space (optional, but recommended)
            try:
                os.remove(av1_file)
            except OSError:
                pass
                
        except subprocess.CalledProcessError as e:
            print(f"[Filter-Mux] Muxing failed with error code {e.returncode}")

if __name__ == "__main__":
    main()