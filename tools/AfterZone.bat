@echo off
:: This batch file uses AfterZone.py to re-encode chosen scenes of an encode
:: that has already finished.
::
:: AfterZone re-encodes ONLY the chunks a zones.txt touches, reusing every other
:: chunk from that finished encode. Run it after the normal encode, once you
:: know which scenes you want different settings for.
::
:: All three encoders in this package are supported. Which one made an encode is
:: read off the working folder it left behind, so there is nothing to set here:
::
::   av1an   temp\<name>\.<hash>\chunks.json  (+ done.json, encode\NNNNN.ivf)
::           left by the av1an-*.bat and autoboost-*.bat files
::   LQTC    temp\.<hash>\cmd.txt             (+ done.txt, encode\NNNN.obu)
::           left by the lqtc-*.bat files, along with temp\<name>_scd.txt
::   Condor  temp\<name>-condor.json          (+ temp\<name>-condor\scenes\NNNNN.ivf)
::           left by the condor-*.bat files
::
:: Requirements:
::   1. The encode already finished and its working folder above still exists
::      (all of these .bat files keep it; don't run cleanup before AfterZone)
::   2. The original input is still in video-input\<name>.mkv
::   3. A zones file named after the input sits next to it:
::        video-input\<name>.txt
::      AfterZone can auto-generate one from the finished file's bitrate if it
::      is missing. See zones-example.txt for the format.
::
:: Result: video-output\<name>-afterzone.mkv
:: Your original video-output\<name>-output.mkv is left alone.
::
:: On an LQTC encode, the zones go into LQTC's own scene file, and LQTC applies
:: a scene's parameters on top of the ones the encode was started with - so a
:: zone line only has to name what it changes, and the 'reset' keyword does not
:: apply. A zone that sets --crf overrides the quality target search for the
:: scenes it covers; one that does not sets everything else and lets the search
:: choose a CRF again. AfterZone re-runs the exact command LQTC recorded in
:: cmd.txt, because that is the only command LQTC will resume with, so the
:: build, the worker counts and the quality target all stay as they were.
::
:: On a Condor encode, the zones go straight into condor.json's scene array.
:: Condor has no zones option of its own, so this is the only way to zone one.
:: Each scene there carries a complete set of encoder parameters, including the
:: quantizer Target Quality picked for it, and AfterZone keeps that quantizer
:: for every scene no zone covers - a zone line only changes what it names.
:: Target Quality is NOT run again: AfterZone runs 'condor encode' followed by
:: 'condor concatenate', so no scene is re-measured and nothing outside your
:: zones changes settings. A scene is re-encoded purely because its chunk file
:: was removed from scenes\, which is exactly how condor's own resume works.
::
:: Interrupting is safe. Once AfterZone has handed the job to the encoder it
:: leaves a marker in temp\afterzone-active-<name>.txt. While that file is
:: there, running this .bat again changes NOTHING on disk: AfterZone skips the
:: zones file and the plan and just restarts the encoder, which resumes at the
:: first chunk that is not finished. The marker is removed once the result is
:: muxed.

:: --- ENCODER SETTINGS FOR THE MKV TAG (av1an encodes only) ---
:: These are written into the output's Encoded_Library_Settings tag by
:: av1an-tag.py. They do NOT drive the encode: the base settings come from the
:: original chunks.json and the per-zone overrides come from your zones.txt.
:: Copy these three lines from the .bat you originally encoded with so the tag
:: stays truthful.
::
:: They are a fallback. AfterZone reads the tag off your finished
:: video-output\<name>-output.mkv first and copies that, because it already
:: describes the encode these chunks came from. An LQTC result only ever uses
:: that route - its settings live in its own lqtc-*.bat, not here - so it is
:: left untagged rather than wrongly tagged when there is nothing to copy.
set "av1an_settings=--lineart-psy-bias 3 --texture-psy-bias 3 --hbd-mds 1 --lp 3 --photon-noise 200"
set "FINAL_SPEED=4"
set "CRF=30"

cls
setlocal enableextensions disabledelayedexpansion

:: Set the current working directory
cd /d "%~dp0"

:: --- STEP 0A: CREATE BATCH MARKER ---
:: av1an-tag.py reads the newest tools\bat-used-*.txt marker to find which .bat
:: to pull the settings above from, so this one is written last and wins.
::
:: Only this .bat's own marker is cleared. The marker left by the .bat that ran
:: the encode is deliberately kept: for an av1an encode AfterZone.py reads the
:: worker count out of that .bat (custom-av1an-workers, filled in by the one-time
:: optimization benchmark) so the re-encode runs with the same worker count the
:: encode did. Every encode .bat clears tools\bat*.txt itself when it starts, so
:: only one encode marker is ever present.
echo.
del "tools\bat-used-%~nx0.txt" 2>nul
type NUL > "tools\bat-used-%~nx0.txt"

:: --- STEP 0B: SET TEMP PATH ---
:: tools\LQTC is deliberately not on here: an LQTC encode is restarted with the
:: full path to the build it originally used, which AfterZone.py takes from
:: cmd.txt.
set "PATH=%~dp0VapourSynth;%~dp0tools\av1an;%~dp0tools\MKVToolNix;%PATH%"

:: --- STEP 0C: POINT CONDOR AT VAPOURSYNTH ---
:: Condor decodes through VSScript rather than vspipe and finds the DLL through
:: this variable. Without it, it exits with "VSScript API not available" before
:: reading a frame. AfterZone.py sets this itself as well, so this line only
:: matters if you run condor by hand from the same window.
set "VSSCRIPT_PATH=%~dp0VapourSynth\VSScript.dll"

:: --- STEP 1: WORKER COUNT ---
:: Nothing to do here, and no benchmark is run from this .bat on purpose.
::
:: Only av1an encodes need a worker count, and AfterZone.py resolves it itself:
:: it prefers the custom-av1an-workers value in the .bat that ran the encode
:: (written there by the one-time optimization benchmark) and falls back to
:: tools\workercount-config.txt, so do not be surprised if the number it reports
:: is not the one in that file. Every av1an .bat writes workercount-config.txt
:: when it first starts, so any av1an encode AfterZone can work on has already
:: produced one.
::
:: An LQTC encode never uses that number at all - its -w and -v are part of the
:: command AfterZone resumes it with - so benchmarking av1an here would cost an
:: LQTC user a full sample encode for a value nothing reads.

:: --- STEP 2: AFTERZONE ---
:: No renaming step here on purpose: the working folder is tied to the input
:: file's name, so renaming the input now would orphan the finished chunks.
:: An unfinished encode from a previous run (temp\afterzone-active-*.txt) is
:: picked up here automatically and simply continued.
echo Starting AfterZone...
echo Reading finished encodes from: temp
echo Outputs will go to:            video-output
echo.

"VapourSynth\python.exe" "tools\AfterZone.py"

:: Exit code 7 means AfterZone already finished on its own interactive prompt
:: (zone generation), so pausing again here would just be a second key press.
if "%ERRORLEVEL%"=="7" goto :afterzone_done

echo.
echo All tasks finished.
pause
:afterzone_done

:: --- STEP 3: CLEANUP ---
:: Cleanup is intentionally NOT run here. AfterZone keeps the chunks it replaced,
:: and the state files it rewrote, in an afterzone-backup folder inside the
:: working folder it used:
::   temp\<name>\.<hash>\afterzone-backup   (av1an)
::   temp\.<hash>\afterzone-backup          (LQTC)
::   temp\<name>-condor\afterzone-backup    (Condor)
:: so you can compare results or re-run with different zones. Run cleanup.py
:: yourself when you are finished:
::   "VapourSynth\python.exe" "tools\cleanup.py"
::
:: Do not run cleanup while temp\afterzone-active-*.txt still exists - it
:: deletes the temp folder, which is the encode that marker is waiting to
:: resume.
