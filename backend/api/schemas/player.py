from typing import Optional
from pydantic import BaseModel
from backend.models.playback import PlayCommand


class PlayRequest(BaseModel):
    hash: str
    file_id: int
    file_name: str
    start_time: int = 0
    audio_track: Optional[int] = None
    subtitle_track: Optional[int] = None

    def to_command(self) -> PlayCommand:
        return PlayCommand(
            hash=self.hash,
            file_id=self.file_id,
            file_name=self.file_name,
            start_time=self.start_time,
            audio_track=self.audio_track,
            subtitle_track=self.subtitle_track,
        )


class NextRequest(BaseModel):
    hash: str
    file_id: int


class MagnetRequest(BaseModel):
    magnet: str
    title: str = ""


class SetAudioTrackRequest(BaseModel):
    hash: str
    track_id: int
    file_id: Optional[int] = None


class PlayerStatusResponse(BaseModel):
    status: str


class PlaybackStateResponse(BaseModel):
    hash: str
    file_id: int
    timecode: int
    duration: int
    audio_track: int
    subtitle_track: int
    is_watched: bool


class MagnetResponse(BaseModel):
    hash: str
    title: str = ""


class AudioTrackResponse(BaseModel):
    track_id: int