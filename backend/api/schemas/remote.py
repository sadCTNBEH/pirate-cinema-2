"""Pydantic schemas and DTOs for remote control and mobile playback."""

from typing import Any

from pydantic import BaseModel, Field


class PairRequest(BaseModel):
    code: str = Field(
        min_length=1, max_length=32, description="Pairing code displayed on host screen"
    )


class PairResponse(BaseModel):
    paired: bool = Field(default=True)
    token: str = Field(min_length=1, description="Authorized session token")


class RemoteAuthRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128, description="Authentication token")


class RemotePlayRequest(BaseModel):
    hash: str | None = Field(default=None, max_length=128, description="Torrent hash")
    magnet: str | None = Field(default=None, max_length=4096, description="Torrent magnet link")
    title: str = Field(default="", max_length=500, description="Media or release title")
    file_id: int | None = Field(default=None, ge=0, description="File index in torrent")
    file_name: str | None = Field(default=None, max_length=500, description="File name")
    fullscreen: bool | None = Field(default=False, description="Open player in fullscreen")


class MobilePlayRequest(RemotePlayRequest):
    season: int | None = Field(default=None, ge=0, le=1000, description="Season number")
    episode: int | None = Field(default=None, ge=0, le=10000, description="Episode number")
    absolute: int | None = Field(
        default=None, ge=0, le=10000, description="Absolute episode number"
    )


class MobileProgress(BaseModel):
    sequence: int = Field(ge=0, description="Sequence counter")
    position: float = Field(
        default=0.0, ge=0.0, le=604800.0, description="Current playback timecode in seconds"
    )
    duration: float = Field(
        default=0.0, ge=0.0, le=604800.0, description="Media duration in seconds"
    )
    close: bool = Field(default=False, description="Terminate mobile streaming session")


class RemoteSeekRequest(BaseModel):
    seconds: float = Field(ge=-86400, le=86400, description="Seek offset or target time in seconds")
    mode: str = Field(default="relative", pattern=r"^(relative|absolute|absolute\+exact|percent)$")


class RemoteVolumeRequest(BaseModel):
    volume: int = Field(ge=0, le=100, description="Volume level from 0 to 100")


class RemoteInfoResponse(BaseModel):
    url: str
    local_url: str
    ip_url: str
    hostname: str
    ip: str
    port: int
    qr_svg: str
    ip_qr_svg: str


class MobilePlayResponse(BaseModel):
    token: str
    url: str
    mode: str
    duration: float
    hash: str
    file_id: int
    file_name: str
    resume: int
    next: dict[str, Any] | None = None
    previous: dict[str, Any] | None = None
    expires_in: int = 180
