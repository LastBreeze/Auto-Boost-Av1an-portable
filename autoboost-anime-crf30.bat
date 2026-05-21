@echo off
:: Notepad++ is suggested for editing this file. Never add noise/grain to fast params, this will break metrics.
set "FAST_PARAMS=--lineart-psy-bias 4 --texture-psy-bias 2 --hbd-mds 0 --keyint 305 --noise-level-thr 16000 --tune 0 --filtering-noise-detection 4"
set "FINAL_PARAMS=--lineart-psy-bias 4 --texture-psy-bias 2 --hbd-mds 1 --keyint 305 --noise-level-thr 16000 --tune 0 --filtering-noise-detection 4 --lp 3 --photon-noise 200"
set "FINAL_SPEED=4"
set "QUALITY=30"
:: Set photon noise to 0 if using film-grain
set "fork=5fish"
:: example forks: 5fish, essential, hdr, custom
set "DENOISE=True"
:: DENOISE updates denoise=True/False in settings.txt before dispatch. 5fish should use True; other forks default to False.
set "AVX512_FLAG="
:: Optional: set AVX512_FLAG=--avx512 only if your CPU supports AVX-512 and the fork has an AVX-512 build.

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
if exist "tools\workercount-config.txt" (
    REM Read the worker count from the config file
    for /f "usebackq tokens=2 delims==" %%a in ("tools\workercount-config.txt") do set WORKER_COUNT=%%a
) else (
    echo.
    echo -------------------------------------------------------------------------------
    echo First Run Detected: Calculating optimal encode worker count...
    echo -------------------------------------------------------------------------------
    "VapourSynth\python.exe" "tools\workercount.py"
    
    REM Reload config after generation
    for /f "usebackq tokens=2 delims==" %%a in ("tools\workercount-config.txt") do set WORKER_COUNT=%%a
    
    REM Pause so user can see the calculation results, then continue
    echo.
    echo Encode worker count calculated.
)

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

:: --- STEP 2: HANDOFF TO DISPATCH ---

echo Starting Auto-Boost-Av1an Dispatcher...
echo Encoding inputs from: video-input
echo Outputs will go to:   video-output
echo.

"VapourSynth\python.exe" "tools\dispatch.py" --fork %fork% %AVX512_FLAG% --denoise %DENOISE% --quality %QUALITY% --ssimu2 %SSIMU2_TOOL% --verbose --ssimu2-cpu-workers %SSIMU2_WORKERS% --resume --fast-speed 8 --final-speed %FINAL_SPEED% --workers %WORKER_COUNT% --fast-params "%FAST_PARAMS%" --final-params "%FINAL_PARAMS%"

echo.
echo All tasks finished.
pause

:: --- STEP 3: CLEANUP ---
echo Cleaning up temporary files and folders...
"VapourSynth\python.exe" "tools\cleanup.py"