import builtins
from unittest.mock import MagicMock

import pytest

from backend import gui
from backend.services import tray


def test_linux_defaults_to_browser_mode(monkeypatch):
    monkeypatch.setattr(gui.sys, "platform", "linux")
    monkeypatch.delenv("PIRATE_CINEMA_GUI", raising=False)
    monkeypatch.setattr(gui, "webview", MagicMock())
    assert gui.is_native_gui_available() is False


def test_tray_import_failure_is_optional(monkeypatch, tmp_path, caplog):
    original_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "pystray":
            raise RuntimeError("No X display or tray backend")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    monkeypatch.setattr(tray, "_tray", None)
    tray.start_tray(tmp_path / "missing.png", lambda: None, lambda: None)
    assert not tray.is_tray_running()
    assert "continuing without tray" in caplog.text


@pytest.mark.parametrize("original", [None, "/usr/local/lib"])
def test_frozen_browser_restores_system_library_paths(monkeypatch, tmp_path, original):
    monkeypatch.setattr(gui.sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123/internal-libs")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    if original is not None:
        monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", original)
    monkeypatch.setattr(gui, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(gui, "find_available_browser", lambda: ("/usr/bin/chromium", True))
    spawn = MagicMock()
    monkeypatch.setattr(gui.subprocess, "Popen", spawn)
    gui.open_browser_window("http://127.0.0.1:8000")
    assert spawn.call_args.kwargs["env"].get("LD_LIBRARY_PATH") == original
    assert "LD_LIBRARY_PATH_ORIG" not in spawn.call_args.kwargs["env"]


def test_missing_browser_reports_failure(monkeypatch):
    monkeypatch.setattr(gui, "find_available_browser", lambda: None)
    monkeypatch.setattr(gui.shutil, "which", lambda name: None)
    monkeypatch.setattr("webbrowser.open", lambda *args, **kwargs: False)
    with pytest.raises(RuntimeError, match="Could not open a browser"):
        gui.open_browser_window("http://127.0.0.1:8000")


def test_failed_backend_does_not_accept_another_apps_port(monkeypatch):
    from backend import main

    monkeypatch.setattr(main.server, "started", False)
    thread = MagicMock()
    thread.is_alive.return_value = False
    assert main.wait_for_backend(thread, timeout=1) is False
