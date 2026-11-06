import builtins
from unittest.mock import MagicMock

import pytest

from backend import gui
from backend.services import tray


@pytest.mark.parametrize(
    ("display", "inherited", "expected"),
    [(":1", "wayland", "xcb"), (":1", "wayland;xcb", "xcb"),
     (":1", "offscreen", "offscreen"), ("", "wayland", "wayland")],
)
def test_linux_qt_platform_supports_embedded_mpv(monkeypatch, display, inherited, expected):
    monkeypatch.setattr(gui.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", display)
    monkeypatch.setenv("PYWEBVIEW_GUI", "qt")
    monkeypatch.setenv("QT_QPA_PLATFORM", inherited)
    gui._configure_qt_platform()
    assert gui.os.environ["QT_QPA_PLATFORM"] == expected


def test_linux_defaults_to_browser_mode(monkeypatch):
    monkeypatch.setattr(gui.sys, "platform", "linux")
    monkeypatch.delenv("PIRATE_CINEMA_GUI", raising=False)
    monkeypatch.delenv("pirate_cinema_gui", raising=False)
    monkeypatch.setattr(gui, "webview", MagicMock())
    monkeypatch.setattr(gui, "_can_load_native_linux_gui", lambda: False)
    assert gui.is_native_gui_available() is False


@pytest.mark.parametrize("env_key,env_val", [
    ("PIRATE_CINEMA_GUI", "webview"),
    ("pirate_cinema_gui", "webview/"),
    ("PIRATE_CINEMA_GUI", "gtk/"),
    ("pirate_cinema_gui", "native"),
])
def test_linux_gui_env_enables_native(monkeypatch, env_key, env_val):
    monkeypatch.setattr(gui.sys, "platform", "linux")
    monkeypatch.delenv("PIRATE_CINEMA_GUI", raising=False)
    monkeypatch.delenv("pirate_cinema_gui", raising=False)
    monkeypatch.setenv(env_key, env_val)
    monkeypatch.setattr(gui, "webview", MagicMock())
    assert gui.is_native_gui_available() is True


def test_linux_gui_native_when_backend_available(monkeypatch):
    monkeypatch.setattr(gui.sys, "platform", "linux")
    monkeypatch.delenv("PIRATE_CINEMA_GUI", raising=False)
    monkeypatch.delenv("pirate_cinema_gui", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setattr(gui, "webview", MagicMock())
    monkeypatch.setattr(gui, "_can_load_native_linux_gui", lambda: True)
    assert gui.is_native_gui_available() is True


def test_linux_native_window_uses_pywebview_instead_of_winforms(monkeypatch):
    monkeypatch.setattr(gui.os, "name", "posix")
    window = MagicMock()
    monkeypatch.setattr(gui, "_window", window)
    api = gui.WindowApi()
    assert api.ensure_player_hwnd() is None
    assert api.set_pip(True) is False
    assert api.set_fullscreen(True) is True
    assert api.set_fullscreen(True) is True
    assert api.set_fullscreen(False) is False
    assert window.toggle_fullscreen.call_count == 2


def test_tray_assertion_error_caught_safely(monkeypatch, tmp_path, caplog):
    original_import = builtins.__import__
    mock_pystray = MagicMock()
    mock_icon = MagicMock()
    mock_icon.run.side_effect = AssertionError("Failed to dock icon")
    mock_pystray.Icon.return_value = mock_icon

    def custom_import(name, *args, **kwargs):
        if name == "pystray":
            return mock_pystray
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("backend.services.tray._tray", None)
    monkeypatch.setattr(tray, "_linux_backend", lambda: "xorg")
    monkeypatch.setattr(tray.sys, "platform", "linux")
    monkeypatch.setenv("PYSTRAY_BACKEND", "before-test")
    monkeypatch.setattr(tray.threading, "Thread", lambda **kwargs: MagicMock(start=lambda: kwargs["target"]()))
    monkeypatch.setattr(builtins, "__import__", custom_import)

    tray.start_tray(tmp_path / "test.png", lambda: None, lambda: None)
    assert not tray.is_tray_running()
    assert tray.os.environ["PYSTRAY_BACKEND"] == "before-test"


def test_tray_import_failure_is_optional(monkeypatch, tmp_path, caplog):
    original_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "pystray":
            raise RuntimeError("No X display or tray backend")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    monkeypatch.setattr(tray, "_linux_backend", lambda: "xorg")
    monkeypatch.setattr(tray.sys, "platform", "linux")
    monkeypatch.setattr(tray, "_tray", None)
    tray.start_tray(tmp_path / "missing.png", lambda: None, lambda: None)
    assert not tray.is_tray_running()
    assert "continuing without tray" in caplog.text


def test_linux_wayland_without_status_notifier_disables_tray(monkeypatch, tmp_path):
    monkeypatch.setattr(tray.sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("DISPLAY", ":1")
    monkeypatch.setattr(tray, "_has_status_notifier_host", lambda: False)
    monkeypatch.setattr(tray, "_has_xembed_tray", lambda: False)
    monkeypatch.setattr(tray, "_has_appindicator", lambda: True)
    monkeypatch.setattr(tray, "_tray", None)
    tray.start_tray(tmp_path / "missing.png", lambda: None, lambda: None)
    assert not tray.is_available()
    assert not tray.is_tray_running()


def test_wayland_xwayland_uses_xorg_only_if_xembed_selection_exists(monkeypatch):
    monkeypatch.setattr(tray.sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("DISPLAY", ":1")
    monkeypatch.setattr(tray, "_has_status_notifier_host", lambda: False)
    monkeypatch.setattr(tray, "_has_appindicator", lambda: False)
    monkeypatch.setattr(tray, "_has_xembed_tray", lambda: True)
    assert tray._linux_backend() == "xorg"


def test_linux_status_notifier_uses_appindicator_only_with_dependencies(monkeypatch):
    monkeypatch.setattr(tray.sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setattr(tray, "_has_status_notifier_host", lambda: True)
    monkeypatch.setattr(tray, "_has_appindicator", lambda: True)
    monkeypatch.setattr(tray, "_has_xembed_tray", lambda: False)
    assert tray._linux_backend() == "appindicator"


def test_linux_x11_uses_xorg_only_with_xembed_manager(monkeypatch):
    monkeypatch.setattr(tray.sys, "platform", "linux")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(tray, "_has_status_notifier_host", lambda: False)
    monkeypatch.setattr(tray, "_has_appindicator", lambda: False)
    monkeypatch.setattr(tray, "_has_xembed_tray", lambda: True)
    assert tray._linux_backend() == "xorg"
    monkeypatch.setattr(tray, "_has_xembed_tray", lambda: False)
    assert tray._linux_backend() is None


def test_xembed_probe_checks_the_per_screen_tray_selection(monkeypatch):
    class Owner:
        id = 42

    class FakeDisplay:
        closed = False

        def get_default_screen(self):
            return 2

        def intern_atom(self, name, only_if_exists):
            assert name == "_NET_SYSTEM_TRAY_S2" and only_if_exists
            return 10

        def get_selection_owner(self, selection):
            assert selection == 10
            return Owner()

        def close(self):
            self.closed = True

    fake = FakeDisplay()
    monkeypatch.setenv("DISPLAY", ":1")
    monkeypatch.setattr("Xlib.display.Display", lambda: fake)
    assert tray._has_xembed_tray()
    assert fake.closed


def test_xembed_probe_handles_display_access_denial(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":1")
    monkeypatch.setattr("Xlib.display.Display", lambda: (_ for _ in ()).throw(PermissionError("display denied")))
    assert tray._has_xembed_tray() is False


def test_close_minimizes_only_when_the_tray_icon_is_really_running(monkeypatch):
    monkeypatch.setattr(tray, "_tray", None)
    assert tray.should_minimize_to_tray(True) is False
    monkeypatch.setattr(tray, "_tray", MagicMock(visible=True))
    assert tray.should_minimize_to_tray(True) is True
    assert tray.should_minimize_to_tray(False) is False


def test_windows_tray_detection_does_not_probe_linux_backends(monkeypatch):
    monkeypatch.setattr(tray.sys, "platform", "win32")
    monkeypatch.setattr(tray, "_linux_backend", lambda: pytest.fail("Linux backend must not run"))
    assert tray.is_available()


def test_windows_tray_start_keeps_pystray_default_backend(monkeypatch, tmp_path):
    original_import = builtins.__import__
    mock_pystray = MagicMock()
    mock_icon = MagicMock()
    mock_pystray.Icon.return_value = mock_icon

    def custom_import(name, *args, **kwargs):
        if name == "pystray":
            return mock_pystray
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(tray.sys, "platform", "win32")
    monkeypatch.setenv("PYSTRAY_BACKEND", "")
    monkeypatch.setattr(tray.threading, "Thread", lambda **kwargs: MagicMock(start=lambda: None))
    monkeypatch.setattr(builtins, "__import__", custom_import)
    tray.start_tray(tmp_path / "missing.png", lambda: None, lambda: None)
    assert mock_pystray.Icon.called
    assert tray.os.environ["PYSTRAY_BACKEND"] == ""
    tray.stop_tray()


def test_external_player_api_accepts_only_local_animego_player_route(monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url, new=0: opened.append((url, new)) or True)
    monkeypatch.setattr(gui.config, "APP_HOST", "127.0.0.1")
    monkeypatch.setattr(gui.config, "APP_PORT", 8000)
    api = gui.WindowApi()
    assert api.open_external_player("https://evil.test/")['opened'] is False
    result = api.open_external_player("/api/online/animego/web/" + "a" * 32)
    assert result['opened'] is True
    assert opened == [("http://127.0.0.1:8000/api/online/animego/web/" + "a" * 32, 2)]


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
