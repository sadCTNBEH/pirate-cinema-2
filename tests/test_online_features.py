"""Tests for TASK-001: Online Videos, Playlists, History and Playback."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from starlette.testclient import TestClient

from backend.api.schemas.online import OnlineSearchResult
from backend.app import app
from backend.exceptions import (
    ExternalServiceError,
    NotFoundError,
    ProviderUnavailableError,
)
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.online import OnlineRepository
from backend.repositories.playback import PlaybackRepository
from backend.services.online.online_history import OnlineHistoryService
from backend.services.online.playlist_service import PlaylistService
from backend.services.online.providers.generic import GenericHLSProvider
from backend.services.online.providers.rutube import RutubeProvider
from backend.services.playback import PlaybackService

# ─── Rutube Provider Tests ───


@pytest.mark.anyio
async def test_rutube_search_success():
    fake_response = {
        "results": [
            {
                "id": "d07af4321b54d2e8a46b4fe015081314",
                "title": "Documentary Film",
                "thumbnail_url": "https://pic.rtbcdn.ru/video.jpg",
                "duration": 3600,
            }
        ]
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.is_closed = False

    provider = RutubeProvider(client=mock_client)
    results = await provider.search("Documentary")

    assert len(results) == 1
    assert results[0].id == "d07af4321b54d2e8a46b4fe015081314"
    assert results[0].title == "Documentary Film"
    assert results[0].provider == "rutube"
    assert results[0].duration == 3600


@pytest.mark.anyio
async def test_rutube_search_network_failure_raises_provider_unavailable():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = httpx.ConnectError("Connection refused")
    mock_client.is_closed = False

    provider = RutubeProvider(client=mock_client)
    with pytest.raises(ProviderUnavailableError):
        await provider.search("test")


@pytest.mark.anyio
async def test_rutube_search_http_error():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    request = httpx.Request("GET", "https://rutube.ru")
    response = httpx.Response(500, request=request)
    mock_client.get.side_effect = httpx.HTTPStatusError(
        "Server Error", request=request, response=response
    )
    mock_client.is_closed = False

    provider = RutubeProvider(client=mock_client)
    with pytest.raises(ExternalServiceError):
        await provider.search("test")


@pytest.mark.anyio
async def test_rutube_resolve_stream_qualities():
    options_json = {
        "title": "Sample Video",
        "thumbnail_url": "https://pic.rtbcdn.ru/thumb.jpg",
        "duration": 600,
        "video_balancer": {
            "m3u8": "https://bl.rutube.ru/master.m3u8",
        },
    }

    m3u8_text = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=640x360\n"
        "https://river.rutube.ru/360.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=3000,RESOLUTION=1280x720\n"
        "https://river.rutube.ru/720.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=6000,RESOLUTION=1920x1080\n"
        "https://river.rutube.ru/1080.m3u8\n"
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)

    def mock_get(url, *args, **kwargs):
        resp = MagicMock()
        if "play/options" in str(url):
            resp.status_code = 200
            resp.json.return_value = options_json
            resp.raise_for_status = MagicMock()
        elif "master.m3u8" in str(url):
            resp.status_code = 200
            resp.text = m3u8_text
            resp.raise_for_status = MagicMock()
        return resp

    mock_client.get.side_effect = mock_get
    mock_client.is_closed = False

    provider = RutubeProvider(client=mock_client)

    # Auto quality returns master m3u8
    info_auto = await provider.resolve_stream("d07af4321b54d2e8a46b4fe015081314")
    assert info_auto.url == "https://bl.rutube.ru/master.m3u8"
    assert info_auto.quality == "auto"
    assert "1080p" in info_auto.available_qualities
    assert "720p" in info_auto.available_qualities

    # Specific quality returns subplaylist
    info_720 = await provider.resolve_stream(
        "d07af4321b54d2e8a46b4fe015081314", quality="720p"
    )
    assert info_720.url == "https://river.rutube.ru/720.m3u8"
    assert info_720.quality == "720p"


@pytest.mark.anyio
async def test_rutube_not_found():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    resp = MagicMock()
    resp.status_code = 404
    mock_client.get.return_value = resp
    mock_client.is_closed = False

    provider = RutubeProvider(client=mock_client)
    with pytest.raises(NotFoundError):
        await provider.get_metadata("00000000000000000000000000000000")


# ─── Generic HLS & SSRF Tests ───


@pytest.mark.anyio
async def test_generic_hls_valid_stream():
    provider = GenericHLSProvider()
    valid_url = "https://example.com/live/stream.m3u8"

    results = await provider.search(valid_url)
    assert len(results) == 1
    assert results[0].id == valid_url
    assert results[0].provider == "direct"

    info = await provider.resolve_stream(valid_url)
    assert info.url == valid_url
    assert info.quality == "auto"


@pytest.mark.anyio
async def test_generic_hls_ssrf_prevention():
    provider = GenericHLSProvider()

    # Localhost / loopback / private IP disallowed
    disallowed_urls = [
        "http://localhost:8000/stream.m3u8",
        "http://127.0.0.1/video.mp4",
        "http://0.0.0.0/test",
        "http://10.0.0.1/hls",
        "http://192.168.1.5/live",
        "ftp://example.com/video.mp4",
        "file:///etc/passwd",
    ]

    for bad_url in disallowed_urls:
        res = await provider.search(bad_url)
        assert res == []

        with pytest.raises(ValueError):
            await provider.resolve_stream(bad_url)


# ─── Playlists & History Repository Tests ───


def test_playlist_lifecycle_and_order_preservation():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test_online.sqlite3")
        db.init_db()
        repo = OnlineRepository(db)
        service = PlaylistService(repo)

        # 1. Create playlist
        pl = service.create_playlist("Chill Vibes")
        assert pl.title == "Chill Vibes"
        assert pl.items == []

        # 2. Add items
        item1 = OnlineSearchResult(
            id="vid1", title="Nature 4K", provider="rutube", duration=120
        )
        item2 = OnlineSearchResult(
            id="vid2", title="Ocean Relax", provider="rutube", duration=300
        )
        item3 = OnlineSearchResult(
            id="vid3", title="Forest Sounds", provider="rutube", duration=600
        )

        service.add_item(pl.id, item1)
        service.add_item(pl.id, item2)
        service.add_item(pl.id, item3)

        updated_pl = service.get_playlist(pl.id)
        assert len(updated_pl.items) == 3
        assert [it.id for it in updated_pl.items] == ["vid1", "vid2", "vid3"]

        # 3. Remove middle item and verify sequence order is preserved
        service.remove_item(pl.id, "vid2")
        after_remove = service.get_playlist(pl.id)
        assert len(after_remove.items) == 2
        assert [it.id for it in after_remove.items] == ["vid1", "vid3"]

        # 4. Rename playlist
        renamed = service.update_playlist(pl.id, "Atmospheric Relax")
        assert renamed.title == "Atmospheric Relax"

        # 5. Delete playlist
        service.delete_playlist(pl.id)
        assert service.list_playlists() == []


def test_online_history_isolation_from_torrent_history():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test_isolation.sqlite3")
        db.init_db()

        torrent_repo = HistoryRepository(db)
        online_repo = OnlineRepository(db)
        online_history_service = OnlineHistoryService(online_repo)

        # 1. Add torrent history
        torrent_repo.mark_played("abc123hash", 0, "Movie.2024.mkv")
        torrent_repo.update_progress("abc123hash", 0, timecode=500, duration=7200)

        # 2. Add online history
        online_history_service.mark_played(
            provider="rutube",
            item_id="vid_rutube_99",
            title="Rutube Show Episode 1",
            thumbnail="https://example.com/thumb.jpg",
            duration=1800,
        )
        online_history_service.update_progress(
            provider="rutube",
            item_id="vid_rutube_99",
            timecode=900,
            duration=1800,
        )

        # 3. Verify strict isolation: torrent history contains only torrents
        torrent_entries = torrent_repo.list_history()
        assert len(torrent_entries) == 1
        assert torrent_entries[0]["torrent_hash"] == "abc123hash"
        assert torrent_entries[0]["file_name"] == "Movie.2024.mkv"

        # 4. Verify online history contains only online videos
        online_entries = online_history_service.list_history()
        assert len(online_entries) == 1
        assert online_entries[0].provider == "rutube"
        assert online_entries[0].item_id == "vid_rutube_99"
        assert online_entries[0].playback_timecode == 900
        assert online_entries[0].playback_duration == 1800
        assert online_entries[0].is_watched is False

        # 5. Watched threshold: remaining time < 180s marks as watched
        online_history_service.update_progress(
            provider="rutube",
            item_id="vid_rutube_99",
            timecode=1700,
            duration=1800,
        )
        updated_entry = online_history_service.list_history()[0]
        assert updated_entry.is_watched is True

        # 6. Delete online item
        online_history_service.delete_history_item("rutube", "vid_rutube_99")
        assert len(online_history_service.list_history()) == 0
        # Torrent history still intact
        assert len(torrent_repo.list_history()) == 1


# ─── Playback Service Online Integration Tests ───


@pytest.mark.anyio
async def test_playback_service_launch_and_stop_online():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test_playback.sqlite3")
        db.init_db()

        playback_repo = PlaybackRepository(db)
        history_repo = HistoryRepository(db)
        online_repo = OnlineRepository(db)

        mock_controller = MagicMock()
        mock_controller.is_running = True
        mock_controller.launch = MagicMock()
        mock_controller.stop = MagicMock()

        mock_torrserver = MagicMock()

        service = PlaybackService(
            playback_repo=playback_repo,
            history_repo=history_repo,
            metadata_repo=MagicMock(),
            mpv_controller_factory=lambda: mock_controller,
            torrserver_client=mock_torrserver,
            settings_provider=lambda: "http://127.0.0.1:8090",
            online_repo=online_repo,
        )

        status = await service.launch_online(
            provider="rutube",
            video_id="vid_online_1",
            stream_url="https://bl.rutube.ru/stream.m3u8",
            title="Sample Online Video",
            start_time=45,
            duration=1200,
        )

        assert status == "launched"
        assert mock_controller.launch.called

        # Verify active playback status
        active = service.get_active_playback()
        assert active["active"] is True
        assert active["is_online"] is True
        assert active["online_provider"] == "rutube"
        assert active["online_id"] == "vid_online_1"
        assert active["timecode"] == 45

        # Verify state retrieval
        state = await service.get_state("online:rutube:vid_online_1", 0)
        assert state.timecode == 45
        assert state.duration == 1200

        # Stop player and verify cleanup
        service.stop()
        assert mock_controller.stop.called
        assert service.get_active_playback()["active"] is False


# ─── API Router Endpoints Tests ───


def test_api_online_endpoints():
    client = TestClient(app)

    # 1. Search endpoint
    resp = client.post("/api/online/search", json={"query": "test"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # 2. Playlists CRUD via API
    # Create
    pl_resp = client.post("/api/online/playlists", json={"title": "Favorites Online"})
    assert pl_resp.status_code == 200
    pl_data = pl_resp.json()
    pl_id = pl_data["id"]
    assert pl_data["title"] == "Favorites Online"

    # List
    list_resp = client.get("/api/online/playlists")
    assert list_resp.status_code == 200
    assert any(p["id"] == pl_id for p in list_resp.json())

    # Add item
    item_resp = client.post(
        f"/api/online/playlists/{pl_id}/items",
        json={
            "id": "vid_abc_1",
            "title": "Online Video 1",
            "provider": "rutube",
            "duration": 500,
        },
    )
    assert item_resp.status_code == 200
    assert len(item_resp.json()["items"]) == 1

    # Remove item
    rem_resp = client.delete(f"/api/online/playlists/{pl_id}/items/vid_abc_1")
    assert rem_resp.status_code == 200
    assert len(rem_resp.json()["items"]) == 0

    # Delete playlist
    del_resp = client.delete(f"/api/online/playlists/{pl_id}")
    assert del_resp.status_code == 200

    # History API
    hist_resp = client.get("/api/online/history")
    assert hist_resp.status_code == 200
    assert isinstance(hist_resp.json(), list)
