from pydantic import BaseModel


class SettingsUpdate(BaseModel):
    torrserver_url: str | None = None
    language: str | None = None
    jackett_url: str | None = None
    jackett_api_key: str | None = None
    player_type: str | None = None
    player_path: str | None = None
    minimize_to_tray: bool | None = None
    register_magnet_handler: bool | None  = None
    onboarding_complete: bool | None  = None
