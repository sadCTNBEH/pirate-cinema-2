"""Unit tests for desktop API and LAN access separation (G-001)."""

import pytest
from fastapi.testclient import TestClient

import backend.views  # noqa: F401
from backend.app import app
from backend.core.settings import config


def test_config_interface_separation():
    """Verify config interface separation settings."""
    assert hasattr(config, "DESKTOP_HOST")
    assert config.DESKTOP_HOST == "127.0.0.1"
    assert hasattr(config, "DESKTOP_BIND_ADDRESS")
    assert config.DESKTOP_BIND_ADDRESS == "127.0.0.1"

    assert hasattr(config, "REMOTE_PORT")
    assert isinstance(config.REMOTE_PORT, int)
    assert hasattr(config, "LAN_PORT")
    assert config.LAN_PORT == config.REMOTE_PORT

    assert hasattr(config, "REMOTE_ENABLED")
    assert config.REMOTE_ENABLED is True
    assert hasattr(config, "LAN_REMOTE_ENABLED")
    assert config.LAN_REMOTE_ENABLED is True


def test_dangerous_desktop_apis_blocked_from_lan():
    """Verify that dangerous desktop APIs are blocked when accessed from LAN."""
    lan_client = TestClient(app, base_url="http://192.168.1.50:8000", client=("192.168.1.100", 54321))

    # 1. System Settings & Autostart
    resp = lan_client.get("/api/settings")
    assert resp.status_code == 403
    assert "desktop API запрещён" in resp.text

    resp = lan_client.post("/api/settings", json={"autostart": False})
    assert resp.status_code == 403
    assert "desktop API запрещён" in resp.text

    resp = lan_client.get("/api/settings/backup")
    assert resp.status_code == 403

    resp = lan_client.post("/api/settings/restore")
    assert resp.status_code == 403

    resp = lan_client.post("/api/settings/open_folder")
    assert resp.status_code == 403

    # 2. Process Management: Updater
    resp = lan_client.get("/api/updater/check")
    assert resp.status_code == 403
    assert "desktop API запрещён" in resp.text

    resp = lan_client.post("/api/updater/apply")
    assert resp.status_code == 403
    assert "desktop API запрещён" in resp.text

    # 3. Process Management: Diagnostics & TorrServer control
    resp = lan_client.post("/api/diagnostics/torrserver/restart")
    assert resp.status_code == 403
    assert "desktop API запрещён" in resp.text

    resp = lan_client.get("/api/diagnostics/torrserver/log")
    assert resp.status_code == 403
    assert "desktop API запрещён" in resp.text

    resp = lan_client.get("/api/diagnostics")
    assert resp.status_code == 403

    # 4. Process termination: Window close
    resp = lan_client.post("/api/window/close")
    assert resp.status_code == 403
    assert "desktop API запрещён" in resp.text


def test_desktop_apis_accessible_from_loopback():
    """Verify that loopback / desktop clients can access desktop APIs normally."""
    desktop_client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345))

    resp = desktop_client.get("/api/settings")
    assert resp.status_code == 200

    resp = desktop_client.get("/api/window/state")
    assert resp.status_code == 200


def test_safe_remote_endpoints_accessible_from_lan():
    """Verify that safe remote control endpoints and pages remain accessible on LAN."""
    from backend.services.mobile import mobile_access

    lan_client = TestClient(app, base_url="http://192.168.1.50:8000", client=("192.168.1.100", 54321))

    # Remote web page loads
    resp = lan_client.get("/remote")
    assert resp.status_code == 200
    assert "Pirate Cinema Remote" in resp.text

    # Pairing endpoint is reachable and functions for LAN client
    resp_invalid = lan_client.post("/api/remote/pair", json={"code": "000000"})
    assert resp_invalid.status_code == 403
    assert "актуальный QR-код" in resp_invalid.text

    resp_valid = lan_client.post("/api/remote/pair", json={"code": mobile_access.code})
    assert resp_valid.status_code == 200
    assert resp_valid.json().get("paired") is True


def test_dns_rebinding_protection():
    """Verify that Host headers pointing to untrusted external domains are blocked."""
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345))

    # Untrusted domain in Host header -> blocked
    resp = client.get("/api/remote/info", headers={"Host": "evil.com"})
    assert resp.status_code == 403
    assert "DNS rebinding" in resp.text

    resp = client.get("/api/settings", headers={"Host": "rebind.attacker.xyz:8000"})
    assert resp.status_code == 403
    assert "DNS rebinding" in resp.text

    # Trusted Host headers -> allowed
    resp = client.get("/api/settings", headers={"Host": "127.0.0.1:8000"})
    assert resp.status_code == 200

    resp = client.get("/api/settings", headers={"Host": "localhost:8000"})
    assert resp.status_code == 200


def test_cross_origin_protection():
    """Verify that untrusted Origin or cross-site Sec-Fetch-Site requests to API are blocked."""
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345))

    # Untrusted Origin on API -> blocked
    resp = client.post("/api/remote/pair", json={"code": "123456"}, headers={"Origin": "https://evil.com"})
    assert resp.status_code == 403

    # Cross-site Sec-Fetch-Site on API -> blocked
    resp = client.post("/api/remote/pair", json={"code": "123456"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert resp.status_code == 403


def test_remote_play_lan_requires_pairing():
    """Verify that remote playback launch from LAN requires pairing authorization and validates magnet."""
    lan_client = TestClient(app, base_url="http://192.168.1.50:8000", client=("192.168.1.100", 54321))

    # Unpaired LAN peer cannot launch playback
    resp = lan_client.post("/api/remote/play", json={"hash": "a" * 40})
    assert resp.status_code == 401

    # Loopback can call /api/remote/play without remote pairing token
    desktop_client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345))
    resp = desktop_client.post("/api/remote/play", json={})
    assert resp.status_code == 400
    assert "Missing torrent hash" in resp.text

    # Invalid magnet format is rejected with 422
    resp = desktop_client.post("/api/remote/play", json={"magnet": "http://evil.com/video.mp4"})
    assert resp.status_code == 422


def test_lan_remote_disabled_blocks_all_lan_access(monkeypatch):
    """Verify that disabling REMOTE_ENABLED prevents any LAN access."""
    monkeypatch.setattr(config, "REMOTE_ENABLED", False)

    lan_client = TestClient(app, base_url="http://192.168.1.50:8000", client=("192.168.1.100", 54321))
    resp = lan_client.get("/remote")
    assert resp.status_code == 403
    assert "отключён" in resp.text

    # Loopback remains working
    desktop_client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345))
    resp = desktop_client.get("/api/settings")
    assert resp.status_code == 200
