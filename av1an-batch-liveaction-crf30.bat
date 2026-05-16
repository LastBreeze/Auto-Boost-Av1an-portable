@echo off
:: Notepad++ is suggested for editing this file.
:: This batch file uses av1an-dispatch.py to call av1an.exe directly.
set "av1an_settings=--ac-bias 1.0 --tx-bias 3 --luminance-qp-bias 20 --enable-alt-dlf 1 --qp-scale-compress-strength 3 --complex-hvs 1 --photon-noise 200"
set "FINAL_SPEED=4"
set "QUALITY=30"
:: Set photon noise to 0 if using film-grain
set "fork=essential"
:: example forks: 5fish, essential, hdr, custom

del tools\bat*.txt
move *.mkv video-input
move *.mp4 video-input
move *.m2ts video-input
cls
setlocal enableextensions disabledelayedexpansion

:: Set the current working directory
cd /d "%~dp0"

:: --- STEP 0A: CREATE BATCH MARKER ---
echo.
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

:: --- STEP 2: RENAMING ---
echo Starting Renaming Process...
"VapourSynth\python.exe" "tools\rename.py"

:: --- STEP 3: DISPATCH ---
echo Starting Av1an Direct Dispatcher...
echo Encoding inputs from: video-input
echo Outputs will go to:   video-output
echo.
:: If you'd like to use --film-grain, then --photon-noise must be set to 0, do not remove the setting.
"VapourSynth\python.exe" "tools\av1an-dispatch.py" --autocrop --quality %QUALITY% --workers %WORKER_COUNT% --final-speed %FINAL_SPEED% --final-params "%av1an_settings%"

echo.
echo All tasks finished.
pause

:: --- STEP 4: CLEANUP ---
echo Cleaning up temporary files and folders...
"VapourSynth\python.exe" "tools\cleanup.py"