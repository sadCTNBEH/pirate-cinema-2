"""Updater integration tests operate only on disposable application fixtures."""

import io
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.services.update_helper import (
    generate_linux_helper_script,
    generate_windows_helper_script,
    launch_detached_helper,
    prepare_linux_bundle,
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
