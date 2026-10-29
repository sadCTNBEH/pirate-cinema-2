"""Observe Alloha's public player events inside its WebView2 document."""
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
  let attached = false;
  const timer = setInterval(() => {
    if (attached || typeof player === 'undefined' || typeof player.on !== 'function') return;
    attached = true;
    clearInterval(timer);
    let ended = false;
    player.on('play', () => { ended = false; });
    player.on('ended', () => {
      if (ended) return;
      ended = true;
      window.parent.postMessage({type: 'pc-alloha', event: 'ended'}, '*');
    });
    window.parent.postMessage({type: 'pc-alloha', event: 'ready'}, '*');
  }, 500);
  window.addEventListener('pagehide', () => clearInterval(timer), {once: true});
})();"""
