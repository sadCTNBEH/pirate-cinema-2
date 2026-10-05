"""Desktop UI & Tray Manager."""

import logging
import os

import uvicorn
import webview

from backend.core.settings import BASE_DIR, config
from backend.core.settings import load_settings as _load_settings
from backend.infrastructure.torrserver import process as torrserver_process
from backend.services import tray
from backend.services.i18n import DEFAULT_LANG, t

logger = logging.getLogger(__name__)

_window: webview.Window | None = None


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

    _window = webview.create_window(
        "Pirate Cinema",
        app_url,
        width=1280,
        height=800,
        background_color="#141414",
    )

    def initialize_tray():
        icon_path = static_dir / "favicon.png"
        tray.start_tray(
            icon_path=icon_path,
            on_show=on_tray_show,
            on_exit=on_tray_exit,
            show_text=t("tray_show", lang=lang),
            exit_text=t("tray_exit", lang=lang),
        )

    def on_closing():
        prefs = _load_settings()
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

    webview.start(initialize_tray)

    # Очистка при завершении основного цикла окон
    tray.stop_tray()
    server.should_exit = True
    torrserver_process.stop()
    os._exit(0)
