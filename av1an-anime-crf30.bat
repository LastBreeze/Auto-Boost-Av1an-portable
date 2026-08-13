@echo off
:: Notepad++ is suggested for editing this file.
:: This batch file uses av1an-dispatch.py to call av1an.exe directly.
set "av1an_settings=--scd 0 --lineart-psy-bias 3 --texture-psy-bias 3 --hbd-mds 1 --lp 3 --photon-noise 200"
set "FINAL_SPEED=4"
set "CRF=30"
:: Set photon noise to 0 if using film-grain
set "fork=5fish"
:: example forks: 5fish, essential, hdr, custom
set "DENOISE=True"
:: DENOISE updates denoise=True/False in settings.txt before dispatch. 5fish should use True; other forks default to False.
set "ARCH=x86-64-v3"
:: ARCH picks the CPU build of the encoder: x86-64-v3 (any modern CPU),
:: znver2 (AMD Ryzen 3000+), avx512 (only CPUs with AVX-512).
:: A fork without that build falls back to x86-64-v3. The hdr fork is x86-64-v3 only.

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
set "WORKER_COUNT_CFG="
if exist "tools\workercount-config.txt" (
    for /f "usebackq tokens=1,2 delims==" %%a in ("tools\workercount-config.txt") do (
        if /I "%%a"=="workers" set "WORKER_COUNT_CFG=%%b"
    )
)
if not defined WORKER_COUNT_CFG (
    echo.
    echo -------------------------------------------------------------------------------
    echo First Run Detected: Calculating optimal encode worker count...
    echo -------------------------------------------------------------------------------
    "VapourSynth\python.exe" "tools\workercount.py"
    for /f "usebackq tokens=1,2 delims==" %%a in ("tools\workercount-config.txt") do (
        if /I "%%a"=="workers" set "WORKER_COUNT_CFG=%%b"
    )
    echo.
    echo Encode worker count calculated.
)
if defined WORKER_COUNT_CFG set "WORKER_COUNT=%WORKER_COUNT_CFG%"

:: --- STEP 2: RENAMING ---
echo Starting Renaming Process...
"VapourSynth\python.exe" "tools\rename.py"

:: --- STEP 3: DISPATCH ---
echo Starting Av1an Direct Dispatcher...
echo Encoding inputs from: video-input
echo Outputs will go to:   video-output
echo.

"VapourSynth\python.exe" "tools\av1an-dispatch.py" --fork %fork% --arch %ARCH% --denoise %DENOISE% --crf %CRF% --workers %WORKER_COUNT% --final-speed %FINAL_SPEED% --final-params "%av1an_settings%"

echo.
echo All tasks finished.
echo Ctrl+C to keep temp files and exit.
echo Or, to cleanup temp files:
pause

:: --- STEP 4: CLEANUP ---
echo Cleaning up temporary files and folders...
"VapourSynth\python.exe" "tools\cleanup.py"
