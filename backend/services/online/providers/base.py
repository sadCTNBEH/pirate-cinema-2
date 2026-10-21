"""Base provider interface for online video sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from backend.api.schemas.online import OnlineSearchResult


@dataclass
class StreamInfo:
    url: str
    title: str
    thumbnail: str | None = None
    duration: int | None = None
    quality: str | None = None
    available_qualities: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)


class OnlineProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique provider identifier (e.g. 'rutube', 'direct')."""

    @property
    def supports_search(self) -> bool:
        """Whether this provider supports text search."""
        return True

    @abstractmethod
    async def search(self, query: str) -> list[OnlineSearchResult]:
        """Search videos by query."""

    @abstractmethod
    async def get_metadata(self, video_id: str) -> OnlineSearchResult:
        """Fetch metadata for a single video."""

    @abstractmethod
    async def resolve_stream(
        self, video_id: str, quality: str | None = None
    ) -> StreamInfo:
        """Resolve a video ID to a playable stream URL and quality."""

    @abstractmethod
    async def get_qualities(self, video_id: str) -> list[str]:
        """Fetch available qualities for a video."""

    async def close(self) -> None:
        """Clean up HTTP client or background resources."""
