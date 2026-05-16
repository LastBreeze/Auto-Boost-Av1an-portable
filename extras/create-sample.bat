@echo off
echo Place your mkv file in this folder and run this. It will create a 90 second
echo sample mkv you can use for testing different encode settings
pause
setlocal

:: --- Configuration ---
:: Set relative path to mkvmerge from this script's location
set "MKVMERGE=%~dp0..\tools\MKVToolNix\mkvmerge.exe"

:: --- Check if mkvmerge exists ---
if not exist "%MKVMERGE%" (
    echo [ERROR] Could not find mkvmerge at:
    echo "%MKVMERGE%"
    echo Please verify the folder structure.
    pause
    exit /b
)

:: --- Find the first MKV file in the current directory ---
set "INPUT_FILE="
for %%f in ("%~dp0*.mkv") do (
    set "INPUT_FILE=%%f"
    goto :FoundFile
)

:FoundFile
if "%INPUT_FILE%"=="" (
    echo [ERROR] No .mkv files found in this folder.
    pause
    exit /b
)

:: --- Set Output Filename ---
:: Creates "sample_[original_name].mkv"
for %%F in ("%INPUT_FILE%") do set "OUTPUT_FILE=%~dp0sample_%%~nxF"

echo Processing: "%INPUT_FILE%"
echo Using: "%MKVMERGE%"
echo.

:: --- Run mkvmerge ---
:: --no-audio: drops audio tracks
:: --split parts:00:00:00-00:01:30: keeps the first 90 seconds
"%MKVMERGE%" -o "%OUTPUT_FILE%" --no-audio --split parts:00:03:00-00:04:30 "%INPUT_FILE%"

echo.
if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] Sample created: "%OUTPUT_FILE%"
) else (
    echo [FAILURE] Something went wrong.
)

pause