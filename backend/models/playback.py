from dataclasses import dataclass
from typing import Optional


@dataclass
class PlayCommand:
    hash: str
    file_id: int
    file_name: str
    start_time: Optional[int] = None
    audio_track: Optional[int] = None
    subtitle_track: Optional[int] = None


@dataclass
class PlaybackState:
    hash: str
    file_id: int
    timecode: int = 0
    duration: int = 0
    audio_track: int = 0
    subtitle_track: int = 0
    is_watched: bool = False