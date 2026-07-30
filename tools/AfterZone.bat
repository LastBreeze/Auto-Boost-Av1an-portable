@echo off
:: This batch file uses AfterZone.py to call av1an.exe directly.
::
:: AfterZone re-encodes ONLY the chunks a zones.txt touches, reusing every other
:: chunk from an encode that has already finished. Run it after the normal
:: encode, once you know which scenes you want different settings for.
::
:: Requirements:
::   1. The encode already finished and its temp folder still exists:
::        temp\<name>\.<hash>\chunks.json
::      (the av1an .bat files keep this; don't run cleanup before AfterZone)
::   2. The original input is still in video-input\<name>.mkv
::   3. A zones file named after the input sits next to it:
::        video-input\<name>.txt
::      AfterZone can auto-generate one from the finished file's bitrate if it
::      is missing. See zones-example.txt for the format.
::
:: Result: video-output\<name>-afterzone.mkv
:: Your original video-output\<name>-output.mkv is left alone.

:: --- ENCODER SETTINGS FOR THE MKV TAG ---
:: These are written into the output's ENCODING_SETTINGS tag by av1an-tag.py.
:: They do NOT drive the encode: the base settings come from the original
:: chunks.json and the per-zone overrides come from your zones.txt.
:: Copy these three lines from the .bat you originally encoded with so the tag
:: stays truthful.
set "av1an_settings=--lineart-psy-bias 3 --texture-psy-bias 3 --hbd-mds 1 --lp 3 --photon-noise 200"
set "FINAL_SPEED=4"
set "CRF=30"

cls
setlocal enableextensions disabledelayedexpansion

:: Set the current working directory
cd /d "%~dp0"

:: --- STEP 0A: CREATE BATCH MARKER ---
:: av1an-tag.py reads the newest tools\bat-used-*.txt marker to find which .bat
:: to pull the settings above from.
echo.
del tools\bat*.txt 2>nul
type NUL > "tools\bat-used-%~nx0.txt"

:: --- STEP 0B: SET TEMP PATH ---
set "PATH=%~dp0VapourSynth;%~dp0tools\av1an;%~dp0tools\MKVToolNix;%PATH%"

:: --- STEP 1: WORKER COUNT CHECK ---
if exist "tools\workercount-config.txt" (
    for /f "usebackq tokens=2 delims==" %%a in ("tools\workercount-config.txt") do set WORKER_COUNT=%%a
) else (
    echo.
    echo -------------------------------------------------------------------------------
    echo First Run Detected: Calculating optimal encode worker count...
    echo -------------------------------------------------------------------------------
    "VapourSynth\python.exe" "tools\workercount.py"
    for /f "usebackq tokens=2 delims==" %%a in ("tools\workercount-config.txt") do set WORKER_COUNT=%%a
    echo.
    echo Encode worker count calculated.
)

:: --- STEP 2: AFTERZONE ---
:: No renaming step here on purpose: the av1an temp folder is named after the
:: input file, so renaming the input now would orphan the finished chunks.
echo Starting AfterZone...
echo Reading finished encodes from: temp
echo Outputs will go to:            video-output
echo.

"VapourSynth\python.exe" "tools\AfterZone.py"

echo.
echo All tasks finished.
pause

:: --- STEP 3: CLEANUP ---
:: Cleanup is intentionally NOT run here. AfterZone keeps the replaced chunks in
:: temp\<name>\.<hash>\afterzone-backup so you can compare results or re-run
:: with different zones. Run cleanup.py yourself when you are finished:
::   "VapourSynth\python.exe" "tools\cleanup.py"
