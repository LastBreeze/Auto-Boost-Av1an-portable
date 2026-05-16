@echo off
echo Place your mkv file(s) in this folder then run vspreview.bat
echo It will open vspreview for viewing your mkv files. You can use this to compare files locally
echo or to retrieve frame numbers if you're building a zones txt file. If you have multiple mkv files
echo loaded, you may use 1, 2, 3, etc to switch between mkv files. You may zoom in with Ctrl+mousewheel
pause

:: --- Configuration ---
:: Path to Python executable (relative to this bat file in 'extras')
set "PYTHON_EXE=..\VapourSynth\python.exe"

:: Path to the Dispatch Script (relative to this bat file)
set "DISPATCH_SCRIPT=..\tools\vspreview-dispatch.py"

:: Set PYTHONPATH to ensure dependencies are found
set "PYTHONPATH=..\VapourSynth\Lib\site-packages"

:: --- Execution ---
:: Check if Python exists
if not exist "%PYTHON_EXE%" (
    echo Error: Could not find Python at %PYTHON_EXE%
    pause
    exit /b
)

:: Run the dispatcher script
"%PYTHON_EXE%" "%DISPATCH_SCRIPT%"

:: --- Safety Cleanup ---
:: (The Python script handles this, but this is a fail-safe if Python crashes hard)
if exist *.ffindex del *.ffindex
if exist *.vpy del *.vpy
if exist .vsjet rd /s /q .vsjet

cls