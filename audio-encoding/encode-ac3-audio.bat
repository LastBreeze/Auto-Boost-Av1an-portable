@echo off
setlocal
echo ============================================================
echo      Audio Encoder (AC3)
echo ============================================================
echo.
echo This script is included for people who have older audio hardware 
echo and need AC3 Dolby audio.
echo.
echo Place mkv files in this folder (audio-encoding).
echo.
echo Re-encoding compressed audio degrades quality like a copy of a copy, 
echo so we recommend encoding only lossless tracks.
echo.
echo This script converts audio tracks to AC3 (Dolby Digital)
echo using FFMPEG and muxes them into new files in "ac3-output".
echo.

REM ============================================================
REM Setup Portable Paths
REM ============================================================

REM Root is one level up from "audio-encoding"
SET "PORTABLE_ROOT=%~dp0.."
SET "PYTHON_EXE=%PORTABLE_ROOT%\VapourSynth\python.exe"

REM Script is located in the 'tools' folder
SET "AC3_SCRIPT=%PORTABLE_ROOT%\tools\ac3.py"

REM Check if tools exist
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Could not find Python at:
    echo %PYTHON_EXE%
    echo.
    echo Please make sure the 'Auto-Boost-Essential' folder structure is intact.
    pause
    exit /b
)

if not exist "%AC3_SCRIPT%" (
    echo [ERROR] Could not find ac3.py at:
    echo %AC3_SCRIPT%
    pause
    exit /b
)

REM ============================================================
REM Execution
REM ============================================================

"%PYTHON_EXE%" "%AC3_SCRIPT%"

echo.
echo Workflow finished.
echo Cleaning up temporary extracted files...
del *.flac >nul 2>&1
del *.ac3 >nul 2>&1
del *.thd >nul 2>&1
del *.dtshd >nul 2>&1
del *.dts >nul 2>&1
del *.aac >nul 2>&1
del *.opus >nul 2>&1
del *.eac3 >nul 2>&1
del *.wav >nul 2>&1

pause