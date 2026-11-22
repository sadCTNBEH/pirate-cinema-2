@echo off
setlocal
cd /d "%~dp0"

:: 1. If uv is available, use it for dependency management and execution
where uv >nul 2>&1
if not errorlevel 1 (
    if not exist "%CD%\.venv\Scripts\python.exe" (
        echo Virtual environment not found. Initializing with uv sync...
        uv sync --frozen
        if errorlevel 1 (
            echo Fallback: resolving dependencies with uv sync...
            uv sync
            if errorlevel 1 goto error
        )
    )
    echo Downloading missing binaries if any...
    uv run --no-sync scripts\download_binaries.py
    if errorlevel 1 goto error

    echo Starting Pirate Cinema...
    uv run --no-sync run.py %*
    set "CINEMA_EXIT=%ERRORLEVEL%"
    goto finish
)

:: 2. Fallback if uv is not in PATH, but .venv already exists
set "CINEMA_PYTHON="
if exist "%CD%\.venv\Scripts\python.exe" set "CINEMA_PYTHON=%CD%\.venv\Scripts\python.exe"
if not defined CINEMA_PYTHON if exist "%CD%\.venv-win\Scripts\python.exe" set "CINEMA_PYTHON=%CD%\.venv-win\Scripts\python.exe"

if defined CINEMA_PYTHON (
    "%CINEMA_PYTHON%" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        echo [INFO] uv is not in PATH, but existing virtual environment found.
        echo Starting Pirate Cinema using existing environment...
        "%CINEMA_PYTHON%" scripts\download_binaries.py
        if errorlevel 1 goto error
        "%CINEMA_PYTHON%" run.py %*
        set "CINEMA_EXIT=%ERRORLEVEL%"
        goto finish
    )
)

:: 3. Neither uv nor working .venv found
echo.
echo [ERROR] uv is not installed and no existing virtual environment was found.
echo Pirate Cinema uses uv for fast, reliable dependency management.
echo.
echo To install uv on Windows, run in PowerShell:
echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
echo.
echo Or via winget / pip:
echo   winget install --id=astral-sh.uv -e
echo   pip install uv
echo.
echo Documentation: https://docs.astral.sh/uv/
goto error

:error
echo.
echo An error occurred during startup.
set "CINEMA_EXIT=1"

:finish
echo.
if not "%CI%"=="true" if not "%GITHUB_ACTIONS%"=="true" pause
exit /b %CINEMA_EXIT%
