"""System tray support and dynamic tray menu manager (Windows / Linux)."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, UnidentifiedImageError

from backend.core.settings.base import BASE_DIR

if TYPE_CHECKING:
    import pystray

logger = logging.getLogger(__name__)


def resolve_tray_icon(custom_path: Path | str | None = None) -> Path:
    """Find an available tray icon asset on disk, falling back to brand assets."""
    if custom_path:
        p = Path(custom_path)
        if p.is_file():
            return p

    candidates = [
        BASE_DIR / "static" / "tray.png",
        BASE_DIR / "static" / "favicon.png",
        BASE_DIR / "static" / "icon.png",
        BASE_DIR / "build" / "icon.ico",
        BASE_DIR / "assets" / "brand" / "icon.ico",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return BASE_DIR / "static" / "favicon.png"


def create_tray_image(icon_source: Path | str | Image.Image | None = None) -> Image.Image:
    """Create a validated PIL Image for the system tray icon."""
    if isinstance(icon_source, Image.Image):
        return icon_source

    icon_path = Path(icon_source) if icon_source else resolve_tray_icon()
    if icon_path.exists():
        try:
            image = Image.open(icon_path)
            image.load()
            return image
        except (OSError, UnidentifiedImageError, ValueError) as err:
            logger.warning("Failed to load tray icon %s: %s", icon_path, err)

    return Image.new("RGB", (64, 64), "black")


class TrayManager:
    """Manages system tray lifecycle, dynamic menu creation, and tray event routing."""

    def __init__(self) -> None:
        self._tray: pystray.Icon | None = None
        self._on_show: Callable[[], None] | None = None
        self._on_exit: Callable[[], None] | None = None
        self._shutdown_service: Callable[[], None] | None = None
        self._show_text: str = "Show"
        self._exit_text: str = "Exit"
        self._status_text: str | None = None
        self._extra_items: list[Any] = []
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None

    def set_shutdown_service(self, service: Callable[[], None] | None) -> None:
        with self._lock:
            self._shutdown_service = service

    def _handle_show(self) -> None:
        with self._lock:
            cb = self._on_show
        if cb is not None:
            try:
                cb()
            except (RuntimeError, ValueError, AttributeError) as e:
                logger.warning("Error executing show action from system tray: %s", e)

    def _handle_exit(self) -> None:
        logger.info("[TRAY] Exit triggered from system tray")
        with self._lock:
            shutdown = self._shutdown_service
            on_exit = self._on_exit
        if shutdown is not None:
            try:
                shutdown()
                return
            except (RuntimeError, ValueError, AttributeError, OSError) as e:
                logger.warning("Error executing unified shutdown from system tray: %s", e)
        if on_exit is not None:
            try:
                on_exit()
            except (RuntimeError, ValueError, AttributeError, OSError) as e:
                logger.warning("Error executing exit action from system tray: %s", e)

    def build_menu(
        self,
        show_text: str | None = None,
        exit_text: str | None = None,
        status_text: str | None = None,
        extra_items: list[Any] | None = None,
    ) -> pystray.Menu | None:
        """Construct a pystray Menu instance from configured actions and status."""
        try:
            import pystray
        except ImportError:
            return None

        st_text = status_text if status_text is not None else self._status_text
        sh_text = show_text or self._show_text
        ex_text = exit_text or self._exit_text
        extras = extra_items if extra_items is not None else self._extra_items

        menu_items: list[pystray.MenuItem] = []
        if st_text:
            menu_items.append(
                pystray.MenuItem(st_text, None, enabled=False)
            )

        menu_items.append(
            pystray.MenuItem(sh_text, lambda icon, item: self._handle_show(), default=True)
        )

        for item in extras:
            if isinstance(item, pystray.MenuItem):
                menu_items.append(item)

        menu_items.append(
            pystray.MenuItem(ex_text, lambda icon, item: self._handle_exit())
        )

        return pystray.Menu(*menu_items)

    def start(
        self,
        icon_path: Path | str | None = None,
        on_show: Callable[[], None] | None = None,
        on_exit: Callable[[], None] | None = None,
        show_text: str = "Show",
        exit_text: str = "Exit",
        shutdown_service: Callable[[], None] | None = None,
        status_text: str | None = None,
        extra_items: list[Any] | None = None,
    ) -> bool:
        """Initialize and display the system tray icon."""
        with self._lock:
            self._on_show = on_show
            self._on_exit = on_exit
            self._show_text = show_text
            self._exit_text = exit_text
            self._status_text = status_text
            if extra_items is not None:
                self._extra_items = list(extra_items)
            if shutdown_service is not None:
                self._shutdown_service = shutdown_service

        if "WAYLAND_DISPLAY" in os.environ and "PYSTRAY_BACKEND" not in os.environ:
            os.environ["PYSTRAY_BACKEND"] = "appindicator"

        try:
            import pystray
        except ImportError as error:
            logger.warning("System tray backend is unavailable; continuing without tray: %s", error)
            return False
        except Exception:
            logger.exception("System tray backend is unavailable; continuing without tray")
            return False

        image = create_tray_image(icon_path)
        menu = self.build_menu()
        if menu is None:
            return False

        try:
            title = f"Pirate Cinema - {status_text}" if status_text else "Pirate Cinema"
            self._tray = pystray.Icon("Pirate Cinema", image, title, menu)

            def _run_tray_safe() -> None:
                try:
                    if self._tray is not None:
                        self._tray.run()
                except (Exception, BaseException) as e:
                    logger.warning("System tray loop encountered error: %s", e)
                finally:
                    with self._lock:
                        self._tray = None

            self._thread = threading.Thread(
                target=_run_tray_safe,
                daemon=True,
                name="SystemTrayThread",
            )
            self._thread.start()
            return True
        except (Exception, BaseException) as e:
            logger.warning("Failed to initialize system tray: %s", e)
            with self._lock:
                self._tray = None
            return False

    def update_status(self, status_text: str | None) -> None:
        """Update the displayed status text in tray menu and tooltip."""
        with self._lock:
            self._status_text = status_text
            if self._tray is not None:
                new_menu = self.build_menu()
                if new_menu is not None:
                    self._tray.menu = new_menu
                self._tray.title = f"Pirate Cinema - {status_text}" if status_text else "Pirate Cinema"

    def update_icon(self, icon_source: Path | str | Image.Image) -> None:
        """Update system tray icon image dynamically."""
        with self._lock:
            if self._tray is not None:
                new_image = create_tray_image(icon_source)
                self._tray.icon = new_image

    def update_menu(self, extra_items: list[Any] | None = None) -> None:
        """Update dynamic tray menu items."""
        with self._lock:
            if extra_items is not None:
                self._extra_items = list(extra_items)
            if self._tray is not None:
                new_menu = self.build_menu()
                if new_menu is not None:
                    self._tray.menu = new_menu

    def is_running(self) -> bool:
        """Check if system tray icon is currently active."""
        with self._lock:
            return self._tray is not None and getattr(self._tray, "visible", False)

    def stop(self) -> None:
        """Stop system tray icon and clean up callbacks."""
        with self._lock:
            icon = self._tray
            self._tray = None
            self._on_show = None
            self._on_exit = None
            self._shutdown_service = None
        if icon is not None:
            try:
                icon.stop()
            except (RuntimeError, OSError) as e:
                logger.warning("Stop tray failed: %s", e)


_tray_manager = TrayManager()
_tray: Any = None


def _handle_exit() -> None:
    """Module-level legacy handler for system tray exit."""
    _tray_manager._handle_exit()


def set_shutdown_service(service: Callable[[], None]) -> None:
    _tray_manager.set_shutdown_service(service)


def start_tray(
    icon_path: Path | str | None = None,
    on_show: Callable[[], None] | None = None,
    on_exit: Callable[[], None] | None = None,
    show_text: str = "Show",
    exit_text: str = "Exit",
    shutdown_service: Callable[[], None] | None = None,
    status_text: str | None = None,
) -> bool:
    return _tray_manager.start(
        icon_path=icon_path,
        on_show=on_show,
        on_exit=on_exit,
        show_text=show_text,
        exit_text=exit_text,
        shutdown_service=shutdown_service,
        status_text=status_text,
    )


def is_tray_running() -> bool:
    return _tray_manager.is_running()


def stop_tray() -> None:
    _tray_manager.stop()


def update_tray_status(status_text: str | None) -> None:
    _tray_manager.update_status(status_text)


def update_tray_icon(icon_source: Path | str | Image.Image) -> None:
    _tray_manager.update_icon(icon_source)


def update_tray_menu(extra_items: list[Any] | None = None) -> None:
    _tray_manager.update_menu(extra_items)


def setup_app_tray(
    on_show: Callable[[], None],
    on_exit: Callable[[], None] | None = None,
    shutdown_service: Callable[[], None] | None = None,
    show_text: str = "Show",
    exit_text: str = "Exit",
    icon_path: Path | str | None = None,
    status_text: str | None = None,
) -> bool:
    """High-level application helper to initialize system tray with resolved icon."""
    resolved_icon = resolve_tray_icon(icon_path)
    return start_tray(
        icon_path=resolved_icon,
        on_show=on_show,
        on_exit=on_exit,
        show_text=show_text,
        exit_text=exit_text,
        shutdown_service=shutdown_service,
        status_text=status_text,
    )
