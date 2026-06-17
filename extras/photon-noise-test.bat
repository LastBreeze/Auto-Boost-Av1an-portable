@echo off
setlocal enableextensions
pushd "%~dp0" || exit /b 1

echo ========================================================
echo          Auto-Boost Photon Noise Test
echo ========================================================
echo.
echo Please ensure you have placed your source AV1 MKV file
echo into this folder.
echo.
echo This script will:
echo  1. Rename your source file to "0source.mkv"
echo  2. Generate 5 variations using the essential fork's
echo     built-in photon noise at distortion/fidelity level 0:
echo     --crf 30 --preset 8 --scd 0 --enable-dlf 3 --photon-noise LEVEL
echo     av1an runs attached to this window so progress stays visible.
echo  3. Test photon levels: 200, 400, 600, 800, 1000.
echo  4. Launch VSPreview for comparison.
echo.
echo External photon noise table files are no longer needed.
echo.
echo Need to generate an AV1 MKV sample of your source?
echo 1. Place your mkv in this folder
echo 2. Run create-sample.bat
echo 3. Encode that sample to AV1 using a batch script such as batch-anime-25-high.bat
echo 4. Place the output AV1 MKV file into this folder and run photon-noise-test.bat
echo The AV1 MKV file should be the only mkv in this folder, except for existing photon test outputs.
echo Press any key to start generation...
pause >nul

:: Find the first .mkv file that is not an existing photon test output and rename it.
if not exist "0source.mkv" (
    for %%f in (*.mkv) do (
        if /I not "%%f"=="photon02.mkv" if /I not "%%f"=="photon04.mkv" if /I not "%%f"=="photon06.mkv" if /I not "%%f"=="photon08.mkv" if /I not "%%f"=="photon10.mkv" (
            ren "%%f" "0source.mkv"
            goto :source_ready
        )
    )
)

:source_ready
if not exist "0source.mkv" (
    echo.
    echo ERROR: No source MKV found. Place one AV1 MKV in this folder and try again.
    echo.
    pause
    popd
    exit /b 1
)

set "PATH=%~dp0..\VapourSynth;%~dp0..\tools\av1an;%~dp0..\tools\MKVToolNix;%PATH%"
if exist "..\VapourSynth\python.exe" (
    set "PYTHON_EXE=..\VapourSynth\python.exe"
) else (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" -u "..\tools\photon-test.py"
if errorlevel 1 (
    echo.
    echo Photon noise test generation failed.
    echo.
    pause
    popd
    exit /b 1
)

if exist "vspreview.bat" (
    call "vspreview.bat"
) else (
    echo.
    echo Warning: vspreview.bat was not found in this folder.
    pause
)

popd
