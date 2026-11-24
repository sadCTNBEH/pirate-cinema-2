"""Qt WebEngine shutdown ordering fixes for pywebview."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


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

    original_close_event = view_class.closeEvent
    deferred_delete = getattr(QtCore.QEvent, "DeferredDelete", None)
    if deferred_delete is None:
        deferred_delete = QtCore.QEvent.Type.DeferredDelete

    def close_event(self, event):
        original_close_event(self, event)
        if not event.isAccepted():
            return

        try:
            # pywebview calls page.deleteLater() just before app.exit() in its
            # closeEvent. Process that event while the profile is still alive.
            QtCore.QCoreApplication.sendPostedEvents(None, deferred_delete)
        except (RuntimeError, TypeError):
            log.debug("Could not flush Qt WebEngine deferred deletes", exc_info=True)

    view_class.closeEvent = close_event
    view_class._pc_webengine_shutdown_installed = True
    return True
