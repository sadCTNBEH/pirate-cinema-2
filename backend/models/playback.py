from dataclasses import dataclass, field
from typing import Any


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
    is_muted: bool = False
    is_buffering: bool = False
    is_online: bool = False
    online_provider: str | None = None
    online_id: str | None = None
    playlist_id: str | None = None
    episode_index: int | None = None
    is_ready: bool = False
    has_next: bool = False
    resume_candidate: dict[str, Any] | None = None
    track_list: list[dict[str, Any]] = field(default_factory=list)
    chapter_list: list[dict[str, Any]] = field(default_factory=list)
