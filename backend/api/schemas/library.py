from typing import Any, Optional
from pydantic import BaseModel


class RecentMediaItem(BaseModel):
    torrent_hash: str
    file_index: int
    file_name: str
    playback_timecode: Optional[int] = 0
    playback_duration: Optional[int] = 0
    is_watched: int = 0
    last_played_at: str
    title: Optional[str] = None
    poster_file: Optional[str] = None
    year: Optional[int] = None


class TorrentFilesStructureResponse(BaseModel):
    type: str
    seasons: dict[str, list[dict[str, Any]]] = {}
    movies: list[dict[str, Any]] = []
    flat_files: list[dict[str, Any]] = []
