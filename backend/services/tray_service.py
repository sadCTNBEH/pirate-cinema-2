"""System tray support (Windows / Linux)."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

import pystray
from PIL import Image

_tray: pystray.Icon | None = None
_on_show: Callable | None = None
_on_exit: Callable | None = None

logger = logging.getLogger(__name__)

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

    image = Image.open(icon_path) if icon_path.exists() else Image.new("RGB", (64, 64), "black")

    menu = pystray.Menu(
        pystray.MenuItem(show_text, lambda: _on_show() if _on_show else None),
        pystray.MenuItem(exit_text, lambda: _on_exit() if _on_exit else None),
    )
    _tray = pystray.Icon("Pirate Cinema", image, "Pirate Cinema", menu)

    if _tray is not None:
        assert _tray is not None
        tr = threading.Thread(target=_tray.run, daemon=False)
        tr.start()


def stop_tray() -> None:
    global _tray
    if _tray is not None:
        assert _tray is not None
        try:
            _tray.stop()
        except RuntimeError:
            logger.exception("Stop tray failed")
        _tray = None