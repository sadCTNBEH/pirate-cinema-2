"""Tests for player state machine, epoch management, and fast-switch race cancellation (G-003)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.infrastructure.mpv.controller import MPVController
from backend.models.playback import PlaybackState, PlayCommand
from backend.repositories.playback import PlaybackRepository
from backend.services.playback import PlayerState, PlaybackService


class ControlledMockController:
    """Mock controller that can simulate slow startup to test cancellation and serialization."""

    def __init__(self, start_delay: float = 0.05) -> None:
        self.start_delay = start_delay
        self.is_running = False
        self._stop_requested = False
        self.control_lock = asyncio.Lock()
        self.launch_called_with = None
        self.stop_called = False
        self.on_progress = None
        self.on_end = None

    def cancel_start(self) -> None:
        self._stop_requested = True

    def launch(self, **kwargs) -> None:
        self.launch_called_with = kwargs
        import time
        deadline = time.time() + self.start_delay
        while time.time() < deadline:
            if self._stop_requested:
                raise RuntimeError("MPV launch cancelled")
            time.sleep(0.005)
        if self._stop_requested:
            raise RuntimeError("MPV launch cancelled")
        self.is_running = True

    def stop(self) -> None:
        self.stop_called = True
        self.is_running = False
        self._stop_requested = True

    def send_command(self, cmd) -> None:
        pass


def make_service(controller_factory=None):
    mock_db = MagicMock()
    repo = PlaybackRepository(mock_db)
    repo.get_previous_progress = MagicMock(return_value=None)
    repo.logical_progress = MagicMock(return_value=None)
    repo.file_choice = MagicMock(return_value=None)
    repo.file_intent = MagicMock(return_value=None)

    history = MagicMock()
    metadata = MagicMock()
    metadata.save_media_type = MagicMock()
    metadata.save_metadata_title = MagicMock()
    metadata.get_imdb_id = MagicMock(return_value=None)

    torrserver = MagicMock()
    torrserver.require_ram_cache = AsyncMock()
    torrserver.stream_url = MagicMock(side_effect=lambda url, h, fid, fname: f"http://ts/{h}/{fid}")
    torrserver.torrent_video_files = AsyncMock(return_value=[])

    controllers_created = []

    def default_factory():
        c = ControlledMockController(start_delay=0.03)
        controllers_created.append(c)
        return c

    factory = controller_factory or default_factory

    service = PlaybackService(
        playback_repo=repo,
        history_repo=history,
        metadata_repo=metadata,
        mpv_controller_factory=factory,
        torrserver_client=torrserver,
        settings_provider=lambda: "http://localhost:8090",
    )
    return service, controllers_created


@pytest.mark.asyncio
async def test_player_state_transitions_idle_starting_playing_paused_stopping():
    """Verify player state machine transitions: idle -> starting -> playing -> paused -> stopping -> idle."""
    controller = ControlledMockController(start_delay=0.01)
    service, _ = make_service(lambda: controller)

    # 1. Initial state must be IDLE
    assert service.state == PlayerState.IDLE
    assert service.state == "idle"
    assert service.player_state == "idle"
    assert service.epoch_id == 0

    cmd = PlayCommand(hash="hash1", file_id=1, file_name="Movie1.mkv")
    launch_task = asyncio.create_task(service.play(cmd))

    # Give it a moment to enter starting
    await asyncio.sleep(0.005)
    assert service.state == PlayerState.STARTING
    assert service.player_state == "starting"
    assert service.epoch_id == 1

    # Wait for completion
    res = await launch_task
    assert res == "launched"
    assert service.state == PlayerState.PLAYING
    assert service.player_state == "playing"

    # Pause
    service._handle_progress("hash1", "pause", True)
    assert service.state == PlayerState.PAUSED
    assert service.player_state == "paused"

    # Unpause
    service._handle_progress("hash1", "pause", False)
    assert service.state == PlayerState.PLAYING

    # Stop
    service.stop()
    assert service.state == PlayerState.IDLE
    assert service.player_state == "idle"


@pytest.mark.asyncio
async def test_fast_switch_play_a_then_b_only_b_works():
    """Scenario: play(A) -> immediately play(B) -> only B is working."""
    controllers = []

    def factory():
        c = ControlledMockController(start_delay=0.08)
        controllers.append(c)
        return c

    service, _ = make_service(factory)

    cmd_a = PlayCommand(hash="hashA", file_id=1, file_name="VideoA.mkv")
    cmd_b = PlayCommand(hash="hashB", file_id=2, file_name="VideoB.mkv")

    # Launch A
    task_a = asyncio.create_task(service.play(cmd_a))
    # Give A enough time to pass preparation and create controller A (starting launch)
    for _ in range(50):
        await asyncio.sleep(0.005)
        if len(controllers) == 1:
            break

    assert len(controllers) == 1
    assert service.epoch_id == 1
    assert service.state == PlayerState.STARTING

    # Immediately launch B while controller A is still in launch()
    task_b = asyncio.create_task(service.play(cmd_b))

    results = await asyncio.gather(task_a, task_b, return_exceptions=True)

    # Task A was cancelled or raised cancellation 409
    assert isinstance(results[0], BaseException)
    # Task B succeeded
    assert results[1] == "launched"

    # Verify state and active playback
    assert service.epoch_id == 2
    assert service.state == PlayerState.PLAYING

    active = service.get_active_playback()
    assert active["active"] is True
    assert active["hash"] == "hashB"
    assert active["file_id"] == 2
    assert active["epoch_id"] == 2

    # Controller for A must be stopped, Controller for B must be running
    assert len(controllers) == 2
    controller_a, controller_b = controllers[0], controllers[1]
    assert controller_a.is_running is False
    assert controller_b.is_running is True

    # Only B is in active_states and controllers
    assert "hashA" not in service.active_states
    assert "hashA" not in service.controllers
    assert "hashB" in service.active_states
    assert "hashB" in service.controllers
    assert service.controllers["hashB"] is controller_b


@pytest.mark.asyncio
async def test_fast_switch_same_torrent_episodes():
    """Fast switching between episodes in the same torrent cancels older launch."""
    controllers = []

    def factory():
        c = ControlledMockController(start_delay=0.05)
        controllers.append(c)
        return c

    service, _ = make_service(factory)

    ep1 = PlayCommand(hash="series1", file_id=1, file_name="Series.S01E01.mkv")
    ep2 = PlayCommand(hash="series1", file_id=2, file_name="Series.S01E02.mkv")

    task1 = asyncio.create_task(service.play(ep1))
    await asyncio.sleep(0.01)
    task2 = asyncio.create_task(service.play(ep2))

    results = await asyncio.gather(task1, task2, return_exceptions=True)
    assert isinstance(results[0], BaseException)
    assert results[1] == "launched"

    active = service.get_active_playback()
    assert active["active"] is True
    assert active["file_id"] == 2
    assert active["epoch_id"] == 2
    assert service.state == PlayerState.PLAYING


@pytest.mark.asyncio
async def test_error_state_on_launch_failure_no_hang_in_starting():
    """Ensure error state is set on launch failure and state does NOT hang in starting."""
    controller = ControlledMockController(start_delay=0.01)

    def failing_launch(**kwargs):
        raise OSError("MPV binary crashed or not found")

    controller.launch = failing_launch
    service, _ = make_service(lambda: controller)

    cmd = PlayCommand(hash="fail_hash", file_id=1, file_name="Fail.mkv")

    with pytest.raises(Exception):
        await service.play(cmd)

    # State must transition to ERROR, not hang in STARTING
    assert service.state == PlayerState.ERROR
    assert service.player_state == "error"
    assert service.last_error is not None
    assert service.get_active_playback()["active"] is False


@pytest.mark.asyncio
async def test_mpv_controller_lock_serialization():
    """Verify MPVController start and stop serialize through asyncio.Lock without overlap."""
    controller = MPVController()
    execution_order = []

    def mock_launch(*args, **kwargs):
        import time
        execution_order.append("start_begin")
        time.sleep(0.04)
        execution_order.append("start_end")

    def mock_stop_sync():
        execution_order.append("stop_sync")

    controller.launch = mock_launch
    controller._stop_internal = mock_stop_sync

    # Launch start and stop concurrently
    t1 = asyncio.create_task(controller.start("mpv", "http://test", "title"))
    await asyncio.sleep(0.01)
    t2 = asyncio.create_task(controller.stop_async())

    await asyncio.gather(t1, t2)

    # stop_async must wait for start to release control_lock
    assert execution_order == ["start_begin", "start_end", "stop_sync"]


def test_playback_repository_progress_owner_epoch():
    """Verify PlaybackRepository prevents older epoch from overwriting newer progress."""
    import sqlite3
    db = MagicMock()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE media_file_history (
            torrent_hash TEXT, file_index INTEGER, playback_timecode INTEGER,
            playback_duration INTEGER, audio_track INTEGER, subtitle_track INTEGER,
            is_watched INTEGER, last_played_at TEXT, PRIMARY KEY(torrent_hash, file_index)
        )"""
    )
    conn.execute("INSERT INTO media_file_history VALUES ('h1', 1, 10, 100, 0, 0, 0, '')")
    conn.commit()

    db.get_connection.return_value.__enter__.return_value = conn
    db.get_connection.return_value.__exit__.return_value = None

    repo = PlaybackRepository(db)

    # Epoch 2 saves progress at 50s
    state_ep2 = PlaybackState(hash="h1", file_id=1, timecode=50, duration=100)
    repo.save_progress(state_ep2, epoch_id=2)

    row = conn.execute("SELECT playback_timecode FROM media_file_history WHERE torrent_hash='h1'").fetchone()
    assert row["playback_timecode"] == 50

    # Stale Epoch 1 tries to save progress at 20s -> must be ignored!
    state_ep1 = PlaybackState(hash="h1", file_id=1, timecode=20, duration=100)
    repo.save_progress(state_ep1, epoch_id=1)

    row = conn.execute("SELECT playback_timecode FROM media_file_history WHERE torrent_hash='h1'").fetchone()
    assert row["playback_timecode"] == 50  # Retained epoch 2 progress!
