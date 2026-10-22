from typing import Any

from pydantic import BaseModel, Field, model_validator


class LibraryFilter(BaseModel):
    type: str | None = None
    status: str | None = None
    year: int | None = None
    year_from: int | None = None
    year_to: int | None = None
    genre: str | list[str] | None = None
    sort: str | None = None
    order: str | None = None
    limit: int | None = Field(default=None, ge=1, le=1000)
    offset: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_filter(self) -> "LibraryFilter":
        if self.type is not None:
            t = str(self.type).strip().lower()
            if t not in ("movie", "series", "all", ""):
                raise ValueError(f"Invalid type '{self.type}'. Must be 'movie' or 'series'.")
            self.type = t if t not in ("all", "") else None

        if self.status is not None:
            s = str(self.status).strip().lower()
            if s not in (
                "watching",
                "completed",
                "planned",
                "unwatched",
                "watched",
                "in_progress",
                "all",
                "",
            ):
                raise ValueError(
                    f"Invalid status '{self.status}'. Must be 'watching', 'completed', or 'planned'."
                )
            self.status = s if s not in ("all", "") else None

        if self.sort is not None:
            s = str(self.sort).strip().lower()
            allowed = {
                "title",
                "title_asc",
                "title_desc",
                "-title",
                "+title",
                "year",
                "year_asc",
                "year_desc",
                "-year",
                "+year",
                "added",
                "added_asc",
                "added_desc",
                "-added",
                "+added",
                "progress",
                "progress_asc",
                "progress_desc",
                "-progress",
                "+progress",
                "rating",
                "rating_asc",
                "rating_desc",
                "-rating",
                "+rating",
                "date",
                "recent",
                "last_played",
                "last_played_asc",
                "last_played_desc",
            }
            if s not in allowed:
                raise ValueError(
                    f"Invalid sort '{self.sort}'. Must be one of 'title', 'year', 'added', 'progress'."
                )

        if self.order is not None:
            o = str(self.order).strip().lower()
            if o not in ("asc", "desc", ""):
                raise ValueError(f"Invalid order '{self.order}'. Must be 'asc' or 'desc'.")
            self.order = o or None

        # Synchronize legacy year with year_from/year_to
        if self.year is not None:
            if self.year_from is None:
                self.year_from = self.year
            if self.year_to is None:
                self.year_to = self.year

        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("year_from cannot be greater than year_to")

        return self


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
    added_at: str | None = None


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
