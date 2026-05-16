@echo off
:: Launcher for the Auto-Boost/Av1an Batch Builder
cd /d "%~dp0"

:: Check if the portable Python exists, otherwise fall back to system Python
if exist "VapourSynth\python.exe" (
    "VapourSynth\python.exe" "tools\bat-builder.py"
) else (
    python "tools\bat-builder.py"
)