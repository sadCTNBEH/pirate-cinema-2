@echo off
setlocal
set "CINEMA_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%CINEMA_PYTHON%" (
    echo Project environment .venv was not found.
    echo Create it with: python -m venv .venv
    echo Then run: .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)
pushd "%~dp0"
echo Downloading missing binaries if any...
"%CINEMA_PYTHON%" scripts\download_binaries.py
echo Starting Pirate Cinema...
"%CINEMA_PYTHON%" run.py
set "CINEMA_EXIT=%ERRORLEVEL%"
popd
exit /b %CINEMA_EXIT%
