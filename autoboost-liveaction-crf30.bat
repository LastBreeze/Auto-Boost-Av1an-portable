@echo off
:: Notepad++ is suggested for editing this file. Never add --film-grain to fast params, this will break metrics.
set "FAST_PARAMS=--scd 0 --distortion-bias-preset 1"
set "FINAL_PARAMS=--scd 0 --distortion-bias-preset 1 --photon-noise 400"
set "FINAL_SPEED=4"
set "CRF=30"
:: Set photon noise to 0 if using film-grain
set "fork=essential"
:: example forks: 5fish, essential, hdr, custom
set "DENOISE=False"
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

:: --- STEP 1A: WORKER COUNT CHECK (ENCODE) ---
set "WORKER_COUNT_CFG="
if exist "tools\workercount-config.txt" (
    REM Read the worker count from the config file. Only workers= is read, so
    REM other keys, such as the cputarget= the builders remember, are ignored.
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
    
    REM Reload config after generation
    for /f "usebackq tokens=1,2 delims==" %%a in ("tools\workercount-config.txt") do (
        if /I "%%a"=="workers" set "WORKER_COUNT_CFG=%%b"
    )
    
    REM Pause so user can see the calculation results, then continue
    echo.
    echo Encode worker count calculated.
)
if defined WORKER_COUNT_CFG set "WORKER_COUNT=%WORKER_COUNT_CFG%"

:: --- STEP 1B: WORKER COUNT CHECK (SSIMU2) ---
if exist "tools\workercount-ssimu2.txt" (
    REM Read config
    for /f "usebackq tokens=1,2 delims==" %%a in ("tools\workercount-ssimu2.txt") do (
        if /I "%%a"=="tool" set "SSIMU2_TOOL=%%b"
        if /I "%%a"=="workercount" set "SSIMU2_WORKERS=%%b"
    )
) else (
    echo.
    echo -------------------------------------------------------------------------------
    echo First Run Detected: Calculating optimal SSIMU2 settings...
    echo -------------------------------------------------------------------------------
    echo Checking GPU support ^(vs-hip^) and CPU benchmarks...
    "VapourSynth\python.exe" "tools\ssimu2-workercount.py"
    
    REM Read config after generation
    for /f "usebackq tokens=1,2 delims==" %%a in ("tools\workercount-ssimu2.txt") do (
        if /I "%%a"=="tool" set "SSIMU2_TOOL=%%b"
        if /I "%%a"=="workercount" set "SSIMU2_WORKERS=%%b"
    )
  
    REM Pause so user can see benchmark results, then continue
    echo.
    echo av1an worker count and SSIMU2 benchmark complete.
    echo You may edit workercount-config.txt and workercount-ssimu2.txt, or delete these .txt files if you want to run the
	echo benchmark again. Task Manager is not accurate for displaying CPU percent used, use hwinfo. Not enough cpu%% being
	echo used? increase worker count. CPU oversaturated and PC is unusable during encoding or out of ram errors?
	echo Decrease worker count.
    pause
)

if not defined SSIMU2_TOOL set "SSIMU2_TOOL=vs-hip"
if not defined SSIMU2_WORKERS set "SSIMU2_WORKERS=1"

:: --- STEP 2: RENAMING ---
echo Starting Renaming Process...
"VapourSynth\python.exe" "tools\rename.py"

:: --- STEP 3: DISPATCH ---
echo Starting Auto-Boost-Av1an Dispatcher...
echo Encoding inputs from: video-input
echo Outputs will go to:   video-output
echo.
:: If you'd like to use --film-grain, then --photon-noise must be set to 0, do not remove the setting.
"VapourSynth\python.exe" "tools\dispatch.py" --fork %fork% --arch %ARCH% --denoise %DENOISE% --crf %CRF% --autocrop --ssimu2 %SSIMU2_TOOL% --ssimu2-cpu-workers %SSIMU2_WORKERS% --resume --fast-speed 8 --final-speed %FINAL_SPEED% --workers %WORKER_COUNT% --fast-params "%FAST_PARAMS%" --final-params "%FINAL_PARAMS%"

echo.
echo All tasks finished.
echo Ctrl+C to keep temp files and exit.
echo Or, to cleaup temp files:
pause

:: --- STEP 4: CLEANUP ---
echo Cleaning up temporary files and folders...
"VapourSynth\python.exe" "tools\cleanup.py"
