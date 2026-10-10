
from pydantic import BaseModel, Field, computed_field


class TorznabConfig(BaseModel):
    enabled: bool = False
    url: str = ""
    api_key: str = ""
    categories: list[int] = Field(default_factory=list)


class SearchResult(BaseModel):
    title: str
    magnet: str | None = None
    infohash: str | None = None
    size: int | None = None
    seeders: int | None = None
    quality: str | None = None
    source: str = "Unknown"
    score: float = 0.0

    @computed_field
    @property
    def hash(self) -> str | None:
        """Alias for infohash to provide backward compatibility with frontend clients."""
        return self.infohash

    def __eq__(self, other: object) -> bool:
        if isinstance(other, dict):
            return all(getattr(self, k, None) == v for k, v in other.items())
        return super().__eq__(other)
