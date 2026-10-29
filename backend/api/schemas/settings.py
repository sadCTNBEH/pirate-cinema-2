from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

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
    auto_next: bool | None = None
    audio_languages: list[Literal["ru", "en", "original", "auto"]] | None = Field(default=None, min_length=1, max_length=4)
    yummyanime_public_key: str | None = None
    yummyanime_private_key: str | None = None
    subtitle_languages: list[Literal["ru", "en", "auto", "off"]] | None = Field(default=None, min_length=1, max_length=3)

    @field_validator("audio_languages", "subtitle_languages")
    @classmethod
    def validate_languages(cls, values):
        if values is None:
            return values
        if len(values) != len(set(values)) or ("off" in values and values != ["off"]) or ("auto" in values and values[-1] != "auto"):
            raise ValueError("Languages must be unique; auto must be last and off must be exclusive")
        return values


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
    auto_next: bool = True
    audio_languages: list[str] = Field(default_factory=lambda: ["auto"])
    subtitle_languages: list[str] = Field(default_factory=lambda: ["auto"])
    yummyanime_public_key: str = "bz7uk_nr9bouyrn9"
    yummyanime_private_key: str = ""
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
