import asyncio
import logging
from collections.abc import Callable
from typing import Any

from backend.infrastructure.search.base import (
    SearchProvider,
    extract_quality,
    rank_results,
)
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
    ):
        self._providers = list(providers) if providers is not None else []
        self._torrserver = torrserver_client
        self._get_ts_url = settings_provider
        self._get_torznab_config = torznab_config_provider
        self._search_timeout = search_timeout

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

    async def search_torrents(
        self,
        query: str,
        quality: str | None = None,
        min_seeders: int | None = None,
    ) -> list[SearchResult]:
        """Search torrents across all configured providers in parallel.

        Data flow: query -> providers.parallel -> normalize -> score/filter -> return.
        Ensures provider errors do not block other providers (e.g. Torznab failure won't block RuTor).
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
            except (ValueError, KeyError, TypeError, OSError) as e:
                logger.warning("Failed to resolve dynamic Torznab config: %s", e)

        if not active_providers:
            logger.info(
                "No active search providers configured for query: %s", clean_query
            )
            return []

        # Run providers in parallel with timeout guard
        tasks = [provider.search(clean_query) for provider in active_providers]
        try:
            responses = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self._search_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Search query '%s' timed out after %.1fs across %d providers",
                clean_query,
                self._search_timeout,
                len(active_providers),
            )
            return []

        aggregated_results: list[SearchResult] = []
        for provider, resp in zip(active_providers, responses):
            if isinstance(resp, Exception):
                logger.error(
                    "Search provider '%s' failed for query '%s': %s",
                    provider.name,
                    clean_query,
                    resp,
                )
                continue
            if isinstance(resp, list):
                aggregated_results.extend(resp)

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

        return ranked_results
