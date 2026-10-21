import inspect
import json
import re
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.api.deps import (
    get_history_repo,
    get_history_service,
    get_library_repo,
    get_metadata_repo,
    get_playback_repo,
    get_progress_service,
)
from backend.app import app
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.repositories.playback import PlaybackRepository
from backend.services.history import HistoryService
from backend.services.playback import PlaybackService, PlayCommand
from backend.services.progress import SeasonProgressService


def test_per_file_progress_and_resume():
    """Verify that multiple files in the same torrent track positions independently and resume accurately."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        play_repo = PlaybackRepository(db=db)
        hist_repo = HistoryRepository(db=db)
        meta_repo = MetadataRepository(db=db)
        lib_repo = LibraryRepository(db=db)

        thash = "1111222233334444555566667777888899990000"

        # File 0: Played 500s out of 1800s
        hist_repo.mark_played(thash, 0, "Show.S01E01.mkv", season=1, episode=1)
        hist_repo.update_progress(thash, 0, timecode=500, duration=1800)

        # File 1: Played 950s out of 1800s
        hist_repo.mark_played(thash, 1, "Show.S01E02.mkv", season=1, episode=2)
        hist_repo.update_progress(thash, 1, timecode=950, duration=1800)

        # File 0 and File 1 positions should be independent
        f0_prog = play_repo.get_previous_progress(thash, 0)
        f1_prog = play_repo.get_previous_progress(thash, 1)

        assert f0_prog is not None
        assert f0_prog["playback_timecode"] == 500
        assert f1_prog is not None
        assert f1_prog["playback_timecode"] == 950

        # Launch MPV for File 1 without explicit start_time -> should resume at 950
        mock_controller = MagicMock()
        mock_controller.is_running = True
        mock_controller.launch = MagicMock()

        mock_ts = MagicMock()
        mock_ts.save_torrent_to_db = AsyncMock()
        mock_ts.stream_url = MagicMock(return_value="http://localhost:8090/stream/1")
        mock_ts.get_torrents = AsyncMock(return_value=[])

        mock_meta = MagicMock()
        mock_meta.trigger_metadata_fetch = MagicMock()

        playback_service = PlaybackService(
            playback_repo=play_repo,
            history_repo=hist_repo,
            metadata_repo=meta_repo,
            mpv_controller_factory=lambda: mock_controller,
            torrserver_client=mock_ts,
            settings_provider=lambda: "http://localhost:8090",
            library_repo=lib_repo,
            metadata_service=mock_meta,
        )

        import anyio
        anyio.run(playback_service.launch, PlayCommand(hash=thash, file_id=1, file_name="Show.S01E02.mkv"))

        # Verify MPV was launched with start_time = 950
        mock_controller.launch.assert_called_once()
        _, kwargs = mock_controller.launch.call_args
        assert kwargs.get("start_time") == 950


def test_watched_threshold_and_latch():
    """Verify 90% or <= 180s remaining triggers watched, and once watched it cannot be cleared by rewind."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        play_repo = PlaybackRepository(db=db)
        hist_repo = HistoryRepository(db=db)
        thash = "hash_watched_threshold"

        # Duration 3000s, at 1000s (33.3%, remaining 2000s) -> unwatched
        hist_repo.mark_played(thash, 0, "Movie.mkv")
        hist_repo.update_progress(thash, 0, timecode=1000, duration=3000)
        assert play_repo.get_previous_progress(thash, 0)["is_watched"] == 0

        # At 2700s (90.0%, remaining 300s) -> watched by 90% threshold
        hist_repo.update_progress(thash, 0, timecode=2700, duration=3000)
        assert play_repo.get_previous_progress(thash, 0)["is_watched"] == 1

        # Rewind to 50s -> is_watched remains 1 (latch behavior)
        hist_repo.update_progress(thash, 0, timecode=50, duration=3000)
        assert play_repo.get_previous_progress(thash, 0)["is_watched"] == 1

        # Another test for remaining <= 180s rule:
        # Duration 600s, at 430s (71.6%, remaining 170s <= 180s) -> watched
        hist_repo.mark_played(thash, 1, "Short.mkv")
        hist_repo.update_progress(thash, 1, timecode=430, duration=600)
        assert play_repo.get_previous_progress(thash, 1)["is_watched"] == 1


def test_per_episode_mark_watched_and_idempotence():
    """Verify mark_episode_watched in repo and via API."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        hist_repo = HistoryRepository(db=db)
        imdb_id = "tt0944947"

        # Initially no episodes watched
        assert hist_repo.get_watched_episodes_map(imdb_id) == set()

        # Mark S01E01 watched
        hist_repo.mark_episode_watched(imdb_id, season=1, episode=1, watched=True)
        assert (1, 1) in hist_repo.get_watched_episodes_map(imdb_id)

        # Mark S01E01 watched again (idempotent)
        hist_repo.mark_episode_watched(imdb_id, season=1, episode=1, watched=True)
        assert (1, 1) in hist_repo.get_watched_episodes_map(imdb_id)

        # Mark S01E02 watched
        hist_repo.mark_episode_watched(imdb_id, season=1, episode=2, watched=True)
        assert hist_repo.get_watched_episodes_map(imdb_id) == {(1, 1), (1, 2)}

        # Unmark S01E01
        hist_repo.mark_episode_watched(imdb_id, season=1, episode=1, watched=False)
        assert hist_repo.get_watched_episodes_map(imdb_id) == {(1, 2)}


@pytest.mark.anyio
async def test_season_progress_service_and_next_unwatched():
    """Verify season progress calculation and next unwatched resolution."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        hist_repo = HistoryRepository(db=db)
        meta_repo = MetadataRepository(db=db)
        lib_repo = LibraryRepository(db=db)

        # Catalog with 2 seasons:
        # S1: E1, E2, E3, E4
        # S2: E1, E2
        mock_meta_service = MagicMock()
        mock_meta_service.details = AsyncMock(
            return_value={
                "type": "series",
                "videos": [
                    {"season": 1, "episode": 1, "title": "Winter Is Coming"},
                    {"season": 1, "episode": 2, "title": "The Kingsroad"},
                    {"season": 1, "episode": 3, "title": "Lord Snow"},
                    {"season": 1, "episode": 4, "title": "Cripples, Bastards, and Broken Things"},
                    {"season": 2, "episode": 1, "title": "The North Remembers"},
                    {"season": 2, "episode": 2, "title": "The Night Lands"},
                ],
            }
        )
        mock_meta_service.movie_meta = mock_meta_service.details

        mock_ts = MagicMock()
        progress_service = SeasonProgressService(
            history_repo=hist_repo,
            metadata_repo=meta_repo,
            library_repo=lib_repo,
            torrserver_client=mock_ts,
            settings_provider=lambda: "http://localhost:8090",
            metadata_service=mock_meta_service,
        )

        imdb_id = "tt0944947"

        # 1. 0% progress initially
        prog = await progress_service.get_season_progress(imdb_id)
        assert prog["total_files"] == 6
        assert prog["watched_files"] == 0
        assert prog["progress"] == 0.0
        assert prog["is_completed"] is False
        assert prog["seasons"]["1"]["watched"] == 0
        assert prog["seasons"]["1"]["total"] == 4
        assert prog["seasons"]["1"]["progress_percent"] == 0.0
        assert prog["seasons"]["1"]["next_episode"] == 1

        next_ep = await progress_service.get_next_unwatched(imdb_id)
        assert next_ep["found"] is True
        assert next_ep["season"] == 1
        assert next_ep["episode"] == 1

        # 2. Watch S01E01 and S01E03 (S01E02 skipped!)
        hist_repo.mark_episode_watched(imdb_id, 1, 1, watched=True)
        hist_repo.mark_episode_watched(imdb_id, 1, 3, watched=True)

        prog2 = await progress_service.get_season_progress(imdb_id)
        assert prog2["seasons"]["1"]["watched"] == 2
        assert prog2["seasons"]["1"]["progress_percent"] == 50.0
        # Next unwatched in S1 MUST be the skipped E2!
        assert prog2["seasons"]["1"]["next_episode"] == 2

        next_ep2 = await progress_service.get_next_unwatched(imdb_id)
        assert next_ep2["season"] == 1
        assert next_ep2["episode"] == 2

        # 3. Watch S01E02 and S01E04 -> Season 1 complete!
        hist_repo.mark_episode_watched(imdb_id, 1, 2, watched=True)
        hist_repo.mark_episode_watched(imdb_id, 1, 4, watched=True)

        prog3 = await progress_service.get_season_progress(imdb_id)
        assert prog3["seasons"]["1"]["is_completed"] is True
        assert prog3["seasons"]["1"]["next_episode"] is None

        # Next unwatched for entire show should now be Season 2 Episode 1
        next_ep3 = await progress_service.get_next_unwatched(imdb_id)
        assert next_ep3["season"] == 2
        assert next_ep3["episode"] == 1

        # 4. Watch all season 2 episodes
        hist_repo.mark_episode_watched(imdb_id, 2, 1, watched=True)
        hist_repo.mark_episode_watched(imdb_id, 2, 2, watched=True)

        prog4 = await progress_service.get_season_progress(imdb_id)
        assert prog4["is_completed"] is True
        assert prog4["watched_files"] == 6

        next_ep4 = await progress_service.get_next_unwatched(imdb_id)
        assert next_ep4 is None or next_ep4.get("found") is False


def test_selective_deletion_and_continue_watching_api():
    """Verify DELETE /api/history/{id} deletes only the specific entry without deleting the whole series."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        hist_repo = HistoryRepository(db=db)
        play_repo = PlaybackRepository(db=db)
        meta_repo = MetadataRepository(db=db)
        lib_repo = LibraryRepository(db=db)

        thash = "hash_selective_del"
        imdb_id = "tt_selective_1"

        # Create 3 history entries for files 0, 1, 2
        id0 = hist_repo.mark_played(thash, 0, "Show.S01E01.mkv", season=1, episode=1, imdb_id=imdb_id)
        hist_repo.update_progress(thash, 0, timecode=300, duration=1000)

        id1 = hist_repo.mark_played(thash, 1, "Show.S01E02.mkv", season=1, episode=2, imdb_id=imdb_id)
        hist_repo.update_progress(thash, 1, timecode=400, duration=1000)

        id2 = hist_repo.mark_played(thash, 2, "Show.S01E03.mkv", season=1, episode=3, imdb_id=imdb_id)
        hist_repo.update_progress(thash, 2, timecode=1000, duration=1000)  # Finished/watched

        mock_ts = MagicMock()
        mock_meta = MagicMock()
        prog_service = SeasonProgressService(
            history_repo=hist_repo,
            metadata_repo=meta_repo,
            library_repo=lib_repo,
            torrserver_client=mock_ts,
            settings_provider=lambda: "http://localhost:8090",
            metadata_service=mock_meta,
        )
        hist_service = HistoryService(
            history_repo=hist_repo,
            progress_service=prog_service,
        )

        app.dependency_overrides[get_history_repo] = lambda: hist_repo
        app.dependency_overrides[get_history_service] = lambda: hist_service
        app.dependency_overrides[get_progress_service] = lambda: prog_service
        app.dependency_overrides[get_metadata_repo] = lambda: meta_repo
        app.dependency_overrides[get_library_repo] = lambda: lib_repo
        app.dependency_overrides[get_playback_repo] = lambda: play_repo

        try:
            client = TestClient(app)

            # Check continue watching API -> should only return unfinished entries (id0, id1), not id2
            res_cont = client.get("/api/history/continue")
            assert res_cont.status_code == 200
            cont_items = res_cont.json()
            assert len(cont_items) == 2
            file_indices = {it["file_index"] for it in cont_items}
            assert file_indices == {0, 1}

            # Delete only entry for file 1
            entry_to_del = next(it for it in cont_items if it["file_index"] == 1)
            res_del = client.delete(f"/api/history/{entry_to_del['id']}")
            assert res_del.status_code == 200
            assert res_del.json().get("status") == "ok"

            # Entry 0 and Entry 2 MUST still exist!
            remaining_history = hist_repo.list_history()
            remaining_files = {e["file_index"] for e in remaining_history}
            assert remaining_files == {0, 2}

            # Continue watching now only has entry 0
            res_cont2 = client.get("/api/history/continue")
            assert res_cont2.status_code == 200
            cont_items2 = res_cont2.json()
            assert len(cont_items2) == 1
            assert cont_items2[0]["file_index"] == 0

            # Test mark-watched endpoint via API
            res_mw = client.post(
                "/api/history/mark-watched",
                json={"imdb_id": imdb_id, "season": 1, "episode": 1, "watched": True},
            )
            assert res_mw.status_code == 200
            assert res_mw.json().get("status") == "ok"
            assert (1, 1) in hist_repo.get_watched_episodes_map(imdb_id)

        finally:
            app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_torrent_with_multiple_files_not_limited_to_one():
    """Verify that a torrent with multiple files displays the full file count even if only 1 file was played."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        hist_repo = HistoryRepository(db=db)
        meta_repo = MetadataRepository(db=db)
        lib_repo = LibraryRepository(db=db)

        thash = "hash_multi_episodes_test"
        # Only 1 file played in history
        hist_repo.mark_played(thash, 0, "Stranger.Things.S05E01.mkv", season=5, episode=1)

        # But TorrServer has 7 files in the torrent
        mock_ts = MagicMock()
        mock_ts.torrent_video_files = AsyncMock(
            return_value=[
                {"id": 0, "name": "Stranger.Things.S05E01.mkv", "length": 1000},
                {"id": 1, "name": "Stranger.Things.S05E02.mkv", "length": 1000},
                {"id": 2, "name": "Stranger.Things.S05E03.mkv", "length": 1000},
                {"id": 3, "name": "Stranger.Things.S05E04.mkv", "length": 1000},
                {"id": 4, "name": "Stranger.Things.S05E05.mkv", "length": 1000},
                {"id": 5, "name": "Stranger.Things.S05E06.mkv", "length": 1000},
                {"id": 6, "name": "Stranger.Things.S05E07.mkv", "length": 1000},
            ]
        )
        mock_ts.get_torrents = AsyncMock(
            return_value=[
                {
                    "hash": thash,
                    "title": "Stranger Things S05",
                    "total_files": 7,
                }
            ]
        )

        mock_meta_service = MagicMock()
        mock_meta_service.movie_meta = AsyncMock(return_value={"videos": []})

        prog_service = SeasonProgressService(
            history_repo=hist_repo,
            metadata_repo=meta_repo,
            library_repo=lib_repo,
            torrserver_client=mock_ts,
            settings_provider=lambda: "http://localhost:8090",
            metadata_service=mock_meta_service,
        )

        prog = await prog_service.get_season_progress(thash)
        assert prog["total_files"] == 7
        assert prog["seasons"]["5"]["total"] == 7
        assert prog["seasons"]["5"]["watched"] == 0

        # Also test LibraryService returns total_files = 7
        from backend.api.schemas.library import LibraryFilter
        from backend.services.library import LibraryService

        lib_service = LibraryService(
            library_repo=lib_repo,
            torrserver_client=mock_ts,
            settings_provider=lambda: "http://localhost:8090",
            metadata_service=mock_meta_service,
        )
        lib_items = await lib_service.get_filtered_library(LibraryFilter())
        assert len(lib_items) == 1
        assert lib_items[0]["total_files"] == 7
        assert lib_items[0]["watched_files"] == 0


def test_no_broad_exceptions_in_modified_code():
    """Verify strict exception handling rule: NO universal except clauses in modified backend files."""
    files_to_check = [
        "backend/repositories/history.py",
        "backend/repositories/playback.py",
        "backend/repositories/db.py",
        "backend/services/progress.py",
        "backend/services/history.py",
        "backend/api/routers/history.py",
        "backend/api/routers/library.py",
    ]

    broad_pattern = re.compile(r"^\s*except\s*(Exception|BaseException)?\s*:", re.MULTILINE)

    for file_path in files_to_check:
        p = Path(file_path)
        if not p.exists():
            continue
        content = p.read_text(encoding="utf-8")
        matches = broad_pattern.findall(content)
        assert not matches, f"Found broad exception handling in {file_path}: {matches}"
