@echo off
setlocal enableextensions enabledelayedexpansion
pushd "%~dp0" || exit /b 1

echo ========================================================
echo          Auto-Boost Grain / Photon Test
echo ========================================================
echo.
echo Please place exactly one MKV file into this folder.
echo.
echo This script will:
echo  1. Detect the single source MKV in this folder.
echo  2. Ask whether you want a photon-noise test or film-grain test.
echo  3. Ask for default values or a custom range.
echo  4. Ask for a 10 second test range. Press Enter for the
echo     default 10 seconds from the middle of the clip, or type
echo     a start time in seconds.
echo  5. Use tools\MKVToolNix\mkvmerge.exe to create a 10 second
echo     temporary clip from that range.
echo  6. Generate the requested comparison MKV files using the
echo     essential SVT-AV1 fork.
echo  7. Launch VSPreview directly when the encodes finish.

set "PATH=%~dp0..\VapourSynth;%~dp0..\tools\av1an;%~dp0..\tools\MKVToolNix;%PATH%"
if exist "..\VapourSynth\python.exe" (
    set "PYTHON_EXE=..\VapourSynth\python.exe"
) else (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" -u "..\tools\photon-test.py"
if errorlevel 1 (
    echo.
    echo Grain / photon test generation failed.
    echo.
    echo Press any key to exit.
    pause >nul
    popd
    exit /b 1
)

popd
