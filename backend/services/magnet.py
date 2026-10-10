from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from backend.exceptions import DatabaseError, ExternalServiceError
from backend.infrastructure.torrserver import client as torrserver

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

            key = winreg.CreateKey(
                winreg.HKEY_CURRENT_USER, r"Software\Classes\magnet"
            )
            winreg.SetValue(key, "", winreg.REG_SZ, "URL:Magnet Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

            cmd_key = winreg.CreateKey(key, r"shell\open\command")
            winreg.SetValue(cmd_key, "", winreg.REG_SZ, _app_command())
            return True
        except OSError as e:
            logger.error(
                "Failed to register magnet handler in Windows registry: %s", e
            )
            return False
    else:
        desktop = (
            Path.home()
            / ".local/share/applications/pirate-cinema-magnet.desktop"
        )
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
        desktop = (
            Path.home()
            / ".local/share/applications/pirate-cinema-magnet.desktop"
        )
        try:
            if desktop.exists():
                desktop.unlink()
                logger.info("Magnet .desktop file successfully removed.")
            else:
                logger.debug(
                    "Magnet .desktop file not found, nothing to remove."
                )
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
    ):
        self._torrserver = torrserver_client
        self._get_ts_url = settings_provider
        self._metadata_service = metadata_service

    async def add_magnet(
        self, magnet: str, title: str = ""
    ) -> dict[str, Any]:
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

        # Запуск фонового получения метаданных
        torrent_hash = result.get("hash")
        if torrent_hash and self._metadata_service:
            self._metadata_service.trigger_metadata_fetch(
                torrent_hash, title or torrent_hash
            )

        return result

    async def delete_torrent(self, hash: str) -> dict[str, str]:
        torrserver_url = self._get_ts_url()
        try:
            await self._torrserver.remove_torrent(torrserver_url, hash)
            return {"status": "removed"}
        except httpx.HTTPStatusError as e:
            logger.error("TorrServer status error while removing torrent %s: %s", hash, e)
            raise ExternalServiceError(
                f"TorrServer error: {e.response.status_code}", status_code=502
            ) from e
        except httpx.RequestError as e:
            logger.error("TorrServer connection error while removing torrent %s: %s", hash, e)
            raise ExternalServiceError(
                f"TorrServer network error: {e}", status_code=502
            ) from e
        except (ValueError, OSError) as e:
            logger.error("Failed to delete torrent %s: %s", hash, e)
            raise DatabaseError(str(e)) from e

    def register_magnet_handler(self) -> bool:
        return register_magnet_handler()

    def unregister_magnet_handler(self) -> bool:
        return unregister_magnet_handler()
