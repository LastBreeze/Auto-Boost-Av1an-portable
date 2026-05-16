@echo off
echo Place your mkv file in this folder then run this.
echo It will apply filters (Denoise/Deband/Downscale) based on settings.txt
echo and encode in x265 lossless 10-bit mode (CPU).
echo.
echo - Lossless files can be huge.
echo - CPU encoding is slower than NVIDIA GPU.
pause
setlocal

:: --- Configuration ---
:: 1. Go to the directory where this .bat file is located (the 'prefilter' folder)
cd /d "%~dp0"

:: 2. Set Path to Python (Go up one level to root, then into VapourSynth)
set "PYTHON_EXE=..\VapourSynth\python.exe"

:: 3. Set Path to Script (Go up one level to root, then into tools\prefilter)
set "SCRIPT_PATH=..\tools\prefilter\x265-prefilter.py"

:: 4. Set Path to Settings (Located right here in the 'prefilter' folder)
set "SETTINGS=settings.txt"

:: --- Checks ---
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python not found at:
    echo "%PYTHON_EXE%"
    echo Please verify folder structure.
    pause
    exit /b
)

if not exist "%SETTINGS%" (
    echo [ERROR] Settings file not found at:
    echo "%SETTINGS%"
    echo Please create settings.txt in this folder.
    pause
    exit /b
)

if not exist "%SCRIPT_PATH%" (
    echo [ERROR] Script not found at:
    echo "%SCRIPT_PATH%"
    echo Please verify the tools folder structure.
    pause
    exit /b
)

:: --- Execution ---
echo Starting x265 Prefilter Workflow...
"%PYTHON_EXE%" "%SCRIPT_PATH%"

:: Cleanup index files if any remain
if exist *.ffindex del *.ffindex
pause