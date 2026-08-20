@echo off
:: Every path below is relative to this folder, the fail-safe deletes at the
:: end included, so make sure that is where we are running. Started from the
:: package root instead, those deletes would take the .vsjet folder holding
:: ArtCNN's ONNX models with them.
cd /d "%~dp0"
echo Place your mkv file(s) in this folder then run vspreview.bat
echo It will open vsview for viewing your mkv files. You can use this to compare files locally
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

:: Open in vsview instead of vspreview. vsview is the successor previewer from
:: the same authors and is bundled with this package. Read by the dispatch
:: script, and set here rather than globally so it applies to this window only.
:: Delete the line to go back to vspreview.
set "AUTOBOOST_PREVIEWER=vsview"

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