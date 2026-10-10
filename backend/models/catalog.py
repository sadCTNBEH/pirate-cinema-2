from typing import Any

from pydantic import BaseModel, Field


class MediaItem(BaseModel):
    id: str  # IMDB ID or provider unique ID
    title: str
    original_title: str | None = None
    title_ru: str | None = None
    year: int | None = None
    rating: float | None = None
    poster_url: str | None = None
    background_url: str | None = None
    overview: str | None = None
    overview_ru: str | None = None
    genres: list[str] = Field(default_factory=list)
    source: str = "cinemeta"
    type: str = "movie"  # "movie" | "series"


class Movie(MediaItem):
    type: str = "movie"


class Series(MediaItem):
    type: str = "series"


class MediaDetail(MediaItem):
    videos: list[dict[str, Any]] = Field(default_factory=list)


class PosterItem(BaseModel):
    url: str
    language: str | None = None
    width: int | None = None
    height: int | None = None
    source: str = "unknown"
    score: float = 0.0
