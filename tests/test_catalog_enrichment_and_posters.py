import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.testclient import TestClient

from backend.app import app
from backend.infrastructure.catalog.enrich import (
    FALLBACK_POPULAR_MOVIES,
    FALLBACK_POPULAR_SERIES,
    download_catalog_posters,
    enrich_catalog,
    get_popular_movies,
    get_popular_series,
    is_valid_imdb,
    load_catalog_cache,
    load_stale_catalog_cache,
    make_thumbnail,
    save_catalog_cache,
)
from backend.infrastructure.catalog.wikidata import WikidataProvider


def test_is_valid_imdb():
    assert is_valid_imdb("tt0111161") is True
    assert is_valid_imdb("tt1") is True
    assert is_valid_imdb("tt123456789012") is True
    assert is_valid_imdb("tt1234567890123") is False  # 13 digits
    assert is_valid_imdb("0111161") is False
    assert is_valid_imdb("invalid") is False
    assert is_valid_imdb("") is False
    assert is_valid_imdb(None) is False
    assert is_valid_imdb("../tt0111161") is False


@pytest.mark.asyncio
async def test_enrich_catalog_merge_rules():
    items = [
        {
            "id": "tt0111161",
            "title": "The Shawshank Redemption",
            "original_title": "The Shawshank Redemption",
            "year": 1994,
            "rating": 9.3,
            "poster_url": "https://example.com/shawshank.jpg",
            "overview": "English description of Shawshank",
            "genres": ["Drama"],
        },
        {
            "id": "tt0068646",
            "title": "The Godfather",
            "original_title": "The Godfather",
            "year": 1972,
            "rating": 9.2,
            "poster_url": None,
            "overview": "English description of Godfather",
            "genres": ["Crime", "Drama"],
        },
    ]

    mock_wikidata = MagicMock(spec=WikidataProvider)
    mock_wikidata.lookup_batch_imdb = AsyncMock(
        return_value={
            "tt0111161": {
                "id": "tt0111161",
                "title_ru": "Побег из Шоушенка",
                "overview_ru": "Русское описание Побега",
                "image_url": "https://commons.wikimedia.org/shawshank.jpg",
            },
            "tt0068646": {
                "id": "tt0068646",
                "title_ru": "Крёстный отец",
                "overview_ru": "Русское описание Крёстного отца",
                "image_url": "https://commons.wikimedia.org/godfather.jpg",
            },
        }
    )

    with patch(
        "backend.infrastructure.catalog.enrich.fetch_wikipedia_summaries",
        new=AsyncMock(return_value={}),
    ):
        enriched = await enrich_catalog(items, wikidata_provider=mock_wikidata)

    assert len(enriched) == 2

    # 1. English title and original_title preserved
    assert enriched[0]["title"] == "The Shawshank Redemption"
    assert enriched[0]["original_title"] == "The Shawshank Redemption"
    # 2. Russian title and overview set from Wikidata
    assert enriched[0]["title_ru"] == "Побег из Шоушенка"
    assert enriched[0]["overview_ru"] == "Русское описание Побега"
    # 3. English overview preserved
    assert enriched[0]["overview"] == "English description of Shawshank"
    # 4. Poster preserved if already present
    assert enriched[0]["poster_url"] == "https://example.com/shawshank.jpg"

    # Second item: poster_url was None, so wikidata image fills it
    assert enriched[1]["title_ru"] == "Крёстный отец"
    assert enriched[1]["poster_url"] == "https://commons.wikimedia.org/godfather.jpg"


@pytest.mark.asyncio
async def test_enrich_catalog_wikipedia_overview():
    items = [
        {
            "id": "tt0111161",
            "title": "The Shawshank Redemption",
            "overview": "Short English overview",
        }
    ]

    mock_wikidata = MagicMock(spec=WikidataProvider)
    mock_wikidata.lookup_batch_imdb = AsyncMock(
        return_value={
            "tt0111161": {
                "id": "tt0111161",
                "title_ru": "Побег из Шоушенка",
                "overview_ru": "фильм 1994 года",  # short stub from Wikidata
            }
        }
    )

    with patch(
        "backend.infrastructure.catalog.enrich.fetch_wikipedia_summaries",
        new=AsyncMock(
            return_value={
                "tt0111161": {
                    "extract": "Полное подробное описание фильма из русской Википедии на несколько предложений.",
                    "poster_url": "https://upload.wikimedia.org/poster.jpg",
                }
            }
        ),
    ):
        enriched = await enrich_catalog(items, wikidata_provider=mock_wikidata)

    assert len(enriched) == 1
    assert enriched[0]["title_ru"] == "Побег из Шоушенка"
    # Wikipedia extract replaces short stub
    assert "Полное подробное описание фильма" in enriched[0]["overview_ru"]
    assert enriched[0]["_wp_image"] == "https://upload.wikimedia.org/poster.jpg"


@pytest.mark.asyncio
async def test_enrich_catalog_partial_wikidata_failure():
    items = [
        {
            "id": "tt0111161",
            "title": "The Shawshank Redemption",
            "original_title": "The Shawshank Redemption",
            "overview": "English description",
        }
    ]

    mock_wikidata = MagicMock(spec=WikidataProvider)
    mock_wikidata.lookup_batch_imdb = AsyncMock(side_effect=RuntimeError("SPARQL down"))

    # Errors in Wikidata must not fail the catalog
    enriched = await enrich_catalog(items, wikidata_provider=mock_wikidata)
    assert len(enriched) == 1
    assert enriched[0]["title"] == "The Shawshank Redemption"
    assert enriched[0]["overview"] == "English description"
    assert enriched[0].get("title_ru") is None


def test_disk_cache_load_and_save():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cache_file = tmp_path / "popular.json"
        posters_dir = tmp_path / "posters" / "catalog"
        posters_dir.mkdir(parents=True, exist_ok=True)

        # Create dummy local poster file
        dummy_poster = posters_dir / "tt0111161.jpg"
        dummy_poster.write_bytes(b"dummy image bytes")

        items = [
            {
                "id": "tt0111161",
                "title": "The Shawshank Redemption",
                "title_ru": "Побег из Шоушенка",
            },
            {
                "id": "tt0068646",
                "title": "The Godfather",
                "title_ru": "Крёстный отец",
            },
        ]

        # 1. Save cache
        save_catalog_cache(cache_file, items)
        assert cache_file.is_file()

        # 2. Fresh cache hit (< TTL)
        loaded = load_catalog_cache(cache_file, ttl_seconds=3600, posters_dir=posters_dir)
        assert loaded is not None
        assert len(loaded) == 2
        # Verify poster_local_url is resolved for existing file
        assert loaded[0]["poster_local_url"] == "/api/posters/catalog/tt0111161.jpg"
        # No local file for tt0068646
        assert loaded[1]["poster_local_url"] is None

        # 3. Expired cache (TTL = -1) returns None
        expired = load_catalog_cache(cache_file, ttl_seconds=-1, posters_dir=posters_dir)
        assert expired is None

        # 4. Stale cache reader returns items even if expired
        stale = load_stale_catalog_cache(cache_file, posters_dir=posters_dir)
        assert stale is not None
        assert len(stale) == 2


@pytest.mark.asyncio
async def test_download_catalog_posters():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        posters_dir = tmp_path / "posters" / "catalog"

        items = [
            {
                "id": "tt0111161",
                "title": "The Shawshank Redemption",
                "poster_url": "https://example.com/poster1.jpg",
            },
            {
                "id": "tt0068646",
                "title": "The Godfather",
                "poster_url": "https://example.com/fail.jpg",
            },
        ]

        async def mock_handler(request: httpx.Request):
            if "poster1.jpg" in str(request.url):
                return httpx.Response(
                    200,
                    content=b"\xff\xd8\xff" + b"A" * 500,  # valid jpeg bytes
                    headers={"content-type": "image/jpeg"},
                )
            return httpx.Response(404, text="Not Found")

        transport = httpx.MockTransport(mock_handler)
        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
            await download_catalog_posters(items, target_dir=posters_dir)

        # tt0111161 succeeded
        saved_file = posters_dir / "tt0111161.jpg"
        assert saved_file.is_file()
        assert items[0]["poster_local_url"] == "/api/posters/catalog/tt0111161.jpg"

        # tt0068646 failed (404) -> file not saved, poster_local_url is None, no crash
        assert not (posters_dir / "tt0068646.jpg").is_file()
        assert items[1]["poster_local_url"] is None


@pytest.mark.asyncio
async def test_get_popular_movies_lifecycle():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cache_dir = tmp_path / "catalog"
        posters_dir = tmp_path / "posters" / "catalog"

        mock_cinemeta = MagicMock()
        mock_cinemeta.popular = AsyncMock(
            return_value=[
                {
                    "id": "tt0111161",
                    "title": "The Shawshank Redemption",
                    "original_title": "The Shawshank Redemption",
                    "poster_url": None,
                    "overview": "English overview",
                }
            ]
        )

        mock_wikidata = MagicMock(spec=WikidataProvider)
        mock_wikidata.lookup_batch_imdb = AsyncMock(
            return_value={
                "tt0111161": {
                    "id": "tt0111161",
                    "title_ru": "Побег из Шоушенка",
                    "overview_ru": "Русское описание",
                    "image_url": None,
                }
            }
        )

        # 1. First fetch -> cache created and returned
        res1 = await get_popular_movies(
            cinemeta_provider=mock_cinemeta,
            wikidata_provider=mock_wikidata,
            cache_dir=cache_dir,
            posters_dir=posters_dir,
            ttl_seconds=3600,
        )
        assert len(res1) == 1
        assert res1[0]["title_ru"] == "Побег из Шоушенка"
        assert (cache_dir / "popular.json").is_file()

        # 2. Second fetch within TTL -> served from cache without calling Cinemeta again
        mock_cinemeta.popular.reset_mock()
        res2 = await get_popular_movies(
            cinemeta_provider=mock_cinemeta,
            wikidata_provider=mock_wikidata,
            cache_dir=cache_dir,
            posters_dir=posters_dir,
            ttl_seconds=3600,
        )
        assert len(res2) == 1
        assert res2[0]["title_ru"] == "Побег из Шоушенка"
        mock_cinemeta.popular.assert_not_called()

        # 3. Cinemeta fails but stale cache exists -> served from stale cache
        mock_cinemeta.popular = AsyncMock(side_effect=Exception("Network dead"))
        res3 = await get_popular_movies(
            cinemeta_provider=mock_cinemeta,
            wikidata_provider=mock_wikidata,
            cache_dir=cache_dir,
            posters_dir=posters_dir,
            ttl_seconds=-1,  # force expired cache
        )
        assert len(res3) == 1
        assert res3[0]["title_ru"] == "Побег из Шоушенка"

        # 4. Cinemeta fails and no cache exists -> hardcoded fallback returned
        (cache_dir / "popular.json").unlink()
        res4 = await get_popular_movies(
            cinemeta_provider=mock_cinemeta,
            wikidata_provider=mock_wikidata,
            cache_dir=cache_dir,
            posters_dir=posters_dir,
            ttl_seconds=3600,
        )
        assert len(res4) == len(FALLBACK_POPULAR_MOVIES)
        assert res4[0]["id"] == "tt0111161"
        assert res4[0]["title_ru"] == "Побег из Шоушенка"


@pytest.mark.asyncio
async def test_get_popular_series_lifecycle():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cache_dir = tmp_path / "catalog"
        posters_dir = tmp_path / "posters" / "catalog"

        mock_cinemeta = MagicMock()
        mock_cinemeta.popular_series = AsyncMock(side_effect=Exception("Cinemeta offline"))

        # No cache exists -> fallback series list returned
        res = await get_popular_series(
            cinemeta_provider=mock_cinemeta,
            cache_dir=cache_dir,
            posters_dir=posters_dir,
        )
        assert len(res) == len(FALLBACK_POPULAR_SERIES)
        assert res[0]["id"] == "tt0903747"
        assert res[0]["title_ru"] == "Во все тяжкие"


def test_posters_api_endpoints():
    client = TestClient(app)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        catalog_posters_dir = tmp_path / "posters" / "catalog"
        catalog_posters_dir.mkdir(parents=True, exist_ok=True)

        # Write test poster file
        test_poster = catalog_posters_dir / "tt0111161.jpg"
        test_poster.write_bytes(b"\xff\xd8\xff\xe0" + b"JPEG_DATA")

        with patch(
            "backend.api.routers.posters.get_catalog_posters_dir",
            return_value=catalog_posters_dir,
        ):
            # 1. Valid existing poster -> 200 + image/jpeg + Cache-Control
            res = client.get("/api/posters/catalog/tt0111161.jpg")
            assert res.status_code == 200
            assert "image/jpeg" in res.headers.get("content-type", "")
            assert "max-age=86400" in res.headers.get("cache-control", "")
            assert res.content == b"\xff\xd8\xff\xe0JPEG_DATA"

            # Direct route without /api
            res_direct = client.get("/posters/catalog/tt0111161.jpg")
            assert res_direct.status_code == 200

            # 2. Non-existent valid IMDb ID -> 404
            res_404 = client.get("/api/posters/catalog/tt9999999.jpg")
            assert res_404.status_code == 404

            # 3. Invalid IMDb format (not tt...) -> 404
            res_invalid = client.get("/api/posters/catalog/movie123.jpg")
            assert res_invalid.status_code == 404

            # 4. Path traversal attempt -> 404
            res_traversal = client.get("/api/posters/catalog/..%2F..%2Fetc.jpg")
            assert res_traversal.status_code in (404, 422)


def test_popular_api_router_integration():
    client = TestClient(app)

    # Calling popular movies endpoint returns list of media items
    res_movies = client.get("/api/library/popular")
    assert res_movies.status_code == 200
    movies = res_movies.json()
    assert isinstance(movies, list)
    assert len(movies) > 0
    first_movie = movies[0]
    assert "id" in first_movie
    assert "title" in first_movie
    assert "title_ru" in first_movie

    # Calling popular series endpoint returns list of media items
    res_series = client.get("/api/library/popular/series")
    assert res_series.status_code == 200
    series = res_series.json()
    assert isinstance(series, list)
    assert len(series) > 0
    first_series = series[0]
    assert "id" in first_series
    assert "title" in first_series
    assert "title_ru" in first_series


def test_make_thumbnail_resizing():
    import io

    from PIL import Image

    # Generate a large 1200x1800 test image in memory
    img = Image.new("RGB", (1200, 1800), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    large_bytes = buf.getvalue()

    thumb_bytes = make_thumbnail(large_bytes, max_width=380, max_height=570, quality=82)

    with Image.open(io.BytesIO(thumb_bytes)) as thumb_img:
        assert thumb_img.width <= 380
        assert thumb_img.height <= 570
        assert thumb_img.width == 380


def test_poster_etag_and_304_caching():
    client = TestClient(app)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        catalog_posters_dir = tmp_path / "posters" / "catalog"
        catalog_posters_dir.mkdir(parents=True, exist_ok=True)

        test_poster = catalog_posters_dir / "tt0111161.jpg"
        test_poster.write_bytes(b"\xff\xd8\xff\xe0" + b"TEST_IMAGE")

        with patch(
            "backend.api.routers.posters.get_catalog_posters_dir",
            return_value=catalog_posters_dir,
        ):
            # First request -> 200 with ETag header
            res1 = client.get("/api/posters/catalog/tt0111161.jpg")
            assert res1.status_code == 200
            etag = res1.headers.get("etag")
            assert etag is not None

            # Conditional request with matching ETag -> 304 Not Modified
            res2 = client.get(
                "/api/posters/catalog/tt0111161.jpg",
                headers={"If-None-Match": etag},
            )
            assert res2.status_code == 304


@pytest.mark.asyncio
async def test_get_popular_movies_background_mode():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cache_dir = tmp_path / "catalog"
        posters_dir = tmp_path / "posters" / "catalog"

        mock_cinemeta = MagicMock()
        mock_cinemeta.popular = AsyncMock(
            return_value=[
                {
                    "id": "tt0111161",
                    "title": "The Shawshank Redemption",
                    "poster_url": "https://example.com/shawshank.jpg",
                }
            ]
        )

        mock_wikidata = MagicMock(spec=WikidataProvider)
        mock_wikidata.lookup_batch_imdb = AsyncMock(return_value={})

        # Call with background=True: returns Cinemeta items immediately without blocking
        res = await get_popular_movies(
            cinemeta_provider=mock_cinemeta,
            wikidata_provider=mock_wikidata,
            cache_dir=cache_dir,
            posters_dir=posters_dir,
            background=True,
        )
        assert len(res) == 1
        assert res[0]["title"] == "The Shawshank Redemption"
        # Background task was scheduled, wait briefly for completion
        await asyncio.sleep(0.1)




@pytest.mark.asyncio
async def test_cinemeta_search_metadata_quotes_query():
    from backend.infrastructure.catalog import cinemeta

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"metas": []}
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch.object(cinemeta, "_get", return_value=mock_client):
        res = await cinemeta.search_metadata("Игра престолов", "series")
        assert res == []
        mock_client.get.assert_awaited_once()
        requested_url = mock_client.get.await_args[0][0]
        # Query must be URL-quoted, not raw Cyrillic
        assert "search=%D0%98%D0%B3%D1%80%D0%B0%20%D0%BF%D1%80%D0%B5%D1%81%D1%82%D0%BE%D0%BB%D0%BE%D0%B2.json" in requested_url


@pytest.mark.asyncio
async def test_torrserver_video_files_parses_windows_backslashes():
    from backend.infrastructure.torrserver import client

    mock_resp1 = MagicMock()
    mock_resp1.text = "ok"
    mock_resp1.json.return_value = {
        "data": "{\"TorrServer\":{\"Files\":[{\"id\":1,\"path\":\"Season 1\\\\Episode 01.mkv\",\"length\":1000}]}}"
    }
    mock_resp1.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp1)

    with patch.object(client, "get_client", return_value=mock_client):
        files = await client.torrent_video_files("http://localhost:8090", "1111222233334444555566667777888899990000")
        assert len(files) == 1
        assert files[0]["name"] == "Episode 01.mkv"
        assert files[0]["id"] == 1

    mock_resp2 = MagicMock()
    mock_resp2.text = "ok"
    mock_resp2.json.return_value = {
        "file_stats": [
            {"id": 2, "path": "Season 2\\Episode 05.mp4", "length": 2000}
        ]
    }
    mock_resp2.raise_for_status = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp2)

    with patch.object(client, "get_client", return_value=mock_client):
        files2 = await client.torrent_video_files("http://localhost:8090", "1111222233334444555566667777888899990002")
        assert len(files2) == 1
        assert files2[0]["name"] == "Episode 05.mp4"
        assert files2[0]["id"] == 2
