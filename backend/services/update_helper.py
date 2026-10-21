"""Update helper process and script generator for safe in-place replacement and rollback."""

from __future__ import annotations

import logging
import os
import stat
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_windows_helper_script(
    script_path: Path,
    target_exe: Path,
    new_file: Path,
    backup_file: Path,
    pid: int,
    is_installer: bool,
    log_file: Path,
) -> Path:
    """Generate a detached Windows CMD script for replacing the executable and restarting."""
    target_clean = str(target_exe.resolve())
    new_clean = str(new_file.resolve())
    backup_clean = str(backup_file.resolve())
    log_clean = str(log_file.resolve())

    if is_installer:
        script_content = f"""@echo off
setlocal
echo [%date% %time%] Starting installer updater for PID {pid}... > "{log_clean}"

:wait_exit
tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto wait_exit
)

echo [%date% %time%] Parent process exited. Running installer... >> "{log_clean}"
start "" /wait "{new_clean}" /S
set INSTALL_CODE=%ERRORLEVEL%
echo [%date% %time%] Installer completed with code %INSTALL_CODE%. >> "{log_clean}"

if %INSTALL_CODE% equ 0 (
    echo [%date% %time%] Starting updated application... >> "{log_clean}"
    start "" "{target_clean}"
) else (
    echo [%date% %time%] Installer failed. Attempting to restart previous version... >> "{log_clean}"
    if exist "{target_clean}" start "" "{target_clean}"
)

exit /b %INSTALL_CODE%
"""
    else:
        # Portable single-file replacement with rollback
        target_name = target_exe.name
        script_content = f"""@echo off
setlocal
echo [%date% %time%] Starting portable updater for PID {pid}... > "{log_clean}"

set WAIT_COUNT=0
:wait_exit
tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL
if not errorlevel 1 (
    set /a WAIT_COUNT+=1
    if %WAIT_COUNT% geq 25 (
        echo [%date% %time%] Parent PID {pid} timed out, force terminating... >> "{log_clean}"
        taskkill /F /PID {pid} >NUL 2>&1
        timeout /t 1 /nobreak >NUL
        goto do_replace
    )
    timeout /t 1 /nobreak >NUL
    goto wait_exit
)

:do_replace
echo [%date% %time%] Parent process exited. Creating backup... >> "{log_clean}"
if exist "{backup_clean}" del /f /q "{backup_clean}" 2>NUL
move /y "{target_clean}" "{backup_clean}" >> "{log_clean}" 2>&1
if errorlevel 1 goto rollback

echo [%date% %time%] Installing new version... >> "{log_clean}"
move /y "{new_clean}" "{target_clean}" >> "{log_clean}" 2>&1
if errorlevel 1 goto rollback

echo [%date% %time%] Starting new executable... >> "{log_clean}"
start "" "{target_clean}"
timeout /t 2 /nobreak >NUL

:: Verify new version process is alive
tasklist /FI "IMAGENAME eq {target_name}" 2>NUL | find /I "{target_name}" >NUL
if errorlevel 1 (
    echo [%date% %time%] New executable crashed on startup! Triggering rollback... >> "{log_clean}"
    goto rollback
)

echo [%date% %time%] Update succeeded. Cleaning up backup... >> "{log_clean}"
if exist "{backup_clean}" del /f /q "{backup_clean}" 2>NUL
exit /b 0

:rollback
echo [%date% %time%] Rolling back to previous version... >> "{log_clean}"
if exist "{backup_clean}" (
    move /y "{backup_clean}" "{target_clean}" >> "{log_clean}" 2>&1
    start "" "{target_clean}"
    echo [%date% %time%] Rolled back and started previous version. >> "{log_clean}"
)
exit /b 1
"""

    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script_content, encoding="utf-8")
    return script_path


def generate_linux_helper_script(
    script_path: Path,
    target_exe: Path,
    new_file: Path,
    backup_file: Path,
    pid: int,
    is_archive: bool,
    log_file: Path,
) -> Path:
    """Generate a detached Linux bash script for replacing the executable and restarting."""
    target_clean = str(target_exe.resolve())
    new_clean = str(new_file.resolve())
    backup_clean = str(backup_file.resolve())
    log_clean = str(log_file.resolve())

    script_content = f"""#!/bin/sh
echo "[$(date)] Starting Linux updater for PID {pid}..." > "{log_clean}"

WAIT_COUNT=0
while kill -0 {pid} 2>/dev/null; do
    WAIT_COUNT=$((WAIT_COUNT+1))
    if [ "$WAIT_COUNT" -ge 25 ]; then
        echo "[$(date)] Force terminating PID {pid}..." >> "{log_clean}"
        kill -9 {pid} 2>/dev/null
        sleep 1
        break
    fi
    sleep 0.5
done

chmod +x "{new_clean}" 2>/dev/null

echo "[$(date)] Creating backup..." >> "{log_clean}"
cp -f "{target_clean}" "{backup_clean}" 2>> "{log_clean}"

echo "[$(date)] Replacing binary..." >> "{log_clean}"
mv -f "{new_clean}" "{target_clean}" 2>> "{log_clean}"
chmod +x "{target_clean}" 2>/dev/null

echo "[$(date)] Launching new version..." >> "{log_clean}"
"{target_clean}" >/dev/null 2>&1 &
NEW_PID=$!
sleep 2

if kill -0 "$NEW_PID" 2>/dev/null; then
    echo "[$(date)] Update verified successful. Cleaning backup..." >> "{log_clean}"
    rm -f "{backup_clean}" 2>/dev/null
    exit 0
else
    echo "[$(date)] New version failed to run! Rolling back..." >> "{log_clean}"
    cp -f "{backup_clean}" "{target_clean}" 2>> "{log_clean}"
    chmod +x "{target_clean}" 2>/dev/null
    "{target_clean}" >/dev/null 2>&1 &
    exit 1
fi
"""

    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script_content, encoding="utf-8")
    try:
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)
    except OSError as e:
        logger.debug("Failed to set executable bit on script: %s", e)
    return script_path


def launch_detached_helper(script_path: Path) -> subprocess.Popen:
    """Launch the helper script detached from the current process tree."""
    if sys.platform == "win32":
        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
        )
        return subprocess.Popen(
            ["cmd.exe", "/c", str(script_path)],
            creationflags=creation_flags,
            close_fds=True,
        )
    return subprocess.Popen(
        ["/bin/sh", str(script_path)],
        start_new_session=True,
        close_fds=True,
    )
