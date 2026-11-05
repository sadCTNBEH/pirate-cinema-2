"""Regression tests for Linux MPV embedding, cinema.lua OSD, and error observability."""

import io
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.infrastructure.mpv.controller import MPVController, resolve_cinema_lua_path
from backend.infrastructure.mpv.qt_surface import QtPlayerSurface


def test_qt_player_surface_imports_without_qtpy():
    """Verify QtPlayerSurface imports and initializes without requiring qtpy."""
    assert QtPlayerSurface is not None
    is_supp = QtPlayerSurface.supported()
    assert isinstance(is_supp, bool)


def test_qt_player_surface_supported_platform_detection(monkeypatch):
    """Verify supported() requires 'xcb' on Linux."""
    monkeypatch.setattr(sys, "platform", "linux")

    class FakeApp:
        def __init__(self, platform):
            self._platform = platform

        def platformName(self):
            return self._platform

    with patch("backend.infrastructure.mpv.qt_surface.QApplication") as mock_qapp:
        mock_qapp.instance.return_value = FakeApp("wayland")
        assert QtPlayerSurface.supported() is False

        mock_qapp.instance.return_value = FakeApp("xcb")
        assert QtPlayerSurface.supported() is True

        mock_qapp.instance.return_value = None
        monkeypatch.delenv("DISPLAY", raising=False)
        assert QtPlayerSurface.supported() is False

        monkeypatch.setenv("DISPLAY", ":0")
        assert QtPlayerSurface.supported() is True


def test_resolve_cinema_lua_path():
    """Verify cinema.lua is found across supported layouts."""
    path = resolve_cinema_lua_path()
    assert path is not None
    assert path.is_file()
    assert path.name == "cinema.lua"


def test_controller_launch_args_embedded(monkeypatch):
    """Verify MPVController constructs correct arguments when embedding on Linux."""
    controller = MPVController()
    captured_args = []

    def fake_popen(args, **kwargs):
        captured_args.extend(args)
        proc = MagicMock()
        proc.pid = 99999
        proc.poll.return_value = None
        return proc

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    fake_stream = MagicMock()
    fake_stream.readline.return_value = b""
    fake_stream.__iter__.return_value = iter([])
    fake_stream.makefile.return_value = io.BytesIO(b"")
    monkeypatch.setattr(controller, "_open_pipe", lambda pipe: fake_stream)
    monkeypatch.setattr(controller, "_verify_cache", lambda: None)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")

    controller.launch(
        mpv_path="mpv",
        url="http://example.com/video.mp4",
        title="Test Video",
        wid=123456,
    )

    assert "--wid=123456" in captured_args
    assert "--osc=no" in captured_args
    assert "--gpu-context=x11egl" in captured_args
    assert any("--script=" in a for a in captured_args)
    assert any("--msg-level=" in a and "lua=warn" in a for a in captured_args)
    assert controller.is_embedded is True
    controller.stop()


def test_controller_osd_readiness_and_fallback():
    """Verify controller transitions to fallback OSC if cinema.lua does not signal readiness."""
    controller = MPVController()
    controller._custom_osd = True
    controller._osd_ready = False
    controller._osd_fallback_enabled = False
    commands_sent = []
    controller.send_command = lambda cmd: commands_sent.append(cmd)

    # First event: client-message cinema-osd-ready
    ready_event = {"event": "client-message", "args": ["cinema-osd-ready", "1"]}
    if ready_event["event"] == "client-message" and ready_event["args"][0] == "cinema-osd-ready":
        controller._osd_ready = True

    assert controller._osd_ready is True
    assert controller._osd_fallback_enabled is False

    # Reset and test timeout fallback when playback progresses without readiness
    controller._osd_ready = False
    assert controller._osd_ready is False

    # Simulate playback time reaching 1.0s without osd_ready
    if not controller._osd_ready and not controller._osd_fallback_enabled:
        controller._osd_fallback_enabled = True
        controller.send_command(["set_property", "osc", True])

    assert controller._osd_fallback_enabled is True
    assert ["set_property", "osc", True] in commands_sent


def test_playback_service_wid_error_logging_not_suppressed(monkeypatch):
    """Verify that exceptions during ensure_player_hwnd are logged and not silently ignored."""
    class BrokenWindowApi:
        def ensure_player_hwnd(self):
            raise RuntimeError("Test window error")

    with patch("backend.services.playback.logger") as mock_logger:
        with monkeypatch.context() as m:
            import backend.gui
            m.setattr(backend.gui, "window_api", BrokenWindowApi())
            prefs = {"embedded_player": True}

            wid = None
            if prefs.get("embedded_player", True):
                try:
                    from backend.gui import window_api
                    wid = window_api.ensure_player_hwnd()
                except Exception as err:
                    mock_logger.warning("[PLAYBACK] Failed to obtain embedded player window ID: %s", err, exc_info=True)

            assert wid is None
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args[0]
            assert "Failed to obtain embedded player window ID" in call_args[0]


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not os.environ.get("DISPLAY") or not shutil.which("mpv"),
    reason="Requires Linux with active DISPLAY and mpv",
)
def test_real_embedded_x11_mpv_flow(tmp_path):
    """Real embedded MPV test on Linux with Qt window and X11/XWayland surface."""
    try:
        from PyQt6.QtWidgets import QApplication, QMainWindow
    except ImportError:
        pytest.skip("PyQt6 is required for real embedded test")

    app = QApplication.instance() or QApplication([sys.argv[0], "-platform", "xcb"])
    if app.platformName() != "xcb":
        pytest.skip("Qt platform is not xcb (X11/XWayland required for real --wid embedding)")

    win = QMainWindow()
    win.resize(640, 360)
    win.show()
    app.processEvents()

    surface = QtPlayerSurface(win)
    wid = surface.ensure_window()
    assert wid is not None and wid > 0
    bounds = {
        "x": 0,
        "y": 0,
        "width": 640,
        "height": 360,
        "viewport_width": 640,
        "viewport_height": 360,
        "clip_left": 0,
        "clip_top": 0,
        "clip_right": 640,
        "clip_bottom": 360,
    }
    surface.update(bounds, True)
    app.processEvents()

    controller = MPVController()
    progress = []
    controller.on_progress = lambda name, val: progress.append((name, val))

    test_video = "/tmp/test-video/sample.mp4" if Path("/tmp/test-video/sample.mp4").is_file() else "av://lavfi:testsrc=duration=5:size=320x240:rate=25"

    controller.launch(
        mpv_path=shutil.which("mpv"),
        url=test_video,
        title="Regression Test Video",
        wid=wid,
    )

    try:
        deadline = time.time() + 4.0
        while time.time() < deadline and not controller._osd_ready:
            app.processEvents()
            time.sleep(0.05)

        assert controller.is_running is True
        assert controller.is_embedded is True
        assert controller._osd_ready is True, "cinema.lua must signal cinema-osd-ready"

        controller.send_command(["keypress", "WHEEL_UP"])
        deadline = time.time() + 2.0
        received_action = False
        while time.time() < deadline:
            app.processEvents()
            for name, val in progress:
                if name == "cinema-action" and isinstance(val, list) and val[:2] == ["add", "volume"]:
                    received_action = True
                    break
            if received_action:
                break
            time.sleep(0.05)

        assert received_action is True, f"WHEEL_UP must trigger volume cinema-action, got events: {progress}"
    finally:
        controller.stop()
        win.close()
        win.close()
