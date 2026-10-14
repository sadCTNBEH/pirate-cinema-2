"""Unit tests for window controls and brand assets."""

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


