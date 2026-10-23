"""System tray support (Windows / Linux)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, UnidentifiedImageError

if TYPE_CHECKING:
    import pystray

_tray: pystray.Icon | None = None
_on_show: Callable | None = None
_on_exit: Callable | None = None

logger = logging.getLogger(__name__)


def _handle_show() -> None:
    if _on_show is not None:
        try:
            _on_show()
        except (RuntimeError, ValueError, AttributeError):
            logger.exception("Error executing show action from system tray")


def _handle_exit() -> None:
    if _on_exit is not None:
        try:
            _on_exit()
        except (RuntimeError, ValueError, AttributeError):
            logger.exception("Error executing exit action from system tray")


def start_tray(
    icon_path: Path,
    on_show: Callable,
    on_exit: Callable,
    show_text: str = "Show",
    exit_text: str = "Exit",
) -> None:
    global _tray, _on_show, _on_exit
    _on_show = on_show
    _on_exit = on_exit

    # A missing desktop tray backend must not prevent the application from opening.
    try:
        import pystray
    except Exception:
        logger.exception("System tray backend is unavailable; continuing without tray")
        return

    if icon_path.exists():
        try:
            image = Image.open(icon_path)
            image.load()  # Проверяем и декодируем изображение сразу
        except (OSError, UnidentifiedImageError, ValueError) as e:
            logger.warning("Failed to load tray icon %s: %s", icon_path, e)
            image = Image.new("RGB", (64, 64), "black")
    else:
        image = Image.new("RGB", (64, 64), "black")

    menu = pystray.Menu(
        pystray.MenuItem(show_text, lambda icon, item: _handle_show(), default=True),
        pystray.MenuItem(exit_text, lambda icon, item: _handle_exit()),
    )

    try:
        _tray = pystray.Icon("Pirate Cinema", image, "Pirate Cinema", menu)

        def _run_tray_safe():
            try:
                if _tray is not None:
                    _tray.run()
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("System tray loop encountered error: %s", e)

        # Запускаем трей в фоновом (daemon) потоке, чтобы он не блокировал выход из приложения
        thread = threading.Thread(target=_run_tray_safe, daemon=True, name="SystemTrayThread")
        thread.start()
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Failed to initialize system tray: %s", e)
        _tray = None


def is_tray_running() -> bool:
    """Check if system tray icon is currently active."""
    return _tray is not None and getattr(_tray, "visible", False)


def stop_tray() -> None:
    global _tray, _on_show, _on_exit
    if _tray is not None:
        try:
            _tray.stop()
        except (RuntimeError, OSError) as e:
            logger.warning("Stop tray failed: %s", e)
        finally:
            _tray = None
            _on_show = None
            _on_exit = None
