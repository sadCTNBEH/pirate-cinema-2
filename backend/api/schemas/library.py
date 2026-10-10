from typing import Any

from pydantic import BaseModel


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
