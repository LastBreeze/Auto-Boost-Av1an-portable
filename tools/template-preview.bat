@echo off
:: Notepad++ is suggested for editing this file.
:: Previews video-input\template.vpy before you commit to an encode.
:: It renders the template the same way the encoders do, then opens vsview
:: with the untouched source and the filtered result side by side.
::
:: vsview is the successor to vspreview from the same authors and is bundled
:: with this package. Only this preview is switched over - settings-preview.bat
:: still opens vspreview - which is what AUTOBOOST_PREVIEWER below does.
::
:: This file lives in video-input, next to template.vpy. bat-builder.bat puts it
:: there when it writes the template.
setlocal enableextensions disabledelayedexpansion

:: Step up out of video-input into the root of the portable package.
cd /d "%~dp0.."

echo -------------------------------------------------------------------------------
echo template.vpy preview
echo -------------------------------------------------------------------------------
echo Edit video-input\template.vpy, then run this to see what it does to your video
echo before spending hours on an encode.
echo.
echo Put the file you want to test in the video-input folder. What you see here is
echo what the encoders use: the same script, rendered the same way.
echo.
echo You will be asked about cropping first: press Enter for no crop, or 1 to crop
echo using the [crop] section of settings.txt. Auto crop has to scan the file, so
echo it adds a short wait before the preview opens.
echo.
echo In vsview, press 1 for the untouched source and 2 for the template applied.
echo Ctrl+mousewheel zooms in. Close the vsview window when you are done.
echo.
echo Nothing is encoded and no file is modified.
echo -------------------------------------------------------------------------------
pause

:: --- STEP 0: SET TEMP PATH ---
set "PATH=%CD%\VapourSynth;%CD%\tools\av1an;%CD%\tools\MKVToolNix;%PATH%"
set "PYTHONPATH=%CD%\VapourSynth\Lib\site-packages"

:: Open this preview in vsview instead of vspreview. Read by
:: tools\vspreview-dispatch.py, and set here rather than globally so it applies
:: to this window only. Delete the line to go back to vspreview.
set "AUTOBOOST_PREVIEWER=vsview"

if not exist "VapourSynth\python.exe" (
    echo Error: Could not find "VapourSynth\python.exe".
    echo Make sure this batch file stays in the video-input folder of the portable package.
    pause
    exit /b 1
)

if not exist "tools\template-preview.py" (
    echo Error: Could not find "tools\template-preview.py".
    pause
    exit /b 1
)

if not exist "video-input\template.vpy" (
    echo Error: Could not find "video-input\template.vpy".
    echo Write one from bat-builder.bat, "Setup advanced tools", option 5.
    pause
    exit /b 1
)

:: --- STEP 1: PREVIEW ---
cls
"VapourSynth\python.exe" "tools\template-preview.py" %*
set "PREVIEW_ERROR=%ERRORLEVEL%"

echo.
if not "%PREVIEW_ERROR%"=="0" (
    echo Preview did not finish cleanly ^(exit code %PREVIEW_ERROR%^).
) else (
    echo Preview closed. Edit template.vpy and run this again to compare another change.
)
pause
exit /b %PREVIEW_ERROR%
