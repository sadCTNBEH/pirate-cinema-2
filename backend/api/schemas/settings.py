from pydantic import BaseModel


class SettingsUpdate(BaseModel):
    torrserver_url: str | None = None
    language: str | None = None
    jackett_url: str | None = None
    jackett_api_key: str | None = None