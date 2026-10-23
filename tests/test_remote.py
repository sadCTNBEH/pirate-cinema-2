"""Unit tests for Web Remote control service and endpoints."""

from fastapi.testclient import TestClient

import backend.views  # noqa: F401
from backend.app import app
from backend.services.remote import generate_qr_svg, get_lan_ip, get_remote_info, get_remote_url


def test_remote_service_functions():
    ip = get_lan_ip()
    assert isinstance(ip, str)
    assert len(ip) >= 7

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
    assert "<svg" in info["qr_svg"]


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
    assert "Pirate Cinema" in resp_html.text
    assert "seekSlider" in resp_html.text
    assert "btnPlayPause" in resp_html.text
    assert "btnNext" in resp_html.text
