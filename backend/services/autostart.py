"""Windows and cross-platform autostart management service."""

import logging
import sys
from pathlib import Path

from backend.core.settings.base import BASE_DIR

logger = logging.getLogger(__name__)

RUN_KEY_NAME = "Pirate Cinema"
REG_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def get_autostart_command() -> str:
    """Return the executable command line configured to launch minimized at startup."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'

    main_script = BASE_DIR / "backend" / "main.py"
    return f'"{sys.executable}" "{main_script}" --minimized'


def is_autostart_enabled() -> bool:
    """Check if the application is currently registered to launch at OS startup."""
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                REG_RUN_PATH,
                0,
                winreg.KEY_READ,
            ) as key:
                val, _ = winreg.QueryValueEx(key, RUN_KEY_NAME)
                return bool(val)
        except (OSError, FileNotFoundError):
            return False

    desktop_file = Path.home() / ".config" / "autostart" / "pirate-cinema.desktop"
    return desktop_file.is_file()


def set_autostart(enable: bool) -> bool:
    """Enable or disable autostart in OS registry / desktop entry."""
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                REG_RUN_PATH,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                if enable:
                    cmd = get_autostart_command()
                    winreg.SetValueEx(key, RUN_KEY_NAME, 0, winreg.REG_SZ, cmd)
                    logger.info("Enabled autostart in Windows registry: %s", cmd)
                else:
                    try:
                        winreg.DeleteValue(key, RUN_KEY_NAME)
                        logger.info("Removed autostart from Windows registry")
                    except FileNotFoundError:
                        pass
            return True
        except OSError as e:
            logger.warning("Failed to modify Windows Run registry key: %s", e)
            return False

    # Linux autostart via .desktop file
    desktop_file = Path.home() / ".config" / "autostart" / "pirate-cinema.desktop"
    if enable:
        try:
            desktop_file.parent.mkdir(parents=True, exist_ok=True)
            cmd = get_autostart_command()
            desktop_file.write_text(
                f"[Desktop Entry]\nType=Application\nName=Pirate Cinema\nExec={cmd}\nHidden=false\nNoDisplay=false\nX-GNOME-Autostart-enabled=true\n",
                encoding="utf-8",
            )
            return True
        except OSError as e:
            logger.warning("Failed to create Linux autostart desktop file: %s", e)
            return False
    else:
        try:
            if desktop_file.is_file():
                desktop_file.unlink()
            return True
        except OSError as e:
            logger.warning("Failed to remove Linux autostart desktop file: %s", e)
            return False
