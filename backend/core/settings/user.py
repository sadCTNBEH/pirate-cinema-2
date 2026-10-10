import json
import logging
from pathlib import Path
from typing import Any

from backend.core.settings.base import get_data_dir
from backend.core.settings.config import config
from backend.models.search import TorznabConfig

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS: dict[str, Any] = {
    "language": "ru",
    "torrserver_url": config.TORRSERVER_DEFAULT_URL,
    "torrserver_endpoint": config.TORRSERVER_DEFAULT_URL,
    "jackett_url": "",
    "jackett_api_key": "",
    "jackett_key": "",
    "torznab_url": "",
    "torznab_api_key": "",
    "torznab_enabled": False,
    "torznab_categories": [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060],
    "torznab": {
        "enabled": False,
        "url": "",
        "api_key": "",
        "categories": [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060],
    },
    "player_type": "mpv",  # "mpv" | "external"
    "player_path": "",
    "embedded_player": True,
    "onboarding_complete": False,
    "minimize_to_tray": True,
    "register_magnet_handler": False,
}


def settings_path() -> Path:
    return get_data_dir() / "settings.json"


def load_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        merged = DEFAULT_SETTINGS.copy()
        merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})

        # Sync TorrServer aliases
        ts_url = (
            merged.get("torrserver_url")
            or merged.get("torrserver_endpoint")
            or config.TORRSERVER_DEFAULT_URL
        )
        merged["torrserver_url"] = ts_url
        merged["torrserver_endpoint"] = ts_url

        # Sync Jackett / Torznab aliases
        tz_raw = merged.get("torznab")
        tz_dict = tz_raw.copy() if isinstance(tz_raw, dict) else {}

        t_url = (
            tz_dict.get("url")
            or merged.get("torznab_url")
            or merged.get("jackett_url")
            or ""
        )
        t_key = (
            tz_dict.get("api_key")
            or merged.get("torznab_api_key")
            or merged.get("jackett_api_key")
            or merged.get("jackett_key")
            or ""
        )
        t_cats = (
            tz_dict.get("categories")
            or merged.get("torznab_categories")
            or [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060]
        )
        t_enabled = tz_dict.get("enabled", merged.get("torznab_enabled", bool(t_url)))

        merged["jackett_url"] = t_url
        merged["jackett_api_key"] = t_key
        merged["jackett_key"] = t_key
        merged["torznab_url"] = t_url
        merged["torznab_api_key"] = t_key
        merged["torznab_enabled"] = t_enabled
        merged["torznab_categories"] = t_cats
        merged["torznab"] = {
            "enabled": t_enabled,
            "url": t_url,
            "api_key": t_key,
            "categories": t_cats,
        }

        return merged
    except (OSError, json.JSONDecodeError):
        logger.exception("Error loading settings")
        return DEFAULT_SETTINGS.copy()


def save_settings(data: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_settings()
    current.update(data)

    # Sync torznab and jackett fields before saving
    if "torznab" in data and isinstance(data["torznab"], dict):
        tz = data["torznab"]
        if "url" in tz:
            current["jackett_url"] = tz["url"]
            current["torznab_url"] = tz["url"]
        if "api_key" in tz:
            current["jackett_api_key"] = tz["api_key"]
            current["torznab_api_key"] = tz["api_key"]
        if "enabled" in tz:
            current["torznab_enabled"] = tz["enabled"]
        if "categories" in tz:
            current["torznab_categories"] = tz["categories"]
    elif "jackett_url" in data or "jackett_api_key" in data:
        j_url = current.get("jackett_url", "")
        j_key = current.get("jackett_api_key", "")
        current["torznab_url"] = j_url
        current["torznab_api_key"] = j_key
        current["torznab"] = {
            "enabled": current.get("torznab_enabled", bool(j_url)),
            "url": j_url,
            "api_key": j_key,
            "categories": current.get(
                "torznab_categories", [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060]
            ),
        }

    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def get_torrserver_url() -> str:
    return load_settings().get("torrserver_endpoint", config.TORRSERVER_DEFAULT_URL)


def get_torznab_config() -> TorznabConfig:
    s = load_settings()
    tz = s.get("torznab") or {}
    enabled = tz.get("enabled", s.get("torznab_enabled", False))
    url = tz.get("url") or s.get("torznab_url") or s.get("jackett_url") or ""
    api_key = (
        tz.get("api_key") or s.get("torznab_api_key") or s.get("jackett_api_key") or ""
    )
    categories = tz.get("categories") or s.get("torznab_categories") or []
    return TorznabConfig(
        enabled=enabled,
        url=url,
        api_key=api_key,
        categories=categories,
    )


def resolve_mpv_binary(prefs: dict[str, Any] | None = None) -> Path:
    import os
    import shutil
    import sys

    if prefs is None:
        prefs = load_settings()
    if prefs.get("player_path"):
        custom_path = Path(prefs["player_path"])
        if custom_path.is_file():
            return custom_path

    if sys.platform == "win32":
        mpv_bin = get_data_dir() / "vendor" / "mpv" / "mpv.exe"
        if not mpv_bin.is_file():
            prog_files = (
                Path(os.environ.get("ProgramFiles", "C:/Program Files"))
                / "MPV Player"
                / "mpv.exe"
            )
            if prog_files.is_file():
                mpv_bin = prog_files
    else:
        mpv_bin = get_data_dir() / "vendor" / "mpv" / "mpv"

    if not mpv_bin.is_file():
        which_mpv = shutil.which("mpv")
        mpv_bin = Path(which_mpv) if which_mpv else Path("mpv")

    return mpv_bin
