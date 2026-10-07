from pydantic import BaseModel


class PlayRequest(BaseModel):
    hash: str
    file_id: int
    file_name: str
    start_time: int = 0
    audio_track: int | None = None
    subtitle_track: int | None = None


class NextRequest(BaseModel):
    hash: str
    file_id: int


class MagnetRequest(BaseModel):
    magnet: str
    title: str = ""