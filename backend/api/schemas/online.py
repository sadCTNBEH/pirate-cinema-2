"""Pydantic schemas for online videos, playlists, and history."""

from datetime import datetime

from pydantic import BaseModel, Field


class OnlineSearchResult(BaseModel):
    id: str
    title: str
    provider: str
    thumbnail: str | None = None
    duration: int | None = None
    is_playlist: bool = False


class OnlineSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    provider: str | None = Field(default=None, max_length=50)


class PlayOnlineRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=50)
    id: str = Field(..., min_length=1, max_length=1000)
    quality: str | None = Field(default=None, max_length=50)
    playlist_id: str | None = Field(default=None, max_length=100)
    episode_index: int | None = Field(default=None, ge=0)


class PlayOnlineResponse(BaseModel):
    url: str
    title: str
    thumbnail: str | None = None
    duration: int | None = None
    quality: str | None = None
    timecode: int = 0
    provider: str
    id: str
    available_qualities: list[str] = Field(default_factory=list)
    status: str = "launched"


class PlaylistCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class PlaylistUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class PlaylistItemCreateRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=1000)
    title: str = Field(..., min_length=1, max_length=500)
    provider: str = Field(..., min_length=1, max_length=50)
    thumbnail: str | None = None
    duration: int | None = None
    is_playlist: bool = False


class Playlist(BaseModel):
    id: str
    title: str
    items: list[OnlineSearchResult] = Field(default_factory=list)
    created_at: datetime


class OnlineHistoryItem(BaseModel):
    item_id: str
    provider: str
    title: str
    thumbnail: str | None = None
    duration: int | None = None
    playback_timecode: int = 0
    playback_duration: int = 0
    is_watched: bool = False
    last_played_at: str
    launch_count: int = 1
