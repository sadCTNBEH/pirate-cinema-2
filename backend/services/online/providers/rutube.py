"""Rutube online video provider."""

import json
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from backend.api.schemas.online import OnlineSearchResult
from backend.exceptions import (
    ExternalServiceError,
    NotFoundError,
    ProviderUnavailableError,
)
from backend.services.online.providers.base import OnlineProvider, StreamInfo

logger = logging.getLogger(__name__)


def _extract_rutube_id(raw: str) -> str:
    cleaned = raw.strip()
    match = re.search(r"([a-f0-9]{32})", cleaned, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return cleaned


class RutubeProvider(OnlineProvider):
    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self._owns_client = client is None

    @property
    def name(self) -> str:
        return "rutube"

    @property
    def supports_search(self) -> bool:
        return True

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0),
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                },
                follow_redirects=True,
            )
            self._owns_client = True
        return self._client

    async def search(self, query: str) -> list[OnlineSearchResult]:
        stripped = query.strip()
        if not stripped:
            return []

        # Check if query directly contains a Rutube video ID / URL
        rutube_id = _extract_rutube_id(stripped)
        if len(rutube_id) == 32 and re.fullmatch(r"[a-f0-9]{32}", rutube_id):
            try:
                single = await self.get_metadata(rutube_id)
                return [single]
            except (NotFoundError, ExternalServiceError, ProviderUnavailableError):
                logger.debug("Rutube ID lookup failed for '%s', falling back to search", stripped)

        client = await self._get_client()
        url = f"https://rutube.ru/api/search/video/?query={quote(stripped)}&format=json"

        try:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as err:
            logger.warning("Rutube search network failure: %s", err)
            raise ProviderUnavailableError(f"Сервер Rutube недоступен: {err}") from err
        except httpx.HTTPStatusError as err:
            logger.warning("Rutube search HTTP error %s: %s", err.response.status_code, err)
            raise ExternalServiceError(f"Ошибка Rutube API: {err.response.status_code}") from err
        except (json.JSONDecodeError, ValueError) as err:
            logger.warning("Rutube search JSON decode error: %s", err)
            raise ExternalServiceError("Некорректный ответ от поискового сервиса Rutube") from err

        results: list[OnlineSearchResult] = []
        raw_items: list[dict[str, Any]] = data.get("results") or []
        for item in raw_items:
            vid = item.get("id")
            title = item.get("title") or "Без названия"
            if not vid:
                continue

            dur_val = item.get("duration")
            duration: int | None = None
            if isinstance(dur_val, (int, float)) and dur_val > 0:
                duration = int(dur_val)

            results.append(
                OnlineSearchResult(
                    id=str(vid),
                    title=str(title).strip(),
                    provider="rutube",
                    thumbnail=item.get("thumbnail_url"),
                    duration=duration,
                    is_playlist=False,
                )
            )
        return results

    async def get_metadata(self, video_id: str) -> OnlineSearchResult:
        clean_id = _extract_rutube_id(video_id)
        client = await self._get_client()
        url = f"https://rutube.ru/api/play/options/{clean_id}/?format=json"

        try:
            resp = await client.get(url)
            if resp.status_code == 404:
                raise NotFoundError(f"Видео {clean_id} не найдено на Rutube")
            resp.raise_for_status()
            data = resp.json()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as err:
            logger.warning("Rutube metadata network error: %s", err)
            raise ProviderUnavailableError(f"Rutube недоступен: {err}") from err
        except httpx.HTTPStatusError as err:
            logger.warning("Rutube metadata HTTP error %s: %s", err.response.status_code, err)
            raise ExternalServiceError(f"Ошибка Rutube API: {err.response.status_code}") from err
        except (json.JSONDecodeError, ValueError) as err:
            logger.warning("Rutube metadata JSON error: %s", err)
            raise ExternalServiceError("Некорректный формат ответа Rutube") from err

        title = str(data.get("title") or "Видео Rutube").strip()
        thumbnail = data.get("thumbnail_url")
        dur_val = data.get("duration")
        duration = int(dur_val) if isinstance(dur_val, (int, float)) and dur_val > 0 else None

        return OnlineSearchResult(
            id=clean_id,
            title=title,
            provider="rutube",
            thumbnail=thumbnail,
            duration=duration,
            is_playlist=False,
        )

    async def _parse_m3u8_qualities(self, m3u8_url: str) -> dict[str, str]:
        client = await self._get_client()
        try:
            resp = await client.get(m3u8_url, timeout=5.0)
            if resp.status_code != 200:
                return {}
            text = resp.text
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError, httpx.NetworkError) as err:
            logger.debug("Failed to fetch m3u8 subplaylist qualities: %s", err)
            return {}

        qualities: dict[str, str] = {}
        # Parse RESOLUTION=widthxheight followed by URL
        matches = re.findall(
            r"RESOLUTION=\d+x(\d+).*?\n(https?://[^\s\r\n]+)",
            text,
            re.DOTALL,
        )
        for h_str, stream_link in matches:
            try:
                h_int = int(h_str)
                label = f"{h_int}p"
                if label not in qualities:
                    qualities[label] = stream_link.strip()
            except ValueError:
                continue

        # Sort qualities descending (e.g. 1080p, 720p, 480p)
        sorted_keys = sorted(
            qualities.keys(),
            key=lambda k: int(k.rstrip("p")) if k.rstrip("p").isdigit() else 0,
            reverse=True,
        )
        return {k: qualities[k] for k in sorted_keys}

    async def resolve_stream(
        self, video_id: str, quality: str | None = None
    ) -> StreamInfo:
        clean_id = _extract_rutube_id(video_id)
        client = await self._get_client()
        url = f"https://rutube.ru/api/play/options/{clean_id}/?format=json"

        try:
            resp = await client.get(url)
            if resp.status_code == 404:
                raise NotFoundError(f"Видео {clean_id} не найдено на Rutube")
            resp.raise_for_status()
            data = resp.json()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as err:
            logger.warning("Rutube resolve stream network error: %s", err)
            raise ProviderUnavailableError(f"Rutube недоступен: {err}") from err
        except httpx.HTTPStatusError as err:
            logger.warning("Rutube resolve stream HTTP error %s: %s", err.response.status_code, err)
            raise ExternalServiceError(f"Ошибка Rutube API: {err.response.status_code}") from err
        except (json.JSONDecodeError, ValueError) as err:
            logger.warning("Rutube resolve stream JSON error: %s", err)
            raise ExternalServiceError("Некорректный формат ответа Rutube") from err

        balancer = data.get("video_balancer") or {}
        m3u8_url = balancer.get("m3u8") or balancer.get("default")
        if not m3u8_url:
            raise ExternalServiceError("Видео поток недоступен для данного видео Rutube")

        title = str(data.get("title") or "Видео Rutube").strip()
        thumbnail = data.get("thumbnail_url")
        dur_val = data.get("duration")
        duration = int(dur_val) if isinstance(dur_val, (int, float)) and dur_val > 0 else None

        qualities_map: dict[str, str] = {}
        chosen_quality = "auto"
        stream_url = m3u8_url

        if quality and quality != "auto":
            qualities_map = await self._parse_m3u8_qualities(m3u8_url)
            # Match directly or by number
            q_norm = quality if quality.endswith("p") else f"{quality}p"
            if q_norm in qualities_map:
                stream_url = qualities_map[q_norm]
                chosen_quality = q_norm

        available = list(qualities_map.keys()) if qualities_map else ["1080p", "720p", "480p", "360p", "auto"]

        return StreamInfo(
            url=stream_url,
            title=title,
            thumbnail=thumbnail,
            duration=duration,
            quality=chosen_quality,
            available_qualities=available,
        )

    async def get_qualities(self, video_id: str) -> list[str]:
        info = await self.resolve_stream(video_id)
        return info.available_qualities

    async def close(self) -> None:
        if self._owns_client and self._client and not self._client.is_closed:
            try:
                await self._client.aclose()
            except (RuntimeError, OSError) as err:
                logger.debug("Error closing Rutube HTTP client: %s", err)
