from pydantic import BaseModel


class PlayRequest(BaseModel):
    hash: str
    file_id: int
    file_name: str
    start_time: int = 0
    audio_track: int | None = None
    subtitle_track: int | None = None

class PlaybackState(BaseModel):
    hash: str
    file_id: int
    timecode: int
    duration: int
    audio_track: int
    subtitle_track: int
    is_watched: bool