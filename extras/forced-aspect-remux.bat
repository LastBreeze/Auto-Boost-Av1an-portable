@echo off
setlocal

:: Set directory to the folder containing this batch file (extras)
cd /d "%~dp0"

:: Move up one level to the root (Auto-Boost-Av1an-portable)
cd ..

echo ===============================================================================
echo                           ASPECT RATIO REMUXER
echo ===============================================================================
echo.
echo Use this script after av1 encoding is complete.
echo This script will remux files and copy over a forced aspect ratio from
echo source files.
echo.
echo    [1] Continue
echo    [2] Exit
echo.

set /p choice="Select an option (1 or 2): "

if "%choice%"=="1" goto RunScript
if "%choice%"=="2" goto ExitScript

:RunScript
echo.
echo Starting Python Remuxer...
echo -------------------------------------------------------------------------------
:: UPDATED PATH: Pointing to tools\forced-aspect-remux.py
"VapourSynth\python.exe" "tools\forced-aspect-remux.py"
echo.
echo Process complete.
pause
exit

:ExitScript
exit