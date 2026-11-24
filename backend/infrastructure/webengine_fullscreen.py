"""Bridge HTML fullscreen requests from embedded players to the desktop window."""

import logging
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

_DELEGATE_FULLSCREEN_SCRIPT = r"""(() => {
  const grantFullscreen = frame => {
    const policies = (frame.getAttribute('allow') || '')
      .split(';').map(policy => policy.trim())
      .filter(policy => policy && !/^fullscreen(?:\s|$)/i.test(policy));
    policies.push('fullscreen *');
    frame.setAttribute('allow', policies.join('; '));
    frame.setAttribute('allowfullscreen', '');
  };
  const createElement = Document.prototype.createElement;
  Document.prototype.createElement = function(name, ...args) {
    const element = createElement.call(this, name, ...args);
    if (String(name).toLowerCase() === 'iframe') grantFullscreen(element);
    return element;
  };
  const visit = node => {
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    if (node.matches('iframe')) grantFullscreen(node);
    node.querySelectorAll?.('iframe').forEach(grantFullscreen);
  };
  document.querySelectorAll('iframe').forEach(grantFullscreen);
  new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) visit(node);
  }).observe(document, {childList: true, subtree: true});
})();"""


def install_qt_webengine_fullscreen(window_api) -> bool:
    """Accept fullscreen requests from web players and resize the app window."""
    try:
        from qtpy.QtWebEngineCore import QWebEngineScript, QWebEngineSettings
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
        script = QWebEngineScript()
        script.setName("pirate-cinema-delegate-embedded-fullscreen")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(True)
        script.setSourceCode(_DELEGATE_FULLSCREEN_SCRIPT)
        self.scripts().insert(script)
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
