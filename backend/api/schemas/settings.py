from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from backend.models.search import TorznabConfig


class SettingsUpdate(BaseModel):
    hotkeys: (
        dict[
            Annotated[str, StringConstraints(pattern=r"^[a-zA-Z][a-zA-Z0-9]{0,39}$")],
            Annotated[
                str,
                StringConstraints(
                    max_length=80,
                    pattern=r"^(?:(?:Ctrl\+)?(?:Alt\+)?(?:Shift\+)?[a-zA-Z][a-zA-Z0-9]*|)$",
                ),
            ],
        ]
        | None
    ) = Field(default=None, max_length=64)
    torrserver_url: str | None = None
    language: str | None = None
    jackett_url: str | None = None
    jackett_api_key: str | None = None
    torznab: TorznabConfig | None = None
    torznab_url: str | None = None
    torznab_api_key: str | None = None
    torznab_enabled: bool | None = None
    torznab_categories: list[int] | None = None
    player_type: str | None = None
    player_path: str | None = None
    minimize_to_tray: bool | None = None
    register_magnet_handler: bool | None = None
    onboarding_complete: bool | None = None
    autostart: bool | None = None
    autostart_prompted: bool | None = None


class SettingsResponse(BaseModel):
    hotkeys: dict[str, str] = Field(default_factory=dict)
    torrserver_url: str
    language: str
    jackett_url: str = ""
    jackett_api_key: str = ""
    player_path: str = ""
    minimize_to_tray: bool = True
    autostart: bool = False
    autostart_prompted: bool = False
    torznab: TorznabConfig = Field(default_factory=TorznabConfig)


class ServerStatusResponse(BaseModel):
    active: bool
    url: str


class UpdatesResponse(BaseModel):
    has_update: bool
    latest: str
    current: str
    url: str
    error: str | None = None


class DiagnosticsResponse(BaseModel):
    torrserver_version: str
    mpv_path: str
    db_size: int
    data_folder: str
    last_error: str
