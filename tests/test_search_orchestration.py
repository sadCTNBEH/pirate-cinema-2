import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.infrastructure.search.base import SearchProviderError
from backend.infrastructure.search.cache import SearchCache
from backend.infrastructure.search.rutor import RuTorTorrServerProvider
from backend.infrastructure.search.torznab import TorznabProvider
from backend.models.search import SearchResult, TorznabConfig
from backend.services.search import SearchService


@pytest.fixture
def anyio_backend():
    return "asyncio"


def provider(name="test", results=None):
    mock = MagicMock()
    mock.name = name
    mock.search = AsyncMock(return_value=results if results is not None else [])
    return mock


@pytest.mark.anyio
@pytest.mark.parametrize("overall,individual", [(0.03, 1), (1, 0.03)])
async def test_timeout_keeps_completed_and_cleans_up(overall, individual):
    stopped = asyncio.Event()

    async def hang(query):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    slow = provider("slow")
    slow.search = hang
    fast = provider(results=[SearchResult(title="Movie")])
    service = SearchService(
        providers=[slow, fast], search_timeout=overall, provider_timeout=individual
    )
    assert [r.title for r in await service.search_torrents("Movie")] == ["Movie"]
    assert stopped.is_set()
    assert not service._inflight
    assert not service._waiters


@pytest.mark.anyio
async def test_multilingual_queries_deduplicate_and_limit_load():
    active = peak = 0
    queries = []

    async def search(query):
        nonlocal active, peak
        queries.append(query)
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return [
            SearchResult(title=query, infohash="same"),
            SearchResult(title=query + " 1080p", infohash=query),
        ]

    p = provider()
    p.search = search
    service = SearchService(providers=[p], concurrency_limit=2)
    titles = [
        " начало ",
        "Inception",
        "INCEPTION",
        "夢",
        "",
        "Extra",
        "More",
        "Last",
        "Ignored",
    ]
    results = await service.search_torrents("Начало", titles=titles)
    assert len(queries) == 6
    assert queries[:3] == ["Начало", "Inception", "夢"]
    assert len(results) == 7
    assert peak == 2
    await service.search_torrents("Начало", titles=titles)
    assert len(queries) == 6


@pytest.mark.anyio
async def test_single_flight_and_cancelled_waiter():
    started, release = asyncio.Event(), asyncio.Event()

    async def search(query):
        started.set()
        await release.wait()
        return [SearchResult(title="Movie")]

    p = provider()
    p.search = AsyncMock(side_effect=search)
    service = SearchService(providers=[p])
    first = asyncio.create_task(service.search_torrents("Movie"))
    await started.wait()
    second = asyncio.create_task(service.search_torrents("Movie"))
    while not service._waiters or max(service._waiters.values()) < 2:
        await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert len(await second) == 1
    assert p.search.await_count == 1
    await service.search_torrents("Movie")
    assert p.search.await_count == 1
    assert not service._inflight


@pytest.mark.anyio
async def test_ttl_empty_ttl_errors_and_bounds(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(
        "backend.infrastructure.search.cache.time.monotonic", lambda: now[0]
    )
    cache = SearchCache(max_entries=2, max_results=2)
    p = provider(results=[SearchResult(title="Movie")])
    service = SearchService(providers=[p], cache=cache)
    await service.search_torrents("Movie")
    now[0] += 299
    await service.search_torrents("Movie")
    assert p.search.await_count == 1
    now[0] += 2
    await service.search_torrents("Movie")
    assert p.search.await_count == 2
    p.search.return_value = []
    await service.search_torrents("empty")
    now[0] += 21
    await service.search_torrents("empty")
    assert p.search.await_count == 4
    p.search.side_effect = SearchProviderError("private URL")
    await service.search_torrents("error")
    await service.search_torrents("error")
    assert p.search.await_count == 6
    cache.set("a", [SearchResult(title="a")])
    cache.set("b", [SearchResult(title="b")])
    cache.set("c", [SearchResult(title="c")])
    assert len(cache._entries) == 2
    assert cache.get("a") is None
    now[0] += 301
    cache.prune()
    assert not cache._entries


@pytest.mark.anyio
async def test_settings_invalidate_source_cache(monkeypatch):
    cfg = TorznabConfig(enabled=True, url="http://index/api", api_key="one")
    search = AsyncMock(return_value=[SearchResult(title="Movie")])
    monkeypatch.setattr(TorznabProvider, "search", search)
    service = SearchService(torznab_config_provider=lambda: cfg)
    await service.search_torrents("Movie")
    await service.search_torrents("Movie")
    assert search.await_count == 1
    cfg.api_key = "two"
    await service.search_torrents("Movie")
    cfg.categories = [5000]
    await service.search_torrents("Movie")
    cfg.url = "http://other/api"
    await service.search_torrents("Movie")
    assert search.await_count == 4
    cfg.enabled = False
    assert await service.search_torrents("Movie") == []
    endpoint = ["http://rutor-one"]
    client = MagicMock()
    client.search_torrserver = AsyncMock(return_value=[])
    rutor = RuTorTorrServerProvider(client, lambda: endpoint[0])
    service = SearchService(providers=[rutor])
    await service.search_torrents("Movie")
    endpoint[0] = "http://rutor-two"
    await service.search_torrents("Movie")
    assert client.search_torrserver.await_count == 2


@pytest.mark.anyio
async def test_private_links_preserved_only_in_memory_and_logs_redacted(
    caplog, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    secret = "TOP_SECRET_PASSKEY"
    magnet = f"magnet:?xt=urn:btih:{'a' * 40}&tr=https://tracker/{secret}/announce"
    xml = f"<rss><channel><item><title>Movie</title><link>{magnet.replace('&', '&amp;')}</link></item></channel></rss>"
    calls = []

    async def respond(request):
        calls.append(request)
        return httpx.Response(200, text=xml)

    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            p = TorznabProvider(
                TorznabConfig(
                    enabled=True, url=f"https://index/{secret}/api", api_key=secret
                ),
                http_client=client,
            )
            service = SearchService(providers=[p])
            first = await service.search_torrents("Movie")
            first[0].magnet = "mutated"
            assert (await service.search_torrents("Movie"))[0].magnet == magnet
            assert len(calls) == 1
            assert secret not in repr(list(service._cache._entries))
    assert secret not in caplog.text
    assert not list(tmp_path.iterdir())


@pytest.mark.anyio
@pytest.mark.parametrize(
    "body,status",
    [
        ("", 200),
        ("<broken>", 200),
        ('<error description="SECRET"/>', 200),
        ("<html/>", 200),
        ("", 403),
    ],
)
async def test_source_errors_not_cached_as_empty(body, status, caplog):
    client = MagicMock(is_closed=False)
    client.get = AsyncMock(return_value=httpx.Response(status, text=body))
    p = TorznabProvider(
        TorznabConfig(enabled=True, url="https://index/api"),
        http_client=client,
        max_retries=0,
    )
    service = SearchService(providers=[p])
    assert await service.search_torrents("Movie") == []
    assert await service.search_torrents("Movie") == []
    assert client.get.await_count == 2
    assert "SECRET" not in caplog.text


@pytest.mark.anyio
async def test_season_episode_and_release_filters_are_preserved():
    item = SearchResult(
        title="Show S02E03 1080p HDR RUS Dub",
        seeders=30,
        size=2 * 1024**3,
        source="RuTor",
    )
    p = provider(results=[item])
    service = SearchService(providers=[p])
    filters = {
        "quality": "1080p",
        "min_seeders": 20,
        "hdr": "hdr",
        "voiceover": "dub",
        "language": "russian",
        "min_size": 1024**3,
        "max_size": 3 * 1024**3,
        "source": "rutor",
    }
    results = await service.search_torrents(
        "Show S02E03", titles=["Сериал сезон 2 серия 3"], **filters
    )
    assert len(results) == 1
    assert [call.args[0] for call in p.search.await_args_list] == [
        "Show S02E03",
        "Сериал сезон 2 серия 3",
    ]
    await service.search_torrents(
        "Show S02E03", titles=["Сериал сезон 2 серия 3"], **filters
    )
    assert p.search.await_count == 2
    assert not await service.search_torrents(
        "Show S02E03", **{**filters, "quality": "2160p"}
    )
    assert p.search.await_count == 3


@pytest.mark.anyio
async def test_rutor_transport_failure_is_not_cached_or_logged(caplog, monkeypatch):
    from backend.infrastructure.torrserver import client as torrserver

    secret = "SECRET_RUTOR_PASSKEY"

    async def fail(request):
        raise httpx.ConnectError(f"https://private/{secret}", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        monkeypatch.setattr(torrserver, "get_client", lambda: client)
        p = RuTorTorrServerProvider(torrserver, lambda: f"https://host/{secret}")
        service = SearchService(providers=[p])
        for _ in range(2):
            assert await service.search_torrents("Movie") == []
        assert not service._cache._entries
    assert secret not in caplog.text


@pytest.mark.anyio
async def test_source_configuration_failure_does_not_discard_other_results():
    def broken_config():
        raise ValueError("private source configuration")

    broken = RuTorTorrServerProvider(MagicMock(), broken_config)
    fast = provider(results=[SearchResult(title="Movie")])
    service = SearchService(providers=[broken, fast])
    assert len(await service.search_torrents("Movie")) == 1


def test_api_accepts_bounded_title_variants_and_keeps_list_response():
    from fastapi.testclient import TestClient

    from backend.api import deps
    from backend.app import app

    p = provider(results=[SearchResult(title="Movie", infohash="same")])
    service = SearchService(providers=[p])
    app.dependency_overrides[deps.get_search_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.get(
            "/api/search", params=[("q", "Фильм"), ("titles", "Movie")]
        )
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert p.search.await_count == 2
        assert (
            client.get(
                "/api/search",
                params=[("q", "Movie"), *[("titles", str(i)) for i in range(6)]],
            ).status_code
            == 422
        )
    finally:
        client.close()
        app.dependency_overrides.pop(deps.get_search_service, None)
