from typing import Optional
from pydantic import BaseModel


class SettingsUpdate(BaseModel):
    torrserver_url: Optional[str] = None
    language: Optional[str] = None
    jackett_url: Optional[str] = None
    jackett_api_key: Optional[str] = None
    player_type: Optional[str] = None
    player_path: Optional[str] = None
    minimize_to_tray: Optional[bool] = None
    register_magnet_handler: Optional[bool] = None
    onboarding_complete: Optional[bool] = None


class SettingsResponse(BaseModel):
    torrserver_url: str
    language: str
    jackett_url: str = ""
    jackett_api_key: str = ""


class ServerStatusResponse(BaseModel):
    active: bool
    url: str


class UpdatesResponse(BaseModel):
    has_update: bool
    latest: str
    current: str
    url: str
    error: Optional[str] = None


class DiagnosticsResponse(BaseModel):
    torrserver_version: str
    mpv_path: str
    db_size: int
    data_folder: str
    last_error: str
