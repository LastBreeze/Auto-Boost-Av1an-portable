@echo off
echo Place your MKV file in this folder and run this.
echo It will create a video-only sample capped at 9.98 MB for Discord.
pause
setlocal EnableDelayedExpansion

:: --- Configuration ---
:: Set relative path to mkvmerge from this script's location
set "MKVMERGE=%~dp0..\tools\MKVToolNix\mkvmerge.exe"
set "SPLIT_BASE=%~dp0discord_10mb_sample_temp.mkv"
set "MAX_SIZE=9980000"
set "SPLIT_SIZE=9980000"

:: --- Check if mkvmerge exists ---
if not exist "%MKVMERGE%" (
    echo [ERROR] Could not find mkvmerge at:
    echo "%MKVMERGE%"
    echo Please verify the folder structure.
    pause
    exit /b 1
)

:: --- Find the first MKV file in this folder ---
set "INPUT_FILE="
for %%f in ("%~dp0*.mkv") do (
    set "CANDIDATE_NAME=%%~nxf"
    if /I not "!CANDIDATE_NAME:~0,20!"=="discord_10mb_sample_" (
        set "INPUT_FILE=%%f"
        goto :FoundFile
    )
)

:FoundFile
if "%INPUT_FILE%"=="" (
    echo [ERROR] No .mkv files found in this folder.
    pause
    exit /b 1
)

:: --- Set output filename ---
for %%F in ("%INPUT_FILE%") do set "OUTPUT_FILE=%~dp0discord_10mb_sample_%%~nxF"

echo Processing: "%INPUT_FILE%"
echo Using: "%MKVMERGE%"
echo Target maximum size: 9.98 MB ^(9,980,000 bytes^)
echo.

:TrySplit
if exist "%OUTPUT_FILE%" del /q "%OUTPUT_FILE%"
if exist "%SPLIT_BASE%" del /q "%SPLIT_BASE%"
if exist "%~dp0discord_10mb_sample_temp-001.mkv" del /q "%~dp0discord_10mb_sample_temp-001.mkv"
if exist "%~dp0discord_10mb_sample_temp-002.mkv" del /q "%~dp0discord_10mb_sample_temp-002.mkv"

:: mkvmerge splits on video keyframes, so a requested split can exceed its size.
:: Retry with a smaller split request until the actual first file is Discord-safe.
echo Trying split target: %SPLIT_SIZE% bytes...
"%MKVMERGE%" -o "%SPLIT_BASE%" --no-audio --no-attachments --no-subtitles --split size:%SPLIT_SIZE% --split-max-files 2 "%INPUT_FILE%"

if errorlevel 1 goto :Failure

:: Split output is normally numbered; handle a short source that is not split too.
if exist "%~dp0discord_10mb_sample_temp-001.mkv" (
    move /y "%~dp0discord_10mb_sample_temp-001.mkv" "%OUTPUT_FILE%" >nul
) else if exist "%SPLIT_BASE%" (
    move /y "%SPLIT_BASE%" "%OUTPUT_FILE%" >nul
) else (
    goto :Failure
)

if exist "%~dp0discord_10mb_sample_temp-002.mkv" del /q "%~dp0discord_10mb_sample_temp-002.mkv"

if not exist "%OUTPUT_FILE%" goto :Failure
for %%S in ("%OUTPUT_FILE%") do set "OUTPUT_SIZE=%%~zS"
if %OUTPUT_SIZE% GTR %MAX_SIZE% goto :RetrySmaller

echo.
echo [SUCCESS] Discord sample created: "%OUTPUT_FILE%"
echo Final size: %OUTPUT_SIZE% bytes
pause
exit /b 0

:RetrySmaller
echo Generated size was %OUTPUT_SIZE% bytes, which is over 9.98 MB.
set /a SPLIT_SIZE-=500000
if %SPLIT_SIZE% LSS 1000000 goto :Failure
echo Retrying with an earlier keyframe...
echo.
goto :TrySplit

:Failure
if exist "%SPLIT_BASE%" del /q "%SPLIT_BASE%"
if exist "%~dp0discord_10mb_sample_temp-001.mkv" del /q "%~dp0discord_10mb_sample_temp-001.mkv"
if exist "%~dp0discord_10mb_sample_temp-002.mkv" del /q "%~dp0discord_10mb_sample_temp-002.mkv"
echo.
echo [FAILURE] Something went wrong.
pause
exit /b 1
