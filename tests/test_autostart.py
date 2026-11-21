"""Unit tests for Windows autostart service and window show endpoint."""

from fastapi.testclient import TestClient

from backend.app import app
from backend.services.autostart import (
    LinuxAutostartBackend,
    WindowsAutostartBackend,
    get_autostart_command,
    is_autostart_enabled,
    set_autostart,
    should_start_minimized,
)


def test_autostart_command():
    cmd = get_autostart_command()
    assert "--minimized" in cmd


def test_set_and_query_autostart():
    # Test setting autostart
    ok = set_autostart(True)
    assert ok is True
    assert is_autostart_enabled() is True

    # Test clearing autostart
    ok_disable = set_autostart(False)
    assert ok_disable is True
    assert is_autostart_enabled() is False


def test_settings_api_autostart_fields():
    client = TestClient(app)

    # Initial get
    get_resp = client.get("/api/settings")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert "autostart" in data
    assert "autostart_prompted" in data

    # Update autostart settings
    post_resp = client.post(
        "/api/settings",
        json={"autostart": False, "autostart_prompted": True},
    )
    assert post_resp.status_code == 200

    # Verify updated settings
    verify_resp = client.get("/api/settings")
    assert verify_resp.status_code == 200
    updated = verify_resp.json()
    assert updated.get("autostart") is False
    assert updated.get("autostart_prompted") is True


def test_window_show_endpoint():
    client = TestClient(app)
    resp = client.post("/api/window/show")
    assert resp.status_code == 200
    data = resp.json()
    assert "success" in data
    assert data["is_visible"] is True


def test_should_start_minimized():
    assert should_start_minimized(["--minimized"]) is True
    assert should_start_minimized(["--autostart"]) is True
    assert should_start_minimized(["--tray"]) is True
    assert should_start_minimized(["--port", "8000"]) is False
    assert should_start_minimized([]) is False


def test_linux_autostart_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = LinuxAutostartBackend("test-app.desktop")

    assert backend.is_enabled() is False

    # Enable
    ok = backend.set_enabled(True)
    assert ok is True
    assert backend.is_enabled() is True
    desktop_file = backend.desktop_file
    assert desktop_file.is_file()
    content = desktop_file.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert "--minimized" in content

    # Disable
    ok_disable = backend.set_enabled(False)
    assert ok_disable is True
    assert backend.is_enabled() is False
    assert not desktop_file.exists()


def test_windows_autostart_backend_structure():
    backend = WindowsAutostartBackend()
    assert backend.run_key_name == "Pirate Cinema"
    assert "CurrentVersion\\Run" in backend.reg_path
