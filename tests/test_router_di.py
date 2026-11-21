"""Tests for FastAPI dependency injection and dependency overrides in routers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import (
    RemoteService,
    get_history_repo,
    get_library_service,
    get_magnet_service,
    get_mobile_service,
    get_playback_repo,
    get_playback_service,
    get_remote_service,
    get_torrserver_client,
    get_torrserver_url,
    get_window_api,
)
from backend.api.routers.player import player_router
from backend.api.routers.remote import remote_router
from backend.models.playback import PlayCommand


@pytest.fixture
def test_app():
    app = FastAPI()
    app.include_router(player_router)
    app.include_router(remote_router)
    return app


def test_player_router_dependency_overrides_playback_service(test_app):
    mock_playback = MagicMock()
    mock_playback.launch = AsyncMock(return_value="launched")
    mock_playback.stop_playback = AsyncMock(return_value={"status": "stopped"})
    mock_playback.get_active_playback.return_value = {
        "active": True,
        "hash": "test_hash",
        "file_id": 1,
        "file_name": "video.mkv",
    }
    mock_playback.handle_command = AsyncMock()
    mock_playback.set_fullscreen.return_value = True
    mock_playback.get_state = AsyncMock(return_value={"timecode": 42, "duration": 100})

    test_app.dependency_overrides[get_playback_service] = lambda: mock_playback

    client = TestClient(test_app)

    # 1. POST /api/player/play
    resp = client.post(
        "/api/player/play",
        json={"hash": "test_hash", "file_id": 1, "file_name": "video.mkv"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "launched"}
    assert mock_playback.launch.await_count == 1
    call_arg = mock_playback.launch.await_args[0][0]
    assert isinstance(call_arg, PlayCommand)
    assert call_arg.hash == "test_hash"

    # 2. GET /api/player/active
    resp = client.get("/api/player/active")
    assert resp.status_code == 200
    assert resp.json()["active"] is True
    assert resp.json()["file_name"] == "video.mkv"
    mock_playback.get_active_playback.assert_called_once()

    # 3. POST /api/player/command
    resp = client.post("/api/player/command", json=["pause"])
    assert resp.status_code == 200
    assert resp.json() == {"success": True}
    mock_playback.handle_command.assert_awaited_once_with(["pause"])

    # 4. POST /api/player/fullscreen
    resp = client.post("/api/player/fullscreen", json={"fullscreen": True})
    assert resp.status_code == 200
    assert resp.json() == {"is_fullscreen": True}
    mock_playback.set_fullscreen.assert_called_once_with(True)

    # 5. GET /api/player/state/{hash}/{file_id}
    resp = client.get("/api/player/state/test_hash/1")
    assert resp.status_code == 200
    assert resp.json() == {"timecode": 42, "duration": 100}
    mock_playback.get_state.assert_awaited_once_with("test_hash", 1)

    # 6. POST /api/player/stop
    resp = client.post("/api/player/stop")
    assert resp.status_code == 200
    assert resp.json() == {"status": "stopped"}
    mock_playback.stop_playback.assert_awaited_once()


def test_player_router_dependency_overrides_magnet_service(test_app):
    mock_magnet = MagicMock()
    mock_magnet.add_magnet = AsyncMock(return_value={"hash": "abc1234", "title": "Test Title"})
    mock_magnet.delete_torrent = AsyncMock(return_value={"status": "deleted"})

    test_app.dependency_overrides[get_magnet_service] = lambda: mock_magnet

    client = TestClient(test_app)

    # 1. POST /api/player/add_magnet
    resp = client.post(
        "/api/player/add_magnet",
        json={"magnet": "magnet:?xt=urn:btih:abc1234", "title": "Test Title"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"hash": "abc1234", "title": "Test Title"}
    mock_magnet.add_magnet.assert_awaited_once_with("magnet:?xt=urn:btih:abc1234", "Test Title")

    # 2. DELETE /api/player/torrent/{hash}
    resp = client.delete("/api/player/torrent/abc1234")
    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted"}
    mock_magnet.delete_torrent.assert_awaited_once_with("abc1234")


def test_remote_router_dependency_overrides_remote_service_and_mobile(test_app):
    mock_remote_service = MagicMock(spec=RemoteService)
    mock_remote_service.get_info.return_value = {
        "url": "http://mock-remote:8001/remote#pair=1234",
        "local_url": "http://mock-remote:8001/remote#pair=1234",
        "ip_url": "http://192.168.1.50:8001/remote#pair=1234",
        "hostname": "mock-host",
        "ip": "192.168.1.50",
        "port": 8001,
        "qr_svg": "<svg>mock_qr</svg>",
        "ip_qr_svg": "<svg>mock_ip_qr</svg>",
    }

    mock_mobile = MagicMock()
    mock_mobile.pair.return_value = "mock_auth_token_xyz"

    test_app.dependency_overrides[get_remote_service] = lambda: mock_remote_service
    test_app.dependency_overrides[get_mobile_service] = lambda: mock_mobile

    client = TestClient(test_app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234))

    # 1. GET /api/remote/info
    resp = client.get("/api/remote/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == "http://mock-remote:8001/remote#pair=1234"
    assert data["port"] == 8001
    assert data["qr_svg"] == "<svg>mock_qr</svg>"
    mock_remote_service.get_info.assert_called_once()

    # 2. POST /api/remote/pair
    resp = client.post("/api/remote/pair", json={"code": "1234"})
    assert resp.status_code == 200
    assert resp.json() == {"paired": True, "token": "mock_auth_token_xyz"}
    assert "pc_remote" in resp.cookies
    assert resp.cookies["pc_remote"] == "mock_auth_token_xyz"
    mock_mobile.pair.assert_called_once()


def test_remote_router_dependency_overrides_remote_play(test_app):
    mock_playback = MagicMock()
    mock_playback.launch = AsyncMock(return_value="launched")

    mock_magnet = MagicMock()
    mock_magnet.add_magnet = AsyncMock(return_value={"hash": "overridden_hash"})

    mock_library = MagicMock()
    mock_library.get_torrent_files_structure = AsyncMock(
        return_value={
            "type": "movie",
            "movies": [{"id": 4, "name": "Overridden_Movie.mkv", "length": 500000}],
        }
    )

    mock_mobile = MagicMock()
    mock_window_api = MagicMock()
    mock_window_api.show = MagicMock(return_value=True)
    mock_window_api.set_fullscreen = MagicMock(return_value=True)

    test_app.dependency_overrides[get_playback_service] = lambda: mock_playback
    test_app.dependency_overrides[get_magnet_service] = lambda: mock_magnet
    test_app.dependency_overrides[get_library_service] = lambda: mock_library
    test_app.dependency_overrides[get_mobile_service] = lambda: mock_mobile
    test_app.dependency_overrides[get_window_api] = lambda: mock_window_api

    client = TestClient(test_app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234))

    resp = client.post(
        "/api/remote/play",
        json={
            "hash": "overridden_hash",
            "title": "Overridden Movie",
            "fullscreen": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "launched"
    assert data["hash"] == "overridden_hash"
    assert data["file_id"] == 4
    assert data["file_name"] == "Overridden_Movie.mkv"

    # Verify injected mocks were called
    mock_playback.launch.assert_awaited_once()
    launched_cmd = mock_playback.launch.await_args[0][0]
    assert isinstance(launched_cmd, PlayCommand)
    assert launched_cmd.hash == "overridden_hash"
    assert launched_cmd.file_id == 4

    mock_window_api.show.assert_called_once()
    mock_window_api.set_fullscreen.assert_called_once_with(True)


def test_player_router_extra_endpoints_with_overrides(test_app):
    mock_playback = MagicMock()
    mock_playback.subtitles.search = AsyncMock(return_value=[{"id": "sub1", "title": "Russian"}])
    mock_playback.subtitles.attach = AsyncMock(return_value={"status": "attached"})
    mock_playback.select_torrent_file = AsyncMock(
        return_value={"file": {"id": 0, "name": "ep1.mkv"}}
    )
    mock_playback.play_next_file = AsyncMock(return_value=True)
    mock_playback.recover = AsyncMock(return_value="recovered")
    mock_playback.tv.info.return_value = {"enabled": True, "channel": "Demo"}
    mock_playback.tv_action = AsyncMock(return_value={"action": "ok"})

    test_app.dependency_overrides[get_playback_service] = lambda: mock_playback

    client = TestClient(test_app)

    # subtitles search
    resp = client.post(
        "/api/player/subtitles/search",
        json={"hash": "abc", "file_id": 0, "title": "Movie"},
    )
    assert resp.status_code == 200
    assert resp.json() == [{"id": "sub1", "title": "Russian"}]

    # subtitles attach
    resp = client.post(
        "/api/player/subtitles/attach",
        json={"hash": "abc", "file_id": 0, "token": "tok"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "attached"}

    # select file
    resp = client.post("/api/player/select-file", json={"hash": "abc"})
    assert resp.status_code == 200
    assert resp.json() == {"file": {"id": 0, "name": "ep1.mkv"}}

    # next
    resp = client.post("/api/player/next", json={"hash": "abc", "file_id": 0})
    assert resp.status_code == 200
    assert resp.json() == {"status": "launched"}

    # recover
    resp = client.post("/api/player/recover")
    assert resp.status_code == 200
    assert resp.json() == {"status": "recovered"}

    # cast
    resp = client.get("/api/player/cast")
    assert resp.status_code == 200
    assert resp.json() == {"enabled": True, "channel": "Demo"}

    # cast action
    resp = client.post("/api/player/cast/stop")
    assert resp.status_code == 200
    assert resp.json() == {"action": "ok"}


def test_remote_router_dependency_overrides_mobile_play(test_app, monkeypatch):
    from unittest.mock import patch

    torrent_hash = "a" * 40
    mock_playback = MagicMock()
    mock_playback.select_torrent_file = AsyncMock(
        return_value={
            "file": {"id": 2, "name": "Ep2.mkv", "length": 1000},
            "candidates": [],
            "reason": None,
        }
    )
    mock_playback.active_states = {}

    mock_magnet = MagicMock()
    mock_history = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_previous_progress = MagicMock(return_value=None)
    mock_repo.logical_progress = MagicMock(return_value=None)

    mock_mobile = MagicMock()
    mock_mobile.authorize.return_value = "client_owner_1"
    mock_mobile.sessions = {}
    mock_mobile.preparing = MagicMock()
    mock_mobile.preparing.__aenter__ = AsyncMock()
    mock_mobile.preparing.__aexit__ = AsyncMock()

    mock_ts = MagicMock()
    mock_ts.require_ram_cache = AsyncMock()
    mock_ts.stream_url.return_value = "http://torrserver/stream/2"
    mock_ts.torrent_video_files = AsyncMock(return_value=[{"id": 2, "name": "Ep2.mkv"}])

    test_app.dependency_overrides[get_playback_service] = lambda: mock_playback
    test_app.dependency_overrides[get_magnet_service] = lambda: mock_magnet
    test_app.dependency_overrides[get_history_repo] = lambda: mock_history
    test_app.dependency_overrides[get_playback_repo] = lambda: mock_repo
    test_app.dependency_overrides[get_mobile_service] = lambda: mock_mobile
    test_app.dependency_overrides[get_torrserver_client] = lambda: mock_ts
    test_app.dependency_overrides[get_torrserver_url] = lambda: "http://mock-ts:8090"

    client = TestClient(test_app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234))

    with patch(
        "backend.api.routers.remote.probe",
        new=AsyncMock(return_value={"mode": "direct", "duration": 100.0}),
    ):
        resp = client.post(
            "/api/remote/mobile",
            json={"hash": torrent_hash, "file_id": 2, "title": "Series"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["hash"] == torrent_hash
    assert data["file_id"] == 2
    assert data["file_name"] == "Ep2.mkv"
    assert "token" in data
    assert mock_ts.require_ram_cache.awaited
    mock_playback.select_torrent_file.assert_awaited_once()


def test_remote_router_dependency_overrides_mobile_progress(test_app):
    from backend.models.playback import PlaybackState

    mock_repo = MagicMock()
    mock_repo.save_progress = MagicMock()

    mock_session = MagicMock()
    mock_session.sequence = 0
    mock_session.progress_lock = MagicMock()
    mock_session.progress_lock.__aenter__ = AsyncMock()
    mock_session.progress_lock.__aexit__ = AsyncMock()
    mock_session.state = PlaybackState(hash="h", file_id=1, file_name="f")
    mock_session.close = AsyncMock()

    mock_mobile = MagicMock()
    mock_mobile.session.return_value = mock_session
    mock_mobile.sessions = {"tok123": mock_session}

    test_app.dependency_overrides[get_playback_repo] = lambda: mock_repo
    test_app.dependency_overrides[get_mobile_service] = lambda: mock_mobile

    client = TestClient(test_app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234))

    resp = client.post(
        "/api/remote/mobile/tok123/progress",
        json={"sequence": 1, "position": 120.0, "duration": 3600.0, "close": True},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_mobile.session.assert_called_once()
    mock_session.close.assert_awaited_once()
    assert mock_repo.save_progress.called
