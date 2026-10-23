import asyncio
import logging
import os
import sys
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiofiles
import httpx

from backend import __version__
from backend.core.settings import (
    find_mpv_binary,
    get_data_dir,
)
from backend.core.settings import (
    load_settings as core_load_settings,
)
from backend.core.settings import (
    save_settings as core_save_settings,
)
from backend.core.settings.config import config
from backend.services.autostart import (
    is_autostart_enabled,
    set_autostart,
)
from backend.services.i18n import t
from backend.services.magnet import (
    register_magnet_handler,
    unregister_magnet_handler,
)

logger = logging.getLogger(__name__)


class SettingsService:
    def __init__(
        self,
        torrserver_client: Any,
        settings_provider: Callable[[], str],
    ):
        self._torrserver = torrserver_client
        self._get_ts_url = settings_provider

    def load_settings(self) -> dict[str, Any]:
        return core_load_settings()

    def save_settings(self, prefs: dict[str, Any]) -> None:
        core_save_settings(prefs)

    def get_settings(self) -> dict[str, Any]:
        prefs = self.load_settings()
        return {
            "torrserver_url": self._get_ts_url(),
            "language": prefs.get("language", "ru"),
            "jackett_url": prefs.get("jackett_url", ""),
            "jackett_api_key": prefs.get("jackett_api_key", ""),
            "player_path": prefs.get("player_path", ""),
            "minimize_to_tray": prefs.get("minimize_to_tray", True),
            "autostart": is_autostart_enabled() if sys.platform == "win32" else bool(prefs.get("autostart", False)),
            "autostart_prompted": bool(prefs.get("autostart_prompted", False)),
            "torznab": prefs.get(
                "torznab",
                {
                    "enabled": prefs.get("torznab_enabled", False),
                    "url": prefs.get("jackett_url", ""),
                    "api_key": prefs.get("jackett_api_key", ""),
                    "categories": prefs.get(
                        "torznab_categories",
                        [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060],
                    ),
                },
            ),
        }

    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        prefs = self.load_settings()

        if updates.get("onboarding_complete") is not None:
            prefs["onboarding_complete"] = updates["onboarding_complete"]

        if updates.get("minimize_to_tray") is not None:
            prefs["minimize_to_tray"] = updates["minimize_to_tray"]
            prefs["close_behavior_configured"] = True

        if updates.get("autostart") is not None:
            autostart_val = bool(updates["autostart"])
            prefs["autostart"] = autostart_val
            set_autostart(autostart_val)

        if updates.get("autostart_prompted") is not None:
            prefs["autostart_prompted"] = bool(updates["autostart_prompted"])

        if updates.get("register_magnet_handler") is not None:
            reg = updates["register_magnet_handler"]
            prefs["register_magnet_handler"] = reg
            if reg:
                register_magnet_handler()
            else:
                unregister_magnet_handler()

        if updates.get("player_type") is not None:
            prefs["player_type"] = updates["player_type"]
        if updates.get("player_path") is not None:
            prefs["player_path"] = updates["player_path"]

        if updates.get("torrserver_url") is not None:
            new_url = updates["torrserver_url"].rstrip("/")
            prefs["torrserver_endpoint"] = new_url

        if updates.get("language") is not None:
            prefs["language"] = updates["language"]

        # Torznab / Jackett updates
        if updates.get("torznab") is not None:
            tz = updates["torznab"]
            if hasattr(tz, "model_dump"):
                tz = tz.model_dump()
            elif hasattr(tz, "dict"):
                tz = tz.dict()
            if isinstance(tz, dict):
                prefs["torznab"] = tz
                if "url" in tz:
                    prefs["jackett_url"] = tz["url"]
                    prefs["torznab_url"] = tz["url"]
                if "api_key" in tz:
                    prefs["jackett_api_key"] = tz["api_key"]
                    prefs["torznab_api_key"] = tz["api_key"]
                if "enabled" in tz:
                    prefs["torznab_enabled"] = tz["enabled"]
                if "categories" in tz:
                    prefs["torznab_categories"] = tz["categories"]

        if updates.get("torznab_url") is not None:
            prefs["torznab_url"] = updates["torznab_url"]
            prefs["jackett_url"] = updates["torznab_url"]
            if "torznab" in prefs and isinstance(prefs["torznab"], dict):
                prefs["torznab"]["url"] = updates["torznab_url"]

        if updates.get("torznab_api_key") is not None:
            prefs["torznab_api_key"] = updates["torznab_api_key"]
            prefs["jackett_api_key"] = updates["torznab_api_key"]
            if "torznab" in prefs and isinstance(prefs["torznab"], dict):
                prefs["torznab"]["api_key"] = updates["torznab_api_key"]

        if updates.get("torznab_enabled") is not None:
            prefs["torznab_enabled"] = updates["torznab_enabled"]
            if "torznab" in prefs and isinstance(prefs["torznab"], dict):
                prefs["torznab"]["enabled"] = updates["torznab_enabled"]

        if updates.get("torznab_categories") is not None:
            prefs["torznab_categories"] = updates["torznab_categories"]
            if "torznab" in prefs and isinstance(prefs["torznab"], dict):
                prefs["torznab"]["categories"] = updates["torznab_categories"]

        if updates.get("jackett_url") is not None:
            prefs["jackett_url"] = updates["jackett_url"]
            prefs["torznab_url"] = updates["jackett_url"]
            if "torznab" in prefs and isinstance(prefs["torznab"], dict):
                prefs["torznab"]["url"] = updates["jackett_url"]

        if updates.get("jackett_api_key") is not None:
            prefs["jackett_api_key"] = updates["jackett_api_key"]
            prefs["torznab_api_key"] = updates["jackett_api_key"]
            if "torznab" in prefs and isinstance(prefs["torznab"], dict):
                prefs["torznab"]["api_key"] = updates["jackett_api_key"]

        self.save_settings(prefs)
        return {"torrserver_url": self._get_ts_url()}

    async def get_server_status(self) -> dict[str, Any]:
        url = self._get_ts_url()
        active = await self._torrserver.probe(url)
        return {"active": active, "url": url}

    async def check_updates(self) -> dict[str, Any]:
        app_version = __version__
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    config.GITHUB_API_URL,
                    timeout=5.0,
                )
                if r.status_code == 403:
                    return {
                        "has_update": False,
                        "latest": t("err_github_limit"),
                        "current": app_version,
                        "url": "",
                    }
                if r.status_code == 404:
                    return {
                        "has_update": False,
                        "latest": t("err_releases_not_found"),
                        "current": app_version,
                        "url": "",
                    }
                r.raise_for_status()
                data = r.json()
                latest = data.get("tag_name", "")
                latest_clean = latest.lstrip("v").strip()
                current_clean = app_version.lstrip("v").strip()

                def parse_ver(v: str):
                    parts = []
                    for p in v.split("."):
                        if p.isdigit():
                            parts.append(int(p))
                        else:
                            break
                    return tuple(parts)

                has_update = bool(latest_clean) and parse_ver(latest_clean) > parse_ver(
                    current_clean
                )

                url = data.get("html_url", "")
                return {
                    "has_update": has_update,
                    "latest": latest,
                    "current": app_version,
                    "url": url,
                }
        except httpx.HTTPError as e:
            logger.exception("Failed to check for updates from GitHub")
            return {
                "has_update": False,
                "latest": "",
                "current": app_version,
                "url": "",
                "error": str(e),
            }

    def create_backup_zip(self) -> Path:
        data_dir = get_data_dir()
        fd, tmp_path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)

        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_name in [
                "history.sqlite3",
                "settings.json",
                "preferences.json",
            ]:
                p = data_dir / file_name
                if p.exists():
                    zf.write(p, file_name)

            posters_dir = data_dir / "posters"
            if posters_dir.exists():
                for root, _, files in os.walk(posters_dir):
                    for f in files:
                        file_path = Path(root) / f
                        arcname = file_path.relative_to(data_dir)
                        zf.write(file_path, arcname)

        return Path(tmp_path)

    def restore_backup_zip(self, zip_path: Path) -> None:
        data_dir = get_data_dir()
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                target_path = (data_dir / member).resolve()
                if not target_path.is_relative_to(data_dir.resolve()):
                    raise ValueError(f"Invalid zip payload: {member}")
            zf.extractall(data_dir)

    async def get_diagnostics(self) -> dict[str, Any]:
        data_dir = get_data_dir()
        db_file = data_dir / "history.sqlite3"
        db_size = db_file.stat().st_size if db_file.exists() else 0

        mpv_bin = find_mpv_binary()
        mpv_path_str = str(mpv_bin) if mpv_bin else "Не обнаружен"

        torrserver_url = self._get_ts_url()

        try:
            ts_probe = await self._torrserver.probe(torrserver_url)
        except httpx.HTTPError:
            ts_probe = False

        ts_ver = "unknown"
        if ts_probe:
            try:
                res = await self._torrserver.read_torrserver(torrserver_url)
                if isinstance(res, dict):
                    ts_ver = res.get("version", "unknown")
            except httpx.HTTPError:
                pass

        log_file = data_dir / "mpv_debug.log"
        last_error = ""
        if log_file.exists():
            try:
                async with aiofiles.open(log_file, encoding="utf-8", errors="ignore") as f:
                    content = await f.read()
                lines = content.splitlines()
                errs = [
                    l
                    for l in lines[-100:]
                    if "error" in l.lower() or "exception" in l.lower()
                ]
                if errs:
                    last_error = errs[-1]
            except OSError as e:
                logger.warning("Failed to read MPV log file: %s", e)

        return {
            "torrserver_version": ts_ver,
            "mpv_path": mpv_path_str,
            "db_size": db_size,
            "data_folder": str(data_dir),
            "last_error": last_error,
        }

    async def open_data_folder(self) -> dict[str, Any]:
        data_dir = get_data_dir()
        path_str = str(data_dir)

        if os.name == "nt":
            cmd = ["explorer.exe", path_str]
        elif sys.platform == "darwin":
            cmd = ["open", path_str]
        else:
            cmd = ["xdg-open", path_str]

        try:
            await asyncio.create_subprocess_exec(*cmd)
        except OSError as e:
            logger.error("Failed to open data folder %s: %s", path_str, e)
            return {"status": "error", "message": str(e)}

        return {"status": "ok"}
