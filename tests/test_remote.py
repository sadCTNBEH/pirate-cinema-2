"""Unit tests for Web Remote control service and endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import backend.views  # noqa: F401
from backend.app import app
from backend.infrastructure.torrserver import client as ts_client
from backend.services.remote import (
    generate_qr_svg,
    get_lan_ip,
    get_local_hostname,
    get_remote_info,
    get_remote_url,
)


def test_remote_service_functions():
    ip = get_lan_ip()
    assert isinstance(ip, str)
    assert len(ip) >= 7

    local_host = get_local_hostname()
    if local_host:
        assert local_host.endswith(".local")

    url = get_remote_url(8001)
    assert url.startswith("http://")
    assert ":8001/remote" in url

    qr_svg = generate_qr_svg(url)
    assert "<svg" in qr_svg
    assert "</svg>" in qr_svg

    info = get_remote_info(8001)
    assert info["url"] == url
    assert info["ip"] == ip
    assert info["port"] == 8001
    assert "local_url" in info
    assert "ip_url" in info
    assert "qr_svg" in info
    assert "ip_qr_svg" in info
    assert "<svg" in info["qr_svg"]
    assert "<svg" in info["ip_qr_svg"]


def test_remote_api_and_page_routes():
    client = TestClient(app)

    # 1. API endpoint /api/remote/info
    resp = client.get("/api/remote/info")
    assert resp.status_code == 200
    data = resp.json()
    assert "url" in data
    assert "qr_svg" in data
    assert "ip" in data
    assert "port" in data
    assert "<svg" in data["qr_svg"]

    # 2. HTML view /remote
    resp_html = client.get("/remote")
    assert resp_html.status_code == 200
    assert "text/html" in resp_html.headers.get("content-type", "")
    assert "<title>Pirate Cinema Remote</title>" in resp_html.text
    assert 'apple-mobile-web-app-title" content="Pirate Cinema Remote"' in resp_html.text
    assert 'rel="apple-touch-icon"' in resp_html.text
    assert 'rel="manifest" href="/remote.webmanifest"' in resp_html.text
    assert "Локальный пульт" in resp_html.text
    assert "seekSlider" in resp_html.text
    assert "btnPlayPause" in resp_html.text
    assert "btnNext" in resp_html.text
    assert "tabSearch" in resp_html.text
    assert "searchInput" in resp_html.text

    # 3. Apple touch icon & Web Manifest
    resp_icon = client.get("/apple-touch-icon.png")
    assert resp_icon.status_code == 200
    assert resp_icon.headers.get("content-type") == "image/png"

    resp_manifest = client.get("/remote.webmanifest")
    assert resp_manifest.status_code == 200
    assert resp_manifest.json()["name"] == "Pirate Cinema Remote"
    assert resp_manifest.json()["display"] == "standalone"


def test_remote_play_missing_hash():
    client = TestClient(app)
    resp = client.post("/api/remote/play", json={})
    assert resp.status_code == 400
    assert "Missing torrent hash" in resp.text


def test_torrent_files_not_found_returns_404():
    mock_resp_404 = MagicMock()
    mock_resp_404.status_code = 404
    mock_resp_404.text = "null"

    mock_resp_add = MagicMock()
    mock_resp_add.status_code = 200
    mock_resp_add.text = '{"hash": "8fdd384779efe81511f561426c0d574487254493"}'
    mock_resp_add.json.return_value = {"hash": "8fdd384779efe81511f561426c0d574487254493"}
    mock_resp_add.raise_for_status = MagicMock()

    mock_client = MagicMock()
    # First call adds magnet if needed, second call gets files
    mock_client.post = AsyncMock(side_effect=[mock_resp_add, mock_resp_404, mock_resp_add])

    with patch.object(ts_client, "get_client", return_value=mock_client):
        client = TestClient(app)
        resp = client.get("/api/library/torrents/8fdd384779efe81511f561426c0d574487254493/files")
        assert resp.status_code == 404
        assert "err_files_not_found" in resp.text


def test_player_fullscreen_and_remote_history():
    client = TestClient(app)

    # 1. Player fullscreen via payload
    resp = client.post("/api/player/fullscreen", json={"fullscreen": True})
    assert resp.status_code == 200
    assert "is_fullscreen" in resp.json()

    resp = client.post("/api/player/fullscreen", json={"fullscreen": False})
    assert resp.status_code == 200
    assert "is_fullscreen" in resp.json()

    # 2. Remote HTML contains popstate handling and back prevention
    resp_html = client.get("/remote")
    assert resp_html.status_code == 200
    assert "initMobileHistory" in resp_html.text
    assert "pushRemoteState" in resp_html.text
    assert "popstate" in resp_html.text
    assert "Назад в окно" in resp_html.text



