"""Unit tests for window controls and brand assets."""

import os
from unittest.mock import Mock

from fastapi.testclient import TestClient

import backend.views  # noqa: F401
from backend.app import app


def test_window_routes():
    client = TestClient(app)

    # 1. State
    resp = client.get("/api/window/state")
    assert resp.status_code == 200
    assert "is_maximized" in resp.json()

    # 2. Minimize
    resp = client.post("/api/window/minimize")
    assert resp.status_code == 200
    assert "success" in resp.json()

    # 3. Maximize
    resp = client.post("/api/window/maximize")
    assert resp.status_code == 200
    assert resp.json().get("is_maximized") is True

    # 4. Restore
    resp = client.post("/api/window/restore")
    assert resp.status_code == 200
    assert resp.json().get("is_maximized") is False

    # 5. Toggle Maximize
    resp = client.post("/api/window/toggle_maximize")
    assert resp.status_code == 200
    assert "is_maximized" in resp.json()

    # 6. Close
    resp = client.post("/api/window/close")
    assert resp.status_code == 200
    assert "success" in resp.json()


def test_brand_asset_routes():
    client = TestClient(app)

    # Logo
    resp = client.get("/logo.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")

    # Icon
    resp = client.get("/icon.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")

    # Favicon
    resp = client.get("/favicon.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")

    # Favicon ICO
    resp = client.get("/favicon.ico")
    assert resp.status_code == 200


def test_embedded_player_window_and_player_routes():
    client = TestClient(app)

    # 1. State includes is_fullscreen
    resp = client.get("/api/window/state")
    assert resp.status_code == 200
    assert "is_fullscreen" in resp.json()

    # 2. Player bounds
    resp = client.post(
        "/api/window/player_bounds",
        json={
            "x": 280,
            "y": 90,
            "width": 800,
            "height": 450,
            "viewport_width": 1280,
            "viewport_height": 720,
            "clip_top": 36,
            "clip_left": 256,
        },
    )
    assert resp.status_code == 200
    assert "success" in resp.json()

    # 3. Hide player
    resp = client.post("/api/window/hide_player")
    assert resp.status_code == 200
    assert "success" in resp.json()

    # 4. Window fullscreen toggle
    resp = client.post("/api/window/fullscreen", json={"fullscreen": False})
    assert resp.status_code == 200
    assert "is_fullscreen" in resp.json()

    # 5. Active player state
    resp = client.get("/api/player/active")
    assert resp.status_code == 200
    data = resp.json()
    assert "active" in data
    assert "is_fullscreen" in data

    # 6. Player fullscreen endpoint
    resp = client.post("/api/player/fullscreen", json={})
    assert resp.status_code == 200
    assert "is_fullscreen" in resp.json()

    # 7. Player command endpoint
    resp = client.post("/api/player/command", json=["cycle", "pause"])
    assert resp.status_code == 200
    assert resp.json().get("success") is True

    # 8. Input focus endpoint
    resp = client.post("/api/window/input_focus", json={"focused": True})
    assert resp.status_code == 200
    assert resp.json().get("focused") is True

    # 9. Player occluded endpoint
    resp = client.post("/api/window/player_occluded", json={"occluded": True})
    assert resp.status_code == 200
    assert resp.json().get("success") is True
    resp = client.post("/api/window/input_focus", json={"focused": False})
    assert resp.status_code == 200
    assert resp.json().get("focused") is False

    # 9. PiP endpoints
    resp = client.get("/api/window/state")
    assert resp.status_code == 200
    assert "is_pip" in resp.json()

    resp = client.post("/api/window/pip", json={"pip": True})
    assert resp.status_code == 200
    assert resp.json()["is_pip"] is (os.name == "nt")

    resp = client.post("/api/window/pip", json={"pip": False})
    assert resp.status_code == 200
    assert resp.json()["is_pip"] is False




def test_browser_mode_detection_and_fallback(monkeypatch):
    from backend.gui import (
        find_available_browser,
        is_native_gui_available,
        open_browser_window,
        window_api,
    )

    # 1. Test PIRATE_CINEMA_GUI=browser override
    monkeypatch.setenv("PIRATE_CINEMA_GUI", "browser")
    assert is_native_gui_available() is False

    # 2. Test find_available_browser returns None or valid tuple
    browser = find_available_browser()
    if browser:
        path, is_chrom = browser
        assert isinstance(path, str)
        assert isinstance(is_chrom, bool)

    # 3. Test open_browser_window with mocked Chromium browser
    monkeypatch.setattr(
        "backend.gui.find_available_browser",
        lambda: ("/usr/bin/chromium", True),
    )

    launched_cmd = []

    class DummyProc:
        def __init__(self, cmd):
            launched_cmd.extend(cmd)

        def poll(self):
            return None

        def terminate(self):
            pass

    monkeypatch.setattr("subprocess.Popen", lambda cmd, **kwargs: DummyProc(cmd))
    proc, is_app = open_browser_window("http://127.0.0.1:8000")
    assert is_app is True
    assert any("--app=http://127.0.0.1:8000" in arg for arg in launched_cmd)
    assert any("--user-data-dir=" in arg for arg in launched_cmd)

    # 4. Test window_api browser process lifecycle and close
    class DummyServer:
        should_exit = False

    server = DummyServer()
    window_api.set_browser_process(proc, server)
    assert window_api.close() is True
    assert server.should_exit is True


def test_tray_is_running_safe():
    from backend.services.tray import is_tray_running

    assert isinstance(is_tray_running(), bool)


def test_fullscreen_without_playback_safety(monkeypatch):
    from backend import gui

    window = Mock(native=None)
    monkeypatch.setattr(gui, "_window", window)
    window_api = gui.WindowApi()
    window_api.set_fullscreen(True)
    assert window_api.is_fullscreen() is True
    assert window_api._player_visible is False

    window_api.set_fullscreen(False)
    assert window_api.is_fullscreen() is False
    assert window_api._player_visible is False
    if os.name != "nt":
        assert window.toggle_fullscreen.call_count == 2


def test_tray_menu_initialization_without_gui():
    from PIL import Image

    from backend.services.tray import (
        TrayManager,
        create_tray_image,
        resolve_tray_icon,
    )

    # 1. Image generation without display
    icon_path = resolve_tray_icon()
    assert icon_path.name in ("tray.png", "favicon.png", "icon.png", "icon.ico")
    img = create_tray_image(icon_path)
    assert isinstance(img, Image.Image)

    # 2. Tray menu building and event routing without GUI
    manager = TrayManager()
    events = []
    manager._on_show = lambda: events.append("show")
    manager._on_exit = lambda: events.append("exit")
    manager.set_shutdown_service(lambda: events.append("shutdown"))

    menu = manager.build_menu(
        show_text="Open Pirate Cinema",
        exit_text="Quit",
        status_text="Status: Paused",
    )
    assert menu is not None
    # Verify menu structure: 3 items (Status, Open, Quit)
    items = list(menu.items)
    assert len(items) == 3
    assert items[0].text == "Status: Paused"
    assert items[0].enabled is False
    assert items[1].text == "Open Pirate Cinema"
    assert items[1].default is True
    assert items[2].text == "Quit"

    # Test event invocation
    manager._handle_show()
    assert "show" in events

    manager._handle_exit()
    assert "shutdown" in events

    # Dynamic status update
    manager.update_status("Playing Movie")
    assert manager._status_text == "Playing Movie"


def test_fallback_to_browser_helper(monkeypatch):
    from backend import gui

    launched_calls = []

    def mock_launch_browser_app(server, on_frontend_ready=None, start_minimized=False):
        launched_calls.append({
            "server": server,
            "on_frontend_ready": on_frontend_ready,
            "start_minimized": start_minimized,
        })

    monkeypatch.setattr(gui, "launch_browser_app", mock_launch_browser_app)
    monkeypatch.setattr(gui, "_window", Mock())

    server_mock = Mock()
    ready_mock = Mock()

    gui.fallback_to_browser(
        server_mock,
        on_frontend_ready=ready_mock,
        start_minimized=True,
        reason=RuntimeError("Webview crash"),
    )

    assert gui._window is None
    assert len(launched_calls) == 1
    assert launched_calls[0]["server"] is server_mock
    assert launched_calls[0]["on_frontend_ready"] is ready_mock
    assert launched_calls[0]["start_minimized"] is True


def test_native_input_bridge_polling_and_dispatch(monkeypatch):
    from backend.infrastructure.input_bridge import (
        NativeInputBridge,
        dispatch_browser_event,
    )

    events = []
    bridge = NativeInputBridge(emit_fn=lambda name, payload: events.append((name, payload)))
    bridge.set_hwnds(form_hwnd=1001, player_hwnd=2002)
    bridge.set_state(player_visible=True, player_occluded=False, input_focused=False)

    # Mock user32 API
    class MockUser32:
        GetForegroundWindow = Mock(return_value=1001)
        IsChild = Mock(return_value=False)
        GetGUIThreadInfo = Mock(side_effect=lambda flags, info_ref: setattr(info_ref._obj, "hwndFocus", 2002) or True)

        @staticmethod
        def GetAsyncKeyState(vk):
            # Simulate Spacebar (0x20) pressed
            return 0x8000 if vk == 0x20 else 0

    mock_user32 = MockUser32()
    bridge.poll_once(user32=mock_user32)

    assert any(name == "cinema-native-focus" and payload is True for name, payload in events)
    assert any(name == "cinema-native-key" and payload.get("code") == "Space" for name, payload in events)

    # Test browser DOM dispatch
    win = Mock()
    assert dispatch_browser_event(win, "test-event", {"status": "ok"}) is True
    win.evaluate_js.assert_called_once()
    assert "test-event" in win.evaluate_js.call_args[0][0]
    assert dispatch_browser_event(None, "test-event", {}) is False
