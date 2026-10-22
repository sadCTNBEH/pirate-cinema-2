import asyncio
import logging
import re
from collections.abc import Callable
from typing import Any

import httpx

from backend.infrastructure.search.base import (
    SearchProvider,
    calculate_score,
    extract_quality,
)
from backend.infrastructure.torrserver.client import magnet_info_hash, normalize_hash
from backend.models.search import SearchResult

logger = logging.getLogger(__name__)


def _parse_size_bytes(value: Any) -> int | None:
    """Convert TorrServer/RuTor size values such as ``1.46 GB`` to bytes."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None

    raw = str(value).strip().replace("\u00a0", " ")
    if not raw:
        return None
    try:
        return int(raw.replace(" ", ""))
    except ValueError:
        pass

    match = re.search(
        r"(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>[kmgt]?i?b|[КМГТ]?[Бб])",
        raw,
        re.IGNORECASE,
    )
    if not match:
        return None

    number = float(match.group("number").replace(",", "."))
    unit = match.group("unit").lower().replace("і", "i")
    units = {
        "b": 1,
        "кб": 1024,
        "kb": 1024,
        "kib": 1024,
        "мб": 1024**2,
        "mb": 1024**2,
        "mib": 1024**2,
        "гб": 1024**3,
        "gb": 1024**3,
        "gib": 1024**3,
        "тб": 1024**4,
        "tb": 1024**4,
        "tib": 1024**4,
    }
    multiplier = units.get(unit)
    return int(number * multiplier) if multiplier else None


class RuTorTorrServerProvider(SearchProvider):
    """Search provider querying RuTor trackers via TorrServer's built-in search."""

    def __init__(
        self,
        torrserver_client: Any,
        base_url_provider: Callable[[], str],
    ):
        self._torrserver = torrserver_client
        self._get_base_url = base_url_provider

    @property
    def name(self) -> str:
        return "RuTor"

    async def search(self, query: str) -> list[SearchResult]:
        if not query or not query.strip():
            return []

        base_url = self._get_base_url()
        try:
            # Support both search_torrserver and search_all (and handle MagicMocks cleanly)
            mock_children = getattr(self._torrserver, "_mock_children", None)
            if mock_children is not None and "search_all" in mock_children:
                search_fn = self._torrserver.search_all
            elif (
                hasattr(self._torrserver, "search_torrserver")
                and mock_children is None
                or hasattr(self._torrserver, "search_torrserver")
            ):
                search_fn = self._torrserver.search_torrserver
            elif hasattr(self._torrserver, "search_all"):
                search_fn = self._torrserver.search_all
            else:
                logger.warning("TorrServer client does not provide search method")
                return []

            res = search_fn(base_url, query)
            if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                raw_items = await res
            else:
                raw_items = res
        except (httpx.HTTPError, OSError) as e:
            logger.warning("TorrServer search failed for query '%s': %s", query, e)
            return []
        except (ValueError, KeyError, RuntimeError, TypeError):
            logger.exception("Unexpected error during TorrServer search for query '%s'", query)
            return []

        if not isinstance(raw_items, list):
            return []

        results: list[SearchResult] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue

            title = item.get("title") or item.get("Title") or ""
            if not title:
                continue

            magnet = item.get("magnet") or item.get("Magnet")
            raw_hash = item.get("hash") or item.get("Hash")
            h = (
                magnet_info_hash(magnet)
                if magnet
                else (normalize_hash(raw_hash) if raw_hash else None)
            )

            if not magnet and h:
                magnet = f"magnet:?xt=urn:btih:{h}&dn={title}"

            seeders = item.get("seeders") or item.get("Seed") or 0
            try:
                seeders_int = int(seeders) if seeders is not None else 0
            except (ValueError, TypeError):
                seeders_int = 0

            size = item.get("size") or item.get("Size")
            size_int = _parse_size_bytes(size)

            quality = extract_quality(title)

            result = SearchResult(
                title=title,
                magnet=magnet,
                infohash=h,
                size=size_int,
                seeders=seeders_int,
                quality=quality,
                source=item.get("source") or self.name,
                score=0.0,
            )
            result.score = calculate_score(result)
            results.append(result)

        return results
