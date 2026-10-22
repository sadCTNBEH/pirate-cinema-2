"""Comprehensive tests for TASK-006: Advanced Library Filters & Sorting."""

from __future__ import annotations

import contextlib
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api.deps import get_database, get_library_service
from backend.api.schemas.library import LibraryFilter
from backend.app import app
from backend.repositories.collections import CollectionRepository
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.services.library import LibraryService

# ─── Fixtures ───


@pytest.fixture
def test_db():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test_library_v2.sqlite3")
        db.init_db()
        yield db


@pytest.fixture
def populated_repos(test_db):
    lib_repo = LibraryRepository(db=test_db)
    meta_repo = MetadataRepository(db=test_db)
    hist_repo = HistoryRepository(db=test_db)
    coll_repo = CollectionRepository(db=test_db)

    # 1. Movie 1: Inception (2010), Sci-Fi/Action, Completed (1/1 watched), added: 2026-01-01
    m1 = "hash_inception"
    meta_repo.save_full_metadata(
        torrent_hash=m1,
        title="Inception",
        overview="Dream heist",
        year=2010,
        rating=8.8,
        poster_file="inception.jpg",
        genres_json=json.dumps(["Action", "Sci-Fi"]),
    )
    lib_repo.save_media_type(m1, "movie")
    lib_repo.save_total_files(m1, 1)
    lib_repo.ensure_torrent(m1, "Inception", 1, added_at="2026-01-01T10:00:00Z")
    hist_repo.mark_played(m1, 0, "inception.mkv")
    hist_repo.update_progress(m1, 0, timecode=7200, duration=7200)  # is_watched=1

    # 2. Movie 2: Dune (2021), Sci-Fi/Adventure, Planned (in watch_later, unwatched), added: 2026-01-15
    m2 = "hash_dune"
    meta_repo.save_full_metadata(
        torrent_hash=m2,
        title="Dune",
        overview="Desert planet",
        year=2021,
        rating=8.2,
        poster_file="dune.jpg",
        genres_json=json.dumps(["Sci-Fi", "Adventure"]),
    )
    lib_repo.save_media_type(m2, "movie")
    lib_repo.save_total_files(m2, 1)
    lib_repo.ensure_torrent(m2, "Dune", 1, added_at="2026-01-15T10:00:00Z")
    coll_repo.save_item(
        "watch_later",
        {
            "media_id": m2,
            "title": "Dune",
            "year": 2021,
            "media_type": "movie",
        },
    )

    # 3. Movie 3: The Dark Knight (2008), Action/Crime, Watching (in progress, timecode=3000/9000), added: 2026-01-10
    m3 = "hash_tdk"
    meta_repo.save_full_metadata(
        torrent_hash=m3,
        title="The Dark Knight",
        overview="Batman and Joker",
        year=2008,
        rating=9.0,
        poster_file="tdk.jpg",
        genres_json=json.dumps(["Action", "Crime"]),
    )
    lib_repo.save_media_type(m3, "movie")
    lib_repo.save_total_files(m3, 1)
    lib_repo.ensure_torrent(m3, "The Dark Knight", 1, added_at="2026-01-10T10:00:00Z")
    hist_repo.mark_played(m3, 0, "tdk.mkv")
    hist_repo.update_progress(m3, 0, timecode=3000, duration=9000)  # is_watched=0, tc>0

    # 4. Series 1: Better Call Saul (2022), Crime/Drama, Completed (2/2 episodes watched), added: 2026-01-05
    s1 = "hash_bcs"
    meta_repo.save_full_metadata(
        torrent_hash=s1,
        title="Better Call Saul",
        overview="Jimmy McGill becoming Saul",
        year=2022,
        rating=8.9,
        poster_file="bcs.jpg",
        genres_json=json.dumps(["Crime", "Drama"]),
    )
    lib_repo.save_media_type(s1, "series")
    lib_repo.save_total_files(s1, 2)
    lib_repo.ensure_torrent(s1, "Better Call Saul", 2, added_at="2026-01-05T10:00:00Z")
    hist_repo.mark_played(s1, 1, "BCS.S06E01.mkv")
    hist_repo.update_progress(s1, 1, timecode=3000, duration=3000)  # watched 1
    hist_repo.mark_played(s1, 2, "BCS.S06E02.mkv")
    hist_repo.update_progress(s1, 2, timecode=3000, duration=3000)  # watched 2

    # 5. Series 2: Dark (2017), Sci-Fi/Mystery, Watching (1/3 episodes watched), added: 2026-01-20
    s2 = "hash_dark"
    meta_repo.save_full_metadata(
        torrent_hash=s2,
        title="Dark",
        overview="Winden caves time travel",
        year=2017,
        rating=8.7,
        poster_file="dark.jpg",
        genres_json=json.dumps(["Sci-Fi", "Mystery"]),
    )
    lib_repo.save_media_type(s2, "series")
    lib_repo.save_total_files(s2, 3)
    lib_repo.ensure_torrent(s2, "Dark", 3, added_at="2026-01-20T10:00:00Z")
    hist_repo.mark_played(s2, 1, "Dark.S01E01.mkv")
    hist_repo.update_progress(s2, 1, timecode=3000, duration=3000)  # watched 1 of 3

    # 6. Title with trick genre: "Martial Arts" to verify exact genre match vs substring
    m4 = "hash_kungfu"
    meta_repo.save_full_metadata(
        torrent_hash=m4,
        title="Kung Fu Hustle",
        overview="Martial arts comedy",
        year=2004,
        rating=7.7,
        poster_file="kungfu.jpg",
        genres_json=json.dumps(["Martial Arts", "Comedy"]),
    )
    lib_repo.save_media_type(m4, "movie")
    lib_repo.save_total_files(m4, 1)
    lib_repo.ensure_torrent(m4, "Kung Fu Hustle", 1, added_at="2026-01-02T10:00:00Z")

    return {
        "db": test_db,
        "lib_repo": lib_repo,
        "meta_repo": meta_repo,
        "hist_repo": hist_repo,
        "coll_repo": coll_repo,
    }


# ─── 1. Content Type Filtering ───


def test_filter_by_content_type(populated_repos):
    lib_repo = populated_repos["lib_repo"]

    movies = lib_repo.query_library(media_type="movie")
    assert len(movies) == 4
    for m in movies:
        assert m["media_type"] == "movie"

    series = lib_repo.query_library(media_type="series")
    assert len(series) == 2
    for s in series:
        assert s["media_type"] == "series"

    all_items = lib_repo.query_library(media_type=None)
    assert len(all_items) == 6


# ─── 2. Watch Status Filtering ───


def test_filter_by_status_completed(populated_repos):
    lib_repo = populated_repos["lib_repo"]
    completed = lib_repo.query_library(status="completed")
    hashes = {item["torrent_hash"] for item in completed}
    # Inception (1/1 watched) and Better Call Saul (2/2 watched)
    assert hashes == {"hash_inception", "hash_bcs"}


def test_filter_by_status_watching(populated_repos):
    lib_repo = populated_repos["lib_repo"]
    watching = lib_repo.query_library(status="watching")
    hashes = {item["torrent_hash"] for item in watching}
    # The Dark Knight (partial timecode) and Dark (1/3 episodes watched)
    assert hashes == {"hash_tdk", "hash_dark"}


def test_filter_by_status_planned(populated_repos):
    lib_repo = populated_repos["lib_repo"]
    planned = lib_repo.query_library(status="planned")
    hashes = {item["torrent_hash"] for item in planned}
    # Dune is saved in media_collections with list_name='watch_later'
    assert hashes == {"hash_dune"}


def test_series_with_one_watched_episode_is_not_completed(populated_repos):
    lib_repo = populated_repos["lib_repo"]
    completed = lib_repo.query_library(status="completed", media_type="series")
    hashes = {item["torrent_hash"] for item in completed}
    # Dark has 1 of 3 watched -> NOT completed
    assert "hash_dark" not in hashes
    # Better Call Saul has 2 of 2 watched -> is completed
    assert "hash_bcs" in hashes


# ─── 3. Release Year Range Filtering ───


def test_filter_by_year_range(populated_repos):
    lib_repo = populated_repos["lib_repo"]

    # 2010 to 2021 inclusive: Inception (2010), Dark (2017), Dune (2021)
    res = lib_repo.query_library(year_from=2010, year_to=2021)
    hashes = {item["torrent_hash"] for item in res}
    assert hashes == {"hash_inception", "hash_dark", "hash_dune"}

    # year_from only (>= 2021): Dune (2021), Better Call Saul (2022)
    res_from = lib_repo.query_library(year_from=2021)
    hashes_from = {item["torrent_hash"] for item in res_from}
    assert hashes_from == {"hash_dune", "hash_bcs"}

    # year_to only (<= 2010): Kung Fu Hustle (2004), The Dark Knight (2008), Inception (2010)
    res_to = lib_repo.query_library(year_to=2010)
    hashes_to = {item["torrent_hash"] for item in res_to}
    assert hashes_to == {"hash_kungfu", "hash_tdk", "hash_inception"}

    # Exact boundary match
    res_exact = lib_repo.query_library(year_from=2022, year_to=2022)
    assert len(res_exact) == 1
    assert res_exact[0]["torrent_hash"] == "hash_bcs"


# ─── 4. Genre Filtering & Substring Protection ───


def test_filter_by_genre_exact_and_case_insensitive(populated_repos):
    lib_repo = populated_repos["lib_repo"]

    # Exact match: "Action"
    res_action = lib_repo.query_library(genre="action")
    hashes_action = {item["torrent_hash"] for item in res_action}
    assert hashes_action == {"hash_inception", "hash_tdk"}

    # Exact match: "Crime"
    res_crime = lib_repo.query_library(genre="CRIME")
    hashes_crime = {item["torrent_hash"] for item in res_crime}
    assert hashes_crime == {"hash_tdk", "hash_bcs"}


def test_genre_filter_avoids_false_substring_match(populated_repos):
    """'Art' must NOT match 'Martial Arts'."""
    lib_repo = populated_repos["lib_repo"]
    res_art = lib_repo.query_library(genre="Art")
    hashes_art = {item["torrent_hash"] for item in res_art}
    assert "hash_kungfu" not in hashes_art

    # 'Martial Arts' should match
    res_ma = lib_repo.query_library(genre="Martial Arts")
    hashes_ma = {item["torrent_hash"] for item in res_ma}
    assert "hash_kungfu" in hashes_ma


# ─── 5. Combined Filters ───


def test_combined_filters_and_logic(populated_repos):
    lib_repo = populated_repos["lib_repo"]

    # type=movie + status=completed + genre=Sci-Fi: Inception (2010, completed, Sci-Fi)
    res = lib_repo.query_library(
        media_type="movie",
        status="completed",
        genre="Sci-Fi",
    )
    assert len(res) == 1
    assert res[0]["torrent_hash"] == "hash_inception"

    # type=series + year_from=2020: Better Call Saul (2022)
    res_s = lib_repo.query_library(
        media_type="series",
        year_from=2020,
    )
    assert len(res_s) == 1
    assert res_s[0]["torrent_hash"] == "hash_bcs"

    # Conditions that yield 0 results
    res_empty = lib_repo.query_library(
        media_type="series",
        status="planned",
    )
    assert res_empty == []


# ─── 6. Sorting & Deterministic Tie-Breaking ───


def test_sort_by_title_asc_and_desc(populated_repos):
    lib_repo = populated_repos["lib_repo"]

    res_asc = lib_repo.query_library(sort="title", order="asc")
    titles_asc = [r["title"] for r in res_asc]
    assert titles_asc == sorted(titles_asc, key=lambda s: s.lower())

    res_desc = lib_repo.query_library(sort="title", order="desc")
    titles_desc = [r["title"] for r in res_desc]
    assert titles_desc == sorted(titles_desc, key=lambda s: s.lower(), reverse=True)


def test_sort_by_year_asc_and_desc(populated_repos):
    lib_repo = populated_repos["lib_repo"]

    res_asc = lib_repo.query_library(sort="year", order="asc")
    years_asc = [r["year"] for r in res_asc]
    assert years_asc == [2004, 2008, 2010, 2017, 2021, 2022]

    res_desc = lib_repo.query_library(sort="year", order="desc")
    years_desc = [r["year"] for r in res_desc]
    assert years_desc == [2022, 2021, 2017, 2010, 2008, 2004]


def test_sort_by_added_uses_real_addition_date(populated_repos):
    lib_repo = populated_repos["lib_repo"]

    res_desc = lib_repo.query_library(sort="added", order="desc")
    hashes_desc = [r["torrent_hash"] for r in res_desc]
    # Added dates: Dark (Jan 20), Dune (Jan 15), The Dark Knight (Jan 10), BCS (Jan 5), Kung Fu (Jan 2), Inception (Jan 1)
    assert hashes_desc[0] == "hash_dark"
    assert hashes_desc[-1] == "hash_inception"

    res_asc = lib_repo.query_library(sort="added", order="asc")
    hashes_asc = [r["torrent_hash"] for r in res_asc]
    assert hashes_asc[0] == "hash_inception"
    assert hashes_asc[-1] == "hash_dark"


def test_sort_by_progress(populated_repos):
    lib_repo = populated_repos["lib_repo"]

    res_desc = lib_repo.query_library(sort="progress", order="desc")
    # Inception and BCS have 1.0 progress (top)
    top_progresses = [
        round(r["watched_files"] / r["total_files"], 2)
        for r in res_desc[:2]
        if r["total_files"] > 0
    ]
    assert top_progresses == [1.0, 1.0]

    # Dark has 1/3 (0.33)
    dark_item = next(r for r in res_desc if r["torrent_hash"] == "hash_dark")
    assert round(dark_item["watched_files"] / dark_item["total_files"], 2) == 0.33


def test_deterministic_tie_breaking(populated_repos):
    """When multiple items have identical sort values, order must be deterministic via primary key."""
    lib_repo = populated_repos["lib_repo"]
    # Inception and BCS both have 100% progress
    res1 = lib_repo.query_library(sort="progress", order="desc")
    res2 = lib_repo.query_library(sort="progress", order="desc")
    assert [r["torrent_hash"] for r in res1] == [r["torrent_hash"] for r in res2]


# ─── 7. Pagination & Infinite Scroll ───


def test_pagination_limit_and_offset(populated_repos):
    lib_repo = populated_repos["lib_repo"]

    page1 = lib_repo.query_library(sort="title", order="asc", limit=2, offset=0)
    page2 = lib_repo.query_library(sort="title", order="asc", limit=2, offset=2)
    page3 = lib_repo.query_library(sort="title", order="asc", limit=2, offset=4)
    page_empty = lib_repo.query_library(sort="title", order="asc", limit=2, offset=100)

    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 2
    assert len(page_empty) == 0

    all_paginated = (
        [r["torrent_hash"] for r in page1]
        + [r["torrent_hash"] for r in page2]
        + [r["torrent_hash"] for r in page3]
    )
    full_list = [r["torrent_hash"] for r in lib_repo.query_library(sort="title", order="asc")]

    # Verification: no duplicates and no missing items across pages
    assert len(all_paginated) == len(set(all_paginated))
    assert all_paginated == full_list


def test_count_library_reflects_active_filters(populated_repos):
    lib_repo = populated_repos["lib_repo"]

    assert lib_repo.count_library() == 6
    assert lib_repo.count_library(media_type="movie") == 4
    assert lib_repo.count_library(media_type="series") == 2
    assert lib_repo.count_library(genre="Action") == 2
    assert lib_repo.count_library(year_from=2021) == 2
    assert lib_repo.count_library(status="completed") == 2


# ─── 8. N+1 Query Prevention & Batch Processing ───


@pytest.mark.asyncio
async def test_no_n_plus_one_in_library_query(populated_repos):
    """Verify that querying library items executes in a single SQL query without per-item overhead."""
    lib_repo = populated_repos["lib_repo"]
    meta_service = MagicMock()
    service = LibraryService(
        library_repo=lib_repo,
        torrserver_client=AsyncMock(get_torrents=AsyncMock(return_value=[])),
        settings_provider=lambda: "http://127.0.0.1:8090",
        metadata_service=meta_service,
    )

    query_count = 0
    original_connection = lib_repo.connection

    @contextlib.contextmanager
    def tracked_connection():
        with original_connection() as conn:
            def trace_callback(statement):
                nonlocal query_count
                query_count += 1
            conn.set_trace_callback(trace_callback)
            try:
                yield conn
            finally:
                conn.set_trace_callback(None)

    f = LibraryFilter()
    with patch.object(lib_repo, "connection", tracked_connection):
        items = await service.get_filtered_library(f)
        assert len(items) == 6

    # query_library executes in exactly 1 SQL statement
    assert query_count == 1


# ─── 9. FastAPI Validation & HTTP Endpoints ───


def test_api_validation_year_from_greater_than_year_to():
    client = TestClient(app)
    resp = client.get("/api/library?year_from=2024&year_to=2010")
    assert resp.status_code == 422
    assert "year_from cannot be greater than year_to" in resp.text


def test_api_validation_invalid_type():
    client = TestClient(app)
    resp = client.get("/api/library?type=anime")
    assert resp.status_code == 422
    assert "Invalid type" in resp.text


def test_api_validation_invalid_status():
    client = TestClient(app)
    resp = client.get("/api/library?status=bogus_status")
    assert resp.status_code == 422
    assert "Invalid status" in resp.text


def test_api_validation_invalid_sort():
    client = TestClient(app)
    resp = client.get("/api/library?sort=injected_sql_field")
    assert resp.status_code == 422
    assert "Invalid sort" in resp.text


def test_api_validation_invalid_order():
    client = TestClient(app)
    resp = client.get("/api/library?order=sideways")
    assert resp.status_code == 422
    assert "Invalid order" in resp.text


def test_api_endpoints_x_total_count_header(populated_repos):
    client = TestClient(app)
    db = populated_repos["db"]
    lib_repo = populated_repos["lib_repo"]
    service = LibraryService(
        library_repo=lib_repo,
        torrserver_client=AsyncMock(get_torrents=AsyncMock(return_value=[])),
        settings_provider=lambda: "http://127.0.0.1:8090",
        metadata_service=None,
    )

    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_library_service] = lambda: service

    try:
        resp = client.get("/api/library?limit=2&offset=0")
        assert resp.status_code == 200
        assert resp.headers.get("X-Total-Count") == "6"
        data = resp.json()
        assert len(data) == 2

        resp_filtered = client.get("/api/library?type=series&limit=1")
        assert resp_filtered.status_code == 200
        assert resp_filtered.headers.get("X-Total-Count") == "2"
        assert len(resp_filtered.json()) == 1
    finally:
        app.dependency_overrides.pop(get_database, None)
        app.dependency_overrides.pop(get_library_service, None)
