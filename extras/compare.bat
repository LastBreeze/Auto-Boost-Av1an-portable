@echo off
setlocal

:: 1. Navigate to the current folder (compare)
cd /d "%~dp0"

:: 2. Set Relative Paths
::    Tools are one level up in the "VapourSynth" folder
set "PYTHON_EXE=..\VapourSynth\python.exe"
set "COMP_SCRIPT=..\VapourSynth\comp.py"

if not exist "%PYTHON_EXE%" goto :missing_python
if not exist "%COMP_SCRIPT%" goto :missing_script

:: 3. Leftovers from an earlier run.
::    "generated.compframes" and the .lwi index files hold the slow part of the job
::    (source analysis + indexing), so after a failed upload they're worth reusing.
::    comp.py discards them by itself if they don't match the current files.
set "HAVE_FRAMES="
set "HAVE_INDEX="
if exist "generated.compframes" set "HAVE_FRAMES=1"
if exist "*.lwi" set "HAVE_INDEX=1"
if not defined HAVE_FRAMES if not defined HAVE_INDEX goto :fresh_start

echo Found data from a previous run:
if defined HAVE_FRAMES echo    - frame analysis ^(generated.compframes^) - skips the analysis pass
if defined HAVE_INDEX echo    - source indexes ^(*.lwi^) - skips lwi index creation
set /p "REUSE=Reuse it? [Y/n]: "
if /i "%REUSE%"=="n" goto :fresh_start
echo Reusing cached data.
goto :run

:fresh_start
call :cleanup

:run
:: screenshots and shortcuts are always regenerated
if exist "Comparisons" rmdir /s /q "Comparisons" >nul 2>&1
if exist "screens" rmdir /s /q "screens" >nul 2>&1

:: 4. Run the Python script
::    (No arguments passed; comp.py will detect MKVs in the current dir)
echo Launching comparison script...
"%PYTHON_EXE%" "%COMP_SCRIPT%"
set "COMP_ERROR=%ERRORLEVEL%"

echo:
echo: comp.py done

:: 5a. Something went wrong (dropped upload, crash, ctrl+c, ...).
::     Keep everything so a rerun can pick up where this one left off.
if not "%COMP_ERROR%"=="0" goto :failed

echo: Please consider sharing your slow.pics URL in the AV1 Weebs Discord,
echo: we love seeing comparisons, let us know which batch file you used!
pause

:: 5b. Cleanup steps
echo Cleaning up folder...
call :cleanup
if exist "Comparisons" rmdir /s /q "Comparisons" >nul 2>&1
if exist "screens" rmdir /s /q "screens" >nul 2>&1
echo Cleanup finished.
exit /b 0

:failed
echo:
echo: The comparison did not finish cleanly ^(exit code %COMP_ERROR%^).
echo: Nothing was deleted - rerun this batch file and keep the cached data
echo: to retry without re-analyzing the source.
pause
exit /b %COMP_ERROR%

:missing_python
echo Error: could not find "%PYTHON_EXE%".
echo Make sure this batch file stays inside the "extras" folder.
pause
exit /b 1

:missing_script
echo Error: could not find "%COMP_SCRIPT%".
pause
exit /b 1

:cleanup
if exist "generated*" del /f /q "generated*" >nul 2>&1
if exist "*.lwi" del /f /q "*.lwi" >nul 2>&1
exit /b 0
