"""Qt WebEngine shutdown ordering fixes for pywebview."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)
_pending_views = []
_qt_core = None
_deferred_delete = None


def install_qt_webengine_shutdown() -> bool:
    """Delete pywebview's page before its unparented profile is released.

    pywebview schedules the page for deferred deletion in ``closeEvent`` and
    exits the Qt event loop immediately afterwards. Flush deferred deletes
    before the BrowserView and its profile can be destroyed.
    """
    try:
        from qtpy import QtCore
        from webview.platforms import qt
    except (ImportError, OSError):
        return False

    if not getattr(qt, "is_webengine", False):
        return False

    view_class = qt.BrowserView
    if getattr(view_class, "_pc_webengine_shutdown_installed", False):
        return True

    global _qt_core, _deferred_delete
    _qt_core = QtCore
    original_close_event = view_class.closeEvent
    deferred_delete = getattr(QtCore.QEvent, "DeferredDelete", None)
    if deferred_delete is None:
        deferred_delete = QtCore.QEvent.Type.DeferredDelete
    _deferred_delete = deferred_delete

    def close_event(self, event):
        original_close_event(self, event)
        if event.isAccepted() and self not in _pending_views:
            # Keep the unparented profile alive until webview.start() returns;
            # pywebview exits the Qt loop immediately after scheduling page deletion.
            _pending_views.append(self)

    view_class.closeEvent = close_event
    view_class._pc_webengine_shutdown_installed = True
    return True


def finalize_qt_webengine_shutdown() -> None:
    """Delete closed pages first, then release their profiles and views."""
    if not _pending_views or _qt_core is None or _deferred_delete is None:
        return

    try:
        _qt_core.QCoreApplication.sendPostedEvents(None, _deferred_delete)
        for view in _pending_views:
            webview = getattr(view, "webview", None)
            if webview is not None:
                page = webview.page()
                if page is not None:
                    page.deleteLater()
                    _qt_core.QCoreApplication.sendPostedEvents(page, _deferred_delete)
            if getattr(view, "profile", None) is not None:
                view.profile = None
        _qt_core.QCoreApplication.sendPostedEvents(None, _deferred_delete)
    except (RuntimeError, TypeError):
        log.warning("Could not finish Qt WebEngine page/profile cleanup", exc_info=True)
    finally:
        _pending_views.clear()
