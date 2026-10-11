import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.api.schemas.library import (
    LibraryFilter,
    SeasonProgress,
)
from backend.app import app
from backend.exceptions import NotFoundError
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.services.library import LibraryService


def test_sqlite_indices():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        with db.get_connection() as conn:
            indices = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
            index_names = {row["name"] for row in indices}

            assert "idx_media_types_type" in index_names
            assert "idx_media_metadata_year" in index_names
            assert "idx_media_file_history_status" in index_names
            assert "idx_media_file_history_hash_status" in index_names
            assert "idx_offline_metadata_cache_created" in index_names


def test_library_repository_query_builder():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        lib_repo = LibraryRepository(db=db)
        meta_repo = MetadataRepository(db=db)
        hist_repo = HistoryRepository(db=db)

        # Seed data
        # Item 1: Series, 2022, Drama/Crime, 2 files, both watched -> status: watched
        h1 = "hash1_series_watched"
        meta_repo.save_full_metadata(
            torrent_hash=h1,
            title="Better Call Saul",
            overview="Lawyer show",
            year=2022,
            rating=8.9,
            poster_file="bcs.jpg",
            genres_json=json.dumps(["Crime", "Drama"]),
        )
        lib_repo.save_media_type(h1, "series")
        hist_repo.mark_played(h1, 1, "S06E01.mkv")
        hist_repo.update_progress(h1, 1, timecode=3000, duration=3000)  # is_watched = 1
        hist_repo.mark_played(h1, 2, "S06E02.mkv")
        hist_repo.update_progress(h1, 2, timecode=3000, duration=3000)  # is_watched = 1

        # Item 2: Series, 2020, Sci-Fi/Drama, 2 files, 1 watched, 1 unwatched -> status: in_progress
        h2 = "hash2_series_in_progress"
        meta_repo.save_full_metadata(
            torrent_hash=h2,
            title="Dark",
            overview="Time travel show",
            year=2020,
            rating=8.7,
            poster_file="dark.jpg",
            genres_json=json.dumps(["Sci-Fi", "Drama"]),
        )
        lib_repo.save_media_type(h2, "series")
        hist_repo.mark_played(h2, 1, "Dark.S01E01.mkv")
        hist_repo.update_progress(h2, 1, timecode=3000, duration=3000)  # is_watched = 1
        hist_repo.mark_played(h2, 2, "Dark.S01E02.mkv")
        hist_repo.update_progress(h2, 2, timecode=0, duration=3000)  # is_watched = 0

        # Item 3: Movie, 2010, Sci-Fi/Action, 1 file, timecode=0 -> status: unwatched
        h3 = "hash3_movie_unwatched"
        meta_repo.save_full_metadata(
            torrent_hash=h3,
            title="Inception",
            overview="Dream movie",
            year=2010,
            rating=8.8,
            poster_file="inception.jpg",
            genres_json=json.dumps(["Action", "Sci-Fi"]),
        )
        lib_repo.save_media_type(h3, "movie")

        # 1. Test filter by type
        movies = lib_repo.query_library(media_type="movie")
        assert len(movies) == 1
        assert movies[0]["torrent_hash"] == h3

        series = lib_repo.query_library(media_type="series")
        assert len(series) == 2

        # 2. Test filter by status
        watched = lib_repo.query_library(status="watched")
        assert len(watched) == 1
        assert watched[0]["torrent_hash"] == h1

        in_prog = lib_repo.query_library(status="in_progress")
        assert len(in_prog) == 1
        assert in_prog[0]["torrent_hash"] == h2

        unwatched = lib_repo.query_library(status="unwatched")
        assert len(unwatched) == 1
        assert unwatched[0]["torrent_hash"] == h3

        # 3. Test filter by year
        y2022 = lib_repo.query_library(year=2022)
        assert len(y2022) == 1
        assert y2022[0]["torrent_hash"] == h1

        y2099 = lib_repo.query_library(year=2099)
        assert len(y2099) == 0

        # 4. Test filter by genre
        scifi = lib_repo.query_library(genre="Sci-Fi")
        assert len(scifi) == 2

        crime = lib_repo.query_library(genre="Crime")
        assert len(crime) == 1
        assert crime[0]["torrent_hash"] == h1

        # 5. Combined filters
        combined = lib_repo.query_library(
            media_type="series", genre="Drama", status="watched"
        )
        assert len(combined) == 1
        assert combined[0]["torrent_hash"] == h1

        # 6. Sorting
        sorted_title_asc = lib_repo.query_library(sort="title")
        titles_asc = [r["title"] for r in sorted_title_asc]
        assert titles_asc == sorted(titles_asc, key=lambda s: s.lower())

        sorted_title_desc = lib_repo.query_library(sort="-title")
        titles_desc = [r["title"] for r in sorted_title_desc]
        assert titles_desc == sorted(titles_asc, key=lambda s: s.lower(), reverse=True)

        sorted_year_desc = lib_repo.query_library(sort="year")
        years = [r["year"] for r in sorted_year_desc]
        assert years == [2022, 2020, 2010]

        sorted_rating_desc = lib_repo.query_library(sort="-rating")
        ratings = [r["rating"] for r in sorted_rating_desc]
        assert ratings == [8.9, 8.8, 8.7]


@pytest.mark.anyio
async def test_library_service_filters_and_enrichment():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        lib_repo = LibraryRepository(db=db)
        meta_repo = MetadataRepository(db=db)

        meta_repo.save_full_metadata(
            torrent_hash="h1",
            title="The Matrix",
            overview="Cyberpunk classic",
            year=1999,
            rating=8.7,
            poster_file="matrix.jpg",
            genres_json=json.dumps(["Action", "Sci-Fi"]),
        )
        lib_repo.save_media_type("h1", "movie")

        mock_torrserver = MagicMock()
        mock_torrserver.get_torrents = AsyncMock(return_value=[])

        service = LibraryService(
            library_repo=lib_repo,
            torrserver_client=mock_torrserver,
            settings_provider=lambda: "http://localhost:8090",
            metadata_service=None,
            posters_dir=Path(tmp_dir) / "posters",
        )

        filters = LibraryFilter(type="movie", year=1999)
        results = await service.get_filtered_library(filters)

        assert len(results) == 1
        item = results[0]
        assert item["hash"] == "h1"
        assert item["title"] == "The Matrix"
        assert item["genres"] == ["Action", "Sci-Fi"]
        assert item["status"] == "unwatched"
        assert item["progress"] == 0.0
        assert item["poster_url"] == "/api/library/poster/h1"


@pytest.mark.anyio
async def test_library_service_season_progress():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        lib_repo = LibraryRepository(db=db)
        hist_repo = HistoryRepository(db=db)

        torrent_hash = "series_hash_1"

        # Season 1: 3 episodes (2 watched, 1 unwatched)
        # Season 2: 2 episodes (0 watched)
        hist_repo.mark_played(torrent_hash, 1, "Show.S01E01.mkv")
        hist_repo.update_progress(torrent_hash, 1, 3000, 3000)  # is_watched = 1
        hist_repo.mark_played(torrent_hash, 2, "Show.S01E02.mkv")
        hist_repo.update_progress(torrent_hash, 2, 3000, 3000)  # is_watched = 1
        hist_repo.mark_played(torrent_hash, 3, "Show.S01E03.mkv")
        hist_repo.update_progress(torrent_hash, 3, 0, 3000)  # is_watched = 0

        hist_repo.mark_played(torrent_hash, 4, "Show.S02E01.mkv")
        hist_repo.update_progress(torrent_hash, 4, 0, 3000)  # is_watched = 0
        hist_repo.mark_played(torrent_hash, 5, "Show.S02E02.mkv")
        hist_repo.update_progress(torrent_hash, 5, 0, 3000)  # is_watched = 0

        mock_torrserver = MagicMock()
        mock_torrserver.torrent_video_files = AsyncMock(
            return_value=[
                {"id": 1, "name": "Show.S01E01.mkv"},
                {"id": 2, "name": "Show.S01E02.mkv"},
                {"id": 3, "name": "Show.S01E03.mkv"},
                {"id": 4, "name": "Show.S02E01.mkv"},
                {"id": 5, "name": "Show.S02E02.mkv"},
            ]
        )

        service = LibraryService(
            library_repo=lib_repo,
            torrserver_client=mock_torrserver,
            settings_provider=lambda: "http://localhost:8090",
            metadata_service=None,
        )

        progress_data = await service.get_season_progress(torrent_hash)

        assert progress_data["torrent_hash"] == torrent_hash
        assert progress_data["total_files"] == 5
        assert progress_data["watched_files"] == 2
        assert progress_data["progress"] == round(2 / 5, 2)
        assert progress_data["is_completed"] is False

        # Per-season progress: Progress = watched files / total per season
        s1 = progress_data["seasons"]["1"]
        assert s1["season"] == "1"
        assert s1["total_files"] == 3
        assert s1["watched_files"] == 2
        assert s1["progress"] == round(2 / 3, 2)
        assert s1["is_completed"] is False

        # Validate with SeasonProgress schema
        sp1 = SeasonProgress(**s1)
        assert sp1.season == "1"
        assert sp1.total_files == 3
        assert sp1.watched_files == 2

        s2 = progress_data["seasons"]["2"]
        assert s2["season"] == "2"
        assert s2["total_files"] == 2
        assert s2["watched_files"] == 0
        assert s2["progress"] == 0.0
        assert s2["is_completed"] is False


@pytest.mark.anyio
async def test_library_service_next_unwatched_natural_sort():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        lib_repo = LibraryRepository(db=db)
        hist_repo = HistoryRepository(db=db)

        torrent_hash = "natural_sort_hash"

        # Mark S01E01 watched
        hist_repo.mark_played(torrent_hash, 1, "Series.S01E01.mkv")
        hist_repo.update_progress(torrent_hash, 1, 3000, 3000)  # is_watched = 1

        # TorrServer returns files out of order, including S01E10 before S01E02
        raw_files = [
            {"id": 10, "name": "Series.S01E10.mkv"},
            {"id": 1, "name": "Series.S01E01.mkv"},
            {"id": 3, "name": "Series.S01E03.mkv"},
            {"id": 2, "name": "Series.S01E02.mkv"},
        ]

        mock_torrserver = MagicMock()
        mock_torrserver.torrent_video_files = AsyncMock(return_value=raw_files)

        service = LibraryService(
            library_repo=lib_repo,
            torrserver_client=mock_torrserver,
            settings_provider=lambda: "http://localhost:8090",
            metadata_service=None,
        )

        next_ep = await service.get_next_unwatched(torrent_hash)

        # Because S01E01 is watched, natural sort must pick S01E02 next, NOT S01E10!
        assert next_ep["file_id"] == 2
        assert next_ep["file_name"] == "Series.S01E02.mkv"
        assert next_ep["season"] == 1
        assert next_ep["episode"] == 2
        assert next_ep["is_watched"] is False

        # Mark S01E02 and S01E03 watched
        hist_repo.mark_played(torrent_hash, 2, "Series.S01E02.mkv")
        hist_repo.update_progress(torrent_hash, 2, 3000, 3000)
        hist_repo.mark_played(torrent_hash, 3, "Series.S01E03.mkv")
        hist_repo.update_progress(torrent_hash, 3, 3000, 3000)

        next_ep2 = await service.get_next_unwatched(torrent_hash)
        assert next_ep2["file_id"] == 10
        assert next_ep2["file_name"] == "Series.S01E10.mkv"
        assert next_ep2["episode"] == 10

        # Mark S01E10 watched -> all watched should raise NotFoundError
        hist_repo.mark_played(torrent_hash, 10, "Series.S01E10.mkv")
        hist_repo.update_progress(torrent_hash, 10, 3000, 3000)

        with pytest.raises(NotFoundError):
            await service.get_next_unwatched(torrent_hash)


def test_api_endpoints_integration(monkeypatch):
    client = TestClient(app)

    # 1. GET /api/library with filters
    resp = client.get("/api/library?type=movie&sort=title")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # 2. GET /library alias
    resp_alias = client.get("/library?type=series")
    assert resp_alias.status_code == 200
    assert isinstance(resp_alias.json(), list)

    # 3. Non-existent hash progress -> 404
    resp_prog = client.get("/api/library/nonexistenthash/progress")
    assert resp_prog.status_code == 404

    # 4. Non-existent hash next-unwatched -> 404
    resp_next = client.get("/api/library/nonexistenthash/next-unwatched")
    assert resp_next.status_code == 404


def test_api_endpoints_with_seeded_data():
    from backend.api import deps

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        test_db.init_db()

        lib_repo = LibraryRepository(db=test_db)
        meta_repo = MetadataRepository(db=test_db)
        hist_repo = HistoryRepository(db=test_db)

        meta_repo.save_full_metadata(
            torrent_hash="h100",
            title="Westworld",
            overview="Theme park",
            year=2016,
            rating=8.5,
            poster_file="ww.jpg",
            genres_json=json.dumps(["Sci-Fi", "Western"]),
        )
        lib_repo.save_media_type("h100", "series")
        hist_repo.mark_played("h100", 1, "Westworld.S01E01.mkv")
        hist_repo.update_progress("h100", 1, 3600, 3600)  # watched
        hist_repo.mark_played("h100", 2, "Westworld.S01E02.mkv")
        hist_repo.update_progress("h100", 2, 0, 3600)  # unwatched

        app.dependency_overrides[deps.get_database] = lambda: test_db
        try:
            client = TestClient(app)

            # 1. Filter
            r = client.get("/api/library?type=series&genre=Sci-Fi")
            assert r.status_code == 200
            items = r.json()
            assert any(it["hash"] == "h100" for it in items)

            # 2. Progress
            r_prog = client.get("/api/library/h100/progress")
            assert r_prog.status_code == 200
            prog = r_prog.json()
            assert prog["torrent_hash"] == "h100"
            assert "1" in prog["seasons"]
            assert prog["seasons"]["1"]["total_files"] == 2
            assert prog["seasons"]["1"]["watched_files"] == 1

            # 3. Next unwatched
            r_next = client.get("/api/library/h100/next-unwatched")
            assert r_next.status_code == 200
            next_data = r_next.json()
            assert next_data["file_id"] == 2
            assert next_data["file_name"] == "Westworld.S01E02.mkv"
            assert next_data["season"] == 1
            assert next_data["episode"] == 2

            # 4. Direct /library endpoints
            r_direct = client.get("/library?type=series&genre=Sci-Fi")
            assert r_direct.status_code == 200
            assert any(it["hash"] == "h100" for it in r_direct.json())

            r_prog_direct = client.get("/library/h100/progress")
            assert r_prog_direct.status_code == 200

            r_next_direct = client.get("/library/h100/next-unwatched")
            assert r_next_direct.status_code == 200
        finally:
            app.dependency_overrides.clear()


def test_multi_genre_filter():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        lib_repo = LibraryRepository(db=db)
        meta_repo = MetadataRepository(db=db)

        meta_repo.save_full_metadata(
            torrent_hash="g1",
            title="Sci-Fi Action",
            overview="O1",
            year=2021,
            rating=8.0,
            poster_file="",
            genres_json=json.dumps(["Sci-Fi", "Action"]),
        )
        meta_repo.save_full_metadata(
            torrent_hash="g2",
            title="Drama Romance",
            overview="O2",
            year=2022,
            rating=7.5,
            poster_file="",
            genres_json=json.dumps(["Drama", "Romance"]),
        )
        meta_repo.save_full_metadata(
            torrent_hash="g3",
            title="Comedy Drama",
            overview="O3",
            year=2023,
            rating=6.5,
            poster_file="",
            genres_json=json.dumps(["Comedy", "Drama"]),
        )

        # Multi-genre query comma separated
        res = lib_repo.query_library(genre="Action,Comedy")
        hashes = {r["torrent_hash"] for r in res}
        assert "g1" in hashes
        assert "g3" in hashes
        assert "g2" not in hashes

        # List of genres
        res_list = lib_repo.query_library(genre=["Action", "Romance"])
        hashes_list = {r["torrent_hash"] for r in res_list}
        assert "g1" in hashes_list
        assert "g2" in hashes_list
        assert "g3" not in hashes_list


@pytest.mark.anyio
async def test_natural_sort_and_specials_next_unwatched():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        lib_repo = LibraryRepository(db=db)
        hist_repo = HistoryRepository(db=db)

        h = "series_specials"
        hist_repo.mark_played(h, 0, "Show.S00E01.Special.mkv")
        hist_repo.update_progress(h, 0, 1000, 1000)  # S00E01 watched
        hist_repo.mark_played(h, 1, "Show.S01E01.mkv")
        hist_repo.update_progress(h, 1, 1000, 1000)  # S01E01 watched
        hist_repo.mark_played(h, 2, "Show.S01E02.mkv")
        hist_repo.update_progress(h, 2, 0, 1000)  # S01E02 unwatched
        hist_repo.mark_played(h, 3, "Show.S01E10.mkv")
        hist_repo.update_progress(h, 3, 0, 1000)  # S01E10 unwatched
        hist_repo.mark_played(h, 4, "sample.mkv")
        hist_repo.update_progress(h, 4, 0, 100)

        mock_ts = MagicMock()
        mock_ts.torrent_video_files = AsyncMock(
            return_value=[
                {"id": 4, "name": "sample.mkv"},
                {"id": 3, "name": "Show.S01E10.mkv"},
                {"id": 1, "name": "Show.S01E01.mkv"},
                {"id": 0, "name": "Show.S00E01.Special.mkv"},
                {"id": 2, "name": "Show.S01E02.mkv"},
            ]
        )

        service = LibraryService(
            library_repo=lib_repo,
            torrserver_client=mock_ts,
            settings_provider=lambda: "http://localhost:8090",
            metadata_service=None,
        )

        # Verify next unwatched selects S01E02 with natural sort (not S01E10 or sample)
        next_unwatched = await service.get_next_unwatched(h)
        assert next_unwatched["file_id"] == 2
        assert next_unwatched["file_name"] == "Show.S01E02.mkv"
        assert next_unwatched["season"] == 1
        assert next_unwatched["episode"] == 2
        # Verify hash and torrent_hash consistency
        assert next_unwatched["hash"] == h
        assert next_unwatched["torrent_hash"] == h

        # Verify season progress includes Season 0 and Season 1
        progress = await service.get_season_progress(h)
        assert "0" in progress["seasons"]
        assert "1" in progress["seasons"]
        assert progress["seasons"]["0"]["is_completed"] is True
        assert progress["seasons"]["1"]["is_completed"] is False
        assert progress["hash"] == h
        assert progress["torrent_hash"] == h


@pytest.mark.anyio
async def test_launched_media_added_to_library():
    from backend.models.playback import PlayCommand
    from backend.repositories.playback import PlaybackRepository
    from backend.services.playback import PlaybackService

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        lib_repo = LibraryRepository(db=db)
        hist_repo = HistoryRepository(db=db)
        meta_repo = MetadataRepository(db=db)
        play_repo = PlaybackRepository(db=db)

        mock_ts = MagicMock()
        mock_ts.save_torrent_to_db = AsyncMock()
        mock_ts.stream_url = MagicMock(return_value="http://localhost:8090/stream/1")
        mock_ts.get_torrents = AsyncMock(return_value=[])

        mock_controller = MagicMock()
        mock_controller.is_running = True
        mock_controller.launch = MagicMock()

        mock_meta_service = MagicMock()
        mock_meta_service.trigger_metadata_fetch = MagicMock()

        playback_service = PlaybackService(
            playback_repo=play_repo,
            history_repo=hist_repo,
            metadata_repo=meta_repo,
            mpv_controller_factory=lambda: mock_controller,
            torrserver_client=mock_ts,
            settings_provider=lambda: "http://localhost:8090",
            library_repo=lib_repo,
            metadata_service=mock_meta_service,
        )

        h_movie = "1122334455667788990011223344556677889900"
        cmd = PlayCommand(hash=h_movie, file_id=0, file_name="Interstellar.2014.1080p.mkv")
        await playback_service.launch(cmd)

        # 1. Verify TorrServer persistence was requested
        mock_ts.save_torrent_to_db.assert_awaited_once_with(
            "http://localhost:8090", h_movie, "Interstellar.2014.1080p.mkv"
        )

        # 2. Verify metadata enrichment was triggered
        mock_meta_service.trigger_metadata_fetch.assert_called_once_with(
            h_movie, "Interstellar.2014.1080p.mkv"
        )

        # 3. Verify item is in library repo
        lib_items = lib_repo.query_library()
        assert len(lib_items) == 1
        assert lib_items[0]["torrent_hash"] == h_movie
        assert lib_items[0]["title"] == "Interstellar.2014.1080p.mkv"

        # 4. Verify LibraryService returns it in filtered library
        lib_service = LibraryService(
            library_repo=lib_repo,
            torrserver_client=mock_ts,
            settings_provider=lambda: "http://localhost:8090",
            metadata_service=mock_meta_service,
        )
        library_result = await lib_service.get_filtered_library(LibraryFilter())
        assert len(library_result) == 1
        assert library_result[0]["torrent_hash"] == h_movie
        assert library_result[0]["title"] == "Interstellar.2014.1080p.mkv"

