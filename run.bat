@echo off
setlocal
cd /d "%~dp0"

:: Check if uv is available
where uv >nul 2>&1
if not errorlevel 1 (
    if not exist "%CD%\.venv\Scripts\python.exe" (
        echo Creating virtual environment and installing dependencies with uv...
        uv sync
        if errorlevel 1 goto error
    )
    echo Downloading missing binaries if any...
    uv run --no-sync scripts\download_binaries.py
    if errorlevel 1 goto error

    echo Starting Pirate Cinema...
    uv run --no-sync run.py
    set "CINEMA_EXIT=%ERRORLEVEL%"
    goto finish
)

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
echo uv not detected. For best performance install uv: https://docs.astral.sh/uv/
echo Creating fallback Windows virtual environment...

py -3 -m venv ".venv"
if errorlevel 1 (
    python -m venv ".venv"
    if errorlevel 1 goto error
)
set "CINEMA_PYTHON=%CD%\.venv\Scripts\python.exe"

echo Installing dependencies...
"%CINEMA_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto error
goto start

:broken_venv
echo ERROR: Windows Python environment is broken.
echo Remove .venv and restart this script, or run: uv sync
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
