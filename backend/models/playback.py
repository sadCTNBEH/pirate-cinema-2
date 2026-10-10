from dataclasses import dataclass


@dataclass
class PlaybackState:
    hash: str
    file_id: int
    timecode: int = 0
    duration: int = 0
    audio_track: int = 0
    subtitle_track: int = 0
    is_watched: bool = False