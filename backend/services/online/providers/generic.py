"""Generic HLS and direct stream provider."""

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from backend.api.schemas.online import OnlineSearchResult
from backend.services.online.providers.base import OnlineProvider, StreamInfo

logger = logging.getLogger(__name__)


def _validate_safe_url(url: str) -> None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Поддерживаются только URL с протоколами http и https")

    host = parsed.hostname
    if not host:
        raise ValueError("URL должен содержать корректный хост")

    # Disallow localhost / 0.0.0.0
    if host.lower() in ("localhost", "0.0.0.0", "127.0.0.1", "::1"):
        raise ValueError("Запросы к локальному хосту запрещены")

    # Check if host is direct IP
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise ValueError("Запросы к приватным IP-адресам запрещены")
    except ValueError:
        # Host is a domain name; resolve DNS to check resolved IP
        try:
            addr_info = socket.getaddrinfo(host, None)
            for item in addr_info:
                ip_str = item[4][0]
                resolved_ip = ipaddress.ip_address(ip_str)
                if (
                    resolved_ip.is_private
                    or resolved_ip.is_loopback
                    or resolved_ip.is_link_local
                    or resolved_ip.is_reserved
                    or resolved_ip.is_multicast
                ):
                    raise ValueError("Запросы к приватным IP-адресам запрещены")
        except (socket.gaierror, socket.herror, OSError) as err:
            logger.debug("DNS resolution error for %s: %s", host, err)
            raise ValueError(f"Не удалось разрешить хост {host}") from err


class GenericHLSProvider(OnlineProvider):
    @property
    def name(self) -> str:
        return "direct"

    @property
    def supports_search(self) -> bool:
        return False

    async def search(self, query: str) -> list[OnlineSearchResult]:
        stripped = query.strip()
        if not stripped.startswith(("http://", "https://")):
            return []

        try:
            _validate_safe_url(stripped)
        except ValueError:
            return []

        parsed = urlparse(stripped)
        path_name = parsed.path.rstrip("/").split("/")[-1] or parsed.netloc
        title = path_name if len(path_name) > 3 else f"Прямой поток ({parsed.netloc})"

        return [
            OnlineSearchResult(
                id=stripped,
                title=title,
                provider="direct",
                thumbnail=None,
                duration=None,
                is_playlist=False,
            )
        ]

    async def get_metadata(self, video_id: str) -> OnlineSearchResult:
        _validate_safe_url(video_id)
        parsed = urlparse(video_id)
        path_name = parsed.path.rstrip("/").split("/")[-1] or parsed.netloc
        title = path_name if len(path_name) > 3 else f"Прямой поток ({parsed.netloc})"

        return OnlineSearchResult(
            id=video_id,
            title=title,
            provider="direct",
            thumbnail=None,
            duration=None,
            is_playlist=False,
        )

    async def resolve_stream(
        self, video_id: str, quality: str | None = None
    ) -> StreamInfo:
        _validate_safe_url(video_id)
        parsed = urlparse(video_id)
        path_name = parsed.path.rstrip("/").split("/")[-1] or parsed.netloc
        title = path_name if len(path_name) > 3 else f"Прямой поток ({parsed.netloc})"

        return StreamInfo(
            url=video_id,
            title=title,
            quality=quality or "auto",
            available_qualities=[],
        )

    async def get_qualities(self, video_id: str) -> list[str]:
        return []
