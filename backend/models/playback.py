from dataclasses import dataclass


@dataclass
class PlayCommand:
    hash: str
    file_id: int
    file_name: str
    start_time: int | None = None
    audio_track: int | None = None
    subtitle_track: int | None = None


@dataclass
class PlaybackState:
    hash: str
    file_id: int
    timecode: int = 0
    duration: int = 0
    audio_track: int = 0
    subtitle_track: int = 0
    is_watched: bool = False
    file_name: str = ""
    is_paused: bool = False
    volume: int = 100

