"""Bridge HTML fullscreen requests from embedded players to the desktop window."""

import logging
from urllib.parse import urlsplit

log = logging.getLogger(__name__)


def install_qt_webengine_fullscreen(window_api) -> bool:
    """Accept fullscreen requests from web players and resize the app window."""
    try:
        from qtpy.QtWebEngineCore import QWebEngineSettings
        from webview.platforms import qt
    except (ImportError, OSError):
        return False

    if not getattr(qt, "is_webengine", False):
        return False

    page_class = qt.BrowserView.WebPage
    if getattr(page_class, "_pc_fullscreen_installed", False):
        return True
    original_init = page_class.__init__

    def on_fullscreen_requested(request):
        try:
            origin = request.origin().toString()
            if urlsplit(origin).scheme not in {"http", "https"}:
                request.reject()
                return
            enabled = bool(request.toggleOn())
            if bool(window_api.set_fullscreen(enabled)) != enabled:
                request.reject()
                return
            request.accept()
            log.info("[WEBENGINE] Player fullscreen %s origin=%s",
                     "entered" if enabled else "exited", origin)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            try:
                request.reject()
            except (AttributeError, RuntimeError):
                pass
            log.exception("[WEBENGINE] Could not handle player fullscreen request")

    def page_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        attribute = QWebEngineSettings.WebAttribute.FullScreenSupportEnabled
        self.settings().setAttribute(attribute, True)
        signal = getattr(self, "fullScreenRequested", None)
        if signal is not None:
            signal.connect(on_fullscreen_requested)
            log.info("[WEBENGINE] Fullscreen support enabled for page %s", self.url().toString())
        else:
            log.error("[WEBENGINE] QWebEnginePage has no fullScreenRequested signal")

    page_class.__init__ = page_init
    page_class._pc_fullscreen_installed = True
    log.info("[WEBENGINE] Fullscreen bridge installed")
    return True
