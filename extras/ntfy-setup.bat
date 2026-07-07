@echo off
setlocal enableextensions
pushd "%~dp0.." || exit /b 1

if exist "VapourSynth\python.exe" (
    set "PYTHON_EXE=VapourSynth\python.exe"
) else (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" -u "tools\ntfy-setup.py"
set "SETUP_EXIT=%ERRORLEVEL%"

echo.
if not "%SETUP_EXIT%"=="0" (
    echo ntfy setup failed.
) else (
    echo ntfy setup finished.
)
echo Press any key to exit.
pause >nul
popd
exit /b %SETUP_EXIT%
