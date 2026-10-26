import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

from backend.infrastructure.search.base import (
    SearchProvider,
    extract_quality,
    matches_release_filters,
    rank_results,
)
from backend.infrastructure.search.cache import SearchCache
from backend.infrastructure.search.rutor import RuTorTorrServerProvider
from backend.infrastructure.search.torznab import TorznabProvider
from backend.models.search import SearchResult, TorznabConfig

logger = logging.getLogger(__name__)


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
    ):
        self._providers = list(providers) if providers is not None else []
        self._torrserver = torrserver_client
        self._get_ts_url = settings_provider
        self._get_torznab_config = torznab_config_provider
        self._search_timeout = search_timeout
        self._provider_timeout = provider_timeout
        self._provider_timeouts = provider_timeouts or {}
        self._semaphore = asyncio.Semaphore(concurrency_limit)
        self._cache = cache if cache is not None else SearchCache()
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

    def add_provider(self, provider: SearchProvider) -> None:
        self._providers.append(provider)

    def _cache_key(self, provider: SearchProvider, query: str, filters: tuple) -> str:
        if isinstance(provider, TorznabProvider):
            identity = (provider.name, provider.config.model_dump())
        elif isinstance(provider, RuTorTorrServerProvider):
            identity = (provider.name, provider.cache_identity)
        else:
            identity = (provider.name, id(provider))
        # Even configuration/key material is never retained in cleartext keys.
        return hashlib.sha256(
            json.dumps((identity, query.casefold(), filters), sort_keys=True).encode()
        ).hexdigest()

    async def _fetch(
        self, provider: SearchProvider, query: str, key: str
    ) -> list[SearchResult]:
        async with self._semaphore:
            timeout = self._provider_timeouts.get(provider.name, self._provider_timeout)
            results = await asyncio.wait_for(provider.search(query), timeout=timeout)
        self._cache.set(key, results)
        return results

    async def _search_provider(
        self, provider: SearchProvider, query: str, filters: tuple
    ) -> list[SearchResult]:
        try:
            key = self._cache_key(provider, query, filters)
        except Exception as exc:  # noqa: BLE001 - configuration failure is source-local
            logger.warning(
                "Search source configuration failed (%s)", type(exc).__name__
            )
            return []
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._fetch(provider, query, key))
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
            return []
        finally:
            self._waiters[key] -= 1
            if self._waiters[key] == 0:
                self._inflight.pop(key, None)
                self._waiters.pop(key, None)
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

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

        Data flow: query -> providers.parallel -> normalize -> score/filter -> return.
        Provider errors do not block other providers; for example, a Torznab
        failure does not block RuTor.
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
            logger.info(
                "No active search providers configured for query: %s", clean_query
            )
            return []

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
        tasks = [
            asyncio.create_task(self._search_provider(provider, variant, filters))
            for variant in variants
            for provider in active_providers
        ]
        try:
            done, _ = await asyncio.wait(tasks, timeout=self._search_timeout)
            aggregated_results = [
                item for task in tasks if task in done for item in task.result()
            ]
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        # Deduplicate by infohash and rank by score
        ranked_results = rank_results(aggregated_results)

        # Quality filter
        if quality and quality.strip():
            target_q = quality.strip().lower()
            norm_q = extract_quality(target_q) or target_q
            ranked_results = [
                r
                for r in ranked_results
                if (r.quality and r.quality.lower() == norm_q.lower())
                or (
                    extract_quality(r.title)
                    and extract_quality(r.title).lower() == norm_q.lower()
                )
            ]

        # Minimum seeders filter
        if min_seeders is not None and min_seeders > 0:
            ranked_results = [
                r for r in ranked_results if (r.seeders or 0) >= min_seeders
            ]

        return [
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
