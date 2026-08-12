@echo off
:: Launcher for the Condor Batch Builder
cd /d "%~dp0"

:: Check if the portable Python exists, otherwise fall back to system Python
if exist "VapourSynth\python.exe" (
    "VapourSynth\python.exe" "tools\condor-builder.py"
) else (
    python "tools\condor-builder.py"
)
