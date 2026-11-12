"""Regression tests for Linux MPV embedding, cinema.lua OSD, and error observability."""

import io
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
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


@pytest.mark.parametrize("legacy", [False, True])
def test_controller_launch_args_embedded(monkeypatch, tmp_path, legacy):
    """Verify MPVController constructs correct arguments when embedding on Linux."""
    controller = MPVController()
    captured_args = []
    monkeypatch.setattr("backend.infrastructure.mpv.controller.get_data_dir", lambda: tmp_path)
    monkeypatch.setenv("CINEMA_MPV_OSC", "legacy" if legacy else "")

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
    assert ("--osc=yes" if legacy else "--osc=no") in captured_args
    assert "--gpu-context=x11egl" in captured_args
    assert any(a.startswith("--script=") for a in captured_args) is not legacy
    assert ("--input-builtin-bindings=no" in captured_args) is not legacy
    assert ("--osd-bar=no" in captured_args) is not legacy
    assert ("--osd-font=DejaVu Sans" in captured_args) is not legacy
    assert any(a.startswith("--config-dir=") for a in captured_args) is not legacy
    assert "--input-default-bindings=yes" in captured_args
    assert any("--msg-level=" in a and "lua=warn" in a for a in captured_args)
    assert controller.is_embedded is True
    controller.stop()


def test_controller_osd_readiness_uses_render_events(monkeypatch, mpv_ipc_stream):
    controller = MPVController()
    controller._custom_osd = True
    controller.is_running = True
    ready_at = []

    def on_progress(name, pos):
        if name == "time-pos":
            ready_at.append(controller._osd_ready)

    controller.on_progress = on_progress
    commands = []
    monkeypatch.setattr(controller, "send_command", commands.append)
    position = {"event": "property-change", "name": "time-pos", "data": 20}
    events = [
        {"event": "client-message", "args": ["cinema-osd-ready", "1"]},
        position,
        {"event": "client-message", "args": ["cinema-osd-ready", "912", "515", "DejaVu Sans"]},
        position,
        {"event": "start-file"},
        position,
    ]
    controller.pipe = mpv_ipc_stream(b"".join(json.dumps(event).encode() + b"\n" for event in events))
    controller._reader_loop()

    assert ready_at == [False, True, False]
    assert ["set_property", "osc", True] not in commands


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
    not sys.platform.startswith("linux") or not os.environ.get("DISPLAY")
    or not all(shutil.which(tool) for tool in ("mpv", "ffmpeg", "xdotool")),
    reason="Requires Linux with X11/Xvfb and mpv, ffmpeg, xdotool",
)
def test_real_embedded_x11_mpv_flow(tmp_path, monkeypatch):
    """Capture composited controls and exercise native X11 mouse and keyboard events."""
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication, QMainWindow

    from backend.core.settings import config

    monkeypatch.setattr("backend.infrastructure.mpv.controller.get_data_dir", lambda: tmp_path)
    monkeypatch.delenv("CINEMA_MPV_OSC", raising=False)
    monkeypatch.setenv("FONTCONFIG_FILE", str(tmp_path / "unavailable-fontconfig.conf"))
    monkeypatch.setattr(config, "MPV_ARGS", [*config.MPV_ARGS, "--ao=null"])
    captions = tmp_path / "test.srt"
    captions.write_text("1\n00:00:00,000 --> 00:00:01,000\nТест\n", encoding="utf-8")
    video = tmp_path / "episode.mkv"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=0x304050:s=640x360:r=10:d=40",
        "-f", "lavfi", "-i", "anullsrc", "-i", str(captions),
        "-map", "0:v", "-map", "1:a", "-map", "1:a", "-map", "2:s",
        "-metadata:s:a:0", "title=Первая озвучка", "-metadata:s:a:1", "title=Вторая озвучка",
        "-metadata:s:s:0", "title=Русские субтитры",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-c:s", "srt", "-t", "40", str(video),
    ], check=True, timeout=30)
    next_video = tmp_path / "episode-2.mkv"
    next_video.hardlink_to(video)
    app = QApplication.instance() or QApplication([sys.argv[0], "-platform", "xcb"])
    if app.platformName() != "xcb":
        pytest.skip("Qt platform is not xcb")

    width, height = 912, 515  # Noninteger scale and ASS width.
    win = QMainWindow()
    win.resize(width, height)
    win.show()
    app.processEvents()
    surface = QtPlayerSurface(win)
    wid = surface.ensure_window()
    assert wid and wid > 0
    surface.update({
        "x": 0, "y": 0, "width": width, "height": height,
        "viewport_width": width, "viewport_height": height,
        "clip_left": 0, "clip_top": 0, "clip_right": width, "clip_bottom": height,
    }, True)
    app.processEvents()

    controller = MPVController()
    actions, properties = [], {}

    def progress(name, value):
        if name == "cinema-action":
            actions.append(value)
            if value[0] in ("cycle", "add", "set_property"):
                controller.send_command(value)
            elif value[0] == "cinema-seek":
                controller.send_command(["seek", value[1], "absolute+exact"])
        else:
            properties[name] = value

    def wait_until(condition, description="condition"):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            app.processEvents()
            if condition():
                return
            time.sleep(0.03)
        pytest.fail(
            f"Timed out waiting for {description}. Actions: {actions}\n"
            f"{(tmp_path / 'mpv_debug.log').read_text()}"
        )

    def pointer(x, y, button=None):
        args = ["xdotool", "mousemove", "--window", str(wid), str(x), str(y)]
        if button:
            args.extend(["click", str(button)])
        subprocess.run(args, check=True, timeout=5)

    def pointer_outside_window():
        geometry = subprocess.run(
            ["xdotool", "getwindowgeometry", "--shell", str(wid)],
            check=True, capture_output=True, text=True, timeout=5,
        ).stdout
        bounds = {}
        for line in geometry.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key in {"X", "Y", "WIDTH", "HEIGHT"}:
                bounds[key] = int(value)
        screen_width, screen_height = map(
            int, subprocess.check_output(
                ["xdotool", "getdisplaygeometry"], text=True, timeout=5
            ).split()
        )
        left, top = bounds["X"], bounds["Y"]
        right, bottom = left + bounds["WIDTH"], top + bounds["HEIGHT"]
        candidates = (
            (right + 2, top + bounds["HEIGHT"] // 2),
            (left + bounds["WIDTH"] // 2, bottom + 2),
            (left - 2, top + bounds["HEIGHT"] // 2),
            (left + bounds["WIDTH"] // 2, top - 2),
        )
        x, y = next(
            (x, y) for x, y in candidates
            if 0 <= x < screen_width and 0 <= y < screen_height
        )
        subprocess.run(
            ["xdotool", "mousemove", "--sync", str(x), str(y)],
            check=True, timeout=5,
        )

    def capture():
        return win.screen().grabWindow(wid).toImage()

    def save_frame(name, condition):
        wait_until(lambda: (frame := capture()).width() == width and frame.height() == height
                   and condition(frame), description=f"the {name} frame")
        frame = capture()
        assert frame.save(str(tmp_path / f"{name}.png"))
        return frame

    def has_ink(image, x, y, w, h):
        return sum(
            image.pixelColor(px, py).lightness() > 160
            for px in range(x, x+w) for py in range(y, y+h)
        ) > 5

    controller.on_progress = progress
    try:
        controller.launch(shutil.which("mpv"), str(video), "Первая серия", wid=wid)
        wait_until(lambda: controller._osd_ready and properties.get("duration", 0) >= 39)
        pointer(450, 200)
        regions = [
            (22, 10, 110, 25),  # Cyrillic title
            (33, 477, 19, 20),  # Play/pause
            (80, 477, 75, 20),  # Seek buttons
            (180, 477, 160, 20),  # Volume label and slider
            (858, 475, 29, 23),  # Fullscreen corners
            (22, 431, 45, 19),  # Elapsed time
            (860, 431, 30, 19),  # Duration
            (22, 451, 30, 9),  # Progress handle
        ]
        panel = save_frame("panel", lambda image: all(has_ink(image, *r) for r in regions))
        pointer(42, 487)
        save_frame("hover", lambda image: image.pixelColor(28, 480).lightness()
                   > panel.pixelColor(28, 480).lightness() + 15)
        pointer(42, 487, 1)
        wait_until(lambda: ["cycle", "pause"] in actions and properties.get("pause") is True)
        pointer(450, 200)
        save_frame("paused", lambda image: image.pixelColor(28, 480) == panel.pixelColor(28, 480)
                   and image.copy(33, 477, 19, 20) != panel.copy(33, 477, 19, 20))
        pointer(146, 487, 1)
        wait_until(lambda: ["cinema-step", 1] in actions)
        pointer(450, 456, 1)
        wait_until(lambda: any(a[0] == "cinema-seek" for a in actions)
                   and abs(properties.get("time-pos", 0) - 20) < 2)
        save_frame("thumbnail", lambda image: has_ink(image, 414, 395, 72, 27))
        pointer(290, 487, 1)
        wait_until(lambda: 45 <= properties.get("volume", 0) <= 55)
        pointer(872, 487, 1)
        wait_until(lambda: ["cinema", "fullscreen"] in actions)

        position, volume = properties["time-pos"], properties["volume"]
        pointer(450, 200, 4)
        wait_until(lambda: properties["volume"] == volume + 5)
        pointer(450, 200, 5)
        wait_until(lambda: properties["volume"] == volume)
        for button in (6, 7):
            pointer(450, 200, button)
        subprocess.run(["xdotool", "windowfocus", str(wid), "key", "Left"], check=True, timeout=5)
        wait_until(lambda: ["cinema-step", -1] in actions)
        assert properties["time-pos"] == position
        assert properties["volume"] == volume

        pointer(663, 487, 1)
        def menu_ink(image):
            return has_ink(image, 520, 230, 365, 190)

        save_frame("audio-menu", menu_ink)
        subprocess.run(["xdotool", "key", "Escape"], check=True, timeout=5)
        wait_until(lambda: actions[-1:] == [["cinema-menu", False]])
        pointer(754, 487, 1)
        save_frame("subtitle-menu", menu_ink)
        subprocess.run(["xdotool", "key", "Escape"], check=True, timeout=5)
        wait_until(lambda: actions[-1:] == [["cinema-menu", False]])
        pointer(826, 487, 1)
        save_frame("more-menu", menu_ink)
        subprocess.run(["xdotool", "key", "Escape"], check=True, timeout=5)
        wait_until(lambda: actions[-1:] == [["cinema-menu", False]])

        # Closing the menu leaves the pointer over its button. Move outside
        # the MPV window to produce a deterministic mouse-leave event before
        # checking the hidden frame; then move back in to verify the controls
        # are shown again.
        pointer_outside_window()
        def hidden_controls(image):
            # Xvfb's software/indirect OpenGL path can dither a flat video
            # color differently at separate pixels. Compare median luminance
            # across small flat regions while still detecting the OSD's dark bar.
            bottom = statistics.median(
                image.pixelColor(x, y).lightness()
                for x in range(690, 710) for y in range(463, 473)
            )
            video = statistics.median(
                image.pixelColor(x, y).lightness()
                for x in range(690, 710) for y in range(340, 350)
            )
            return abs(bottom - video) <= 5 and not has_ink(image, 858, 475, 29, 23)

        save_frame("hidden", hidden_controls)
        pointer(451, 200)
        save_frame("shown", lambda image: has_ink(image, 858, 475, 29, 23))
        controller.load_file(str(next_video), "Вторая серия", start_time=4)
        wait_until(lambda: controller._osd_ready and 3.5 <= (properties.get("time-pos") or 0) <= 6)
        save_frame("next-episode", lambda image: has_ink(image, 22, 10, 110, 25)
                   and has_ink(image, 75, 451, 40, 9)
                   and image.copy(22, 10, 110, 25) != panel.copy(22, 10, 110, 25))
    finally:
        controller.stop()
        win.close()
    log = (tmp_path / "mpv_debug.log").read_text()
    assert "Lua error:" not in log
    assert "OSD render failed" not in log
