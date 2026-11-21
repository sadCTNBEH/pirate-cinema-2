"""Tests for PlaybackService decomposition and MPV Controller interface (G-006)."""
import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import get_playback_service
from backend.api.routers.player import player_router
from backend.infrastructure.mpv.controller import IMPVController, MPVController
from backend.models.playback import PlayCommand
from backend.services.playback import PlaybackService, PlayerState


class FakeMPVController:
    """In-memory Fake MPV Controller implementing IMPVController without any real MPV process or IPC pipe."""

    def __init__(self) -> None:
        self.is_running = False
        self.started_files: list[dict[str, Any]] = []
        self.properties: dict[str, Any] = {
            "fullscreen": False,
            "cursor-autohide": "yes",
            "pause": False,
            "volume": 100,
            "time-pos": 0,
            "duration": 600,
        }
        self.commands: list[list[Any]] = []
        self.stopped = False
        self.on_progress = None
        self.on_end = None
        self.control_lock = asyncio.Lock()
        self.is_embedded = False
        self._owned_pid = 99999
        self.media_url: str | None = None
        self.media_switched = False

    def start_file(
        self,
        url: str,
        title: str = "",
        start_time: int = 0,
        audio_track: int = 0,
        subtitle_track: int = 0,
        wid: int | None = None,
        mpv_path: Any = None,
        load_only: bool = False,
        **kwargs: Any,
    ) -> None:
        self.is_running = True
        self.media_url = url
        self.started_files.append({
            "url": url,
            "title": title,
            "start_time": start_time,
            "audio_track": audio_track,
            "subtitle_track": subtitle_track,
            "wid": wid,
            "load_only": load_only,
            **kwargs,
        })

    def set_property(self, name: str, value: Any) -> None:
        self.properties[name] = value
        self.commands.append(["set_property", name, value])

    def get_property(self, name: str, request_id: int | None = None) -> Any:
        return self.properties.get(name)

    def stop(self) -> None:
        self.is_running = False
        self.stopped = True

    def seek(self, position: float | int, reference: str = "absolute+exact") -> None:
        self.commands.append(["seek", position, reference])
        self.properties["time-pos"] = position

    def set_next_available(self, has_next: bool) -> None:
        self.commands.append(["script-message", "cinema-next", "yes" if has_next else "no"])

    def set_osd_fullscreen(self, is_fs: bool) -> None:
        self.commands.append(["script-message", "cinema-fullscreen", "yes" if is_fs else "no"])

    def send_subtitles_menu(self, payload: dict[str, Any]) -> None:
        self.commands.append(["script-message", "cinema-subtitles", payload])

    def open_menu(self) -> None:
        self.commands.append(["script-message", "cinema-open-menu"])

    def send_menu_input(self, action: str) -> None:
        self.commands.append(["script-message", "cinema-continuation-input", action])

    def step_frame(self, backward: bool = False) -> None:
        self.commands.append(["frame-back-step" if backward else "frame-step"])

    def prepare_media_switch(self) -> None:
        self.media_switched = True

    def set_segments(self, segments: Any = None, auto_skip: bool = False) -> None:
        pass

    def send_command(self, cmd: list[Any], request_id: int | None = None) -> None:
        self.commands.append(cmd)
        if len(cmd) >= 3 and cmd[0] == "set_property":
            self.properties[cmd[1]] = cmd[2]


def create_playback_service_with_fake(fake_controller: FakeMPVController):
    playback_repo = MagicMock()
    history_repo = MagicMock()
    metadata_repo = MagicMock()
    metadata_repo.get_imdb_id.return_value = "tt1234567"
    torrserver = MagicMock()
    torrserver.require_ram_cache = AsyncMock()
    torrserver.stream_url.return_value = "http://127.0.0.1:8090/stream/video.mkv"
    torrserver.torrent_video_files = AsyncMock(return_value=[
        {"id": 0, "name": "Episode 1.mkv"},
        {"id": 1, "name": "Episode 2.mkv"},
    ])

    service = PlaybackService(
        playback_repo=playback_repo,
        history_repo=history_repo,
        metadata_repo=metadata_repo,
        mpv_controller_factory=lambda: fake_controller,
        torrserver_client=torrserver,
        settings_provider=lambda: "http://127.0.0.1:8090",
    )
    return service, torrserver


def test_fake_controller_implements_protocol():
    """Verify that FakeMPVController and MPVController both satisfy IMPVController protocol."""
    fake = FakeMPVController()
    assert isinstance(fake, IMPVController)
    real = MPVController()
    assert isinstance(real, IMPVController)


@pytest.mark.asyncio
async def test_playback_service_launch_and_start_file():
    """Verify PlaybackService calls controller.start_file with correct parameters."""
    fake = FakeMPVController()
    service, _ = create_playback_service_with_fake(fake)

    cmd = PlayCommand(hash="abc123hash", file_id=0, file_name="Episode 1.mkv", start_time=42)
    status = await service.launch(cmd)

    assert status == "launched"
    assert fake.is_running is True
    assert len(fake.started_files) == 1
    call_info = fake.started_files[0]
    assert call_info["url"] == "http://127.0.0.1:8090/stream/video.mkv"
    assert call_info["title"] == "Episode 1.mkv"
    assert call_info["start_time"] == 42
    assert call_info["load_only"] is False


@pytest.mark.asyncio
async def test_playback_service_load_only_on_running_controller():
    """Verify PlaybackService uses start_file(load_only=True) and prepare_media_switch when re-using controller."""
    fake = FakeMPVController()
    service, _ = create_playback_service_with_fake(fake)

    cmd1 = PlayCommand(hash="abc123hash", file_id=0, file_name="Episode 1.mkv", start_time=0)
    await service.launch(cmd1)
    assert len(fake.started_files) == 1

    cmd2 = PlayCommand(hash="abc123hash", file_id=1, file_name="Episode 2.mkv", start_time=10)
    await service.launch(cmd2)

    assert fake.media_switched is True
    assert len(fake.started_files) == 2
    assert fake.started_files[1]["load_only"] is True
    assert fake.started_files[1]["title"] == "Episode 2.mkv"
    assert fake.started_files[1]["start_time"] == 10


@pytest.mark.asyncio
async def test_playback_service_set_and_get_property():
    """Verify that set_property and get_property route cleanly to controller interface."""
    fake = FakeMPVController()
    service, _ = create_playback_service_with_fake(fake)

    cmd = PlayCommand(hash="abc123hash", file_id=0, file_name="Episode 1.mkv")
    await service.launch(cmd)

    service.send_command(["set_property", "volume", 85])
    assert fake.get_property("volume") == 85
    assert ["set_property", "volume", 85] in fake.commands

    service.send_command(["set_property", "pause", True])
    assert fake.get_property("pause") is True

    # Test seek
    service.send_command(["seek", 120, "absolute+exact"])
    assert fake.get_property("time-pos") == 120


@pytest.mark.asyncio
async def test_playback_service_stop_cleanly():
    """Verify that stop_playback invokes controller.stop without touching real processes."""
    fake = FakeMPVController()
    service, _ = create_playback_service_with_fake(fake)

    cmd = PlayCommand(hash="abc123hash", file_id=0, file_name="Episode 1.mkv")
    await service.launch(cmd)
    assert fake.is_running is True

    result = await service.stop_playback()
    assert result == {"status": "stopped"}
    assert fake.stopped is True
    assert fake.is_running is False
    assert service.state == PlayerState.IDLE


@pytest.mark.asyncio
async def test_playback_service_fullscreen_orchestration():
    """Verify fullscreen toggle properly communicates with controller properties."""
    fake = FakeMPVController()
    service, _ = create_playback_service_with_fake(fake)

    cmd = PlayCommand(hash="abc123hash", file_id=0, file_name="Episode 1.mkv")
    await service.launch(cmd)

    fake.is_embedded = True
    service.set_fullscreen(True)
    assert ["script-message", "cinema-fullscreen", "yes"] in fake.commands
    assert fake.get_property("cursor-autohide") == "no"

    fake.is_embedded = False
    service.set_fullscreen(False)
    assert fake.get_property("fullscreen") is False


def test_fastapi_player_router_thin_integration():
    """Verify FastAPI player router delegates cleanly to PlaybackService with fake controller."""
    fake = FakeMPVController()
    service, _ = create_playback_service_with_fake(fake)

    app = FastAPI()
    app.include_router(player_router)
    app.dependency_overrides[get_playback_service] = lambda: service

    client = TestClient(app)

    # 1. POST /api/player/play
    resp = client.post("/api/player/play", json={"hash": "testhash", "file_id": 0, "file_name": "Test.mkv"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "launched"}
    assert fake.is_running is True

    # 2. GET /api/player/active
    resp = client.get("/api/player/active")
    assert resp.status_code == 200
    assert resp.json()["active"] is True
    assert resp.json()["file_name"] == "Test.mkv"

    # 3. POST /api/player/command
    resp = client.post("/api/player/command", json=["set_property", "volume", 70])
    assert resp.status_code == 200
    assert resp.json() == {"success": True}
    assert fake.get_property("volume") == 70

    # 4. POST /api/player/fullscreen
    resp = client.post("/api/player/fullscreen", json={"fullscreen": True})
    assert resp.status_code == 200
    assert "is_fullscreen" in resp.json()

    # 5. POST /api/player/stop
    resp = client.post("/api/player/stop")
    assert resp.status_code == 200
    assert resp.json() == {"status": "stopped"}
    assert fake.is_running is False


@pytest.mark.asyncio
async def test_auto_advance_next_episode_on_eof():
    """Verify Continuation.auto_advance sequence on EOF: mark watched -> stop current -> play next."""
    fake = FakeMPVController()
    service, torrserver = create_playback_service_with_fake(fake)
    service.loop = asyncio.get_running_loop()
    service._schedule_save = MagicMock()

    # Launch Episode 1
    cmd = PlayCommand(hash="serieshash123", file_id=0, file_name="Show.S01E01.mkv", start_time=0)
    await service.launch(cmd)

    # Refresh next candidate so next episode is discovered
    await service._refresh_next_available("serieshash123")
    state = service.active_states["serieshash123"]
    state.duration = 1800
    state.timecode = 1800

    assert state.has_next is True
    assert "serieshash123" in service._next_candidates

    # Trigger auto advance directly or via continuation
    advanced = await service.continuation.auto_advance(state)

    assert advanced is True
    assert state.is_watched is True
    # Verify that Episode 2 (file_id 1) was launched
    assert len(fake.started_files) == 2
    next_call = fake.started_files[1]
    assert next_call["title"] == "Episode 2.mkv"
    assert fake.is_running is True


@pytest.mark.asyncio
async def test_continuation_resolve_next_file_delegation():
    """Verify that PlaybackService._next_torrent_file delegates cleanly to Continuation service."""
    fake = FakeMPVController()
    service, _ = create_playback_service_with_fake(fake)

    files = [
        {"id": 10, "name": "Vikings.S02E04.mkv"},
        {"id": 11, "name": "Vikings.S02E05.mkv"},
        {"id": 12, "name": "Vikings.S02E06.mkv"},
    ]

    # Resolve next file from episode 4 (id 10) -> should be episode 5 (id 11)
    next_f = await service._next_torrent_file(files, "vikinghash", 10)
    assert next_f is not None
    assert next_f["id"] == 11
    assert next_f["name"] == "Vikings.S02E05.mkv"

    # Also verify direct call to service.continuation.resolve_next_torrent_file
    next_f2 = await service.continuation.resolve_next_torrent_file(files, "vikinghash", 11)
    assert next_f2 is not None
    assert next_f2["id"] == 12
    assert next_f2["name"] == "Vikings.S02E06.mkv"


def test_tv_live_stream_config_and_parameters():
    """Verify IPTV / Live stream detection, low-latency options, and continuation suppression."""
    from backend.services.tv import LiveStreamConfig

    # 1. Detection
    assert LiveStreamConfig.is_live_stream(url="http://iptv.example.com/stream.m3u8", duration=0) is True
    assert LiveStreamConfig.is_live_stream(url="rtmp://live.twitch.tv/app/stream", duration=0) is True
    assert LiveStreamConfig.is_live_stream(url="http://tv.example.com/live/ch1.ts", duration=0) is True
    assert LiveStreamConfig.is_live_stream(url="http://example.com/video.mp4", duration=0, provider="iptv") is True
    assert LiveStreamConfig.is_live_stream(url="http://local/movie.mkv", duration=7200, provider="") is False

    # 2. Options and parameters
    opts = LiveStreamConfig.get_live_mpv_options()
    assert "--cache-pause=no" in opts
    assert "--demuxer-lavf-o=fflags=+nobuffer" in opts

    launch_kwargs = {"url": "http://tv.live/ch1.m3u8", "start_time": 100, "extra_options": []}
    configured = LiveStreamConfig.configure_live_parameters(launch_kwargs, duration=0, provider="iptv")
    assert configured["start_time"] == 0
    assert configured["is_live"] is True
    assert "--cache-pause=no" in configured["extra_options"]

    # 3. Continuation suppression
    assert LiveStreamConfig.should_suppress_continuation(url="http://tv.live/ch1.m3u8", duration=0) is True
    assert LiveStreamConfig.should_suppress_continuation(url="http://local/series.mkv", duration=2400) is False

    # 4. Cast stream type
    assert LiveStreamConfig.get_cast_stream_type(url="http://tv.live/ch1.m3u8", duration=0) == "LIVE"
    assert LiveStreamConfig.get_cast_stream_type(url="http://local/movie.mp4", duration=3600) == "BUFFERED"


@pytest.mark.asyncio
async def test_live_stream_eof_suppresses_auto_advance():
    """Verify that live / IPTV playback suppresses next episode auto-advance on EOF."""
    fake = FakeMPVController()
    service, _ = create_playback_service_with_fake(fake)
    service.loop = asyncio.get_running_loop()
    service._schedule_save = MagicMock()

    cmd = PlayCommand(hash="livehash123", file_id=0, file_name="Live News.m3u8", start_time=0)
    await service.launch(cmd)

    state = service.active_states["livehash123"]
    state.duration = 0
    state.timecode = 0
    state.online_provider = "iptv"

    # Simulate EOF on a live stream
    service._handle_end("livehash123", reason="eof")
    await asyncio.sleep(0.01)

    # Should not create continuation offer or advance
    assert service.continuation.offer is None
    assert len(fake.started_files) == 1  # Only initial launch, no auto advance


@pytest.mark.asyncio
async def test_auto_advance_online_playlist_on_eof():
    """Verify auto-advance to the next episode in an online playlist when EOF is reached."""
    fake = FakeMPVController()
    service, _ = create_playback_service_with_fake(fake)
    service.loop = asyncio.get_running_loop()
    service._schedule_save = MagicMock()

    # Mock online repository and playlist
    mock_item_0 = MagicMock(provider="anime", id="ep1")
    mock_item_1 = MagicMock(provider="anime", id="ep2")
    mock_playlist = MagicMock(items=[mock_item_0, mock_item_1])
    service._online_repo = MagicMock()
    service._online_repo.get_playlist.return_value = mock_playlist

    # Mock online service stream resolution
    service._online_service = MagicMock()
    stream_info = MagicMock(
        url="http://cdn.stream/ep2.m4v",
        title="Anime Episode 2",
        thumbnail="http://cdn.stream/thumb2.jpg",
        duration=1420,
    )
    service._online_service.resolve_stream = AsyncMock(return_value=stream_info)

    # Set up active online state at episode index 0
    from backend.models.playback import PlaybackState
    state = PlaybackState(
        hash="online:anime:ep1",
        file_id=0,
        file_name="Anime Episode 1",
        duration=1400,
        timecode=1400,
        is_online=True,
        online_provider="anime",
        online_id="ep1",
        playlist_id="playlist_xyz",
        episode_index=0,
        has_next=True,
    )
    service.active_states["online:anime:ep1"] = state
    service.controllers["online:anime:ep1"] = fake
    fake.is_running = True

    # Call continuation.auto_advance
    success = await service.continuation.auto_advance(state)

    assert success is True
    assert state.is_watched is True
    # Verify episode 2 was launched via online player
    assert len(fake.started_files) == 1
    started = fake.started_files[0]
    assert started["url"] == "http://cdn.stream/ep2.m4v"
    assert started["title"] == "Anime Episode 2"

