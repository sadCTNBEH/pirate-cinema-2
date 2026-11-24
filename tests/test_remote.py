"""Unit tests for Web Remote control service and endpoints."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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
from backend.services.remote_html import REMOTE_HTML


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


def test_remote_ip_uses_interface_address_before_loopback_fallback():
    from backend.services import remote

    with patch.object(remote.socket, "socket", side_effect=OSError("no default route")), patch.object(
        remote, "_get_interface_ipv4_addresses", return_value=["192.168.1.23"]
    ):
        assert remote.get_lan_ip() == "192.168.1.23"


def test_remote_api_and_page_routes():
    client = TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 1234))

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
    assert resp_html.text == REMOTE_HTML
    assert "no-store" in resp_html.headers["cache-control"]
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


def test_flatpak_backend_is_reachable_from_lan():
    manifest = Path("scripts/flatpak/io.github.sadctnbeh.PirateCinema.yml").read_text()
    assert "--env=APP_HOST=127.0.0.1" not in manifest
    run_script = Path("run.sh").read_text()
    env_example = Path(".env.example").read_text()
    assert 'export APP_HOST="${APP_HOST:-0.0.0.0}"' in run_script
    assert "APP_HOST=0.0.0.0" in env_example


async def test_remote_page_is_reachable_from_lan():
    transport = httpx.ASGITransport(app=app, client=("192.168.1.50", 1234))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://192.168.1.2:8000",
    ) as client:
        response = await client.get("/remote")

    assert response.status_code == 200
    assert "Pirate Cinema Remote" in response.text


def test_remote_assets_are_local_and_serve_the_expected_content():
    client = TestClient(app)
    page = client.get("/remote").text
    assets = [
        ("/remote/assets/remote.css", "text/css", "--film-bg:#090b10"),
        ("/static/vendor/hls.light.min.js", "javascript", "Hls"),
        ("/remote/assets/remote.js", "text/javascript", "function pollLoop()"),
    ]
    offsets = []
    for url, content_type, marker in assets:
        offsets.append(page.index(f'"{url}"'))
        response = client.get(url, headers={"Origin": "https://untrusted.example"})
        assert response.status_code == 200
        assert content_type in response.headers["content-type"]
        assert marker in response.text
        assert "access-control-allow-origin" not in response.headers
    assert offsets == sorted(offsets)
    assert "<style>" not in page and "<script>" not in page
    assert client.get("/remote/assets/index.html").status_code == 404

    preflight = client.options("/api/remote/pair", headers={
        "Origin": "https://untrusted.example",
        "Access-Control-Request-Method": "POST",
    })
    assert preflight.status_code == 405
    assert "access-control-allow-origin" not in preflight.headers


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

    # 2. The remote script handles popstate and updates the back control label.
    resp_html = client.get("/remote")
    assert resp_html.status_code == 200
    assert 'id="btnFullscreen"' in resp_html.text
    script = client.get("/remote/assets/remote.js")
    assert script.status_code == 200
    assert "initMobileHistory" in script.text
    assert "pushRemoteState" in script.text
    assert "popstate" in script.text
    assert "Назад в окно" in script.text


def test_remote_info_refresh_and_rotate_code():
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234))

    resp1 = client.get("/api/remote/info")
    assert resp1.status_code == 200
    code1 = resp1.json()["code"]
    qr1 = resp1.json()["qr_svg"]

    # Calling refresh rotates the pairing code and generates a new QR code SVG
    resp2 = client.post("/api/remote/refresh")
    assert resp2.status_code == 200
    code2 = resp2.json()["code"]
    qr2 = resp2.json()["qr_svg"]

    assert code1 != code2
    assert qr1 != qr2
    assert code2 in resp2.json()["url"]


def test_remote_watch_tab_and_buffering_hint():
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234))
    resp = client.get("/remote")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="tabWatchBtn"' in html
    assert "Смотреть на телефоне" in html
    assert 'id="panelWatch"' in html
    assert 'id="phoneBufferingHint"' in html
    assert "Буферизация может занять некоторое время" in html
    assert "при ошибке" in html.lower()
    assert 'id="phoneRefreshBtn"' in html
    assert "Обновить видео" in html

    js_resp = client.get("/remote/assets/remote.js")
    assert js_resp.status_code == 200
    js = js_resp.text
    assert "updateWatchTabState" in js
    assert "refreshPhoneStream" in js
    assert "startPosition" in js
    assert "Буферизация" in js
    assert "может занять некоторое время" in js
    assert "при ошибке попробуйте ещё раз" in js





