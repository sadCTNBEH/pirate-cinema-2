from typing import Literal

from pydantic import BaseModel, Field


class AnimePlaybackRequest(BaseModel):
    media_id: str = Field(max_length=128)
    source: Literal['animego', 'yummy']
    source_title_id: str = Field(pattern=r'^\d+$', max_length=30)
    season: int = Field(default=1, ge=1, le=1000)
    episode: int = Field(ge=1, le=5000)
    player: str = Field(default='', max_length=100)
    voice_id: str = Field(default='', max_length=100)
    voice: str = Field(default='', max_length=200)


class HistoryItemResponse(BaseModel):
    id: str | None = None
    torrent_hash: str
    file_index: int
    file_name: str
    file_path: str | None = None
    playback_timecode: int | None = 0
    playback_duration: int | None = 0
    is_watched: bool = False
    last_played_at: str
    title: str | None = None
    anime_playback: dict | None = None
    poster_file: str | None = None
    poster_url: str | None = None
    year: int | None = None
    media_type: str | None = None
    season: int | None = None
    episode: int | None = None
    imdb_id: str | None = None


class FileHistoryEntry(BaseModel):
    id: str
    title_id: str
    imdb_id: str | None = None
    infohash: str | None = None
    torrent_hash: str | None = None
    file_index: int | None = None
    season: int | None = None
    episode: int | None = None
    position_seconds: float = 0.0
    duration_seconds: float | None = None
    playback_timecode: int = 0
    playback_duration: int = 0
    watched: bool = False
    is_watched: bool = False
    last_played_at: str
    file_name: str | None = None
    title: str | None = None
    anime_playback: dict | None = None
    poster_file: str | None = None
    poster_url: str | None = None
    media_type: str | None = None


class MarkWatchedRequest(BaseModel):
    title_id: str | None = None
    imdb_id: str | None = None
    torrent_hash: str | None = None
    file_index: int | None = None
    season: int | None = None
    episode: int | None = None
    watched: bool = True


class NextUnwatchedItem(BaseModel):
    title_id: str | None = None
    imdb_id: str | None = None
    torrent_hash: str | None = None
    season: int | None = None
    episode: int | None = None
    next_episode: int | None = None
    file_id: int | None = None
    file_name: str | None = None
