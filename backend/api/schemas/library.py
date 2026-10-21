from typing import Any

from pydantic import BaseModel, Field


class LibraryFilter(BaseModel):
    type: str | None = None
    status: str | None = None
    year: int | None = None
    genre: str | list[str] | None = None
    sort: str | None = None


class SeasonProgress(BaseModel):
    season: int | str
    watched: int = 0
    total: int = 0
    progress_percent: float = 0.0
    next_episode: int | None = None
    total_files: int = 0
    watched_files: int = 0
    progress: float = 0.0
    is_completed: bool = False
    episodes: list[dict[str, Any]] = Field(default_factory=list)


class LibraryProgressResponse(BaseModel):
    title_id: str = ""
    torrent_hash: str = ""
    hash: str = ""
    total_files: int = 0
    watched_files: int = 0
    progress: float = 0.0
    is_completed: bool = False
    seasons: list[SeasonProgress] | dict[str, SeasonProgress] = Field(default_factory=list)
    watched_episode_keys: list[str] = Field(default_factory=list)

    def model_post_init(self, context: Any, /) -> None:
        if not self.title_id:
            self.title_id = self.torrent_hash or self.hash
        if not self.torrent_hash:
            self.torrent_hash = self.title_id or self.hash
        if not self.hash:
            self.hash = self.torrent_hash


class NextUnwatchedResponse(BaseModel):
    torrent_hash: str
    hash: str = ""
    file_id: int
    file_name: str
    playback_timecode: int = 0
    playback_duration: int = 0
    is_watched: bool = False
    season: int | None = None
    episode: int | None = None

    def model_post_init(self, context: Any, /) -> None:
        if not self.hash:
            self.hash = self.torrent_hash


class LibraryItemResponse(BaseModel):
    hash: str
    torrent_hash: str
    title: str
    poster_file: str | None = None
    poster_url: str | None = None
    type: str | None = None
    media_type: str | None = None
    year: int | None = None
    rating: float | None = None
    genres: list[str] = Field(default_factory=list)
    overview: str | None = None
    overview_ru: str | None = None
    status: str = "unwatched"
    progress: float = 0.0
    total_files: int = 0
    watched_files: int = 0
    last_played_at: str | None = None


class RecentMediaItem(BaseModel):
    torrent_hash: str
    file_index: int
    file_name: str
    playback_timecode: int | None = 0
    playback_duration: int | None = 0
    is_watched: int = 0
    last_played_at: str
    title: str | None = None
    poster_file: str | None = None
    year: int | None = None


class TorrentFilesStructureResponse(BaseModel):
    type: str
    seasons: dict[str, list[dict[str, Any]]] = {}
    movies: list[dict[str, Any]] = []
    flat_files: list[dict[str, Any]] = []
