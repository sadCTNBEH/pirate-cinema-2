import logging
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.exceptions import NotFoundError
from backend.infrastructure.catalog.cache import (
    MetadataCache,
    pick_best_poster,
    rank_posters,
)
from backend.infrastructure.catalog.tvmaze import (
    TVmazeProvider,
    clean_search_query,
    strip_html,
)
from backend.infrastructure.catalog.wikidata import WikidataProvider
from backend.models.catalog import Movie, Series
from backend.repositories.db import Database
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.services.metadata import MetadataService


def test_catalog_schemas():
    movie = Movie(
        id="tt1234567",
        title="Тестовый Фильм",
        original_title="Test Movie",
        title_ru="Тестовый Фильм",
        overview="English overview",
        overview_ru="Русское описание фильма",
        genres=["Action", "Sci-Fi"],
        background_url="https://example.com/bg.jpg",
        source="cinemeta+wikidata",
    )
    assert movie.type == "movie"
    assert movie.overview_ru == "Русское описание фильма"
    assert movie.genres == ["Action", "Sci-Fi"]
    assert movie.background_url == "https://example.com/bg.jpg"
    assert movie.source == "cinemeta+wikidata"

    series = Series(
        id="tt7654321",
        title="Тестовый Сериал",
        overview_ru="Описание сериала",
        genres=["Drama"],
        source="tvmaze",
    )
    assert series.type == "series"
    assert series.source == "tvmaze"


def test_poster_ranking():
    posters = [
        "https://example.com/poster_thumb_small.jpg",
        "https://example.com/poster_en_medium.jpg",
        "https://example.com/poster_ru_1080p.jpg",
        "https://example.com/poster_original_untouched.jpg",
    ]
    ranked = rank_posters(posters, preferred_lang="ru")
    # Russian 1080p poster gets highest priority: language match (+50) + high res (+30)
    assert ranked[0] == "https://example.com/poster_ru_1080p.jpg"
    assert (
        pick_best_poster(posters, preferred_lang="ru")
        == "https://example.com/poster_ru_1080p.jpg"
    )

    # English preference
    ranked_en = rank_posters(posters, preferred_lang="en")
    assert ranked_en[0] in (
        "https://example.com/poster_original_untouched.jpg",
        "https://example.com/poster_en_medium.jpg",
    )


def test_tvmaze_html_stripping():
    html = "<p>Walter White is a <b>chemistry</b> teacher &amp; criminal.</p>"
    clean = strip_html(html)
    assert clean == "Walter White is a chemistry teacher &amp; criminal."


def test_tvmaze_search_query_cleanup():
    assert clean_search_query("День разоблачения") == "День разоблачения"
    assert clean_search_query("Унабомбер / Unabomber") == "Unabomber"
    assert (
        clean_search_query(
            "Unabomber (2026) UHD WEB-DL 2160p | 4K | HDR10 | Dolby Vision P8 | D | Movie Dubbing"
        )
        == "Unabomber"
    )


@pytest.mark.anyio
async def test_offline_cache_hit_on_repeated_request():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        meta_repo = MetadataRepository(db=db)
        lib_repo = LibraryRepository(db=db)
        cache = MetadataCache(
            metadata_repo=meta_repo, posters_dir=Path(tmp_dir) / "posters"
        )

        mock_cinemeta = MagicMock()
        mock_cinemeta.lookup = AsyncMock(
            return_value={
                "id": "tt0903747",
                "title": "Breaking Bad",
                "original_title": "Breaking Bad",
                "year": 2008,
                "rating": 9.5,
                "poster_url": "https://example.com/bb.jpg",
                "background_url": "https://example.com/bb_bg.jpg",
                "overview": "A chemistry teacher diagnosed with cancer...",
                "genres": ["Crime", "Drama"],
                "source": "cinemeta",
                "type": "series",
                "videos": [],
            }
        )

        mock_tvmaze = MagicMock()
        mock_tvmaze.lookup = AsyncMock(return_value=None)

        mock_wikidata = MagicMock()
        mock_wikidata.lookup_by_imdb = AsyncMock(
            return_value={
                "title_ru": "Во все тяжкие",
                "overview_ru": "Американская криминальная драма",
            }
        )

        service = MetadataService(
            metadata_repo=meta_repo,
            library_repo=lib_repo,
            cache=cache,
            cinemeta_provider=mock_cinemeta,
            tvmaze_provider=mock_tvmaze,
            wikidata_provider=mock_wikidata,
        )

        # 1. First request: calls network providers and merges RU label
        meta1 = await service.movie_meta("tt0903747", "series")
        assert meta1["title"] == "Во все тяжкие"  # RU label prioritized
        assert meta1["title_ru"] == "Во все тяжкие"
        assert meta1["overview_ru"] == "Американская криминальная драма"
        assert meta1["original_title"] == "Breaking Bad"
        assert mock_cinemeta.lookup.call_count == 1
        assert mock_wikidata.lookup_by_imdb.call_count == 1

        # 2. Second request: offline cache hit!
        meta2 = await service.movie_meta("tt0903747", "series")
        assert meta2["title"] == "Во все тяжкие"
        assert meta2["title_ru"] == "Во все тяжкие"
        # Network calls should NOT increase
        assert mock_cinemeta.lookup.call_count == 1
        assert mock_wikidata.lookup_by_imdb.call_count == 1

        # Check that cache persisted in SQLite repository
        cached_db = meta_repo.get_cached_metadata("meta:series:ru:tt0903747")
        assert cached_db is not None
        assert cached_db["title_ru"] == "Во все тяжкие"


@pytest.mark.anyio
async def test_tvmaze_fallback_when_cinemeta_missing():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        meta_repo = MetadataRepository(db=db)
        lib_repo = LibraryRepository(db=db)
        cache = MetadataCache(
            metadata_repo=meta_repo, posters_dir=Path(tmp_dir) / "posters"
        )

        # Cinemeta returns None (e.g. unknown or not indexed in Cinemeta)
        mock_cinemeta = MagicMock()
        mock_cinemeta.lookup = AsyncMock(return_value=None)

        # TVmaze returns valid series data
        mock_tvmaze = MagicMock()
        mock_tvmaze.lookup = AsyncMock(
            return_value={
                "id": "tt1234567",
                "title": "Severance",
                "original_title": "Severance",
                "year": 2022,
                "rating": 8.7,
                "poster_url": "https://example.com/severance.jpg",
                "background_url": None,
                "overview": "Mark leads a team of office workers...",
                "overview_ru": None,
                "genres": ["Drama", "Sci-Fi", "Thriller"],
                "source": "tvmaze",
                "type": "series",
                "videos": [
                    {
                        "id": "tt1234567:1:1",
                        "title": "Good News About Hell",
                        "season": 1,
                        "episode": 1,
                    }
                ],
            }
        )

        mock_wikidata = MagicMock()
        mock_wikidata.lookup_by_imdb = AsyncMock(
            return_value={
                "title_ru": "Разделение",
                "overview_ru": "Американский научно-фантастический сериал",
            }
        )

        service = MetadataService(
            metadata_repo=meta_repo,
            library_repo=lib_repo,
            cache=cache,
            cinemeta_provider=mock_cinemeta,
            tvmaze_provider=mock_tvmaze,
            wikidata_provider=mock_wikidata,
        )

        meta = await service.movie_meta("tt1234567", "series")
        # Verified fallback to TVmaze + Wikidata RU label enrichment
        assert meta is not None
        assert meta["title"] == "Разделение"
        assert meta["title_ru"] == "Разделение"
        assert meta["overview_ru"] == "Американский научно-фантастический сериал"
        assert meta["genres"] == ["Drama", "Sci-Fi", "Thriller"]
        assert len(meta["videos"]) == 1
        assert "tvmaze" in meta["source"]


@pytest.mark.anyio
async def test_wikidata_provider_mock():
    mock_client = MagicMock()
    # Mock query search (haswbstatement)
    mock_search_resp = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"query": {"search": [{"title": "Q1079"}]}}),
    )
    # Mock wbgetentities
    mock_entity_resp = MagicMock(
        status_code=200,
        json=MagicMock(
            return_value={
                "entities": {
                    "Q1079": {
                        "labels": {
                            "ru": {"value": "Во все тяжкие"},
                            "en": {"value": "Breaking Bad"},
                        },
                        "descriptions": {
                            "ru": {"value": "криминальная драма"},
                            "en": {"value": "crime drama"},
                        },
                    }
                }
            }
        ),
    )
    mock_client.get = AsyncMock(side_effect=[mock_search_resp, mock_entity_resp])
    mock_client.is_closed = False

    provider = WikidataProvider(client=mock_client)
    res = await provider.lookup_by_imdb("tt0903747")

    assert res is not None
    assert res["wikidata_id"] == "Q1079"
    assert res["title_ru"] == "Во все тяжкие"
    assert res["overview_ru"] == "криминальная драма"


@pytest.mark.anyio
async def test_wikidata_batch_uses_post_and_parses_sparql():
    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_resp = MagicMock(
        json=MagicMock(
            return_value={
                "results": {
                    "bindings": [
                        {
                            "id": {"value": "tt0903747"},
                            "label": {"value": "Во все тяжкие"},
                            "description": {"value": "криминальная драма"},
                            "image": {
                                "value": "http://commons.wikimedia.org/breaking-bad.jpg"
                            },
                        }
                    ]
                }
            }
        )
    )
    mock_resp.raise_for_status = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    provider = WikidataProvider(client=mock_client)
    res = await provider.lookup_batch_imdb(["tt0903747"])

    assert res["tt0903747"]["title_ru"] == "Во все тяжкие"
    assert res["tt0903747"]["overview_ru"] == "криминальная драма"
    assert res["tt0903747"]["image_url"].startswith("https://")
    mock_client.post.assert_awaited_once()
    _, kwargs = mock_client.post.await_args
    assert "data" in kwargs
    assert "query" in kwargs["data"]


@pytest.mark.anyio
async def test_wikidata_batch_logs_empty_httpx_errors(caplog):
    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.post = AsyncMock(side_effect=httpx.ReadTimeout(""))

    provider = WikidataProvider(client=mock_client)
    provider.lookup_by_imdb = AsyncMock(return_value=None)

    caplog.set_level(logging.WARNING)
    res = await provider.lookup_batch_imdb(["tt0903747"])

    assert res == {}
    assert "Wikidata SPARQL batch failed: ReadTimeout" in caplog.text
    assert "Wikidata SPARQL batch failed: ;" not in caplog.text


@pytest.mark.anyio
async def test_tvmaze_provider_mock():
    mock_client = MagicMock()
    show_payload = {
        "id": 169,
        "name": "Breaking Bad",
        "premiered": "2008-01-20",
        "rating": {"average": 9.2},
        "genres": ["Drama", "Crime"],
        "summary": "<p>A high school chemistry teacher...</p>",
        "image": {
            "original": "https://static.tvmaze.com/original.jpg",
            "medium": "https://static.tvmaze.com/medium.jpg",
        },
        "externals": {"imdb": "tt0903747"},
    }
    episodes_payload = [
        {
            "id": 1,
            "name": "Pilot",
            "season": 1,
            "number": 1,
            "airdate": "2008-01-20",
            "summary": "<p>Pilot episode summary</p>",
        }
    ]

    resp_show = MagicMock(status_code=200, json=MagicMock(return_value=show_payload))
    resp_ep = MagicMock(status_code=200, json=MagicMock(return_value=episodes_payload))
    mock_client.get = AsyncMock(side_effect=[resp_show, resp_ep])
    mock_client.is_closed = False

    provider = TVmazeProvider(client=mock_client)
    res = await provider.lookup("tt0903747")

    assert res is not None
    assert res["title"] == "Breaking Bad"
    assert res["year"] == 2008
    assert res["rating"] == 9.2
    assert res["overview"] == "A high school chemistry teacher..."
    assert res["poster_url"] == "https://static.tvmaze.com/original.jpg"
    assert len(res["videos"]) == 1
    assert res["videos"][0]["id"] == "tt0903747:1:1"
    assert res["videos"][0]["title"] == "Pilot"


@pytest.mark.anyio
async def test_graceful_degradation_on_provider_failures():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        meta_repo = MetadataRepository(db=db)
        lib_repo = LibraryRepository(db=db)

        # Cinemeta fails with timeout
        mock_cinemeta = MagicMock()
        mock_cinemeta.lookup = AsyncMock(
            side_effect=httpx.ConnectTimeout("Cinemeta down")
        )

        # TVmaze fails with HTTP 500
        mock_tvmaze = MagicMock()
        mock_tvmaze.lookup = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "500", request=None, response=MagicMock(status_code=500)
            )
        )

        service = MetadataService(
            metadata_repo=meta_repo,
            library_repo=lib_repo,
            cinemeta_provider=mock_cinemeta,
            tvmaze_provider=mock_tvmaze,
        )

        with pytest.raises(NotFoundError):
            await service.movie_meta("tt9999999", "movie")


@pytest.mark.anyio
async def test_library_service_torrent_files_with_title():
    from backend.services.library import LibraryService

    mock_torrserver = MagicMock()
    mock_torrserver.torrent_video_files = AsyncMock(
        return_value=[{"id": 1, "name": "S01E01.mkv"}]
    )
    mock_meta_service = MagicMock()
    lib_repo = MagicMock()
    lib_repo.get_file_history_map = MagicMock(return_value={})

    lib_service = LibraryService(
        library_repo=lib_repo,
        torrserver_client=mock_torrserver,
        settings_provider=lambda: "http://localhost:8090",
        metadata_service=mock_meta_service,
    )

    res = await lib_service.get_torrent_files_structure("hash123", title="Breaking Bad")
    assert res["type"] == "series"
    assert "1" in res["seasons"]
    mock_meta_service.trigger_metadata_fetch.assert_called_once_with(
        "hash123", "Breaking Bad"
    )


@pytest.mark.anyio
async def test_tvmaze_search_composite_query():
    captured_params = {}

    class MockClient:
        is_closed = False

        async def get(self, url, params=None):
            nonlocal captured_params
            captured_params = params
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = [
                {
                    "show": {
                        "id": 1234,
                        "name": "Manhunt: Unabomber",
                        "premiered": "2017-08-01",
                        "genres": ["Crime", "Drama"],
                        "summary": "<p>FBI hunt.</p>",
                        "externals": {"imdb": "tt5618256"},
                    }
                }
            ]
            resp.raise_for_status = MagicMock()
            return resp

        async def aclose(self):
            self.is_closed = True

    provider = TVmazeProvider(client=MockClient())
    results = await provider.search("Унабомбер / Unabomber")
    assert captured_params.get("q") == "Unabomber"
    assert len(results) == 1
    assert results[0]["id"] == "tt5618256"


@pytest.mark.anyio
async def test_tvmaze_search_logs_empty_httpx_errors(caplog):
    class MockClient:
        is_closed = False

        async def get(self, url, params=None):
            raise httpx.ReadTimeout("")

        async def aclose(self):
            self.is_closed = True

    provider = TVmazeProvider(client=MockClient())
    caplog.set_level(logging.WARNING)
    results = await provider.search(
        "Unabomber (2026) UHD WEB-DL 2160p | 4K | HDR10 | Dolby Vision P8 | D | Movie Dubbing"
    )

    assert results == []
    assert "TVmaze search error for query 'Unabomber': ReadTimeout" in caplog.text
    assert "TVmaze search error for query 'Unabomber': " in caplog.text


@pytest.mark.anyio
async def test_torrserver_get_torrents(monkeypatch):
    from backend.infrastructure.torrserver import client as ts_client

    class MockResponse:
        def __init__(self, data, status_code=200):
            self._data = data
            self.status_code = status_code

        def json(self):
            return self._data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("error", request=None, response=self)

    class MockClient:
        async def post(self, url, json=None, timeout=None):
            if json and json.get("action") == "list":
                return MockResponse(
                    [
                        {
                            "hash": "0123456789abcdef0123456789abcdef01234567",
                            "title": "Test Release",
                            "poster": "http://p.jpg",
                        }
                    ]
                )
            return MockResponse([])

    monkeypatch.setattr(ts_client, "get_client", lambda: MockClient())

    torrents = await ts_client.get_torrents("http://localhost:8090")
    assert len(torrents) == 1
    assert torrents[0]["hash"] == "0123456789abcdef0123456789abcdef01234567"
    assert torrents[0]["title"] == "Test Release"


def test_cache_ttl_and_purge():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        meta_repo = MetadataRepository(db=db)
        cache = MetadataCache(
            metadata_repo=meta_repo,
            posters_dir=Path(tmp_dir) / "posters",
            default_ttl=1,
        )

        cache.set("meta:ttl_test", {"title": "TTL Item"})

        # Immediate check within TTL -> Hit
        assert cache.get("meta:ttl_test") is not None

        # Expired check (simulating max_age_seconds=0) -> Miss
        assert cache.get("meta:ttl_test", max_age_seconds=0) is None

        # Purge expired
        purged = meta_repo.purge_expired_cache(max_age_seconds=0)
        assert purged >= 0


def test_russian_poster_domain_scoring():
    from backend.infrastructure.catalog.cache import score_poster_url

    ru_kinopoisk = "https://avatars.mds.yandex.net/get-kinopoisk-image/1900592/poster.jpg"
    ru_domain = "https://st.kp.yandex.net/images/film_iphone/iphone360_435.ru.jpg"
    en_poster = "https://image.tmdb.org/t/p/w500/en_poster.jpg"
    thumb_poster = "https://example.com/thumb.jpg"

    score_kp = score_poster_url(ru_kinopoisk, preferred_lang="ru")
    score_ru = score_poster_url(ru_domain, preferred_lang="ru")
    score_en = score_poster_url(en_poster, preferred_lang="ru")
    score_thumb = score_poster_url(thumb_poster, preferred_lang="ru")

    # Russian sources should outscore generic EN and thumb
    assert score_kp > score_en
    assert score_ru > score_en
    assert score_en > score_thumb
