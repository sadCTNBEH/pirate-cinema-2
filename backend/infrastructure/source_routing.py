"""Direct media routes and environment isolation for native playback."""
from urllib.parse import urlsplit
from urllib.request import getproxies_environment, proxy_bypass_environment



def media_proxy(source, url):
    if source in ('yummyanime', 'torrent', 'animego') or urlsplit(url).hostname in ('localhost', '127.0.0.1', '::1'):
        return ''
    # Preserve other providers' environment routing after stripping the child environment.
    proxies = getproxies_environment()
    if proxy_bypass_environment(urlsplit(url).hostname or '', proxies):
        return ''
    return proxies.get(urlsplit(url).scheme) or proxies.get('all') or ''


def direct_process_env(env):
    return {key: value for key, value in env.items()
            if key.lower() not in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')}
