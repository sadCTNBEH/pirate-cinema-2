@echo off
echo Downloading missing binaries if any...
python scripts\download_binaries.py

echo Starting Pirate Cinema...
python run.py
pause
