"""Windows and cross-platform autostart management service."""

import logging
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path

from backend.core.settings.base import BASE_DIR

logger = logging.getLogger(__name__)

RUN_KEY_NAME = "Pirate Cinema"
REG_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def get_autostart_command() -> str:
    """Return the executable command line configured to launch minimized at startup."""
    appimage = os.environ.get("APPIMAGE")
    if appimage and appimage.strip():
        return f'"{appimage.strip()}" --minimized'
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'

    main_script = BASE_DIR / "backend" / "main.py"
    return f'"{sys.executable}" "{main_script}" --minimized'


def should_start_minimized(argv: list[str] | None = None) -> bool:
    """Check if command-line arguments indicate launching in background or tray."""
    if argv is None:
        argv = sys.argv[1:]
    return any(arg in argv for arg in ("--minimized", "--autostart", "--tray"))


class IAutostartBackend(ABC):
    """Abstract interface for platform-specific autostart registration."""

    @abstractmethod
    def is_enabled(self) -> bool:
        """Check if autostart is currently enabled."""

    @abstractmethod
    def set_enabled(self, enable: bool) -> bool:
        """Enable or disable autostart."""


class WindowsAutostartBackend(IAutostartBackend):
    """Windows autostart registration via HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."""

    def __init__(self, run_key_name: str = RUN_KEY_NAME, reg_path: str = REG_RUN_PATH):
        self.run_key_name = run_key_name
        self.reg_path = reg_path

    def is_enabled(self) -> bool:
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self.reg_path,
                0,
                winreg.KEY_READ,
            ) as key:
                val, _ = winreg.QueryValueEx(key, self.run_key_name)
                return bool(val)
        except (OSError, FileNotFoundError):
            return False

    def set_enabled(self, enable: bool) -> bool:
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self.reg_path,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                if enable:
                    cmd = get_autostart_command()
                    winreg.SetValueEx(key, self.run_key_name, 0, winreg.REG_SZ, cmd)
                    logger.info("Enabled autostart in Windows registry: %s", cmd)
                else:
                    try:
                        winreg.DeleteValue(key, self.run_key_name)
                        logger.info("Removed autostart from Windows registry")
                    except FileNotFoundError:
                        pass
            return True
        except OSError as e:
            logger.warning("Failed to modify Windows Run registry key: %s", e)
            return False


class LinuxAutostartBackend(IAutostartBackend):
    """Linux autostart registration via ~/.config/autostart/*.desktop file."""

    def __init__(self, desktop_filename: str = "pirate-cinema.desktop"):
        self.desktop_filename = desktop_filename

    @property
    def desktop_file(self) -> Path:
        config_home = os.environ.get("XDG_CONFIG_HOME")
        base = Path(config_home) if config_home else Path.home() / ".config"
        return base / "autostart" / self.desktop_filename

    def is_enabled(self) -> bool:
        return self.desktop_file.is_file()

    def set_enabled(self, enable: bool) -> bool:
        if enable:
            try:
                self.desktop_file.parent.mkdir(parents=True, exist_ok=True)
                cmd = get_autostart_command()
                self.desktop_file.write_text(
                    f"[Desktop Entry]\n"
                    f"Type=Application\n"
                    f"Name=Pirate Cinema\n"
                    f"Exec={cmd}\n"
                    f"Hidden=false\n"
                    f"NoDisplay=false\n"
                    f"X-GNOME-Autostart-enabled=true\n",
                    encoding="utf-8",
                )
                logger.info("Created Linux autostart desktop file: %s", self.desktop_file)
                return True
            except OSError as e:
                logger.warning("Failed to create Linux autostart desktop file: %s", e)
                return False
        else:
            try:
                if self.desktop_file.is_file():
                    self.desktop_file.unlink()
                    logger.info("Removed Linux autostart desktop file: %s", self.desktop_file)
                return True
            except OSError as e:
                logger.warning("Failed to remove Linux autostart desktop file: %s", e)
                return False


def get_autostart_backend() -> IAutostartBackend:
    """Return backend implementation for current platform."""
    if sys.platform == "win32":
        return WindowsAutostartBackend()
    return LinuxAutostartBackend()


def is_autostart_enabled() -> bool:
    """Check if the application is currently registered to launch at OS startup."""
    return get_autostart_backend().is_enabled()


def set_autostart(enable: bool) -> bool:
    """Enable or disable autostart in OS registry / desktop entry."""
    return get_autostart_backend().set_enabled(enable)
