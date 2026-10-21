"""Online service managing video providers and operations."""

import logging
from collections.abc import Sequence

from backend.api.schemas.online import OnlineSearchResult
from backend.exceptions import NotFoundError, ProviderUnavailableError
from backend.services.online.providers.base import OnlineProvider, StreamInfo
from backend.services.online.providers.generic import GenericHLSProvider
from backend.services.online.providers.rutube import RutubeProvider

logger = logging.getLogger(__name__)


class OnlineService:
    def __init__(self, providers: Sequence[OnlineProvider] | None = None):
        if providers is not None:
            self._providers = {p.name: p for p in providers}
        else:
            rutube = RutubeProvider()
            direct = GenericHLSProvider()
            self._providers = {
                rutube.name: rutube,
                direct.name: direct,
            }

    def register_provider(self, provider: OnlineProvider) -> None:
        self._providers[provider.name] = provider

    def get_provider(self, name: str) -> OnlineProvider:
        prov = self._providers.get(name)
        if not prov:
            raise NotFoundError(f"Онлайн-провайдер '{name}' не поддерживается")
        return prov

    async def search(
        self, query: str, provider: str | None = None
    ) -> list[OnlineSearchResult]:
        stripped = query.strip()
        if not stripped:
            return []

        if provider:
            p = self.get_provider(provider)
            return await p.search(stripped)

        # Check if query is direct URL
        if stripped.startswith(("http://", "https://")):
            # If Rutube URL, search specifically in Rutube
            if "rutube.ru" in stripped:
                p = self.get_provider("rutube")
                return await p.search(stripped)
            # Otherwise check direct stream
            direct_p = self.get_provider("direct")
            res = await direct_p.search(stripped)
            if res:
                return res

        # Aggregate across search-supporting providers
        aggregated: list[OnlineSearchResult] = []
        for p in self._providers.values():
            if not p.supports_search:
                continue
            try:
                results = await p.search(stripped)
                aggregated.extend(results)
            except (ProviderUnavailableError, NotFoundError, ValueError) as err:
                logger.warning("Provider %s search error: %s", p.name, err)

        return aggregated

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

    async def close(self) -> None:
        for p in self._providers.values():
            await p.close()
