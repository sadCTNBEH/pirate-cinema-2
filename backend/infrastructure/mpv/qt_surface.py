"""Embed MPV in the X11 window used by Qt WebEngine."""

import logging
import os
import sys
from threading import Event

try:
    from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal as Signal
    from PyQt6.QtWidgets import QApplication, QWidget
except ImportError:
    try:
        from PySide6.QtCore import QObject, Qt, QThread, Signal
        from PySide6.QtWidgets import QApplication, QWidget
    except ImportError:
        try:
            from qtpy.QtCore import QObject, Qt, QThread, Signal
            from qtpy.QtWidgets import QApplication, QWidget
        except ImportError:
            try:
                from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal as Signal
                from PyQt5.QtWidgets import QApplication, QWidget
            except ImportError:
                Signal = None
                QObject = object
                QThread = None
                Qt = None
                QApplication = None
                QWidget = None

logger = logging.getLogger(__name__)


class QtPlayerSurface(QObject if QObject is not None else object):
    if Signal is not None:
        _dispatch = Signal(object)
    else:
        _dispatch = None

    def __init__(self, browser):
        super().__init__()
        self.browser = browser
        self.viewport = None
        self.video = None
        self.window_id = None
        if hasattr(self, "moveToThread") and hasattr(browser, "thread"):
            self.moveToThread(browser.thread())
        if self._dispatch is not None:
            self._dispatch.connect(self._run_action, Qt.ConnectionType.QueuedConnection)

    @staticmethod
    def supported() -> bool:
        if not sys.platform.startswith("linux"):
            return False
        if QApplication is None:
            logger.debug("[QT-SURFACE] Qt bindings (PyQt6/PySide6) are not installed")
            return False
        app = QApplication.instance()
        if app is None:
            # QApplication not yet initialized; verify display environment exists
            has_display = bool(os.environ.get("DISPLAY"))
            logger.debug("[QT-SURFACE] QApplication instance is None; has_display=%s", has_display)
            return has_display
        platform = app.platformName()
        is_xcb = platform == "xcb"
        if not is_xcb:
            logger.warning(
                "[QT-SURFACE] Qt platformName is %r (expected 'xcb' for X11/XWayland MPV --wid embedding; DISPLAY=%s)",
                platform,
                os.environ.get("DISPLAY"),
            )
        return is_xcb

    def _run_action(self, action):
        try:
            action()
        except RuntimeError:
            logger.debug("Qt player surface is no longer available", exc_info=True)

    def _ensure_window(self):
        if self.window_id is not None:
            return
        if QWidget is None or Qt is None:
            logger.error("[QT-SURFACE] Cannot create native window: Qt widgets unavailable")
            return
        # The X11 MPV surface must not force WebEngine's QQuickWidget to
        # become a native sibling. Qt 6.4 cannot composite that widget natively.
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
        self.viewport = QWidget(self.browser)
        self.viewport.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.viewport.hide()
        self.video = QWidget(self.viewport)
        self.video.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.video.resize(800, 450)
        self.video.show()
        self.window_id = int(self.video.winId())
        logger.info("[QT-SURFACE] Created embedded player X11 window wid: %s", self.window_id)

    def ensure_window(self) -> int | None:
        if self.window_id is not None:
            return self.window_id
        if QThread is not None and QThread.currentThread() == self.thread():
            self._ensure_window()
        elif self._dispatch is not None:
            ready = Event()

            def ensure():
                try:
                    self._ensure_window()
                finally:
                    ready.set()

            self._dispatch.emit(ensure)
            ready.wait(2)
        else:
            self._ensure_window()
        return self.window_id

    def update(self, bounds, visible: bool, *, focus_browser: bool = False):
        def apply():
            if self.viewport is None:
                return
            if not visible or not bounds:
                self.viewport.hide()
                if focus_browser:
                    self.browser.setFocus()
                return
            cw, ch = self.browser.width(), self.browser.height()
            sx = cw / bounds["viewport_width"] if bounds["viewport_width"] > 0 else 1
            sy = ch / bounds["viewport_height"] if bounds["viewport_height"] > 0 else 1
            x, y = round(bounds["x"] * sx), round(bounds["y"] * sy)
            width, height = round(bounds["width"] * sx), round(bounds["height"] * sy)
            left = max(x, 0, round(bounds["clip_left"] * sx))
            top = max(y, 0, round(bounds["clip_top"] * sy))
            clip_right = round(bounds["clip_right"] * sx) if bounds["clip_right"] > 0 else cw
            clip_bottom = round(bounds["clip_bottom"] * sy) if bounds["clip_bottom"] > 0 else ch
            right = min(x + width, cw, clip_right)
            bottom = min(y + height, ch, clip_bottom)
            if left >= right or top >= bottom:
                self.viewport.hide()
                return
            self.viewport.setGeometry(left, top, right - left, bottom - top)
            self.video.setGeometry(x - left, y - top, width, height)
            self.viewport.show()
            self.viewport.raise_()

        if self._dispatch is not None:
            self._dispatch.emit(apply)
        else:
            apply()
