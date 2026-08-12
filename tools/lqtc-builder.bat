@echo off
:: Launcher for the LQTC Quality Target Batch Builder
cd /d "%~dp0"

:: Check if the portable Python exists, otherwise fall back to system Python
if exist "VapourSynth\python.exe" (
    "VapourSynth\python.exe" "tools\lqtc-builder.py"
) else (
    python "tools\lqtc-builder.py"
)
