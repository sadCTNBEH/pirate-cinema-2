from backend.core.settings import load_settings
from backend.infrastructure.mpv.controller import MPVController

_mpv = MPVController()


def get_torrserver_url() -> str:
    return load_settings()["torrserver_endpoint"]