import socket
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.core.settings import user
from backend.infrastructure.mpv import controller as mpv
from backend.services import playback


def test_linux_missing_mpv_has_linux_instructions(monkeypatch):
    monkeypatch.setattr(playback.sys, "platform", "linux")
    message = playback._player_error_message(FileNotFoundError("mpv"), "ru")
    assert "sudo apt install mpv" in message
    assert "run.bat" not in message
    assert "mpv.exe" not in message


def test_ipc_failure_is_not_reported_as_missing_mpv(monkeypatch, tmp_path):
    monkeypatch.setattr(playback, "get_data_dir", lambda: tmp_path)
    message = playback._player_error_message(RuntimeError("IPC connection failed"), "en")
    assert "IPC connection failed" in message
    assert "mpv_debug.log" in message
    assert "MPV not found" not in message


def test_linux_mpv_preserves_dispatch_symlink(monkeypatch, tmp_path):
    monkeypatch.setattr(user, "BASE_DIR", tmp_path)
    monkeypatch.setattr(user, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("sys.platform", "linux")
    launcher = tmp_path / "mpv"
    monkeypatch.setattr(Path, "is_file", lambda path: path == launcher)
    monkeypatch.setattr("os.access", lambda *args: True)
    resolve = MagicMock(side_effect=AssertionError("Must not resolve Snap launcher"))
    monkeypatch.setattr(Path, "resolve", resolve)
    assert user.find_mpv_binary({}) == launcher


def test_mpv_launch_restores_system_libraries_and_reports_real_exit(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123/libs")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")
    monkeypatch.setattr(mpv, "get_data_dir", lambda: tmp_path)
    child = MagicMock()
    child.poll.return_value = 1

    def fail(args, **kwargs):
        assert kwargs["env"]["LD_LIBRARY_PATH"] == "/usr/local/lib"
        kwargs["stdout"].write("Failed to initialize video output\n")
        kwargs["stdout"].flush()
        return child

    monkeypatch.setattr(mpv.subprocess, "Popen", fail)
    controller = mpv.MPVController()
    with pytest.raises(RuntimeError, match="Failed to initialize video output"):
        controller.launch("mpv", "http://example.test/movie", "Movie")
    assert controller.process is None
    assert controller.log_file is None


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="Requires Unix domain sockets")
def test_failed_unix_ipc_connection_closes_socket(monkeypatch):
    monkeypatch.setattr(mpv.os, "name", "posix")
    sock = MagicMock()
    sock.connect.side_effect = ConnectionRefusedError()
    monkeypatch.setattr(mpv.socket, "socket", lambda *args: sock)
    with pytest.raises(ConnectionRefusedError):
        mpv.MPVController()._open_pipe("/tmp/missing-mpv.sock")
    sock.close.assert_called_once()
