import logging
from typing import Any, Callable

import httpx

from backend.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(
        self,
        torrserver_client: Any,
        settings_provider: Callable[[], str],
    ):
        self._torrserver = torrserver_client
        self._get_ts_url = settings_provider

    async def search_torrents(self, query: str) -> list[dict[str, Any]]:
        torrserver_url = self._get_ts_url()
        try:
            return await self._torrserver.search_all(torrserver_url, query)
        except httpx.HTTPStatusError as e:
            logger.error(
                "TorrServer search returned HTTP status error for query '%s': %s",
                query,
                e,
            )
            raise ExternalServiceError(
                f"TorrServer search returned error: {e.response.status_code}",
                status_code=502,
            ) from e
        except httpx.RequestError as e:
            logger.error(
                "TorrServer connection/network error during search for query '%s': %s",
                query,
                e,
            )
            raise ExternalServiceError(
                f"TorrServer connection error: {e}",
                status_code=502,
            ) from e
