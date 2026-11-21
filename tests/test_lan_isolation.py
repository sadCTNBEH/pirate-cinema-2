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


def test_session_token_lifecycle(tmp_path):
    """Verify session token generation, validation, expiry, and revocation."""
    from backend.services.mobile import MobileAccess

    access = MobileAccess()
    pair_file = tmp_path / "pairs.json"
    access.enable_persistence(pair_file)

    # 1. Generation
    tok = access.generate_token("192.168.1.100", ttl=3600)
    assert isinstance(tok, str)
    assert len(tok) >= 32

    # Secret is not stored in plaintext in the file
    assert tok not in pair_file.read_text()

    # 2. Validation
    assert access.validate_token(tok, "192.168.1.100") is True
    assert access.validate_token(tok, "192.168.1.101") is False  # Wrong host
    assert access.validate_token("unknown_token", "192.168.1.100") is False

    # 3. Expiry
    short_tok = access.generate_token("192.168.1.100", ttl=-1)
    assert access.is_token_expired(short_tok) is True
    assert access.validate_token(short_tok, "192.168.1.100") is False

    # 4. Revocation
    assert access.revoke_token(tok) is True
    assert access.validate_token(tok, "192.168.1.100") is False
    assert access.is_token_expired(tok) is True


def test_remote_session_helpers():
    """Verify remote service session helper functions."""
    from backend.services.remote import (
        generate_remote_session,
        is_remote_session_expired,
        revoke_remote_session,
        validate_remote_session,
    )

    token = generate_remote_session("192.168.1.55", ttl=1800)
    assert validate_remote_session(token, "192.168.1.55") is True
    assert validate_remote_session(token, "192.168.1.56") is False
    assert is_remote_session_expired(token) is False

    assert revoke_remote_session(token) is True
    assert validate_remote_session(token, "192.168.1.55") is False


def test_command_restrictions_and_system_call_rejection():
    """Verify that remote commands cannot execute system calls or arbitrary processes."""
    from backend.services.remote import is_safe_remote_command, validate_remote_command

    # Safe player commands
    assert is_safe_remote_command(["cycle", "pause"]) is True
    assert is_safe_remote_command(["seek", 10, "relative"]) is True
    assert is_safe_remote_command(["set_property", "volume", 50]) is True
    assert is_safe_remote_command(["set_property", "aid", 1]) is True
    assert is_safe_remote_command(["set_property", "sid", "no"]) is True
    assert is_safe_remote_command(["continuation", "play", "tok", 1]) is True

    # Dangerous commands (system calls, script injection, subprocess) must be rejected
    with pytest.raises(ValueError, match="системный вызов"):
        validate_remote_command(["run", "cmd.exe", "/c", "calc.exe"])

    with pytest.raises(ValueError, match="системный вызов"):
        validate_remote_command(["subprocess", "touch", "/tmp/pwned"])

    with pytest.raises(ValueError, match="системный вызов"):
        validate_remote_command(["loadscript", "/path/to/bad.lua"])

    with pytest.raises(ValueError, match="системный вызов"):
        validate_remote_command(["script-binding", "evil"])

    with pytest.raises(ValueError, match="запрещённая команда"):
        validate_remote_command(["arbitrary_custom_command"])

    with pytest.raises(ValueError, match="запрещено"):
        validate_remote_command(["set_property", "input-ipc-server", "/tmp/sock"])

    with pytest.raises(ValueError):
        validate_remote_command([])

    with pytest.raises(ValueError):
        validate_remote_command(None)


def test_media_path_restriction_outside_library():
    """Verify restriction on loading arbitrary filesystem paths outside media library."""
    from backend.services.remote import is_safe_media_source, validate_media_path

    # Safe media sources
    assert is_safe_media_source("http://127.0.0.1:18765/stream/video") is True
    assert is_safe_media_source("https://example.com/stream.m3u8") is True
    assert is_safe_media_source("magnet:?xt=urn:btih:8fdd384779efe81511f561426c0d574487254493") is True
    assert is_safe_media_source("video_file.mp4") is True

    # Dangerous paths outside library
    with pytest.raises(ValueError):
        validate_media_path("/etc/shadow")

    with pytest.raises(ValueError):
        validate_media_path("C:\\Windows\\System32\\cmd.exe")

    with pytest.raises(ValueError, match="path traversal"):
        validate_media_path("../../sensitive_data.mp4")

    with pytest.raises(ValueError, match="схема URL"):
        validate_media_path("file:///etc/passwd")

    with pytest.raises(ValueError, match="расширение"):
        validate_media_path("malicious.exe")


@pytest.mark.anyio
async def test_mobile_probe_blocks_system_files():
    """Verify that probe in mobile.py rejects arbitrary system files with 403."""
    from fastapi import HTTPException
    from backend.services.mobile import probe

    with pytest.raises(HTTPException) as exc_info:
        await probe("/etc/shadow")
    assert exc_info.value.status_code == 403
    assert "запрещён" in exc_info.value.detail

    with pytest.raises(HTTPException) as exc_info:
        await probe("C:\\Windows\\System32\\cmd.exe")
    assert exc_info.value.status_code == 403


def test_webview_bridge_trusted_window_protection():
    """Verify that WebView-bridge in gui.py only accepts calls from the trusted local window."""
    from unittest.mock import Mock
    from backend.gui import WindowApi

    api = WindowApi()
    token = api.get_bridge_token()
    assert isinstance(token, str) and len(token) >= 16

    # Bridge token verification
    assert api.verify_bridge_token(token) is True
    assert api.verify_bridge_token("invalid_token") is False
    assert api.verify_bridge_token(None) is False

    # Window caller verification
    mock_trusted = Mock(name="trusted_window")
    mock_untrusted = Mock(name="untrusted_window")

    api.set_trusted_window(mock_trusted)
    assert api.is_trusted_window(mock_trusted) is True
    assert api.is_trusted_window(mock_untrusted) is False

    assert api.verify_caller(window=mock_trusted) is True
    assert api.verify_caller(window=mock_untrusted) is False
    assert api.verify_caller(token=token) is True
    assert api.verify_caller(token="bad") is False

    # save_backup rejects untrusted caller
    res = api.save_backup(token="wrong_token")
    assert res["saved"] is False
    assert "не является доверенным" in res["error"]

