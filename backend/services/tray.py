"""System tray support (Windows / Linux)."""

from __future__ import annotations

import logging
import os
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
_shutdown_service: Callable[[], None] | None = None

logger = logging.getLogger(__name__)


def set_shutdown_service(service: Callable[[], None]) -> None:
    """Set unified shutdown service to be invoked when Exit is chosen in tray."""
    global _shutdown_service
    _shutdown_service = service


def _handle_show() -> None:
    if _on_show is not None:
        try:
            _on_show()
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.warning("Error executing show action from system tray: %s", e)


def _handle_exit() -> None:
    logger.info("[TRAY] Exit triggered from system tray")
    if _shutdown_service is not None:
        try:
            _shutdown_service()
            return
        except (RuntimeError, ValueError, AttributeError, OSError) as e:
            logger.warning("Error executing unified shutdown from system tray: %s", e)
    if _on_exit is not None:
        try:
            _on_exit()
        except (RuntimeError, ValueError, AttributeError, OSError) as e:
            logger.warning("Error executing exit action from system tray: %s", e)


def start_tray(
    icon_path: Path,
    on_show: Callable,
    on_exit: Callable | None = None,
    show_text: str = "Show",
    exit_text: str = "Exit",
    shutdown_service: Callable[[], None] | None = None,
) -> None:
    global _tray, _on_show, _on_exit, _shutdown_service
    _on_show = on_show
    _on_exit = on_exit
    if shutdown_service is not None:
        _shutdown_service = shutdown_service

    # On Wayland (e.g. Hyprland, Sway), pystray's xorg backend fails with AssertionError.
    # Prefer appindicator if available; if not, suppress docking assertion failures.
    if "WAYLAND_DISPLAY" in os.environ and "PYSTRAY_BACKEND" not in os.environ:
        os.environ["PYSTRAY_BACKEND"] = "appindicator"

    # A missing desktop tray backend must not prevent the application from opening.
    try:
        import pystray
    except ImportError as error:
        logger.warning("System tray backend is unavailable; continuing without tray: %s", error)
        return
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
            global _tray
            try:
                if _tray is not None:
                    _tray.run()
            except (Exception, BaseException) as e:
                logger.warning("System tray loop encountered error: %s", e)
            finally:
                _tray = None

        # Запускаем трей в фоновом (daemon) потоке, чтобы он не блокировал выход из приложения
        thread = threading.Thread(target=_run_tray_safe, daemon=True, name="SystemTrayThread")
        thread.start()
    except (Exception, BaseException) as e:
        logger.warning("Failed to initialize system tray: %s", e)
        _tray = None


def is_tray_running() -> bool:
    """Check if system tray icon is currently active."""
    return _tray is not None and getattr(_tray, "visible", False)


def stop_tray() -> None:
    global _tray, _on_show, _on_exit, _shutdown_service
    icon = _tray
    _tray = None
    _on_show = None
    _on_exit = None
    _shutdown_service = None
    if icon is not None:
        try:
            icon.stop()
        except (RuntimeError, OSError) as e:
            logger.warning("Stop tray failed: %s", e)
