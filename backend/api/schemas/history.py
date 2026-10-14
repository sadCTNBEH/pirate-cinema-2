from pydantic import BaseModel


class HistoryItemResponse(BaseModel):
    torrent_hash: str
    file_index: int
    file_name: str
    file_path: str | None = None
    playback_timecode: int | None = 0
    playback_duration: int | None = 0
    is_watched: bool = False
    last_played_at: str
    title: str | None = None
    poster_file: str | None = None
    year: int | None = None
    media_type: str | None = None
