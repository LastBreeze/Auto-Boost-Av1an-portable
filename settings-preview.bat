@echo off
:: Notepad++ is suggested for editing this file.
:: Previews the filtering in settings.txt before you commit to an encode.
:: It reads settings.txt, builds a temporary VapourSynth script for a file in
:: video-input, and opens vsview with the untouched source and the filtered
:: result side by side.
::
:: vsview is the successor to vspreview from the same authors and is bundled
:: with this package. AUTOBOOST_PREVIEWER below is what selects it.
setlocal enableextensions disabledelayedexpansion

:: Set the current working directory
cd /d "%~dp0"

echo -------------------------------------------------------------------------------
echo settings.txt preview
echo -------------------------------------------------------------------------------
echo Put the file you want to test in the video-input folder, then edit settings.txt
echo (crop, downscaling, dehalo, denoise, deband) and run this to see the result.
echo.
echo You will be asked about cropping first: press Enter for no crop, or 1 to crop
echo using the [crop] section of settings.txt. Auto crop has to scan the file, so
echo it adds a short wait before the preview opens.
echo.
echo In vsview, press 1 for the source and 2 for the filtered version. If crop or
echo downscaling is on you also get 3: the source with only crop/downscale applied,
echo so 2 against 3 shows what the filters alone are doing.
echo Ctrl+mousewheel zooms in. Close the vsview window when you are done.
echo.
echo Nothing is encoded and no file is modified.
echo -------------------------------------------------------------------------------
pause

:: --- STEP 0: SET TEMP PATH ---
set "PATH=%~dp0VapourSynth;%~dp0tools\av1an;%~dp0tools\MKVToolNix;%PATH%"
set "PYTHONPATH=%~dp0VapourSynth\Lib\site-packages"

:: Open this preview in vsview instead of vspreview. Read by
:: tools\vspreview-dispatch.py, and set here rather than globally so it applies
:: to this window only. Delete the line to go back to vspreview.
set "AUTOBOOST_PREVIEWER=vsview"

if not exist "VapourSynth\python.exe" (
    echo Error: Could not find "VapourSynth\python.exe".
    echo Make sure this batch file stays in the root of the portable package.
    pause
    exit /b 1
)

if not exist "tools\settings-preview.py" (
    echo Error: Could not find "tools\settings-preview.py".
    pause
    exit /b 1
)

:: --- STEP 1: PREVIEW ---
cls
"VapourSynth\python.exe" "tools\settings-preview.py" %*
set "PREVIEW_ERROR=%ERRORLEVEL%"

echo.
if not "%PREVIEW_ERROR%"=="0" (
    echo Preview did not finish cleanly ^(exit code %PREVIEW_ERROR%^).
) else (
    echo Preview closed. Edit settings.txt and run this again to compare another setting.
)
pause
exit /b %PREVIEW_ERROR%
