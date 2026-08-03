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
::
:: Interrupting is safe. Once AfterZone has handed the job to av1an it leaves a
:: marker in temp\afterzone-active-<name>.txt. While that file is there, running
:: this .bat again changes NOTHING on disk: AfterZone skips the zones file and
:: the plan and just restarts av1an, which resumes at the first chunk that is
:: not finished. The marker is removed once the result is muxed.

:: --- ENCODER SETTINGS FOR THE MKV TAG ---
:: These are written into the output's Encoded_Library_Settings tag by av1an-tag.py.
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
:: to pull the settings above from, so this one is written last and wins.
::
:: Only this .bat's own marker is cleared. The marker left by the .bat that ran
:: the encode is deliberately kept: AfterZone.py reads the worker count out of
:: that .bat (custom-av1an-workers, filled in by the one-time optimization
:: benchmark) so the re-encode runs with the same worker count the encode did.
:: Every encode .bat clears tools\bat*.txt itself when it starts, so only one
:: encode marker is ever present.
echo.
del "tools\bat-used-%~nx0.txt" 2>nul
type NUL > "tools\bat-used-%~nx0.txt"

:: --- STEP 0B: SET TEMP PATH ---
set "PATH=%~dp0VapourSynth;%~dp0tools\av1an;%~dp0tools\MKVToolNix;%PATH%"

:: --- STEP 1: WORKER COUNT CHECK ---
:: This only makes sure tools\workercount-config.txt exists. AfterZone.py reads
:: it itself, and prints the count it settled on - which is the encode .bat's
:: custom-av1an-workers value when that .bat had one, so do not be surprised if
:: the number it reports is not the one in workercount-config.txt.
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
:: An unfinished encode from a previous run (temp\afterzone-active-*.txt) is
:: picked up here automatically and simply continued.
echo Starting AfterZone...
echo Reading finished encodes from: temp
echo Outputs will go to:            video-output
echo.

"VapourSynth\python.exe" "tools\AfterZone.py"

:: Exit code 7 means AfterZone already finished on its own interactive prompt
:: (zone generation), so pausing again here would just be a second key press.
if "%ERRORLEVEL%"=="7" goto :afterzone_done

echo.
echo All tasks finished.
pause
:afterzone_done

:: --- STEP 3: CLEANUP ---
:: Cleanup is intentionally NOT run here. AfterZone keeps the replaced chunks in
:: temp\<name>\.<hash>\afterzone-backup so you can compare results or re-run
:: with different zones. Run cleanup.py yourself when you are finished:
::   "VapourSynth\python.exe" "tools\cleanup.py"
::
:: Do not run cleanup while temp\afterzone-active-*.txt still exists - it
:: deletes the temp folder, which is the encode that marker is waiting to
:: resume.
