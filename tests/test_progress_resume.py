import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.playback import PlaybackState
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.playback import PlaybackRepository
from backend.services.continuation import Continuation
from backend.services.progress import PlaybackProgressTracker


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_history.sqlite3"
        db = Database(db_path)
        db.init_db()
        yield db


# ============================================================================
# Scenario 1: Игнорирование прогресса первее 5 секунд (< 5s ignored)
# ============================================================================

def test_ignore_progress_earlier_than_5_seconds(temp_db):
    """Progress earlier than 5 seconds (early playback noise) must not be saved."""
    history_repo = HistoryRepository(temp_db)
    tracker = PlaybackProgressTracker(history_repo=history_repo)

    torrent_hash = "hash_ignore_early"
    file_idx = 0
    history_repo.mark_played(torrent_hash, file_idx, "Episode_01.mkv")

    # 1. Try to record at 2, 3, 4 seconds
    assert tracker.should_save(torrent_hash, file_idx, timecode=2.0, duration=1800.0) is False
    assert tracker.should_save(torrent_hash, file_idx, timecode=3.5, duration=1800.0) is False
    assert tracker.should_save(torrent_hash, file_idx, timecode=4.9, duration=1800.0) is False

    # update_position returns False and does not write to DB
    res = tracker.update_position(torrent_hash, file_idx, timecode=3.0, duration=1800.0)
    assert res is False

    entry = history_repo.get_file_entry(torrent_hash, file_idx)
    assert entry is not None
    # timecode in DB remains 0 or None
    assert entry.get("playback_timecode") in (0, None)

    # Calling update_progress directly on HistoryRepository with < 5s also ignores it
    direct_res = history_repo.update_progress(torrent_hash, file_idx, timecode=4, duration=1800)
    assert direct_res is False
    entry = history_repo.get_file_entry(torrent_hash, file_idx)
    assert entry.get("playback_timecode") in (0, None)

    # 2. Once timecode reaches >= 5s, progress is saved
    res_saved = tracker.update_position(torrent_hash, file_idx, timecode=6.0, duration=1800.0, force=True)
    assert res_saved is True
    entry = history_repo.get_file_entry(torrent_hash, file_idx)
    assert entry.get("playback_timecode") == 6


# ============================================================================
# Scenario 2: Падение плеера на 15-й минуте (Player crash at minute 15)
# ============================================================================

def test_player_crash_at_minute_15_preserves_position(temp_db):
    """Simulate playback running to minute 15 (900s), saving via debounce,

    followed by a player crash. The position 900s must be retained in DB.
    """
    history_repo = HistoryRepository(temp_db)
    playback_repo = PlaybackRepository(temp_db)
    tracker = PlaybackProgressTracker(history_repo=history_repo, debounce_interval=5.0)

    torrent_hash = "hash_crash_15min"
    file_idx = 1
    history_repo.mark_played(torrent_hash, file_idx, "Movie.mkv")

    # Playback progresses: 10s, 300s, 600s, 900s (15th minute)
    # At minute 15:
    timecode_15min = 900.0
    duration = 3600.0  # 1 hour total duration

    saved = tracker.update_position(
        torrent_hash, file_idx, timecode=timecode_15min, duration=duration, force=True
    )
    assert saved is True

    # Check that position 900 is in the database
    entry_before_crash = history_repo.get_file_entry(torrent_hash, file_idx)
    assert entry_before_crash["playback_timecode"] == 900
    assert entry_before_crash["is_watched"] == 0

    # Simulate player crash (process killed, state destroyed without clean shutdown)
    del tracker

    # Fresh repository instance reading after crash
    resumed_entry = history_repo.get_file_entry(torrent_hash, file_idx)
    assert resumed_entry is not None
    assert resumed_entry["playback_timecode"] == 900
    assert resumed_entry["playback_duration"] == 3600
    assert resumed_entry["is_watched"] == 0

    # Verify PlaybackRepository also sees the 900s position for resume
    prev_prog = playback_repo.get_previous_progress(torrent_hash, file_idx)
    assert prev_prog is not None
    assert prev_prog["playback_timecode"] == 900


# ============================================================================
# Scenario 3: Успешный переход на следующий эпизод (EOF -> stop -> resume next)
# ============================================================================

@pytest.mark.asyncio
async def test_successful_continuation_transition_to_next_episode():
    """Verify sequence: EOF -> verify previous completed -> stop current -> resume next."""
    mock_service = MagicMock()
    mock_service.active_states = {}
    mock_service.controllers = {}
    mock_service._next_candidates = {}
    mock_service._file_intents = {}
    mock_service._auto_next_enabled = True
    mock_service._history = MagicMock()

    current_state = PlaybackState(
        hash="series_hash",
        file_id=1,
        file_name="Show.S01E01.mkv",
        timecode=1800,
        duration=1800,
        is_ready=True,
    )
    mock_service.active_states["series_hash"] = current_state

    # Controller for current track
    mock_controller = MagicMock()
    mock_controller.is_running = True
    mock_controller.last_error = None
    mock_controller.stop = MagicMock(return_value=None)
    mock_service.controllers["series_hash"] = mock_controller

    # Continuation service
    continuation = Continuation(mock_service)
    continuation.attach(current_state)

    # Next candidate is configured
    mock_service._next_candidates["series_hash"] = (
        None,
        {"file": {"id": 2, "name": "Show.S01E02.mkv"}},
    )
    mock_service.play_next_file = AsyncMock(return_value=True)

    # 1. EOF reached on track 1
    await continuation.eof(current_state, immediate=True)

    # 2. Verify previous track completed successfully
    assert continuation.verify_track_completed(current_state) is True

    # 3. Previous track finalized & marked watched
    assert current_state.is_watched is True
    mock_service._history.mark_watched.assert_called_with("series_hash", 1, True)

    # 4. Current controller stopped
    mock_controller.stop.assert_called()

    # 5. Next episode resumed
    mock_service.play_next_file.assert_awaited_with("series_hash", 1)


@pytest.mark.asyncio
async def test_continuation_refuses_transition_if_previous_track_not_completed():
    """Auto-transition must be rejected if the previous track stopped prematurely or crashed."""
    mock_service = MagicMock()
    mock_service.active_states = {}
    mock_service.controllers = {}
    mock_service._next_candidates = {}
    mock_service._file_intents = {}
    mock_service._auto_next_enabled = True
    mock_service._history = MagicMock()

    # Track stopped at minute 15 out of 45 (not completed, EOF not seen)
    incomplete_state = PlaybackState(
        hash="series_hash_2",
        file_id=1,
        file_name="Show.S01E01.mkv",
        timecode=900,
        duration=2700,
        is_ready=True,
    )
    incomplete_state.is_watched = False
    mock_service.active_states["series_hash_2"] = incomplete_state

    mock_controller = MagicMock()
    mock_controller.is_running = True
    mock_controller.last_error = None
    mock_service.controllers["series_hash_2"] = mock_controller

    continuation = Continuation(mock_service)
    continuation.attach(incomplete_state)

    mock_service._next_candidates["series_hash_2"] = (
        None,
        {"file": {"id": 2, "name": "Show.S01E02.mkv"}},
    )
    mock_service.play_next_file = AsyncMock()

    # Verify track completion check returns False
    assert continuation.verify_track_completed(incomplete_state) is False

    # Attempt auto_advance
    result = await continuation.auto_advance(incomplete_state)
    assert result is False

    # Controller not stopped, play_next_file not called, not marked watched
    mock_controller.stop.assert_not_called()
    mock_service.play_next_file.assert_not_awaited()
    mock_service._history.mark_watched.assert_not_called()


# ============================================================================
# Scenario 4: Периодический дебаунс (5с) и принудительное сохранение (пауза, перемотка, EOF)
# ============================================================================

def test_debounced_saving_and_mandatory_events(temp_db):
    """Test 5-second debouncing during playback ticks and immediate saving on pause, seek, EOF."""
    history_repo = HistoryRepository(temp_db)
    tracker = PlaybackProgressTracker(history_repo=history_repo, debounce_interval=5.0)

    torrent_hash = "hash_debounce"
    file_idx = 0
    history_repo.mark_played(torrent_hash, file_idx, "Episode.mkv")

    # 1. First tick at t=10s: saved
    assert tracker.on_tick(torrent_hash, file_idx, timecode=10.0, duration=1800.0) is True
    entry = history_repo.get_file_entry(torrent_hash, file_idx)
    assert entry["playback_timecode"] == 10

    # 2. Subsequent tick at t=12s (only 2 seconds later): debounced (skipped)
    assert tracker.on_tick(torrent_hash, file_idx, timecode=12.0, duration=1800.0) is False
    entry = history_repo.get_file_entry(torrent_hash, file_idx)
    assert entry["playback_timecode"] == 10  # still 10, not updated

    # 3. Mandatory event: PAUSE at t=13s (still within 5s window): MUST save immediately
    assert tracker.on_pause(torrent_hash, file_idx, timecode=13.0, duration=1800.0) is True
    entry = history_repo.get_file_entry(torrent_hash, file_idx)
    assert entry["playback_timecode"] == 13

    # 4. Mandatory event: SEEK to t=600s: MUST save immediately
    assert tracker.on_seek(torrent_hash, file_idx, timecode=600.0, duration=1800.0) is True
    entry = history_repo.get_file_entry(torrent_hash, file_idx)
    assert entry["playback_timecode"] == 600

    # 5. Mandatory event: EOF: MUST save immediately and mark watched
    assert tracker.on_eof(torrent_hash, file_idx, duration=1800.0) is True
    entry = history_repo.get_file_entry(torrent_hash, file_idx)
    assert entry["is_watched"] == 1


# ============================================================================
# Scenario 5: Титры / ~100% (сброс статуса на 'просмотрено')
# ============================================================================

def test_credits_reset_to_watched_status(temp_db):
    """When position is near 100% (within 180s or >= 90%), status must be reset to watched."""
    history_repo = HistoryRepository(temp_db)
    tracker = PlaybackProgressTracker(history_repo=history_repo)

    torrent_hash = "hash_credits"
    file_idx = 0
    history_repo.mark_played(torrent_hash, file_idx, "Show.mkv")

    # Total duration: 1000s. Position: 920s (> 90% and remaining 80s <= 180s)
    saved = tracker.update_position(torrent_hash, file_idx, timecode=920.0, duration=1000.0, force=True)
    assert saved is True

    entry = history_repo.get_file_entry(torrent_hash, file_idx)
    assert entry["is_watched"] == 1
    # When watched, it must not appear in Continue Watching
    continue_watching = history_repo.list_continue_watching()
    assert not any(item["torrent_hash"] == torrent_hash for item in continue_watching)


# ============================================================================
# Scenario 6: Атомарность записи позиций в БД
# ============================================================================

def test_history_repository_atomic_transaction(temp_db):
    """Writing progress in HistoryRepository must be strictly atomic."""
    history_repo = HistoryRepository(temp_db)

    torrent_hash = "hash_atomic"
    file_idx = 0
    history_repo.mark_played(torrent_hash, file_idx, "Show.S02E05.mkv", season=2, episode=5)

    # Successful atomic update
    res = history_repo.update_progress(torrent_hash, file_idx, timecode=450, duration=1800)
    assert res is True

    entry = history_repo.get_file_entry(torrent_hash, file_idx)
    assert entry["playback_timecode"] == 450
    assert entry["playback_duration"] == 1800

    # Simulate database error during transaction -> verify rollback
    with patch.object(temp_db, "get_connection") as mock_get_conn:
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("DB transaction failure")
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        with pytest.raises(Exception, match="DB transaction failure"):
            history_repo.update_progress(torrent_hash, file_idx, timecode=500, duration=1800)

    # Real DB was not corrupted by the failed call
    entry_after = history_repo.get_file_entry(torrent_hash, file_idx)
    assert entry_after["playback_timecode"] == 450
