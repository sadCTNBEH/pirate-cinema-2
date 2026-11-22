"""Online service managing video providers and operations."""

import asyncio
import logging
import re
import time
from collections import OrderedDict
from collections.abc import Sequence

from backend.api.schemas.online import OnlineSearchResult
from backend.exceptions import NotFoundError
from backend.services.online.providers.base import OnlineProvider, StreamInfo
from backend.services.online.providers.generic import GenericHLSProvider
from backend.services.online.providers.rutube import RutubeProvider

logger = logging.getLogger(__name__)


def extract_year(title: str) -> int | None:
    """Extract release year (1900-2099) from title string."""
    if not title:
        return None
    match = re.search(r"\b(19\d{2}|20\d{2})\b", title)
    return int(match.group(1)) if match else None


def normalize_title(title: str) -> str:
    """Normalize title for cross-source matching."""
    if not title:
        return ""
    clean = re.sub(r"\b(19\d{2}|20\d{2})\b", " ", title)
    clean = re.sub(r"[^\w\s]", " ", clean.lower())
    tokens = sorted(t for t in clean.split() if len(t) > 1 or t.isalnum())
    return " ".join(tokens) or clean.strip().lower()


def deduplicate_online_results(
    results: list[OnlineSearchResult],
) -> list[OnlineSearchResult]:
    """Deduplicate online video/movie search results by provider/id and normalized title/year."""
    seen_ids: set[tuple[str, str]] = set()
    seen_title_year: dict[tuple[str, int | None], OnlineSearchResult] = {}

    for item in results:
        id_key = (item.provider.lower(), item.id.strip())
        if id_key in seen_ids:
            continue
        seen_ids.add(id_key)

        year = extract_year(item.title)
        title_key = normalize_title(item.title)
        ty_key = (title_key, year)

        if ty_key in seen_title_year:
            existing = seen_title_year[ty_key]
            # Merge complementary fields (thumbnail, duration)
            if not existing.thumbnail and item.thumbnail:
                existing.thumbnail = item.thumbnail
            if (existing.duration is None or existing.duration <= 0) and item.duration:
                existing.duration = item.duration
        else:
            seen_title_year[ty_key] = item

    return list(seen_title_year.values())


class OnlineSearchCache:
    """Bounded In-Memory LRU cache for online search results."""

    def __init__(self, ttl: float = 300.0, max_entries: int = 128):
        self.ttl = ttl
        self.max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, list[OnlineSearchResult]]] = OrderedDict()

    def get(self, key: str) -> list[OnlineSearchResult] | None:
        now = time.monotonic()
        if key not in self._entries:
            return None
        created_at, items = self._entries[key]
        if now - created_at >= self.ttl:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return [item.model_copy(deep=True) for item in items]

    def set(self, key: str, results: list[OnlineSearchResult]) -> None:
        if self.max_entries <= 0:
            return
        now = time.monotonic()
        self._entries[key] = (now, [item.model_copy(deep=True) for item in results])
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


class OnlineService:
    def __init__(
        self,
        providers: Sequence[OnlineProvider] | None = None,
        cache: OnlineSearchCache | None = None,
        search_timeout: float = 10.0,
        provider_timeout: float = 8.0,
    ):
        self._search_timeout = search_timeout
        self._provider_timeout = provider_timeout
        self._cache = cache if cache is not None else OnlineSearchCache(ttl=300.0, max_entries=128)
        if providers is not None:
            self._providers = {p.name: p for p in providers}
        else:
            from backend.services.online.providers.animego import AnimegoProvider

            animego = AnimegoProvider()
            rutube = RutubeProvider()
            direct = GenericHLSProvider()
            self._providers = {
                rutube.name: rutube,
                animego.name: animego,
                direct.name: direct,
            }

    def register_provider(self, provider: OnlineProvider) -> None:
        self._providers[provider.name] = provider

    def get_provider(self, name: str) -> OnlineProvider:
        prov = self._providers.get(name)
        if not prov:
            raise NotFoundError(f"Онлайн-провайдер '{name}' не поддерживается")
        return prov

    async def search(self, query: str, provider: str | None = None) -> list[OnlineSearchResult]:
        stripped = query.strip()
        if not stripped:
            return []

        cache_key = f"{provider or '*'}:{stripped.casefold()}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        if provider:
            p = self.get_provider(provider)
            results = await p.search(stripped)
            deduped = deduplicate_online_results(results)
            self._cache.set(cache_key, deduped)
            return deduped

        # Check if query is direct URL
        if stripped.startswith(("http://", "https://")):
            # If Rutube URL, search specifically in Rutube
            if "rutube.ru" in stripped:
                p = self.get_provider("rutube")
                results = await p.search(stripped)
                deduped = deduplicate_online_results(results)
                self._cache.set(cache_key, deduped)
                return deduped
            # Otherwise check direct stream
            direct_p = self.get_provider("direct")
            res = await direct_p.search(stripped)
            if res:
                self._cache.set(cache_key, res)
                return res

        # Aggregate across search-supporting providers in parallel with timeout
        searchable = [p for p in self._providers.values() if p.supports_search]

        async def _query_provider(p: OnlineProvider) -> list[OnlineSearchResult]:
            return await asyncio.wait_for(p.search(stripped), timeout=self._provider_timeout)

        tasks = [asyncio.create_task(_query_provider(p)) for p in searchable]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self._search_timeout,
            )
        except asyncio.TimeoutError:
            results = []
            for t in tasks:
                if t.done() and not t.cancelled():
                    try:
                        results.append(t.result())
                    except BaseException as exc:
                        results.append(exc)
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        aggregated: list[OnlineSearchResult] = []
        for outcome in results:
            if isinstance(outcome, BaseException):
                logger.warning("Online search provider error: %s", type(outcome).__name__)
                continue
            if isinstance(outcome, list):
                aggregated.extend(outcome)

        deduped = deduplicate_online_results(aggregated)
        self._cache.set(cache_key, deduped)
        return deduped

    async def get_metadata(self, provider: str, item_id: str) -> OnlineSearchResult:
        p = self.get_provider(provider)
        return await p.get_metadata(item_id)

    async def resolve_stream(
        self, provider: str, item_id: str, quality: str | None = None
    ) -> StreamInfo:
        p = self.get_provider(provider)
        return await p.resolve_stream(item_id, quality=quality)

    async def get_qualities(self, provider: str, item_id: str) -> list[str]:
        p = self.get_provider(provider)
        return await p.get_qualities(item_id)

    async def health_check_providers(self) -> dict[str, bool]:
        """Check health of registered online providers in parallel."""

        async def _check(p: OnlineProvider) -> tuple[str, bool]:
            try:
                healthy = await asyncio.wait_for(p.health_check(), timeout=self._provider_timeout)
                return p.name, bool(healthy)
            except Exception as exc:
                logger.warning(
                    "Online provider %s health check failed: %s",
                    p.name,
                    type(exc).__name__,
                )
                return p.name, False

        tasks = [_check(p) for p in self._providers.values()]
        if not tasks:
            return {}
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            name: is_healthy
            for item in results
            if isinstance(item, tuple)
            for name, is_healthy in [item]
        }

    async def health_check(self) -> bool:
        """Check if at least one online provider is healthy."""
        if not self._providers:
            return True
        statuses = await self.health_check_providers()
        return any(statuses.values())

    async def close(self) -> None:
        for p in self._providers.values():
            await p.close()
