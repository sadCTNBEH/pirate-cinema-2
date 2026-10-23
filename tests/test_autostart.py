"""Unit tests for Windows autostart service and window show endpoint."""

from fastapi.testclient import TestClient
import pytest

from backend.app import app
from backend.services.autostart import (
    get_autostart_command,
    is_autostart_enabled,
    set_autostart,
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
