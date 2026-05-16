@echo off
echo Add an "autoboost" or "av1an" .bat file to this "filter" folder. It will be used for encoding.
echo See readme.txt for details.
pause
set "PATH=%~dp0..\VapourSynth;%~dp0..\tools\av1an;%~dp0..\tools\MKVToolNix;%PATH%"
cd /d "%~dp0"
cls
..\VapourSynth\python.exe ..\tools\filter.py
pause