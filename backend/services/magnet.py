from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

def _app_command() -> str:
    """Возвращает команду запуска (python -m backend.main или exe) с плейсхолдером для ссылки."""
    # Исправлено: добавлены кавычки для 'frozen'
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" "%1"'

    # Обертываем sys.executable в кавычки на случай пробелов в путях к Python
    return f'"{sys.executable}" -m backend.main "%1"'


def _delete_reg_key_recursive(key, subkey):
    """Рекурсивно удаляет ветку реестра Windows со всеми подветками."""
    import winreg
    try:
        with winreg.OpenKey(key, subkey, 0, winreg.KEY_ALL_ACCESS) as current_key:
            while True:
                try:
                    # Всегда берем первый элемент, так как индекс смещается при удалении
                    sub_name = winreg.EnumKey(current_key, 0)
                    _delete_reg_key_recursive(current_key, sub_name)
                except OSError:
                    break  # Подветок больше нет
        winreg.DeleteKey(key, subkey)
    except OSError as e:
        logger.debug(f"Не удалось удалить ключ реестра {subkey}: {e}")


def register_magnet_handler() -> bool:
    # Исправлено: добавлены кавычки для 'win32'
    if sys.platform == 'win32':
        try:
            import winreg
            # Создаем корневой ключ протокола
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\magnet")
            winreg.SetValue(key, "", winreg.REG_SZ, "URL:Magnet Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

            # Создаем команду открытия
            cmd_key = winreg.CreateKey(key, r"shell\open\command")
            winreg.SetValue(cmd_key, "", winreg.REG_SZ, _app_command())
            return True
        except OSError as e:
            logger.error(f"Failed to register magnet handler in Windows registry: {e}")
            return False
    else:
        # Linux: создать .desktop + xdg-mime
        desktop = Path.home() / ".local/share/applications/pirate-cinema-magnet.desktop"
        desktop.parent.mkdir(parents=True, exist_ok=True)

        # Для Linux заменяем %1 на %u и экранируем команду
        exec_cmd = _app_command().replace('"%1"', '%u')

        content = f"[Desktop Entry]\nName=Pirate Cinema\nExec={exec_cmd}\nType=Application\nMimeType=x-scheme-handler/magnet;\nNoDisplay=true\n"

        try:
            desktop.write_text(content, encoding="utf-8")
            subprocess.run([
                "xdg-mime", "default",
                "pirate-cinema-magnet.desktop",
                "x-scheme-handler/magnet"
            ], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (OSError, subprocess.SubprocessError):
            logger.exception("Failed to register magnet handler")
            return False


def unregister_magnet_handler() -> bool:
    if sys.platform == 'win32':
        try:
            import winreg
            # Используем безопасное рекурсивное удаление
            _delete_reg_key_recursive(winreg.HKEY_CURRENT_USER, r"Software\Classes\magnet")
            return True
        except OSError:
            logger.exception("Failed to unregister magnet handler from Windows registry")
            return False
    else:
        # Linux: удаление .desktop файла
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
