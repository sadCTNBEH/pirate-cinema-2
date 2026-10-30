"""Detached platform helpers for replacement and restart after application shutdown."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def _ps_literal(value: Path) -> str:
    return "'" + str(value.resolve()).replace("'", "''") + "'"


def prepare_linux_bundle(archive: Path, updates_dir: Path, executable_name: str) -> Path:
    """Validate and unpack the complete Linux distribution before closing the app."""
    staging = Path(tempfile.mkdtemp(prefix="bundle-", dir=updates_dir))
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            for member in members:
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "pirate-cinema-linux":
                    raise ValueError("Unexpected path in Linux update archive")
            bundle.extractall(staging, members=members, filter="data")
        root = staging / "pirate-cinema-linux"
        if not (root / executable_name).is_file() or not (root / "_internal").is_dir():
            raise ValueError("Linux update does not contain the complete application bundle")
        return root
    except (OSError, ValueError, tarfile.TarError):
        shutil.rmtree(staging)
        raise


def generate_windows_helper_script(
    script_path: Path,
    target_exe: Path,
    new_file: Path,
    backup_file: Path,
    pid: int,
    is_installer: bool,
    log_file: Path,
) -> Path:
    """Generate PowerShell without CMD pipelines or PID text matching."""
    script = f"""$ErrorActionPreference = 'Stop'
$target = {_ps_literal(target_exe)}
$download = {_ps_literal(new_file)}
$backup = {_ps_literal(backup_file)}
$log = {_ps_literal(log_file)}
$installDir = Split-Path -Parent $target
$env:PYINSTALLER_RESET_ENVIRONMENT = '1'
$backedUp = $false
function Write-Log($message) {{
    Add-Content -LiteralPath $log -Value ('[' + (Get-Date -Format o) + '] ' + $message) -Encoding UTF8
}}
function Start-App {{
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $target
    $info.WorkingDirectory = $installDir
    $info.UseShellExecute = $false
    return [System.Diagnostics.Process]::Start($info)
}}
try {{
    Write-Log 'Waiting for application shutdown'
    $parent = Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue
    if ($parent -and -not $parent.WaitForExit(60000)) {{
        throw 'Application did not exit within 60 seconds; update cancelled'
    }}
"""
    if is_installer:
        script += """    $backup = $installDir + '.update-backup'
    if (Test-Path -LiteralPath $backup) {
        Move-Item -LiteralPath $backup -Destination ($backup + '.' + [Guid]::NewGuid().ToString())
    }
    Move-Item -LiteralPath $installDir -Destination $backup
    $backedUp = $true
    Write-Log 'Starting silent installer'
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $download
    # NSIS requires /D to be last and the path to be unquoted.
    $info.Arguments = '/S /D=' + $installDir
    $info.UseShellExecute = $false
    $installer = [System.Diagnostics.Process]::Start($info)
    $installer.WaitForExit()
    if ($installer.ExitCode -ne 0) { throw ('Installer exit code: ' + $installer.ExitCode) }
"""
    else:
        script += """    # A onefile bootloader may hold the EXE briefly after its child exits.
    $staged = $target + '.update-new'
    Copy-Item -LiteralPath $download -Destination $staged -Force
    $deadline = (Get-Date).AddSeconds(60)
    while ($true) {
        try {
            Copy-Item -LiteralPath $target -Destination $backup -Force
            Move-Item -LiteralPath $staged -Destination $target -Force
            $backedUp = $true
            break
        } catch {
            if ((Get-Date) -ge $deadline) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
"""
    script += """    $app = Start-App
    if ($app.WaitForExit(5000)) { throw ('New application exited early: ' + $app.ExitCode) }
    Write-Log 'Update installed and application restarted; backup retained'
    exit 0
} catch {
    Write-Log ($_ | Out-String)
    if ($backedUp) {
        try {
"""
    if is_installer:
        script += """            if (Test-Path -LiteralPath $installDir) {
                Move-Item -LiteralPath $installDir -Destination ($installDir + '.failed.' + [Guid]::NewGuid().ToString())
            }
            Move-Item -LiteralPath $backup -Destination $installDir
"""
    else:
        script += """            Copy-Item -LiteralPath $backup -Destination $target -Force
"""
    script += """            $null = Start-App
            Write-Log 'Previous version restored'
        } catch { Write-Log ($_ | Out-String) }
    }
    exit 1
}
"""
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script, encoding="utf-8-sig")
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
    """Replace a portable binary or a fully extracted onedir bundle on one filesystem."""
    target = target_exe.resolve()
    destination = target.parent if is_archive else target
    backup = destination.with_name(destination.name + ".update-backup") if is_archive else backup_file.resolve()
    script = f"""#!/bin/sh
set -eu
target={shlex.quote(str(target))}
destination={shlex.quote(str(destination))}
download={shlex.quote(str(new_file.resolve()))}
backup={shlex.quote(str(backup))}
log={shlex.quote(str(log_file.resolve()))}
exec >> "$log" 2>&1
export PYINSTALLER_RESET_ENVIRONMENT=1
unset APPDIR OWD ARGV0
echo "[$(date)] Waiting for application shutdown"
count=0
while kill -0 {int(pid)} 2>/dev/null; do
    count=$((count+1))
    if [ "$count" -ge 120 ]; then
        echo 'Application did not exit; update cancelled'
        exit 1
    fi
    sleep 0.5
done
sleep 0.5
staged=$(mktemp -d "$(dirname "$destination")/.pirate-update.XXXXXX")
backed_up=0
rollback() {{
    if [ "$backed_up" -eq 1 ]; then
        if [ -e "$destination" ]; then mv -- "$destination" "$staged/failed"; fi
        mv -- "$backup" "$destination"
        (cd "$(dirname "$target")" && exec "$target") </dev/null >> "$log" 2>&1 &
        echo 'Previous version restored'
    fi
}}
trap 'rollback; exit 1' HUP INT TERM
"""
    script += 'if ! cp -a -- "$download" "$staged/payload"; then exit 1; fi\n'
    executable_suffix = "/" + target.name if is_archive else ""
    script += f"""if ! chmod u+x -- "$staged/payload"{shlex.quote(executable_suffix)}; then exit 1; fi
if [ -e "$backup" ]; then
    echo 'Previous backup still exists; preserving it before update'
    mv -- "$backup" "$staged/previous-backup"
fi
if ! mv -- "$destination" "$backup"; then exit 1; fi
backed_up=1
if ! mv -- "$staged/payload" "$destination"; then rollback; exit 1; fi
(cd "$(dirname "$target")" && exec "$target") </dev/null >> "$log" 2>&1 &
new_pid=$!
sleep 5
if ! kill -0 "$new_pid" 2>/dev/null; then
    echo 'New application exited early'
    rollback
    exit 1
fi
echo "[$(date)] Update installed and application restarted; backup retained"
exit 0
"""
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o700)
    return script_path


def launch_detached_helper(script_path: Path) -> subprocess.Popen:
    """Launch without a terminal or inherited PyInstaller library search paths."""
    env = os.environ.copy()
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for name in ("LD_LIBRARY_PATH", "LIBPATH", "APPDIR", "OWD", "ARGV0"):
        original = env.pop(name + "_ORIG", None)
        env.pop(name, None)
        if original is not None:
            env[name] = original
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "cwd": str(script_path.parent),
        "env": env,
    }
    if sys.platform == "win32":
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        return subprocess.Popen(
            [str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
            **kwargs,
        )
    return subprocess.Popen(["/bin/sh", str(script_path)], start_new_session=True, **kwargs)
