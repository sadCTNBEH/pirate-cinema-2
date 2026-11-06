"""System tray support (Windows / Linux)."""

from __future__ import annotations

import logging
import os
import importlib.util
import shutil
import subprocess
import sys
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


def _has_status_notifier_host() -> bool:
    """Return whether a StatusNotifier host owns a session-bus name."""
    dbus_send = shutil.which("dbus-send")
    if not dbus_send:
        return False
    for name in (
        "org.kde.StatusNotifierWatcher",
        "org.freedesktop.StatusNotifierWatcher",
        "org.ayatana.StatusNotifierWatcher",
    ):
        try:
            result = subprocess.run(
                [dbus_send, "--session", "--print-reply", "--dest=org.freedesktop.DBus",
                 "/org/freedesktop/DBus", "org.freedesktop.DBus.GetNameOwner", f"string:{name}"],
                capture_output=True, timeout=1, check=False,
            )
            if result.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            return False
    return False


def _has_xembed_tray() -> bool:
    """Check the X11 tray selection without asking pystray to dock blindly."""
    if not os.environ.get("DISPLAY"):
        return False
    try:
        from Xlib.display import Display

        display = Display()
        try:
            screen = display.get_default_screen()
            selection = display.intern_atom(f"_NET_SYSTEM_TRAY_S{screen}", only_if_exists=True)
            if not selection:
                return False
            owner = display.get_selection_owner(selection)
            return owner is not None and getattr(owner, "id", 0) != 0
        finally:
            display.close()
    except Exception:
        logger.debug("Could not inspect X11 system tray selection", exc_info=True)
        return False


def _has_appindicator() -> bool:
    """Check the GI typelib used by pystray's supported AppIndicator backend."""
    try:
        import gi

        for namespace in ("AyatanaAppIndicator3", "AppIndicator3"):
            try:
                gi.require_version(namespace, "0.1")
                getattr(gi.repository, namespace)
                return True
            except (ImportError, ValueError, AttributeError):
                continue
    except (ImportError, ValueError):
        return False
    return False


def _linux_backend() -> str | None:
    """Choose a Linux backend only when its desktop protocol is present."""
    if _has_status_notifier_host() and _has_appindicator():
        return "appindicator"
    # A Wayland session may expose a real XEmbed manager through XWayland.
    # The selection-owner probe distinguishes that from a bare XWayland server.
    if _has_xembed_tray():
        return "xorg"
    return None


def is_available() -> bool:
    """Report whether this session has a tray backend this process can use."""
    if os.name == "nt":
        return True
    if not sys.platform.startswith("linux"):
        return True
    backend = _linux_backend()
    if backend is None or importlib.util.find_spec("pystray") is None:
        return False
    return backend != "appindicator" or _has_appindicator()


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

    selected_backend = None
    previous_backend = os.environ.get("PYSTRAY_BACKEND")
    if sys.platform.startswith("linux"):
        backend = _linux_backend()
        if backend is None:
            logger.info("No usable system tray host is present; running without a tray")
            _tray = None
            return
        logger.info("Using Linux system tray backend %s", backend)
        # PYSTRAY_BACKEND is pystray's documented backend selector. This avoids
        # its automatic XEmbed fallback in Wayland sessions without a tray host.
        selected_backend = backend
        os.environ["PYSTRAY_BACKEND"] = backend

    # A missing desktop tray backend must not prevent the application from opening.
    try:
        import pystray
    except ImportError as error:
        logger.warning("System tray backend is unavailable; continuing without tray: %s", error)
        return
    except Exception:
        logger.exception("System tray backend is unavailable; continuing without tray")
        return
    finally:
        if selected_backend is not None:
            if previous_backend is None:
                os.environ.pop("PYSTRAY_BACKEND", None)
            else:
                os.environ["PYSTRAY_BACKEND"] = previous_backend

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

        icon = _tray

        def _run_tray_safe():
            global _tray
            try:
                icon.run()
            except Exception:
                logger.exception("System tray loop failed")
            finally:
                if _tray is icon:
                    _tray = None

        # Запускаем трей в фоновом (daemon) потоке, чтобы он не блокировал выход из приложения
        thread = threading.Thread(target=_run_tray_safe, daemon=True, name="SystemTrayThread")
        thread.start()
    except Exception:
        logger.exception("Failed to initialize system tray")
        _tray = None


def is_tray_running() -> bool:
    """Check if system tray icon is currently active."""
    return bool(_tray is not None and getattr(_tray, "visible", False))


def should_minimize_to_tray(enabled: bool) -> bool:
    """Never hide the last window unless the tray icon is actually visible."""
    return bool(enabled and is_tray_running())


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
