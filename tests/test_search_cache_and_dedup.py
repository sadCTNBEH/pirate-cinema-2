"""Tests for G-010 Part 2: Caching, SWR, and Deduplication."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.schemas.online import OnlineSearchResult
from backend.models.search import SearchResult
from backend.services.online.providers.base import OnlineProvider
from backend.services.online.service import (
    OnlineService,
)
from backend.services.search import (
    SearchService,
    SearchSWRCache,
    deduplicate_results_by_hash_title_year,
    extract_release_year,
    normalize_title_for_dedup,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def mock_search_provider(name="tracker", results=None):
    prov = MagicMock()
    prov.name = name
    prov.search = AsyncMock(return_value=results if results is not None else [])
    prov.health_check = AsyncMock(return_value=True)
    return prov


# ─── SearchSWRCache & SearchService TTL / SWR Tests ───


@pytest.mark.anyio
async def test_swr_cache_fresh_hit_skips_provider():
    """Verify fresh queries are served immediately from LRU cache without hitting providers."""
    p = mock_search_provider("tracker-1", results=[SearchResult(title="Gladiator 2000 1080p")])
    swr_cache = SearchSWRCache(ttl=60.0, stale_ttl=120.0, max_entries=10)
    service = SearchService(providers=[p], swr_cache=swr_cache)

    res1 = await service.search_torrents("Gladiator")
    assert len(res1) == 1
    assert res1[0].title == "Gladiator 2000 1080p"
    assert p.search.await_count == 1

    # Second call within TTL hits fresh cache
    res2 = await service.search_torrents("Gladiator")
    assert len(res2) == 1
    assert res2[0].title == "Gladiator 2000 1080p"
    assert p.search.await_count == 1  # Not called again


@pytest.mark.anyio
async def test_swr_cache_stale_serves_cached_and_revalidates():
    """Verify stale queries return stale cached results and trigger background revalidation."""
    initial_item = SearchResult(title="Dune 2021 v1", seeders=10)
    updated_item = SearchResult(title="Dune 2021 v2", seeders=50)

    p = mock_search_provider("tracker-1", results=[initial_item])
    # Short TTL for testing: fresh for 0.05s, stale up to 2.0s
    swr_cache = SearchSWRCache(ttl=0.05, stale_ttl=2.0, max_entries=10)
    service = SearchService(providers=[p], swr_cache=swr_cache)

    # 1. First fetch
    first_results = await service.search_torrents("Dune")
    assert first_results[0].title == "Dune 2021 v1"
    assert p.search.await_count == 1

    # 2. Wait until fresh TTL expires, entering stale window
    await asyncio.sleep(0.08)
    p.search.return_value = [updated_item]

    # 3. Second fetch: should return stale v1 immediately, while triggering background refresh
    stale_results = await service.search_torrents("Dune")
    assert stale_results[0].title == "Dune 2021 v1"

    # 4. Allow background revalidation task to finish
    await asyncio.sleep(0.05)
    assert p.search.await_count == 2

    # 5. Subsequent fetch gets the revalidated v2 result
    fresh_results = await service.search_torrents("Dune")
    assert fresh_results[0].title == "Dune 2021 v2"


@pytest.mark.anyio
async def test_swr_cache_lru_eviction_bounded_ram():
    """Verify LRU cache evicts oldest entries when max_entries limit is reached."""
    swr_cache = SearchSWRCache(ttl=60.0, max_entries=2)
    swr_cache.set("key1", [SearchResult(title="Movie 1")])
    swr_cache.set("key2", [SearchResult(title="Movie 2")])
    assert len(swr_cache) == 2

    # Access key1 to make it most recently used
    items, _ = swr_cache.get("key1")
    assert items[0].title == "Movie 1"

    # Insert key3: should evict key2 (least recently used)
    swr_cache.set("key3", [SearchResult(title="Movie 3")])
    assert len(swr_cache) == 2

    key2_val, _ = swr_cache.get("key2")
    assert key2_val is None  # Evicted

    key1_val, _ = swr_cache.get("key1")
    assert key1_val is not None
    key3_val, _ = swr_cache.get("key3")
    assert key3_val is not None


# ─── Deduplication by Hash / Title / Year Tests ───


def test_extract_release_year_and_normalize_title():
    assert extract_release_year("The Matrix (1999) 1080p") == 1999
    assert extract_release_year("Oppenheimer 2023 BDRip") == 2023
    assert extract_release_year("Movie Without Year") is None

    norm1 = normalize_title_for_dedup("Начало / Inception (2010) BDRip 1080p")
    norm2 = normalize_title_for_dedup("Inception / Начало 2010 WEB-DL 720p")
    assert norm1 == norm2


def test_deduplicate_by_infohash():
    """Verify torrents with identical infohash are merged, retaining highest score and complementary fields."""
    r1 = SearchResult(
        title="Avatar 2009 1080p",
        infohash="abc1234567890abcdef1234567890abcdef1234",
        seeders=15,
        size=5000000,
        score=20.0,
        source="TrackerA",
    )
    r2 = SearchResult(
        title="Avatar 2009 BluRay",
        infohash="abc1234567890abcdef1234567890abcdef1234",
        seeders=45,
        size=None,
        magnet="magnet:?xt=urn:btih:abc1234567890abcdef1234567890abcdef1234",
        score=35.0,
        source="TrackerB",
    )

    deduped = deduplicate_results_by_hash_title_year([r1, r2])
    assert len(deduped) == 1
    item = deduped[0]
    assert item.score == 35.0
    assert item.seeders == 45
    assert item.size == 5000000  # Merged from r1
    assert item.magnet is not None  # Preserved from r2


def test_deduplicate_by_title_and_year():
    """Verify non-hash torrent releases with identical normalized title and year are merged."""
    r1 = SearchResult(
        title="Интерстеллар / Interstellar (2014) BDRip 1080p",
        infohash=None,
        seeders=10,
        size=2 * 1024**3,
        score=25.0,
        source="TrackerA",
    )
    r2 = SearchResult(
        title="Interstellar / Интерстеллар (2014) WEB-DL 720p",
        infohash=None,
        seeders=30,
        size=3 * 1024**3,
        score=40.0,
        source="TrackerB",
    )

    deduped = deduplicate_results_by_hash_title_year([r1, r2])
    assert len(deduped) == 1
    assert deduped[0].score == 40.0
    assert deduped[0].seeders == 30


def test_different_years_are_not_deduplicated():
    """Verify items with same title but different release years are kept distinct."""
    r1 = SearchResult(title="Blade Runner (1982) 1080p", score=30.0)
    r2 = SearchResult(title="Blade Runner (2049) 1080p", score=40.0)

    deduped = deduplicate_results_by_hash_title_year([r1, r2])
    assert len(deduped) == 2


# ─── OnlineService Caching, Parallelism & Deduplication Tests ───


class MockOnlineProvider(OnlineProvider):
    def __init__(
        self, name: str, results: list[OnlineSearchResult] | None = None, delay: float = 0.0
    ):
        self._name = name
        self._results = results or []
        self._delay = delay
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    async def search(self, query: str) -> list[OnlineSearchResult]:
        self.call_count += 1
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        return list(self._results)

    async def get_metadata(self, video_id: str) -> OnlineSearchResult:
        return (
            self._results[0]
            if self._results
            else OnlineSearchResult(id=video_id, title="", provider=self.name)
        )

    async def resolve_stream(self, video_id: str, quality: str | None = None):
        raise NotImplementedError

    async def get_qualities(self, video_id: str) -> list[str]:
        return ["1080p", "720p"]


@pytest.mark.anyio
async def test_online_service_caching():
    """Verify OnlineService caches search queries and avoids redundant network calls."""
    res = [OnlineSearchResult(id="vid1", title="Nature Documentary 2023", provider="rutube")]
    p = MockOnlineProvider("rutube", results=res)
    service = OnlineService(providers=[p])

    # First call
    out1 = await service.search("Nature")
    assert len(out1) == 1
    assert p.call_count == 1

    # Second call should hit in-memory cache
    out2 = await service.search("Nature")
    assert len(out2) == 1
    assert p.call_count == 1


@pytest.mark.anyio
async def test_online_service_deduplication():
    """Verify OnlineService deduplicates cross-provider identical movies by title and year."""
    p1_results = [
        OnlineSearchResult(
            id="rt_123",
            title="Чебурашка (2023)",
            provider="rutube",
            duration=6400,
            thumbnail=None,
        )
    ]
    p2_results = [
        OnlineSearchResult(
            id="other_456",
            title="Чебурашка 2023",
            provider="other",
            duration=None,
            thumbnail="https://example.com/poster.jpg",
        )
    ]

    p1 = MockOnlineProvider("rutube", results=p1_results)
    p2 = MockOnlineProvider("other", results=p2_results)

    service = OnlineService(providers=[p1, p2])
    merged = await service.search("Чебурашка")

    assert len(merged) == 1
    item = merged[0]
    assert item.duration == 6400  # Preserved from p1
    assert item.thumbnail == "https://example.com/poster.jpg"  # Merged from p2


@pytest.mark.anyio
async def test_online_service_parallel_execution_and_timeout_isolation():
    """Verify OnlineService runs providers in parallel and isolates slow/failing providers."""
    fast_results = [OnlineSearchResult(id="fast_1", title="Fast Video", provider="fast_p")]
    fast_provider = MockOnlineProvider("fast_p", results=fast_results, delay=0.01)

    # Slow provider that exceeds provider_timeout
    slow_provider = MockOnlineProvider("slow_p", results=[], delay=5.0)

    service = OnlineService(
        providers=[fast_provider, slow_provider],
        provider_timeout=0.05,
        search_timeout=0.5,
    )

    t0 = time.monotonic()
    results = await service.search("Video")
    elapsed = time.monotonic() - t0

    assert len(results) == 1
    assert results[0].id == "fast_1"
    assert elapsed < 0.3  # Did not block for 5 seconds
