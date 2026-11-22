@echo off
setlocal
cd /d "%~dp0"

:: 1. Check if uv is already in PATH or in common install directories
where uv >nul 2>&1
if errorlevel 1 (
    if exist "%USERPROFILE%\.local\bin\uv.exe" set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    if exist "%LOCALAPPDATA%\Programs\uv\bin\uv.exe" set "PATH=%LOCALAPPDATA%\Programs\uv\bin;%PATH%"
    if exist "%APPDATA%\Python\Python312\Scripts\uv.exe" set "PATH=%APPDATA%\Python\Python312\Scripts;%PATH%"
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\Scripts\uv.exe" set "PATH=%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
)

:: 2. If uv is not found, automatically install it
where uv >nul 2>&1
if errorlevel 1 (
    echo [INFO] uv is not installed. Installing uv automatically...
    powershell -ExecutionPolicy ByPass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if exist "%USERPROFILE%\.local\bin\uv.exe" set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>&1
    if errorlevel 1 (
        echo [INFO] Trying pip fallback to install uv...
        py -3 -m pip install uv >nul 2>&1 || python -m pip install uv >nul 2>&1
        for /f "tokens=*" %%i in ('where uv 2^>nul') do set "PATH=%%~dpi;%PATH%"
    )
)

:: 3. Run with uv
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

:: 4. Fallback if automatic installation failed (e.g. offline) but .venv exists
set "CINEMA_PYTHON="
if exist "%CD%\.venv\Scripts\python.exe" set "CINEMA_PYTHON=%CD%\.venv\Scripts\python.exe"
if not defined CINEMA_PYTHON if exist "%CD%\.venv-win\Scripts\python.exe" set "CINEMA_PYTHON=%CD%\.venv-win\Scripts\python.exe"

if defined CINEMA_PYTHON (
    "%CINEMA_PYTHON%" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        echo [WARN] uv could not be installed, using existing virtual environment...
        "%CINEMA_PYTHON%" scripts\download_binaries.py
        if errorlevel 1 goto error
        "%CINEMA_PYTHON%" run.py %*
        set "CINEMA_EXIT=%ERRORLEVEL%"
        goto finish
    )
)

echo.
echo [ERROR] Failed to automatically install uv.
echo Please install uv manually:
echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
echo   Or visit: https://docs.astral.sh/uv/
goto error

:error
echo.
echo An error occurred during startup.
set "CINEMA_EXIT=1"

:finish
echo.
if not "%CI%"=="true" if not "%GITHUB_ACTIONS%"=="true" pause
exit /b %CINEMA_EXIT%
