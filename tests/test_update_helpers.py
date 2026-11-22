"""Updater integration tests operate only on disposable application fixtures."""

import io
import os
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.services.update_helper import (
    generate_linux_helper_script,
    generate_windows_helper_script,
    launch_detached_helper,
    prepare_linux_bundle,
    retry_on_file_lock,
    safe_replace_with_rollback,
)


def test_archive_validation_and_complete_bundle(tmp_path):
    archive = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name in ("pirate-cinema-linux/pirate-cinema-linux", "pirate-cinema-linux/_internal/library.so"):
            member = tarfile.TarInfo(name)
            member.size = 3
            tar.addfile(member, io.BytesIO(b"new"))
    root = prepare_linux_bundle(archive, tmp_path, "pirate-cinema-linux")
    assert (root / "_internal/library.so").read_bytes() == b"new"


@pytest.mark.parametrize("name", ["../escape", "/escape", "pirate-cinema-linux/../../escape", "wrong-root/file"])
def test_archive_rejects_unsafe_paths(tmp_path, name):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.addfile(tarfile.TarInfo(name))
    with pytest.raises(ValueError, match="Unexpected path"):
        prepare_linux_bundle(archive, tmp_path, "pirate-cinema-linux")


def test_helper_environment_and_hidden_windows_launch(tmp_path):
    script = tmp_path / "updater.ps1"
    with (
        patch.dict(os.environ, {
            "LD_LIBRARY_PATH": "/bundle",
            "LD_LIBRARY_PATH_ORIG": "/system",
            "APPDIR": "/tmp/.mount_123",
            "OWD": "/home/user",
        }),
        patch("backend.services.update_helper.subprocess.Popen") as popen,
    ):
        launch_detached_helper(script)
    args, kwargs = popen.call_args
    if sys.platform == "win32":
        assert args[0][-2:] == ["-File", str(script)]
        assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
    else:
        assert args[0] == ["/bin/sh", str(script)]
        assert kwargs["start_new_session"] is True
    assert kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert kwargs["env"]["LD_LIBRARY_PATH"] == "/system"
    assert "APPDIR" not in kwargs["env"]
    assert "OWD" not in kwargs["env"]


def test_generate_linux_helper_script_appimage_structure(tmp_path):
    """Verify Linux updater script safely unsets AppImage variables, quotes paths, and manages backup."""
    folder = tmp_path / "Pirate's & Cinema (v2)"
    target = folder / "Pirate_Cinema-x86_64.AppImage"
    new_file = tmp_path / "updates" / "Pirate_Cinema-x86_64.AppImage"
    backup = folder / "Pirate_Cinema-x86_64.AppImage.bak"
    script = tmp_path / "updater.sh"
    log = tmp_path / "updater.log"

    generate_linux_helper_script(
        script_path=script,
        target_exe=target,
        new_file=new_file,
        backup_file=backup,
        pid=12345,
        is_archive=False,
        log_file=log,
    )

    content = script.read_text(encoding="utf-8")
    assert "unset APPDIR OWD ARGV0" in content
    assert "chmod u+x" in content
    assert "Pirate_Cinema-x86_64.AppImage" in content
    assert "Pirate_Cinema-x86_64.AppImage.bak" in content
    assert "rollback()" in content
    assert 'exec "$target"' in content


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell integration")
@pytest.mark.parametrize("installer", [False, True])
def test_windows_script_parses_with_special_paths(tmp_path, installer):
    script = tmp_path / "update.ps1"
    folder = tmp_path / "Пират's & cinema"
    generate_windows_helper_script(script, folder / "app.exe", tmp_path / "new.exe", folder / "app.bak", 98765, installer, tmp_path / "log")
    command = "$errors=$null; $tokens=$null; [System.Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors) > $null; if ($errors.Count) { $errors; exit 1 }"
    quoted_script = "'" + str(script).replace("'", "''") + "'"
    command = command.replace("$args[0]", quoted_script)
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], capture_output=True, timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell integration")
@pytest.mark.parametrize("installer", [False, True])
@pytest.mark.parametrize("broken", [False, True])
def test_windows_replacement_restart_and_rollback(tmp_path, installer, broken):
    folder = tmp_path / "Пират's & cinema"
    folder.mkdir()
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not compiler.exists():
        pytest.skip("C# fixture compiler unavailable")
    source = tmp_path / "App.cs"
    source.write_text('using System; using System.IO; using System.Threading; class App { static void Main() { File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"started.txt"), System.Diagnostics.Process.GetCurrentProcess().Id.ToString()); Thread.Sleep(15000); } }', encoding="utf-8")
    download = tmp_path / "new.exe"
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/out:" + str(download), str(source)], check=True, capture_output=True, timeout=20)
    target = folder / "app.exe"
    previous = download.read_bytes()
    target.write_bytes(previous)
    if broken:
        download.write_bytes(b"not an executable")
    update_file = download
    if installer:
        installer_source = tmp_path / "Installer.cs"
        installer_source.write_text('using System; using System.IO; class Installer { static void Main(string[] args) { string dest=String.Join(" ",args).Substring(6); Directory.CreateDirectory(dest); File.Copy(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"new.exe"), Path.Combine(dest,"app.exe"),true); Directory.CreateDirectory(Path.Combine(dest,"_internal")); File.WriteAllText(Path.Combine(dest,"_internal","new.dll"),"updated dependency"); } }', encoding="utf-8")
        update_file = tmp_path / "installer.exe"
        subprocess.run([str(compiler), "/nologo", "/target:winexe", "/out:" + str(update_file), str(installer_source)], check=True, capture_output=True, timeout=20)
    backup = folder / "app.bak"
    script = generate_windows_helper_script(tmp_path / "update.ps1", target, update_file, backup, 2147483646, installer, tmp_path / "log")
    try:
        helper = launch_detached_helper(script)
        assert helper.wait(timeout=20) == (1 if broken else 0), (tmp_path / "log").read_text(encoding="utf-8-sig")
        assert target.read_bytes() == (previous if broken else download.read_bytes())
        if installer and not broken:
            assert (folder / "_internal/new.dll").read_text() == "updated dependency"
            assert (folder.with_name(folder.name + ".update-backup") / "app.exe").read_bytes() == previous
        elif not installer:
            assert backup.read_bytes() == previous
        deadline = time.monotonic() + 3
        while not (folder / "started.txt").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (folder / "started.txt").exists()
    finally:
        marker = folder / "started.txt"
        if marker.exists():
            subprocess.run(["taskkill", "/PID", marker.read_text(), "/F"], capture_output=True, timeout=10, check=False)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux shell integration")
@pytest.mark.parametrize("directory", [False, True])
@pytest.mark.parametrize("broken", [False, True])
def test_linux_replaces_complete_payload(tmp_path, directory, broken):
    folder = tmp_path / "Pirate's cinema"
    folder.mkdir()
    target = folder / "app"
    previous = '#!/bin/sh\nsleep 7\n'
    target.write_text(previous)
    target.chmod(0o700)
    payload = tmp_path / "payload"
    if directory:
        payload.mkdir()
        (payload / "_internal").mkdir()
        (payload / "_internal/library.so").write_text("new dependency")
        executable = payload / "app"
    else:
        executable = payload
    executable.write_text('#!/bin/sh\nexit 1\n' if broken else '#!/bin/sh\nsleep 8\n')
    script = generate_linux_helper_script(tmp_path / "update.sh", target, payload, folder / "app.bak", 2147483646, directory, tmp_path / "log")
    helper = launch_detached_helper(script)
    assert helper.wait(timeout=15) == (1 if broken else 0), (tmp_path / "log").read_text()
    assert target.read_text() == (previous if broken else executable.read_text())
    if directory and not broken:
        assert (folder / "_internal/library.so").read_text() == "new dependency"


# ─── G-016 Part 2: Windows File Lock Retry & Rollback Tests ───


def test_windows_script_contains_old_chain_and_retry_loop(tmp_path: Path):
    """Verify generated Windows helper script implements the target -> .old -> new -> start-check -> rollback chain."""
    script_path = tmp_path / "updater.ps1"
    target = tmp_path / "app.exe"
    new_file = tmp_path / "new.exe"
    backup = tmp_path / "app.bak"
    log = tmp_path / "updater.log"

    generate_windows_helper_script(
        script_path=script_path,
        target_exe=target,
        new_file=new_file,
        backup_file=backup,
        pid=54321,
        is_installer=False,
        log_file=log,
    )

    content = script_path.read_text(encoding="utf-8")
    # 1. Renaming target to .old
    assert "$old = $target + '.old'" in content
    assert "Move-Item -LiteralPath $target -Destination $old -Force" in content
    # 2. Deploying new version
    assert "Move-Item -LiteralPath $staged -Destination $target -Force" in content
    # 3. Startup verification
    assert "$app = Start-App" in content
    assert "WaitForExit(5000)" in content
    # 4. Auto-rollback: renaming .old back to target
    assert "Move-Item -LiteralPath $old -Destination $target -Force" in content
    # 5. File lock handling via retry loops
    assert "AddSeconds(60)" in content
    assert "Start-Sleep -Milliseconds 500" in content


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell integration test")
def test_windows_rollback_when_new_binary_crashes_on_startup(tmp_path: Path):
    """Verify helper script automatically rolls back to .old when new binary exits early/crashes."""
    compiler = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not compiler.exists():
        pytest.skip("C# fixture compiler unavailable")

    folder = tmp_path / "AppDir"
    folder.mkdir()

    # 1. Working previous app
    prev_source = tmp_path / "WorkingApp.cs"
    prev_source.write_text(
        'using System; using System.IO; using System.Threading; '
        'class App { static void Main() { '
        'File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "started.txt"), "running"); '
        'Thread.Sleep(15000); } }',
        encoding="utf-8",
    )
    target = folder / "app.exe"
    subprocess.run([str(compiler), "/nologo", "/target:winexe", f"/out:{target}", str(prev_source)], check=True, timeout=20)
    previous_bytes = target.read_bytes()

    # 2. Broken new binary that crashes upon start with exit code 42
    crash_source = tmp_path / "CrashingApp.cs"
    crash_source.write_text(
        'using System; class CrashingApp { static void Main() { Environment.Exit(42); } }',
        encoding="utf-8",
    )
    new_binary = tmp_path / "new_app.exe"
    subprocess.run([str(compiler), "/nologo", "/target:winexe", f"/out:{new_binary}", str(crash_source)], check=True, timeout=20)

    backup = folder / "app.bak"
    script = tmp_path / "update.ps1"
    log = tmp_path / "updater.log"

    generate_windows_helper_script(
        script_path=script,
        target_exe=target,
        new_file=new_binary,
        backup_file=backup,
        pid=2147483646,
        is_installer=False,
        log_file=log,
    )

    try:
        helper = launch_detached_helper(script)
        # Helper must fail (exit 1) because new binary crashed
        exit_code = helper.wait(timeout=25)
        assert exit_code == 1, log.read_text(encoding="utf-8-sig")

        # Rollback check: target executable must have been restored to previous working binary
        assert target.read_bytes() == previous_bytes

        # Working application must have been restarted
        deadline = time.monotonic() + 5
        while not (folder / "started.txt").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (folder / "started.txt").exists()
        assert (folder / "started.txt").read_text() == "running"
    finally:
        marker = folder / "started.txt"
        if marker.exists():
            subprocess.run(["taskkill", "/IM", "app.exe", "/F"], capture_output=True, timeout=10, check=False)


def test_safe_replace_with_rollback_recovers_from_early_crash(tmp_path: Path):
    """Verify safe_replace_with_rollback automatically restores .old if startup verification fails."""
    target = tmp_path / "app.exe"
    target.write_bytes(b"WORKING_V1_PAYLOAD")

    new_file = tmp_path / "new.exe"
    new_file.write_bytes(b"BROKEN_V2_PAYLOAD")

    # verify_func returns False to simulate crash on start
    with pytest.raises(RuntimeError, match="Update failed and rolled back"):
        safe_replace_with_rollback(target, new_file, timeout=10.0, verify_func=lambda p: False)

    # Must be restored to working v1
    assert target.is_file()
    assert target.read_bytes() == b"WORKING_V1_PAYLOAD"


def test_retry_on_file_lock_success_after_retries():
    """Verify retry_on_file_lock retries on transient PermissionError and succeeds."""
    attempts = 0

    def flaky_operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("The process cannot access the file because it is being used by another process.")
        return "SUCCESS"

    result = retry_on_file_lock(flaky_operation, timeout=5.0, delay=0.05)
    assert result == "SUCCESS"
    assert attempts == 3


def test_retry_on_file_lock_timeout_raises():
    """Verify retry_on_file_lock raises TimeoutError when lock is held longer than timeout."""
    def permanently_locked():
        raise PermissionError("Access is denied")

    with pytest.raises(TimeoutError, match="Operation timed out"):
        retry_on_file_lock(permanently_locked, timeout=0.2, delay=0.05)


def test_safe_replace_with_rollback_unpacks_zip(tmp_path: Path):
    """Verify safe_replace_with_rollback extracts and deploys from a Portable ZIP archive."""
    target = tmp_path / "portable-app.exe"
    target.write_bytes(b"OLD_PORTABLE_BYTES")

    zip_file = tmp_path / "update.zip"
    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("portable-app.exe", b"NEW_PORTABLE_FROM_ZIP")

    result = safe_replace_with_rollback(target, zip_file, timeout=10.0, verify_func=lambda p: True)
    assert result == target
    assert target.read_bytes() == b"NEW_PORTABLE_FROM_ZIP"
