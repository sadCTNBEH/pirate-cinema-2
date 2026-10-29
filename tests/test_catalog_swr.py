import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.exceptions import ExternalServiceError
from backend.infrastructure.catalog import enrich
from backend.infrastructure.catalog.cache import MetadataCache
from backend.repositories.db import Database
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.services.metadata import MetadataService


@pytest.fixture
def service(tmp_path):
    db = Database(tmp_path / "test.sqlite")
    db.init_db()
    provider = MagicMock()
    provider.lookup = AsyncMock(return_value={"id": "tt123", "title": "New", "type": "movie"})
    wiki = MagicMock()
    wiki.lookup_by_imdb = AsyncMock(return_value=None)
    result = MetadataService(MetadataRepository(db), LibraryRepository(db),
                             posters_dir=tmp_path, cinemeta_provider=provider,
                             tvmaze_provider=MagicMock(lookup=AsyncMock(return_value=None)),
                             wikidata_provider=wiki)
    return result


def seed(service, age, key="meta:tt123"):
    service.cache.set(key, {"id": "tt123", "title": "Old"})
    service.cache._mem_cache.clear()
    with service._metadata_repo.connection() as conn:
        conn.execute("UPDATE offline_metadata_cache SET created_at=datetime('now', ?) WHERE cache_key=?",
                     (f"-{age} days", key))


@pytest.mark.asyncio
async def test_fresh_metadata_never_calls_provider(service):
    seed(service, 1)
    assert (await service.movie_meta("tt123"))["title"] == "Old"
    service._cinemeta.lookup.assert_not_called()


@pytest.mark.asyncio
async def test_stale_is_immediate_then_replaced_singleflight(service):
    seed(service, 8)
    entered, release = asyncio.Event(), asyncio.Event()

    async def fetch(*args):
        entered.set()
        await release.wait()
        return {"id": "tt123", "title": "New"}

    service._cinemeta.lookup.side_effect = fetch
    assert (await service.movie_meta("tt123"))["title"] == "Old"
    await entered.wait()
    assert (await service.movie_meta("tt123"))["title"] == "Old"
    waiting = asyncio.create_task(service.movie_meta("tt123", refresh=True))
    await asyncio.sleep(0)
    assert not waiting.done()
    release.set()
    assert (await waiting)["title"] == "New"
    assert (await service.movie_meta("tt123"))["title"] == "New"
    assert service._cinemeta.lookup.call_count == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_network_failure_keeps_old_metadata_and_cools_down(service):
    seed(service, 8)
    service._cinemeta.lookup.side_effect = httpx.ConnectError("offline")
    assert (await service.movie_meta("tt123"))["title"] == "Old"
    await asyncio.gather(*service._background_tasks, return_exceptions=True)
    assert (await service.movie_meta("tt123"))["title"] == "Old"
    with pytest.raises(ExternalServiceError):
        await service.movie_meta("tt123", refresh=True)
    assert service._cinemeta.lookup.call_count == 1
    assert service.cache.get("meta:tt123", 30 * 86400)["title"] == "Old"


@pytest.mark.asyncio
async def test_cold_requests_join_and_languages_types_do_not_mix(service):
    first, second = await asyncio.gather(service.movie_meta("tt123"), service.movie_meta("tt123"))
    assert first == second
    assert first["title"] == "New"
    assert service._cinemeta.lookup.call_count == 1
    await service.movie_meta("tt123", language="en")
    await service.movie_meta("tt123", media_type="series")
    await service.movie_meta("tt456")
    assert service._cinemeta.lookup.call_count == 4


def test_disk_reads_do_not_extend_freshness_and_memory_is_bounded(service):
    seed(service, 8)
    cache = MetadataCache(service._metadata_repo)
    assert cache.get("meta:tt123", 30 * 86400)
    assert cache.get("meta:tt123") is None
    for index in range(80):
        cache.set(str(index), {"title": str(index)})
    assert len(cache._mem_cache) <= 64
    cache.set("oversized", {"title": "x" * 300000})
    assert cache.get("oversized") is None


@pytest.mark.asyncio
async def test_catalog_stale_updates_once_and_language_is_separate(tmp_path, monkeypatch):
    cache_file = tmp_path / "popular.json"
    cache_file.write_text(json.dumps({"updated_at": time.time() - 2 * 86400,
                                     "items": [{"id": "tt123", "title": "Old"}]}))
    provider = MagicMock()
    entered, release = asyncio.Event(), asyncio.Event()

    async def fetch():
        entered.set()
        await release.wait()
        return [{"id": "tt123", "title": "New"}]

    provider.popular = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(enrich, "enrich_catalog", AsyncMock(side_effect=lambda items, provider: items))
    monkeypatch.setattr(enrich, "download_catalog_posters", AsyncMock())
    args = {"cinemeta_provider": provider, "cache_dir": tmp_path, "posters_dir": tmp_path}
    assert (await enrich.get_popular_movies(**args, background=True))[0]["title"] == "Old"
    await entered.wait()
    assert (await enrich.get_popular_movies(**args, background=True))[0]["title"] == "Old"
    pending = asyncio.create_task(enrich.get_popular_movies(**args, wait_for_refresh=True))
    release.set()
    assert (await pending)[0]["title"] == "New"
    await enrich.get_popular_movies(**args)
    assert provider.popular.call_count == 1
    await enrich.get_popular_movies(**args, language="en")
    assert provider.popular.call_count == 2
    assert (tmp_path / "popular-en.json").is_file()


@pytest.mark.asyncio
async def test_catalog_error_does_not_replace_or_renew_stale(tmp_path):
    cache_file = tmp_path / "popular.json"
    payload = {"updated_at": time.time() - 2 * 86400, "items": [{"id": "tt123", "title": "Old"}]}
    cache_file.write_text(json.dumps(payload))
    provider = MagicMock(popular=AsyncMock(side_effect=httpx.ConnectError("offline")))
    with pytest.raises(httpx.RequestError):
        await enrich.get_popular_movies(cinemeta_provider=provider, cache_dir=tmp_path,
                                       posters_dir=tmp_path, wait_for_refresh=True)
    assert json.loads(cache_file.read_text()) == payload
    payload["updated_at"] = time.time() - 8 * 86400
    cache_file.write_text(json.dumps(payload))
    assert enrich.load_stale_catalog_cache(cache_file) is None


@pytest.mark.asyncio
async def test_cold_catalog_returns_before_poster_enrichment(tmp_path, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def enrich_later(items, provider):
        entered.set()
        await release.wait()
        return [{**item, "title_ru": "Localized"} for item in items]

    monkeypatch.setattr(enrich, "enrich_catalog", enrich_later)
    monkeypatch.setattr(enrich, "download_catalog_posters", AsyncMock())
    provider = MagicMock(popular=AsyncMock(return_value=[{"id": "tt123", "title": "Raw"}]))
    args = {"cinemeta_provider": provider, "cache_dir": tmp_path, "posters_dir": tmp_path}
    first = await asyncio.wait_for(enrich.get_popular_movies(**args, background=True), 1)
    assert first[0]["title"] == "Raw"
    await entered.wait()
    # Raw data is usable but is not marked fresh until enrichment finishes.
    assert enrich.load_catalog_cache(tmp_path / "popular.json") is None
    waiting = asyncio.create_task(enrich.get_popular_movies(**args, wait_for_refresh=True))
    await asyncio.sleep(0)
    assert not waiting.done()
    release.set()
    assert (await waiting)[0]["title_ru"] == "Localized"
    assert provider.popular.call_count == 1


@pytest.mark.asyncio
async def test_legacy_series_cache_is_read_without_mixing_type(service):
    service.cache.set("meta:tt123", {"id": "tt123", "type": "series", "title": "Series cache"})
    assert (await service.movie_meta("tt123", "series"))["title"] == "Series cache"
    service._cinemeta.lookup.assert_not_called()
    assert (await service.movie_meta("tt123", "movie"))["title"] == "New"
    assert service._cinemeta.lookup.call_count == 1


@pytest.mark.asyncio
async def test_http_stale_header_and_waiting_refresh(service):
    from backend.api import deps
    from backend.app import app

    seed(service, 8)
    entered, release = asyncio.Event(), asyncio.Event()

    async def fetch(*args):
        entered.set()
        await release.wait()
        return {"id": "tt123", "title": "New"}

    service._cinemeta.lookup.side_effect = fetch
    previous = app.dependency_overrides.get(deps.get_metadata_service)
    app.dependency_overrides[deps.get_metadata_service] = lambda: service
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/library/meta/tt123?lang=ru&type=movie")
            assert response.json()["title"] == "Old"
            assert response.headers["X-Catalog-Stale"] == "1"
            assert int(response.headers["X-Catalog-Age"]) >= 8 * 86400
            await entered.wait()
            waiting = asyncio.create_task(client.get("/api/library/meta/tt123?lang=ru&type=movie&refresh=true"))
            release.set()
            response = await waiting
            assert response.json()["title"] == "New"
            assert response.headers["X-Catalog-Stale"] == "0"
    finally:
        if previous is None:
            app.dependency_overrides.pop(deps.get_metadata_service, None)
        else:
            app.dependency_overrides[deps.get_metadata_service] = previous
        await service.shutdown()


def test_persistent_cache_has_retention_count_and_byte_limits(service):
    with service._metadata_repo.connection() as conn:
        conn.executemany("INSERT INTO offline_metadata_cache(cache_key,data_json,created_at) VALUES(?,?,CURRENT_TIMESTAMP)",
                         [(f"entry-{index}", '{"title":"x"}') for index in range(1005)])
        conn.execute("INSERT INTO offline_metadata_cache(cache_key,data_json,created_at) VALUES('expired','{}',datetime('now','-31 days'))")
    service.cache.set("latest", {"title": "Keep"})
    with service._metadata_repo.connection() as conn:
        count, size = conn.execute("SELECT count(*),sum(length(data_json)) FROM offline_metadata_cache").fetchone()
        assert count <= 1000
        assert size <= 8388608
        assert conn.execute("SELECT 1 FROM offline_metadata_cache WHERE cache_key='expired'").fetchone() is None
    assert service.cache.get("latest")["title"] == "Keep"
