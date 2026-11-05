@echo off
setlocal
cd /d "%~dp0"

set "CINEMA_PYTHON="
if exist "%CD%\.venv\Scripts\python.exe" set "CINEMA_PYTHON=%CD%\.venv\Scripts\python.exe"
if not defined CINEMA_PYTHON if exist "%CD%\.venv-win\Scripts\python.exe" set "CINEMA_PYTHON=%CD%\.venv-win\Scripts\python.exe"
if not defined CINEMA_PYTHON set "CINEMA_PYTHON=%CD%\.venv\Scripts\python.exe"

:: Create Windows virtual environment if missing
if not exist "%CINEMA_PYTHON%" goto create_venv

:: Verify Python works
"%CINEMA_PYTHON%" -c "import sys" >nul 2>&1
if errorlevel 1 goto broken_venv
goto start

:create_venv
echo Creating Windows virtual environment...

py -3 -m venv ".venv-win"
if errorlevel 1 (
    python -m venv ".venv-win"
    if errorlevel 1 goto error
)

echo Installing dependencies...
"%CINEMA_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto error
goto start

:broken_venv
echo ERROR: Windows Python environment is broken.
echo Remove .venv-win and restart this script.
goto error

:start
echo Downloading missing binaries if any...
"%CINEMA_PYTHON%" scripts\download_binaries.py
if errorlevel 1 goto error

echo Starting Pirate Cinema...
"%CINEMA_PYTHON%" run.py
set "CINEMA_EXIT=%ERRORLEVEL%"
goto finish

:error
echo.
echo An error occurred.
set "CINEMA_EXIT=1"

:finish
echo.
pause
exit /b %CINEMA_EXIT%