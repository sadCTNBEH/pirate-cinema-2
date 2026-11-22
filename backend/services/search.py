import asyncio
import hashlib
import inspect
import json
import logging
import re
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from backend.infrastructure.search.base import (
    SearchProvider,
    extract_quality,
    matches_release_filters,
    rank_results,
)
from backend.infrastructure.search.cache import SearchCache, time as cache_time
from backend.infrastructure.search.rutor import RuTorTorrServerProvider
from backend.infrastructure.search.torznab import TorznabProvider
from backend.models.search import SearchResult, TorznabConfig

logger = logging.getLogger(__name__)


def extract_release_year(title: str) -> int | None:
    """Extract 4-digit release year (1900-2099) from title string."""
    if not title:
        return None
    match = re.search(r"\b(19\d{2}|20\d{2})\b", title)
    return int(match.group(1)) if match else None


def normalize_title_for_dedup(title: str) -> str:
    """Normalize title for cross-source matching."""
    if not title:
        return ""
    # Strip year
    clean = re.sub(r"\b(19\d{2}|20\d{2})\b", " ", title)
    # Strip common technical/quality/codec tokens
    clean = re.sub(
        r"\b(2160p|4k|uhd|1080p|1080i|fhd|720p|hd|480p|576p|sd|"
        r"bdrip|bluray|blu-ray|remux|web-?dl|web-?rip|dvdrip|dvd|camrip|ts|tc|"
        r"hdr10?\+?|dovi|dv|dolby\s*vision|rus|eng|dub|sub)\b",
        " ",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"[^\w\s]", " ", clean.lower())
    tokens = sorted(t for t in clean.split() if len(t) > 1 or t.isalnum())
    return " ".join(tokens) or clean.strip().lower()


def deduplicate_results_by_hash_title_year(
    results: list[SearchResult],
) -> list[SearchResult]:
    """Deduplicate torrent results across sources prioritizing infohash, falling back to title and year.

    When duplicates are encountered, retains the entry with the highest score
    and merges complementary attributes like seeders, size, magnet, and quality.
    """
    seen_hashes: dict[str, SearchResult] = {}
    no_hash_items: list[SearchResult] = []

    def _merge(best: SearchResult, other: SearchResult) -> SearchResult:
        merged = best.model_copy(deep=True)
        if merged.size is None and other.size is not None:
            merged.size = other.size
        if other.seeders is not None:
            merged.seeders = max(merged.seeders or 0, other.seeders)
        if not merged.magnet and other.magnet:
            merged.magnet = other.magnet
        if not merged.quality and other.quality:
            merged.quality = other.quality
        if not merged.published_at and other.published_at:
            merged.published_at = other.published_at
        return merged

    # 1. Deduplicate by infohash
    for item in results:
        h = (item.infohash or "").strip().lower()
        if h:
            if h in seen_hashes:
                existing = seen_hashes[h]
                if item.score > existing.score:
                    seen_hashes[h] = _merge(item, existing)
                else:
                    seen_hashes[h] = _merge(existing, item)
            else:
                seen_hashes[h] = item
        else:
            no_hash_items.append(item)

    # 2. Build index of hashed items by (normalized_title, year)
    seen_title_year: dict[tuple[str, int | None], SearchResult] = {}
    for item in seen_hashes.values():
        year = extract_release_year(item.title)
        norm_title = normalize_title_for_dedup(item.title)
        if norm_title:
            key = (norm_title, year)
            if key not in seen_title_year or item.score > seen_title_year[key].score:
                seen_title_year[key] = item

    # 3. Deduplicate non-hash items against hashed items and among themselves
    deduped_no_hash: dict[tuple[str, int | None], SearchResult] = {}
    for item in no_hash_items:
        year = extract_release_year(item.title)
        norm_title = normalize_title_for_dedup(item.title)
        key = (norm_title, year) if norm_title else (item.title.strip().lower(), year)

        # If it matches an item with infohash, merge into the hashed item
        if key in seen_title_year:
            existing = seen_title_year[key]
            _merge(existing, item)
        elif key in deduped_no_hash:
            existing = deduped_no_hash[key]
            if item.score > existing.score:
                deduped_no_hash[key] = _merge(item, existing)
            else:
                deduped_no_hash[key] = _merge(existing, item)
        else:
            deduped_no_hash[key] = item

    combined = list(seen_hashes.values()) + list(deduped_no_hash.values())
    combined.sort(key=lambda r: r.score, reverse=True)
    return combined


class SearchSWRCache:
    """Bounded In-Memory LRU cache with Stale-While-Revalidate support."""

    def __init__(
        self,
        ttl: float = 300.0,
        empty_ttl: float = 20.0,
        stale_ttl: float = 900.0,
        max_entries: int = 256,
    ):
        self.ttl = ttl
        self.empty_ttl = empty_ttl
        self.stale_ttl = stale_ttl
        self.max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, float, list[SearchResult]]] = OrderedDict()

    def get(self, key: str) -> tuple[list[SearchResult] | None, bool]:
        now = cache_time.monotonic()
        if key not in self._entries:
            return None, False

        created_at, item_ttl, items = self._entries[key]
        age = now - created_at

        # Empty results expire directly at item_ttl (empty_ttl)
        expire_limit = item_ttl if not items else max(self.stale_ttl, item_ttl)
        if age >= expire_limit:
            del self._entries[key]
            return None, False

        self._entries.move_to_end(key)
        copied = [item.model_copy(deep=True) for item in items]
        is_stale = age >= item_ttl
        return copied, is_stale

    def set(self, key: str, results: list[SearchResult]) -> None:
        if self.max_entries <= 0:
            return
        now = cache_time.monotonic()
        item_ttl = self.ttl if results else self.empty_ttl
        self._entries[key] = (
            now,
            item_ttl,
            [item.model_copy(deep=True) for item in results],
        )
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


class SearchService:
    """Orchestrates multi-provider torrent searches with ranking and deduplication."""

    def __init__(
        self,
        providers: list[SearchProvider] | None = None,
        torrserver_client: Any = None,
        settings_provider: Callable[[], str] | None = None,
        torznab_config_provider: Callable[[], TorznabConfig] | None = None,
        search_timeout: float = 15.0,
        provider_timeout: float = 12.0,
        provider_timeouts: dict[str, float] | None = None,
        concurrency_limit: int = 6,
        cache: SearchCache | None = None,
        swr_cache: SearchSWRCache | None = None,
        swr_ttl: float | None = None,
        swr_stale_ttl: float | None = None,
        swr_max_entries: int | None = None,
    ):
        self._providers = list(providers) if providers is not None else []
        self._torrserver = torrserver_client
        self._get_ts_url = settings_provider
        self._get_torznab_config = torznab_config_provider
        self._search_timeout = search_timeout
        self._provider_timeout = provider_timeout
        self._provider_timeouts = provider_timeouts or {}
        self._semaphore = asyncio.Semaphore(concurrency_limit)

        # Align SWR cache parameters with provided cache if available
        base_ttl = swr_ttl if swr_ttl is not None else (cache.ttl if cache is not None else 300.0)
        base_empty_ttl = cache.empty_ttl if cache is not None else 20.0
        base_stale_ttl = swr_stale_ttl if swr_stale_ttl is not None else base_ttl
        base_max_entries = (
            swr_max_entries
            if swr_max_entries is not None
            else (cache.max_entries if cache is not None else 256)
        )
        self._swr_cache = (
            swr_cache
            if swr_cache is not None
            else SearchSWRCache(
                ttl=base_ttl,
                empty_ttl=base_empty_ttl,
                stale_ttl=base_stale_ttl,
                max_entries=base_max_entries,
            )
        )
        self._cache = (
            cache
            if cache is not None
            else SearchCache(
                ttl=self._swr_cache.ttl,
                empty_ttl=self._swr_cache.empty_ttl,
                max_entries=self._swr_cache.max_entries,
            )
        )
        self._swr_revalidations: dict[str, asyncio.Task] = {}
        self._inflight: dict[str, asyncio.Task] = {}
        self._waiters: dict[str, int] = {}

        # Fallback provider configuration for backward compatibility and direct wiring
        if not self._providers and self._torrserver and self._get_ts_url:
            self._providers.append(
                RuTorTorrServerProvider(
                    torrserver_client=self._torrserver,
                    base_url_provider=self._get_ts_url,
                )
            )

    @property
    def providers(self) -> list[SearchProvider]:
        return self._providers

    @property
    def swr_cache(self) -> SearchSWRCache:
        return self._swr_cache

    def add_provider(self, provider: SearchProvider) -> None:
        self._providers.append(provider)

    def _provider_fingerprint(self, active_providers: list[SearchProvider]) -> tuple:
        fingerprints = []
        for p in active_providers:
            try:
                if isinstance(p, TorznabProvider):
                    fingerprints.append((p.name, p.config.model_dump()))
                elif isinstance(p, RuTorTorrServerProvider):
                    fingerprints.append((p.name, p.cache_identity))
                else:
                    fingerprints.append((p.name, id(p)))
            except Exception:
                fingerprints.append((p.name, id(p)))
        return tuple(fingerprints)

    def _swr_cache_key(
        self,
        query: str,
        quality: str | None,
        min_seeders: int | None,
        hdr: str | None,
        voiceover: str | None,
        language: str | None,
        min_size: int | None,
        max_size: int | None,
        source: str | None,
        titles: list[str] | None,
        provider_fp: tuple,
    ) -> str:
        data = (
            query.strip().casefold(),
            quality,
            min_seeders,
            hdr,
            voiceover,
            language,
            min_size,
            max_size,
            source,
            tuple(sorted(t.strip().casefold() for t in (titles or []) if t.strip())),
            provider_fp,
        )
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def _cache_key(
        self,
        provider: SearchProvider,
        query: str,
        filters: tuple | dict,
    ) -> str:
        if isinstance(provider, TorznabProvider):
            identity = (provider.name, provider.config.model_dump())
        elif isinstance(provider, RuTorTorrServerProvider):
            identity = (provider.name, provider.cache_identity)
        else:
            identity = (provider.name, id(provider))
        # Even configuration/key material is never retained in cleartext keys.
        return hashlib.sha256(
            json.dumps((identity, query.casefold(), filters), sort_keys=True, default=str).encode()
        ).hexdigest()

    async def _call_provider_search(
        self,
        provider: SearchProvider,
        query: str,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        target = getattr(provider.search, "side_effect", None) or provider.search
        try:
            sig = inspect.signature(target)
            params = list(sig.parameters.values())
            if "filters" in sig.parameters:
                res = provider.search(query, filters=filters)
            elif len(params) >= 2 and not any(
                p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                for p in params
            ):
                res = provider.search(query, filters)
            elif len(params) == 1 and not any(
                p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                for p in params
            ):
                res = provider.search(query)
            else:
                try:
                    res = provider.search(query, filters=filters)
                except TypeError:
                    try:
                        res = provider.search(query, filters)
                    except TypeError:
                        res = provider.search(query)
        except (ValueError, TypeError):
            try:
                res = provider.search(query, filters=filters)
            except TypeError:
                try:
                    res = provider.search(query, filters)
                except TypeError:
                    res = provider.search(query)

        if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
            return await res
        return res

    async def _fetch(
        self,
        provider: SearchProvider,
        query: str,
        key: str,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        async with self._semaphore:
            timeout = self._provider_timeouts.get(provider.name, self._provider_timeout)
            call = self._call_provider_search(provider, query, filters)
            results = await asyncio.wait_for(call, timeout=timeout)
        self._cache.set(key, results)
        return results

    async def _search_provider(
        self,
        provider: SearchProvider,
        query: str,
        filters: tuple,
        filters_dict: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        try:
            key = self._cache_key(provider, query, filters)
        except Exception as exc:  # noqa: BLE001 - configuration failure is source-local
            logger.warning("Search source configuration failed (%s)", type(exc).__name__)
            return []
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._fetch(provider, query, key, filters_dict))
            self._inflight[key] = task
            self._waiters[key] = 0
        self._waiters[key] += 1
        try:
            results = await asyncio.shield(task)
            return [item.model_copy(deep=True) for item in results]
        except Exception as exc:  # noqa: BLE001 - isolate arbitrary provider failures
            # Exception messages may contain API keys, credentials or private URLs.
            logger.warning(
                "Search source %s failed (%s)",
                type(provider).__name__,
                type(exc).__name__,
            )
            raise
        finally:
            self._waiters[key] -= 1
            if self._waiters[key] == 0:
                self._inflight.pop(key, None)
                self._waiters.pop(key, None)
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[SearchResult]:
        """Unified search interface method conforming to provider contract."""
        merged_filters = dict(filters or {})
        merged_filters.update(kwargs)
        return await self.search_torrents(query, **merged_filters)

    async def health_check_providers(self) -> dict[str, bool]:
        """Check health of all registered search providers in parallel."""

        async def _check(provider: SearchProvider) -> tuple[str, bool]:
            timeout = self._provider_timeouts.get(provider.name, self._provider_timeout)
            try:
                healthy = await asyncio.wait_for(provider.health_check(), timeout=timeout)
                return provider.name, bool(healthy)
            except Exception as exc:
                logger.warning(
                    "Health check for provider %s failed (%s)",
                    provider.name,
                    type(exc).__name__,
                )
                return provider.name, False

        tasks = [_check(p) for p in self._providers]
        if not tasks:
            return {}
        results = await asyncio.gather(*tasks, return_exceptions=True)
        statuses: dict[str, bool] = {}
        for item in results:
            if isinstance(item, tuple):
                statuses[item[0]] = item[1]
        return statuses

    async def health_check(self) -> bool:
        """Check if active search providers are healthy."""
        if not self._providers:
            return True
        statuses = await self.health_check_providers()
        return any(statuses.values())

    def _trigger_swr_revalidation(
        self,
        swr_key: str,
        clean_query: str,
        quality: str | None,
        min_seeders: int | None,
        hdr: str | None,
        voiceover: str | None,
        language: str | None,
        min_size: int | None,
        max_size: int | None,
        source: str | None,
        titles: list[str] | None,
        active_providers: list[SearchProvider],
    ) -> asyncio.Task:
        if swr_key in self._swr_revalidations:
            return self._swr_revalidations[swr_key]

        async def _revalidate() -> None:
            try:
                refreshed, can_cache = await self._execute_search(
                    clean_query,
                    quality,
                    min_seeders,
                    hdr,
                    voiceover,
                    language,
                    min_size,
                    max_size,
                    source,
                    titles,
                    active_providers,
                )
                if can_cache:
                    self._swr_cache.set(swr_key, refreshed)
            except Exception as e:
                logger.warning(
                    "Background search SWR revalidation failed (%s)",
                    type(e).__name__,
                )
            finally:
                self._swr_revalidations.pop(swr_key, None)

        task = asyncio.create_task(_revalidate())
        self._swr_revalidations[swr_key] = task
        return task

    async def _execute_search(
        self,
        clean_query: str,
        quality: str | None,
        min_seeders: int | None,
        hdr: str | None,
        voiceover: str | None,
        language: str | None,
        min_size: int | None,
        max_size: int | None,
        source: str | None,
        titles: list[str] | None,
        active_providers: list[SearchProvider],
    ) -> tuple[list[SearchResult], bool]:
        # Explicit full query variants preserve season/episode/year constraints.
        unique: dict[str, str] = {}
        for title in [clean_query, *(titles or [])]:
            normalized = " ".join(title.split())
            if normalized:
                unique.setdefault(normalized.casefold(), normalized)
        variants = list(unique.values())[:6]
        filters = (
            quality,
            min_seeders,
            hdr,
            voiceover,
            language,
            min_size,
            max_size,
            source,
        )
        filters_dict = {
            "quality": quality,
            "min_seeders": min_seeders,
            "hdr": hdr,
            "voiceover": voiceover,
            "language": language,
            "min_size": min_size,
            "max_size": max_size,
            "source": source,
        }
        tasks = [
            asyncio.create_task(self._search_provider(provider, variant, filters, filters_dict))
            for variant in variants
            for provider in active_providers
        ]
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

        has_errors = any(isinstance(outcome, BaseException) for outcome in results)
        aggregated_results: list[SearchResult] = []
        for outcome in results:
            if isinstance(outcome, BaseException):
                # Isolate fallen providers and avoid logging private URLs / API keys
                logger.warning(
                    "Search provider failed (%s)",
                    type(outcome).__name__,
                )
                continue
            if isinstance(outcome, list):
                aggregated_results.extend(outcome)

        # Deduplicate by infohash, title, year and rank by score
        ranked_results = rank_results(aggregated_results)
        ranked_results = deduplicate_results_by_hash_title_year(ranked_results)

        # Quality filter
        if quality and quality.strip():
            target_q = quality.strip().lower()
            norm_q = extract_quality(target_q) or target_q
            ranked_results = [
                r
                for r in ranked_results
                if (r.quality and r.quality.lower() == norm_q.lower())
                or (extract_quality(r.title) and extract_quality(r.title).lower() == norm_q.lower())
            ]

        # Minimum seeders filter
        if min_seeders is not None and min_seeders > 0:
            ranked_results = [r for r in ranked_results if (r.seeders or 0) >= min_seeders]

        final_results = [
            result
            for result in ranked_results
            if matches_release_filters(
                result,
                hdr=hdr,
                voiceover=voiceover,
                language=language,
                min_size=min_size,
                max_size=max_size,
                source=source,
            )
        ]
        # Source errors must not be cached as empty
        can_cache = not (has_errors and not aggregated_results)
        return final_results, can_cache

    async def search_torrents(
        self,
        query: str,
        quality: str | None = None,
        min_seeders: int | None = None,
        hdr: str | None = None,
        voiceover: str | None = None,
        language: str | None = None,
        min_size: int | None = None,
        max_size: int | None = None,
        source: str | None = None,
        titles: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search torrents across all configured providers in parallel.

        Data flow: query -> SWR cache -> providers.parallel -> normalize ->
                   deduplicate by hash/title/year -> score/filter -> return.
        """
        clean_query = query.strip()
        if not clean_query:
            return []

        active_providers = list(self._providers)

        # Dynamic Torznab provider resolution if config provider supplied
        if self._get_torznab_config and not any(
            isinstance(p, TorznabProvider) for p in active_providers
        ):
            try:
                cfg = self._get_torznab_config()
                if cfg and cfg.enabled and cfg.url:
                    active_providers.append(TorznabProvider(config=cfg))
            except (ValueError, KeyError, TypeError, OSError):
                logger.warning("Failed to resolve dynamic Torznab config")

        if not active_providers:
            logger.info("No active search providers configured for query: %s", clean_query)
            return []

        provider_fp = self._provider_fingerprint(active_providers)
        swr_key = self._swr_cache_key(
            clean_query,
            quality,
            min_seeders,
            hdr,
            voiceover,
            language,
            min_size,
            max_size,
            source,
            titles,
            provider_fp,
        )

        cached_results, is_stale = self._swr_cache.get(swr_key)
        if cached_results is not None:
            if is_stale:
                self._trigger_swr_revalidation(
                    swr_key,
                    clean_query,
                    quality,
                    min_seeders,
                    hdr,
                    voiceover,
                    language,
                    min_size,
                    max_size,
                    source,
                    titles,
                    active_providers,
                )
            return [item.model_copy(deep=True) for item in cached_results]

        final_results, can_cache = await self._execute_search(
            clean_query,
            quality,
            min_seeders,
            hdr,
            voiceover,
            language,
            min_size,
            max_size,
            source,
            titles,
            active_providers,
        )

        if can_cache:
            self._swr_cache.set(swr_key, final_results)
        return [item.model_copy(deep=True) for item in final_results]
