@echo off
:: ============================================================================
:: x264-filter.bat - lossless x264 intermediary WITH the settings.txt filters
::
:: Same idea as x264.bat next to it, except you do not hand-write the .vpy and
:: av1an is not involved. Every video in this folder is encoded in three steps:
::
::   1. tools\av1an-dispatch.py builds the .vpy from settings.txt, so the filter
::      chain (crop, HDR tonemap, dehalo, denoise, deband, downscale) is exactly
::      the one the AV1 encodes use and cannot drift from it.
::   2. VapourSynth\VSPipe.exe pipes that script as y4m straight into
::      tools\av1an\x264.exe, which writes a raw .h264 stream into
::      temp\x264-filter.
::   3. tools\MKVToolNix\mkvmerge.exe muxes that .h264 into the final .mkv and
::      the raw stream is deleted.
::
:: Input:  every .mkv / .mp4 / .m2ts in the package's video-input folder
:: Output: <name>-x264filter.mkv, written next to the source - so, into that
::         same video-input folder. Files already carrying that suffix are
::         skipped, so a finished intermediary is never filtered twice.
::         The output is VIDEO ONLY: a VapourSynth script carries no audio, so
::         no audio, subtitles, chapters or attachments come over from the
::         source.
::
:: Each source is then moved into the package's originals folder, leaving only
:: the intermediaries in video-input. That is what makes this usable with LQTC,
:: which cannot filter at all: filter here first, then point an LQTC .bat at
:: video-input and it encodes the already-filtered intermediaries.
::
:: THESE FILES ARE LARGE. --qp 0 is mathematically lossless, so a 24 minute
:: 1080p anime episode can land around 40 GB, and a film proportionally more.
:: This is an intermediary, not a delivery encode. If you are feeding the av1an
:: / autoboost .bat files instead of LQTC, turn the filters OFF in settings.txt
:: afterwards so the AV1 encode is not filtered a second time.
::
:: Disk space: the raw .h264 in temp\x264-filter is about the same size as the
:: finished .mkv, and both exist at once while mkvmerge runs. Keep roughly
:: double the output size free until it finishes.
::
:: Notes
::  * settings.txt is only read, never written. The av1an .bat files flip
::    denoise=True/False in settings.txt via their DENOISE= line before they
::    dispatch; this uses whatever settings.txt already says, so set denoise
::    there before running it.
::  * No tools\bat-used-*.txt marker is written on purpose. That marker tells
::    av1an-dispatch.py which .bat launched a run, and this is not one of them.
::  * If you later want the source audio on top of an intermediary, mkvmerge
::    does it in one call:
::    mkvmerge -o final.mkv --no-audio --no-subtitles --no-chapters
::             --no-attachments --no-global-tags "intermediary.mkv"
::             --no-video "source.mkv"
::  * The .vpy is rebuilt from settings.txt on every run, so an edit to
::    settings.txt always takes effect. Only the .ffindex source index in
::    temp\x264-filter is reused, since indexing is the slow part and does not
::    depend on any setting.
:: ============================================================================

:: --- Settings ---------------------------------------------------------------

:: x264 parameters. --qp 0 is lossless. For a much smaller near-lossless
:: intermediary use something like "--preset veryfast --crf 10 --output-depth 10".
set "X264_PARAMS=--preset veryfast --qp 0 --output-depth 10"

:: Apply the [crop] section of settings.txt (crop=auto runs tools\cropdetect.py).
:: False by default because the av1an .bat files only crop when they pass
:: --autocrop to the dispatcher.
set "AUTOCROP=False"

:: Tonemap HDR -> SDR BT.709 through libplacebo. Only files MediaInfo reports
:: as HDR are tonemapped; SDR sources are left alone either way.
set "TONEMAP=False"

:: Keep an existing .vpy instead of rebuilding it from settings.txt. Leave this
:: False: rebuilding takes about a second and is what makes a settings.txt edit
:: take effect. Only worth setting True with AUTOCROP=True, where every rebuild
:: re-runs cropdetect.py - and it will then ignore later settings.txt edits.
set "REUSE_VPY=False"

:: Move each source into the package's originals folder once its intermediary
:: has been written, so video-input is left holding only the intermediaries.
:: Set False to leave the sources where they are - but then every later .bat
:: will queue the source and its intermediary as two separate encodes.
set "MOVE_ORIGINALS=True"

:: ----------------------------------------------------------------------------

setlocal enableextensions disabledelayedexpansion
cd /d "%~dp0"
cls

:: Package root (the folder this tools folder lives in).
for %%I in ("%~dp0..") do set "ROOT=%%~fI"

:: Portable toolchain: VSPipe needs the VapourSynth DLLs next to it, and x264
:: and mkvmerge are called from there too.
set "PATH=%ROOT%\VapourSynth;%ROOT%\tools\av1an;%ROOT%\tools\MKVToolNix;%PATH%"

:: Portable Python, same fallback bat-builder.bat uses.
if exist "%ROOT%\VapourSynth\python.exe" goto :have_python
echo [x264-filter] VapourSynth\python.exe not found; falling back to system Python.
python "%~dp0x264-filter.py" --x264-params "%X264_PARAMS%" --autocrop %AUTOCROP% --tonemap %TONEMAP% --reuse-vpy %REUSE_VPY% --move-originals %MOVE_ORIGINALS%
goto :end

:have_python
"%ROOT%\VapourSynth\python.exe" "%~dp0x264-filter.py" --x264-params "%X264_PARAMS%" --autocrop %AUTOCROP% --tonemap %TONEMAP% --reuse-vpy %REUSE_VPY% --move-originals %MOVE_ORIGINALS%

:end
echo.
pause
endlocal
