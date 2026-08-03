@echo off
setlocal

echo Place your mkv file in this folder and run this. It will create a short
echo sample mkv (video only) you can use for testing different encode settings.
echo.

:: --- CONFIGURATION ---

:: 1. Define the path to the portable Python executable
:: We go up one level (..) from extras\ to find the VapourSynth folder
set "PYTHON_EXE=%~dp0..\VapourSynth\python.exe"

:: 2. Define the path to the Python script
:: We go up one level (..) from extras\ to find the tools folder
set "SCRIPT_PATH=%~dp0..\tools\create-sample.py"

:: --- CHECKS ---

:: Check if the portable Python exists
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Could not find portable Python.
    echo Expected location: "%PYTHON_EXE%"
    pause
    exit /b 1
)

:: Check if the Python script exists
if not exist "%SCRIPT_PATH%" (
    echo [ERROR] Could not find Python script.
    echo Expected location: "%SCRIPT_PATH%"
    pause
    exit /b 1
)

:: --- EXECUTION ---

:: Run from this folder so the script finds the mkv files sitting next to it
pushd "%~dp0"
"%PYTHON_EXE%" "%SCRIPT_PATH%"
popd

echo.
pause
