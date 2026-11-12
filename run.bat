@echo off
setlocal
cd /d "%~dp0"

set "CINEMA_PYTHON=.venv-win\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "CINEMA_PYTHON=.venv\Scripts\python.exe"
if exist "%CINEMA_PYTHON%" goto prepare

py -3 -m venv ".venv-win"
if errorlevel 1 (
    python -m venv ".venv-win"
    if errorlevel 1 goto python_error
)
set "CINEMA_PYTHON=.venv-win\Scripts\python.exe"

:prepare
"%CINEMA_PYTHON%" scripts\bootstrap_source.py
if errorlevel 1 goto error
"%CINEMA_PYTHON%" -m backend.infrastructure.downloader
if errorlevel 1 goto error
"%CINEMA_PYTHON%" run.py %*
set "CINEMA_EXIT=%ERRORLEVEL%"
if not "%CINEMA_EXIT%"=="0" pause
exit /b %CINEMA_EXIT%

:python_error
echo Install Python 3.12 or newer and restart run.bat.
:error
echo Pirate Cinema could not start. See the error above.
pause
exit /b 1
