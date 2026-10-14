import asyncio
import logging
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx

from backend.infrastructure.search.base import (
    SearchProvider,
    calculate_score,
    extract_quality,
)
from backend.infrastructure.torrserver.client import magnet_info_hash, normalize_hash
from backend.models.search import SearchResult, TorznabConfig

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES: list[int] = [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060]


def parse_torznab_xml(
    xml_content: str, default_source: str = "Torznab"
) -> list[SearchResult]:
    """Parse Torznab / Newznab XML feed and extract normalized SearchResult objects."""
    if not xml_content or not xml_content.strip():
        return []

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logger.warning("Failed to parse Torznab XML response: %s", e)
        return []

    if root.tag.lower() == "error":
        code = root.get("code", "")
        desc = root.get("description", root.text or "")
        logger.warning("Torznab API error [%s]: %s", code, desc)
        return []

    # Channel metadata
    channel = root.find("channel")
    channel_title = ""
    if channel is not None:
        title_el = channel.find("title")
        if title_el is not None and title_el.text:
            channel_title = title_el.text.strip()

    items = root.findall(".//item")
    results: list[SearchResult] = []

    for item in items:
        title_el = item.find("title")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        if not title:
            continue

        torznab_attrs: dict[str, str] = {}
        for child in item:
            # Handle namespaced or unnamespaced torznab attrs
            if child.tag.endswith("attr"):
                attr_name = child.get("name")
                attr_val = child.get("value")
                if attr_name and attr_val is not None:
                    torznab_attrs[attr_name.lower()] = attr_val.strip()

        # Extract magnet link
        magnet: str | None = torznab_attrs.get("magneturl")
        if not magnet:
            link_el = item.find("link")
            if (
                link_el is not None
                and link_el.text
                and link_el.text.strip().startswith("magnet:")
            ):
                magnet = link_el.text.strip()
        if not magnet:
            enclosure_el = item.find("enclosure")
            if enclosure_el is not None:
                enc_url = (enclosure_el.get("url") or "").strip()
                if enc_url.startswith("magnet:"):
                    magnet = enc_url

        # Extract infohash
        raw_hash = torznab_attrs.get("infohash")
        infohash = normalize_hash(raw_hash) if raw_hash else None
        if not infohash and magnet:
            infohash = magnet_info_hash(magnet)

        if not magnet and infohash:
            magnet = f"magnet:?xt=urn:btih:{infohash}&dn={title}"

        # Extract size
        size: int | None = None
        raw_size = torznab_attrs.get("size")
        if not raw_size:
            size_el = item.find("size")
            if size_el is not None and size_el.text:
                raw_size = size_el.text.strip()
        if not raw_size:
            enclosure_el = item.find("enclosure")
            if enclosure_el is not None and enclosure_el.get("length"):
                raw_size = enclosure_el.get("length", "").strip()
        if raw_size:
            try:
                size = int(raw_size)
            except (ValueError, TypeError):
                size = None

        # Extract seeders
        seeders: int | None = None
        raw_seeders = torznab_attrs.get("seeders")
        if not raw_seeders:
            seeders_el = item.find("seeders")
            if seeders_el is not None and seeders_el.text:
                raw_seeders = seeders_el.text.strip()
        if raw_seeders:
            try:
                seeders = int(raw_seeders)
            except (ValueError, TypeError):
                seeders = 0

        # Tracker / source
        tracker = torznab_attrs.get("tracker") or channel_title or default_source

        published_at = None
        pub_date_el = item.find("pubDate")
        if pub_date_el is not None and pub_date_el.text:
            try:
                published_at = parsedate_to_datetime(pub_date_el.text.strip())
            except (TypeError, ValueError):
                pass

        quality = extract_quality(title)

        result_item = SearchResult(
            title=title,
            magnet=magnet,
            infohash=infohash,
            size=size,
            seeders=seeders,
            quality=quality,
            source=tracker,
            published_at=published_at,
            score=0.0,
        )
        result_item.score = calculate_score(result_item)
        results.append(result_item)

    return results


class TorznabProvider(SearchProvider):
    """Torznab search provider for Jackett and Prowlarr indexers."""

    def __init__(
        self,
        config: TorznabConfig,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 12.0,
        max_retries: int = 2,
        concurrency_limit: int = 5,
    ):
        self._config = config
        self._http_client = http_client
        self._timeout = timeout
        self._max_retries = max_retries
        self._semaphore = asyncio.Semaphore(concurrency_limit)

    @property
    def name(self) -> str:
        return "Torznab"

    @property
    def config(self) -> TorznabConfig:
        return self._config

    async def search(self, query: str) -> list[SearchResult]:
        if not self._config.enabled or not self._config.url:
            return []

        clean_url = self._config.url.strip()
        if not clean_url:
            return []

        categories = self._config.categories or DEFAULT_CATEGORIES
        cat_param = ",".join(str(c) for c in categories)

        params: dict[str, str] = {
            "t": "search",
            "q": query,
            "cat": cat_param,
        }
        if self._config.api_key and "apikey=" not in clean_url.lower():
            params["apikey"] = self._config.api_key

        async with self._semaphore:
            content = await self._fetch_feed(clean_url, params)
            if not content:
                return []
            return parse_torznab_xml(content, default_source=self.name)

    async def _fetch_feed(self, url: str, params: dict[str, str]) -> str | None:
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                if self._http_client is not None and not self._http_client.is_closed:
                    response = await self._http_client.get(
                        url,
                        params=params,
                        timeout=self._timeout,
                        follow_redirects=True,
                    )
                else:
                    async with httpx.AsyncClient(
                        timeout=self._timeout,
                        follow_redirects=True,
                    ) as client:
                        response = await client.get(url, params=params)

                if response.status_code == 200:
                    return response.text
                elif response.status_code in (401, 403):
                    logger.warning(
                        "Torznab authentication failed (HTTP %s) for %s",
                        response.status_code,
                        url,
                    )
                    return None
                elif response.status_code >= 500:
                    logger.warning(
                        "Torznab server error (HTTP %s) on attempt %d for %s",
                        response.status_code,
                        attempt + 1,
                        url,
                    )
                    if attempt < self._max_retries:
                        await asyncio.sleep(0.4 * (attempt + 1))
                        continue
                    return None
                else:
                    logger.warning(
                        "Torznab search request returned HTTP %s",
                        response.status_code,
                    )
                    return None

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = e
                logger.warning(
                    "Torznab network/timeout error on attempt %d: %s",
                    attempt + 1,
                    e,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
                return None
            except Exception:
                logger.exception("Unexpected error querying Torznab provider")
                return None

        if last_error:
            logger.warning("Torznab search failed after retries: %s", last_error)
        return None
