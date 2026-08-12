@echo off
setlocal
cd /d "%~dp0"

cls
echo This will delete the following from:
echo   %CD%
echo.
echo   Folders: Comparisons, screens
echo   Files:   generated.compframes, *.lwi
echo.
set /p choice="Press 1 to continue, 2 to exit: "

if "%choice%"=="1" goto RUN
if "%choice%"=="2" goto EOF

echo Invalid selection.
pause
goto EOF

:RUN
echo.

if exist "Comparisons\" (
    rd /s /q "Comparisons"
    echo Deleted folder: Comparisons
) else (
    echo Not found: Comparisons
)

if exist "screens\" (
    rd /s /q "screens"
    echo Deleted folder: screens
) else (
    echo Not found: screens
)

if exist "generated.compframes" (
    del /f /q "generated.compframes"
    echo Deleted file: generated.compframes
) else (
    echo Not found: generated.compframes
)

set "found="
for %%F in (*.lwi) do (
    set "found=1"
    del /f /q "%%F"
    echo Deleted file: %%F
)
if not defined found echo Not found: *.lwi

echo.
echo Done.
pause

:EOF
endlocal
