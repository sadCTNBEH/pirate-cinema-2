"""Observe Alloha's player events inside the embedded browser."""
from urllib.parse import urlsplit


def shell_navigation_allowed(app_url, target):
    """The desktop shell stays on its own origin; iframe navigation is separate."""
    try:
        app, destination = urlsplit(app_url), urlsplit(target)
        return destination.scheme in ('http', 'https') and (app.scheme, app.hostname, app.port) == (destination.scheme, destination.hostname, destination.port)
    except ValueError:
        return False

ALLOHA_EVENTS_SCRIPT = r"""(() => {
  if (location.protocol !== 'https:' || location.hostname !== 'alloha.yani.tv' || window === window.parent) return;
  const restoreAdLoaderCursor = () => {
    const style = document.createElement('style');
    style.textContent = '.allplay__ads--loader, .allplay__poster { cursor: default !important; }';
    (document.head || document.documentElement).appendChild(style);
  };
  if (document.documentElement) restoreAdLoaderCursor();
  else document.addEventListener('DOMContentLoaded', restoreAdLoaderCursor, {once: true});
  let attached = false;
  const timer = setInterval(() => {
    if (attached || typeof player === 'undefined' || typeof player.on !== 'function') return;
    attached = true;
    clearInterval(timer);
    let ended = false;
    player.on('play', () => {
      ended = false;
      window.parent.postMessage({type: 'pc-alloha', event: 'started'}, '*');
    });
    player.on('ended', () => {
      if (ended) return;
      ended = true;
      window.parent.postMessage({type: 'pc-alloha', event: 'ended'}, '*');
    });
    window.parent.postMessage({type: 'pc-alloha', event: 'ready'}, '*');
  }, 500);
  window.addEventListener('pagehide', () => clearInterval(timer), {once: true});
})();"""


def install_qt_player_events() -> bool:
    from qtpy.QtWebEngineCore import QWebEngineScript
    from webview.platforms import qt

    if not qt.is_webengine:
        return False
    page = qt.BrowserView.WebPage
    original_init = page.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        script = QWebEngineScript()
        script.setName("pirate-cinema-alloha-events")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(True)
        script.setSourceCode(ALLOHA_EVENTS_SCRIPT)
        self.scripts().insert(script)

    page.__init__ = init
    return True
