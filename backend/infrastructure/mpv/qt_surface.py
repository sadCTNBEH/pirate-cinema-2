"""Embed MPV in the X11 window used by Qt WebEngine."""

import logging
from threading import Event

from qtpy.QtCore import QObject, Qt, QThread, Signal
from qtpy.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)


class QtPlayerSurface(QObject):
    _dispatch = Signal(object)

    def __init__(self, browser):
        super().__init__()
        self.browser = browser
        self.viewport = None
        self.video = None
        self.window_id = None
        self.moveToThread(browser.thread())
        self._dispatch.connect(self._run_action, Qt.ConnectionType.QueuedConnection)

    @staticmethod
    def supported() -> bool:
        app = QApplication.instance()
        return app is not None and app.platformName() == "xcb"

    def _run_action(self, action):
        try:
            action()
        except RuntimeError:
            logger.debug("Qt player surface is no longer available", exc_info=True)

    def _ensure_window(self):
        if self.window_id is not None:
            return
        self.viewport = QWidget(self.browser)
        self.viewport.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.viewport.hide()
        self.video = QWidget(self.viewport)
        self.video.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.video.resize(800, 450)
        self.video.show()
        self.window_id = int(self.video.winId())

    def ensure_window(self) -> int | None:
        if self.window_id is not None:
            return self.window_id
        if QThread.currentThread() == self.thread():
            self._ensure_window()
        else:
            ready = Event()

            def ensure():
                try:
                    self._ensure_window()
                finally:
                    ready.set()

            self._dispatch.emit(ensure)
            ready.wait(2)
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

        self._dispatch.emit(apply)
