"""Pydantic schemas and DTOs for player commands and state."""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from backend.models.playback import PlayCommand


class PlayRequest(BaseModel):
    hash: str = Field(min_length=1, max_length=128, description="Torrent hash or video identifier")
    file_id: int = Field(ge=0, description="Video file index")
    file_name: str = Field(min_length=1, max_length=500, description="Name of the video file")
    start_time: int | None = Field(default=None, ge=0, description="Start playback time in seconds")
    audio_track: int | None = Field(default=None, ge=0, description="Audio track index")
    subtitle_track: int | None = Field(default=None, ge=0, description="Subtitle track index")

    def to_command(self) -> PlayCommand:
        return PlayCommand(
            hash=self.hash,
            file_id=self.file_id,
            file_name=self.file_name,
            start_time=self.start_time,
            audio_track=self.audio_track,
            subtitle_track=self.subtitle_track,
        )


class SeekRequest(BaseModel):
    seconds: float = Field(
        ge=-86400, le=86400, description="Seek offset in seconds or target timestamp"
    )
    mode: str = Field(default="relative", pattern=r"^(relative|absolute|absolute\+exact|percent)$")

    def to_command(self) -> list[Any]:
        return ["seek", self.seconds, self.mode]


class SetVolumeRequest(BaseModel):
    volume: int = Field(ge=0, le=100, description="Volume level from 0 to 100")

    def to_command(self) -> list[Any]:
        return ["set_property", "volume", self.volume]


class PlayerCommandRequest(BaseModel):
    command: list[Any] = Field(min_length=1, max_length=10, description="MPV IPC command array")

    @field_validator("command")
    @classmethod
    def validate_command_structure(cls, v: list[Any]) -> list[Any]:
        if not v:
            raise ValueError("Command list must not be empty")
        if not isinstance(v[0], str):
            raise ValueError("First element of command must be a string action name")
        for item in v:
            if not isinstance(item, (str, int, float, bool)):
                raise ValueError("Command parameters must be primitive scalar values")
        return v


class NextRequest(BaseModel):
    hash: str = Field(min_length=1, max_length=128)
    file_id: int = Field(ge=0)


class MagnetRequest(BaseModel):
    magnet: str = Field(min_length=10, max_length=4096)
    title: str = Field(default="", max_length=500)


class SetAudioTrackRequest(BaseModel):
    hash: str = Field(min_length=1, max_length=128)
    track_id: int = Field(ge=0)
    file_id: int | None = Field(default=None, ge=0)


class PlayerFullscreenPayload(BaseModel):
    fullscreen: bool | None = Field(default=None)


class SubtitleSearch(BaseModel):
    hash: str = Field(min_length=1, max_length=128)
    file_id: int = Field(ge=0)
    title: str = Field(default="", max_length=300)
    year: int | None = Field(default=None, ge=1880, le=2200)
    season: int | None = Field(default=None, ge=0, le=1000)
    episode: int | None = Field(default=None, ge=0, le=10000)
    language: str = Field(default="RU,EN", pattern=r"^(RU|EN|RU,EN)$")


class SubtitleChoice(BaseModel):
    hash: str = Field(min_length=1, max_length=128)
    file_id: int = Field(ge=0)
    token: str = Field(min_length=1, max_length=256)


class FileSelectionRequest(BaseModel):
    hash: str = Field(min_length=1, max_length=128)
    season: int | None = Field(default=None, ge=0, le=1000)
    episode: int | None = Field(default=None, ge=0, le=10000)
    absolute: int | None = Field(default=None, ge=0, le=10000)
    release_title: str = Field(default="", max_length=500)
    media_id: str | None = Field(default=None, max_length=256)
    file_id: int | None = Field(default=None, ge=0)


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
