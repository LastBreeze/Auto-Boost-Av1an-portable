@echo off
:: Set paths relative to this batch file
set "PATH=%~dp0..\VapourSynth;%~dp0..\tools\av1an;%~dp0..\tools\MKVToolNix;%PATH%"
set "PYTHONPATH=%~dp0..\VapourSynth\Lib\site-packages"

cd /d "%~dp0"
cls
echo Multi-gigabyte files may take a moment to load.
:: Execute the dispatch script
..\VapourSynth\python.exe ..\tools\filter-vspreview.py
pause
cls
rmdir /s /q .vsjet
cls