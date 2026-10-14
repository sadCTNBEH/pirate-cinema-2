"""Desktop UI & Tray Manager."""

import logging
import os
import shutil
from pathlib import Path

import uvicorn
import webview

from backend.core.settings import BASE_DIR, config
from backend.core.settings import load_settings as _load_settings
from backend.core.settings import save_settings as _save_settings
from backend.infrastructure.torrserver import process as torrserver_process
from backend.services import tray
from backend.services.i18n import DEFAULT_LANG, t
from backend.services.settings import SettingsService

logger = logging.getLogger(__name__)

_window: webview.Window | None = None


class WindowApi:
    """JS API exposed to pywebview and frontend for window chrome management."""

    def __init__(self):
        self._is_maximized = False

    def minimize(self) -> bool:
        if _window:
            try:
                _window.minimize()
                return True
            except Exception:
                logger.exception("Failed to minimize window")
        return False

    def maximize(self) -> bool:
        if _window:
            try:
                _window.maximize()
                self._is_maximized = True
                return True
            except Exception:
                logger.exception("Failed to maximize window")
        return False

    def restore(self) -> bool:
        if _window:
            try:
                _window.restore()
                self._is_maximized = False
                return True
            except Exception:
                logger.exception("Failed to restore window")
        return False

    def toggle_maximize(self) -> bool:
        if _window:
            if self.is_maximized():
                return not self.restore()
            else:
                return self.maximize()
        return False

    def is_maximized(self) -> bool:
        if _window and getattr(_window, "native", None):
            try:
                # Windows Forms: FormWindowState.Maximized is 2
                state_val = getattr(_window.native, "WindowState", None)
                if state_val is not None:
                    return int(state_val) == 2 or str(state_val).lower() == "maximized"
            except (AttributeError, ValueError, TypeError) as e:
                logger.debug("Failed to determine window state from native handle: %s", e)
        return self._is_maximized

    def close(self) -> bool:
        if _window:
            try:
                _window.destroy()
                return True
            except Exception:
                logger.exception("Failed to close window")
        return False

    def save_backup(self) -> dict[str, str | bool]:
        """Create a backup and save it through the native file chooser."""
        if not _window:
            return {"saved": False, "error": "Desktop window is unavailable"}

        backup_path: Path | None = None
        try:
            backup_path = SettingsService(None, lambda: "").create_backup_zip()
            destination = _window.create_file_dialog(
                webview.FileDialog.SAVE,
                save_filename="pirate_cinema_backup.zip",
                file_types=("ZIP archive (*.zip)",),
            )
            if not destination:
                return {"saved": False, "cancelled": True}

            if isinstance(destination, (list, tuple)):
                destination = destination[0]
            target = Path(str(destination))
            if target.suffix.lower() != ".zip":
                target = target.with_suffix(".zip")
            shutil.copyfile(backup_path, target)
            return {"saved": True, "path": str(target)}
        except (OSError, RuntimeError) as error:
            logger.exception("Failed to save backup through native dialog")
            return {"saved": False, "error": str(error)}
        finally:
            if backup_path:
                backup_path.unlink(missing_ok=True)


window_api = WindowApi()


def launch_gui(server: uvicorn.Server):
    global _window

    lang = _load_settings().get("language", DEFAULT_LANG)
    static_dir = BASE_DIR / "static"
    app_url = f"http://{config.APP_HOST}:{config.APP_PORT}"

    def on_tray_show():
        if _window:
            try:
                _window.show()
                _window.restore()
            except (RuntimeError, AttributeError, OSError):
                logger.exception("Failed to show window from tray")

    def on_tray_exit():
        logger.info("[TRAY] Exit clicked. Cleaning up...")
        server.should_exit = True
        torrserver_process.stop()
        tray.stop_tray()
        os._exit(0)

    # Настройки области перетаскивания pywebview
    webview.settings["DRAG_REGION_SELECTOR"] = ".pywebview-drag-region"
    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True

    _window = webview.create_window(
        config.APP_TITLE,
        app_url,
        width=config.WINDOW_WIDTH,
        height=config.WINDOW_HEIGHT,
        resizable=True,
        frameless=True,
        easy_drag=False,
        background_color=config.WINDOW_BG,
        js_api=window_api,
    )

    def on_maximized():
        window_api._is_maximized = True

    def on_restored():
        window_api._is_maximized = False

    _window.events.maximized += on_maximized
    _window.events.restored += on_restored

    def initialize_tray():
        try:
            screen = webview.screens[0]
            _window.move(
                max(0, (screen.width - config.WINDOW_WIDTH) // 2),
                max(0, (screen.height - config.WINDOW_HEIGHT) // 2),
            )
        except (AttributeError, IndexError, RuntimeError):
            logger.debug("Could not center desktop window")

        tray_icon_path = static_dir / "tray.png"
        if not tray_icon_path.exists():
            tray_icon_path = static_dir / "favicon.png"
        tray.start_tray(
            icon_path=tray_icon_path,
            on_show=on_tray_show,
            on_exit=on_tray_exit,
            show_text=t("tray_show", lang=lang),
            exit_text=t("tray_exit", lang=lang),
        )

    def on_closing():
        prefs = _load_settings()
        if not prefs.get("close_behavior_configured", False):
            if os.name != "nt":
                return True

            import ctypes

            response = ctypes.windll.user32.MessageBoxW(
                0,
                "Да — сворачивать приложение в трей.\n"
                "Нет — полностью закрывать приложение.\n\n"
                "Этот выбор можно изменить в настройках.",
                "Закрытие Pirate Cinema",
                0x00000003 | 0x00000020,
            )
            if response == 2:  # Cancel
                return False

            minimize_to_tray = response == 6  # Yes
            _save_settings(
                {
                    "minimize_to_tray": minimize_to_tray,
                    "close_behavior_configured": True,
                }
            )
            prefs["minimize_to_tray"] = minimize_to_tray

        if prefs.get("minimize_to_tray", False):
            if _window:
                _window.hide()
            return False  # Отменяет закрытие окна
        return True

    def on_closed():
        logger.info("[GUI] Window closed.")
        tray.stop_tray()
        server.should_exit = True
        torrserver_process.stop()

    _window.events.closing += on_closing
    _window.events.closed += on_closed

    # Путь к иконке окна Windows (заменяет дефолтную python/webview)
    app_icon = static_dir / "icon.ico"
    if not app_icon.exists():
        app_icon = BASE_DIR / "build" / "icon.ico"
    if not app_icon.exists():
        app_icon = BASE_DIR / "assets" / "brand" / "icon.ico"

    webview.start(
        initialize_tray,
        icon=str(app_icon) if app_icon.exists() else None,
    )

    # Очистка при завершении основного цикла окон
    tray.stop_tray()
    server.should_exit = True
    torrserver_process.stop()
    os._exit(0)
