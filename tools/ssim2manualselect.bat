@echo off
setlocal

cd /d "%~dp0.."

set "PYTHON_EXE=%~dp0..\VapourSynth\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

"%PYTHON_EXE%" "%~dp0ssim2manualselect.py"
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
    echo.
    echo ssim2manualselect.py exited with error code %EXITCODE%.
)

pause
exit /b %EXITCODE%
