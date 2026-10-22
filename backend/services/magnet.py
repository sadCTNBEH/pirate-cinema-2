from __future__ import annotations

import inspect
import logging
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import httpx

from backend.core.settings import get_data_dir
from backend.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)


def _app_command() -> str:
    """Возвращает команду запуска (python -m backend.main или exe) с плейсхолдером для ссылки."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'

    return f'"{sys.executable}" -m backend.main "%1"'


def _delete_reg_key_recursive(key, subkey: str) -> None:
    """Рекурсивно удаляет ветку реестра Windows со всеми подветками."""
    import winreg

    try:
        with winreg.OpenKey(key, subkey, 0, winreg.KEY_ALL_ACCESS) as current_key:
            while True:
                try:
                    sub_name = winreg.EnumKey(current_key, 0)
                    _delete_reg_key_recursive(current_key, sub_name)
                except OSError:
                    break
        winreg.DeleteKey(key, subkey)
    except OSError as e:
        logger.debug("Не удалось удалить ключ реестра %s: %s", subkey, e)


def register_magnet_handler() -> bool:
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\magnet")
            winreg.SetValue(key, "", winreg.REG_SZ, "URL:Magnet Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

            cmd_key = winreg.CreateKey(key, r"shell\open\command")
            winreg.SetValue(cmd_key, "", winreg.REG_SZ, _app_command())
            return True
        except OSError as e:
            logger.error("Failed to register magnet handler in Windows registry: %s", e)
            return False
    else:
        desktop = Path.home() / ".local/share/applications/pirate-cinema-magnet.desktop"
        desktop.parent.mkdir(parents=True, exist_ok=True)

        exec_cmd = _app_command().replace('"%1"', "%u")

        content = (
            "[Desktop Entry]\n"
            "Name=Pirate Cinema\n"
            f"Exec={exec_cmd}\n"
            "Type=Application\n"
            "MimeType=x-scheme-handler/magnet;\n"
            "NoDisplay=true\n"
        )

        try:
            desktop.write_text(content, encoding="utf-8")
            subprocess.run(
                [
                    "xdg-mime",
                    "default",
                    "pirate-cinema-magnet.desktop",
                    "x-scheme-handler/magnet",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except (OSError, subprocess.SubprocessError):
            logger.exception("Failed to register magnet handler")
            return False


def unregister_magnet_handler() -> bool:
    if sys.platform == "win32":
        try:
            import winreg

            _delete_reg_key_recursive(
                winreg.HKEY_CURRENT_USER, r"Software\Classes\magnet"
            )
            return True
        except OSError:
            logger.exception(
                "Failed to unregister magnet handler from Windows registry"
            )
            return False
    else:
        desktop = Path.home() / ".local/share/applications/pirate-cinema-magnet.desktop"
        try:
            if desktop.exists():
                desktop.unlink()
                logger.info("Magnet .desktop file successfully removed.")
            else:
                logger.debug("Magnet .desktop file not found, nothing to remove.")
            return True
        except OSError:
            logger.exception("Failed to remove Linux .desktop file")
            return False


class MagnetService:
    def __init__(
        self,
        torrserver_client: Any,
        settings_provider: Callable[[], str],
        metadata_service: Any,
        library_repo: Any = None,
    ):
        self._torrserver = torrserver_client
        self._get_ts_url = settings_provider
        self._metadata_service = metadata_service
        self._library_repo = library_repo

    async def add_magnet(self, magnet: str, title: str = "") -> dict[str, Any]:
        torrserver_url = self._get_ts_url()
        effective_title = title or magnet[:60]
        try:
            result = await self._torrserver.add_magnet(
                torrserver_url, magnet, effective_title
            )
        except httpx.HTTPStatusError as e:
            logger.error("TorrServer status error while adding magnet: %s", e)
            raise ExternalServiceError(
                f"TorrServer error: {e.response.status_code}", status_code=502
            ) from e
        except httpx.RequestError as e:
            logger.error("TorrServer connection error while adding magnet: %s", e)
            raise ExternalServiceError(
                f"TorrServer network error: {e}", status_code=502
            ) from e

        torrent_hash = result.get("hash")
        if torrent_hash:
            if self._library_repo:
                try:
                    await anyio.to_thread.run_sync(
                        self._library_repo.ensure_torrent,
                        torrent_hash,
                        effective_title,
                    )
                except sqlite3.Error as db_err:
                    logger.debug("Failed to ensure torrent in library DB: %s", db_err)

            # Запуск фонового получения метаданных
            if self._metadata_service:
                self._metadata_service.trigger_metadata_fetch(
                    torrent_hash, title or torrent_hash
                )

        return result

    async def delete_torrent(self, hash: str) -> dict[str, str]:
        if str(hash).startswith("online:"):
            if self._library_repo:
                try:
                    await anyio.to_thread.run_sync(
                        self._library_repo.delete_torrent, hash
                    )
                except sqlite3.Error as e:
                    logger.error("Failed to delete online item %s from DB: %s", hash, e)
            return {"status": "removed"}

        # 1. Clean local database
        if self._library_repo:
            try:
                await anyio.to_thread.run_sync(
                    self._library_repo.delete_torrent, hash
                )
            except sqlite3.Error as e:
                logger.error("Failed to delete torrent %s from DB: %s", hash, e)

        # 2. Clean poster file if present
        try:
            poster_path = get_data_dir() / "posters" / f"{hash}.jpg"
            if poster_path.exists():
                poster_path.unlink(missing_ok=True)
        except OSError as e:
            logger.debug("Failed to remove poster file for %s: %s", hash, e)

        # 3. Clean TorrServer (best effort)
        if str(hash).startswith("online:"):
            return {"status": "removed"}
        torrserver_url = self._get_ts_url()
        try:
            res = self._torrserver.remove_torrent(torrserver_url, hash)
            if inspect.isawaitable(res):
                await res
        except (httpx.HTTPError, ValueError) as e:
            logger.warning(
                "TorrServer remove torrent %s skipped/failed: %s", hash, e
            )

        return {"status": "removed"}

    def register_magnet_handler(self) -> bool:
        return register_magnet_handler()

    def unregister_magnet_handler(self) -> bool:
        return unregister_magnet_handler()
