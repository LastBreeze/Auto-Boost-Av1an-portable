@echo off
setlocal enabledelayedexpansion

:: --- Configuration ---
:: Set relative path to mkvmerge from this script's location
set "MKVMERGE=%~dp0..\tools\MKVToolNix\mkvmerge.exe"

:: --- User Introduction ---
cls
echo ========================================================
echo                 SIMPLE REMUX TOOL
echo ========================================================
echo.
echo WHAT THIS DOES:
echo This tool "remuxes" your video files. It takes the video,
echo audio, and subtitles etc from your file and packages them 
echo cleanly into a new MKV container.
echo.
echo WHY USE THIS?
echo 1. It fixes "problematic" headers or container errors that
echo    might cause your encoder to crash.
echo 2. It does NOT re-encode (no quality loss).
echo 3. It is very fast.
echo.
echo SUPPORTED FILES: .mkv, .mp4, .m2ts
echo.
echo Press any key to start scanning for files...
pause >nul

:: --- Check if mkvmerge exists ---
if not exist "%MKVMERGE%" (
    echo.
    echo [ERROR] Could not find mkvmerge at:
    echo "%MKVMERGE%"
    echo Please verify your "tools" folder structure.
    pause
    exit /b
)

:: --- Process Files ---
set "count=0"

echo.
echo Scanning for files in: "%~dp0"
echo --------------------------------------------------------

:: Loop through supported extensions
for %%x in (*.mkv *.mp4 *.m2ts) do (
    
    :: Skip files that are already remuxes to avoid infinite loops/duplicates
    echo "%%~nx" | findstr /i "_remux.mkv" >nul
    if errorlevel 1 (
        set /a count+=1
        set "INPUT_FILE=%%f"
        set "OUTPUT_FILE=%%~nxx_remux.mkv"
        
        echo.
        echo [Processing File #!count!]
        echo Input:  "%%x"
        echo Output: "%%~nx_remux.mkv"
        
        :: Run mkvmerge
        "%MKVMERGE%" -o "%%~nx_remux.mkv" "%%x"
        
        if !ERRORLEVEL! EQU 0 (
            echo [STATUS] Success!
        ) else (
            echo [STATUS] Failed.
        )
    )
)

echo.
echo --------------------------------------------------------
if !count! EQU 0 (
    echo No suitable files (.mkv, .mp4, .m2ts) found to remux.
) else (
    echo All operations complete. Processed !count! file(s).
)

pause