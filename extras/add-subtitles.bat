@echo off
setlocal

:: Set directory to the folder containing this batch file
cd /d "%~dp0"

:: Use %CD% (Current Directory) instead of %~dp0 to avoid trailing backslash bugs
set "TARGET_DIR=%CD%"

echo ===============================================================================
echo                            SUBTITLE MUXER
echo ===============================================================================
echo.
echo This tool adds subtitles (.ass/.srt) and fonts (.ttf/.otf) to your MKV files.
echo.
echo [1] SINGLE FILE MODE:
echo     If you have one MKV and one subtitle file (e.g., "French.ass"),
echo     the script will simply combine them. The subtitle track will be named
echo     "French" and tagged as French language.
echo.
echo [2] BATCH MODE (MULTIPLE EPISODES):
echo     If you have multiple episodes, rename them using S01E01 format.
echo     The script will automatically match files:
echo       * MKV: "MyShow.S01E01.1080p.mkv"
echo       * SUB: "S01E01.French.ass"
echo.
echo [FONTS]:
echo     Any .ttf or .otf files found in this folder will be attached
echo     to EVERY MKV processed.
echo.
echo Press any key to start...
echo.
echo Use subtitles that are made for your souce: JPBD subs for a JPBD encode, etc.
pause >nul

:: Move up one level to the root to find Python
cd ..

:: Check if Python exists
if not exist "VapourSynth\python.exe" (
    echo [ERROR] Could not find VapourSynth\python.exe
    pause
    exit /b
)

:: Run the Python script and pass the TARGET_DIR
"VapourSynth\python.exe" "tools\add-subtitles.py" "%TARGET_DIR%"

echo.
echo Process complete.
pause