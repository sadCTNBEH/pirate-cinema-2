from typing import Literal

from pydantic import BaseModel, Field

CollectionName = Literal["favorites", "watch_later"]


class CollectionItemRequest(BaseModel):
    media_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    title_ru: str | None = Field(default=None, max_length=512)
    poster_url: str | None = Field(default=None, max_length=2048)
    year: int | None = Field(default=None, ge=1888, le=3000)
    rating: float | None = Field(default=None, ge=0, le=10)
    overview: str | None = None
    overview_ru: str | None = None
    genres: list[str] = Field(default_factory=list)
    media_type: Literal["movie", "series"] | None = None


class CollectionItemResponse(CollectionItemRequest):
    created_at: str | None = None


class CollectionMembershipResponse(BaseModel):
    favorites: bool = False
    watch_later: bool = False
