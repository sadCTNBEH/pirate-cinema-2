"""AdGuard network lists for the Qt WebEngine profiles used on Linux."""

import ipaddress
import json
import logging
import re
import tempfile
import threading
import time
from contextlib import suppress
from pathlib import Path
from urllib.parse import SplitResult, urlsplit

import requests

from backend.infrastructure.web_filter_rules import NetworkRules, on_domain, site_host

log = logging.getLogger(__name__)
FILTERS = {
    "AdGuard Base filter": "https://filters.adtidy.org/extension/chromium/filters/2.txt",
    "AdGuard Tracking Protection filter": "https://filters.adtidy.org/extension/chromium/filters/3.txt",
}
REFRESH_SECONDS = 24 * 60 * 60
RETRY_SECONDS = 15 * 60
MAX_LIST_BYTES = 32 * 1024 * 1024
MEDIA_PATH = re.compile(
    r"\.(?:m3u8?|mpd|ism[lv]?|mp[34]|m4[asv]|[cm]?m?ts|aac|ac3|eac3|webm|mkv|flv|mov|opus|"
    r"ogg|oga|ogv|wav|flac|vtt|srt|ass|ssa|ttml|dfxp|smi)(?:$|/)", re.I,
)
MEDIA_ENDPOINT = re.compile(
    r"(?:^|/)(?:manifest|playlist|videoplayback|(?:media)?segments?|chunks?|fragments?|subtitles?|captions?)"
    r"(?:/|$|[-_.]?\d)", re.I,
)
RESOURCE_TYPES = {
    "MainFrame": "document", "NavigationPreloadMainFrame": "document",
    "SubFrame": "subdocument", "NavigationPreloadSubFrame": "subdocument",
    "Stylesheet": "stylesheet", "Script": "script", "Image": "image", "Favicon": "image",
    "FontResource": "font", "Object": "object", "Media": "media", "Xhr": "xmlhttprequest",
    "Ping": "ping", "CspReport": "ping", "WebSocket": "websocket", "Worker": "script",
    "SharedWorker": "script", "ServiceWorker": "script",
}
KODIK_DOMAINS = "|".join(
    f"{name}.{suffix}" for name in ("kodik", "kodikplayer")
    for suffix in ("com", "info", "biz", "cc")
)
ADFOX_DOMAINS = f"{KODIK_DOMAINS}|alloha.yani.tv|cdnvideohub.com|ru.yummyani.me"
PLAYER_AD_RULES = NetworkRules([
    "\n".join([
        f"||serving-sys.ru^$domain={KODIK_DOMAINS}|cdnvideohub.com|ru.yummyani.me",
        "||ufouxbwn.com/vast.php^$domain=alloha.yani.tv",
        f"||yandex.ru/ads/adfox/$xmlhttprequest,domain={ADFOX_DOMAINS}",
        f"||ya.ru/adfox/$xmlhttprequest,domain={ADFOX_DOMAINS}",
        # Kodik plays the Yandex ad in a separate video element. Match its
        # output path before exempting regular media requests.
        f"||runtime.strm.yandex.ru/videos/*/outputs/$media,xmlhttprequest,other,domain={KODIK_DOMAINS}",
        "||player.cdnvideohub.com/s2/stable/media-hills-pixels.json^$xmlhttprequest,domain=cdnvideohub.com",
        *(f"||{host}/adsbygoogle.js^$script,domain={KODIK_DOMAINS}"
          for host in KODIK_DOMAINS.split("|")),
    ])
])


def _local(host: str) -> bool:
    if not host or on_domain(host, "localhost"):
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return False


def _download(url: str) -> str:
    with requests.get(url, stream=True, timeout=(5, 12)) as response:
        response.raise_for_status()
        chunks = bytearray()
        deadline = time.monotonic() + 90
        for chunk in response.iter_content(chunk_size=65536):
            chunks.extend(chunk)
            if len(chunks) > MAX_LIST_BYTES or time.monotonic() > deadline:
                raise ValueError("filter download limit exceeded")
    return chunks.decode("utf-8-sig")


def _compile(sources: dict[str, str]) -> NetworkRules:
    for name in FILTERS:
        source = sources[name]
        if not isinstance(source, str) or len(source) > MAX_LIST_BYTES or not any(
            line.casefold() == f"! title: {name}".casefold() for line in source[:4096].splitlines()
        ):
            raise ValueError(f"invalid filter: {name}")
        if source.count("\n") < 99:
            raise ValueError(f"incomplete filter: {name}")
    rules = NetworkRules([sources[name] for name in FILTERS])
    if not rules.count:
        raise ValueError("empty network filter")
    return rules


class QtAdblock:
    def __init__(self, root, load, save, fetch=_download, *, app_url=""):
        prefs = load()
        self.cache = Path(root) / "web-adblock" / "filters.json"
        self._save, self._fetch = save, fetch
        app = urlsplit(app_url)
        self._app_origin = (app.scheme, app.hostname, app.port)
        self._enabled = bool(prefs.get("web_player_linux_adblock", False))
        self._exceptions: tuple[str, ...] = ()
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._rules: NetworkRules | None = None
        self._updated = 0
        self._retry_at = 0.0
        self._updating = False
        self._blocked = 0
        self._error = ""
        saved = prefs.get("web_player_linux_adblock_exceptions")
        if isinstance(saved, list):
            for item in saved[:200]:
                if isinstance(item, str):
                    try:
                        self._exceptions += (site_host(item),)
                    except ValueError:
                        pass

    def start(self):
        threading.Thread(target=self._run, name="web-adblock", daemon=True).start()

    def _run(self):
        self.load_cache()
        while True:
            self._wake.clear()
            with self._lock:
                if not self._enabled:
                    wait = None
                elif self._retry_at:
                    wait = self._retry_at - time.monotonic()
                else:
                    wait = min(REFRESH_SECONDS, self._updated + REFRESH_SECONDS - time.time())
            if wait is not None and wait <= 0:
                self.refresh()
            else:
                self._wake.wait(wait)

    def load_cache(self):
        try:
            with self.cache.open(encoding="utf-8") as file:
                payload = json.loads(file.read(MAX_LIST_BYTES * len(FILTERS) * 2))
            rules = _compile(payload["sources"])
            updated = min(int(payload["updated"]), int(time.time()))
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
            log.warning("Could not read cached web filters: %s", error)
            return
        with self._lock:
            self._rules, self._updated = rules, updated

    def refresh(self):
        with self._lock:
            if self._updating or not self._enabled:
                return
            self._updating = True
        temporary = None
        try:
            sources = {name: self._fetch(url) for name, url in FILTERS.items()}
            rules = _compile(sources)
            updated = int(time.time())
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.cache.parent, delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump({"updated": updated, "sources": sources}, file, ensure_ascii=False)
            temporary.replace(self.cache)
            with self._lock:
                self._rules, self._updated = rules, updated
                self._error, self._retry_at = "", 0
        except (requests.RequestException, OSError, ValueError) as error:
            log.warning("Could not update AdGuard network lists: %s", error)
            with self._lock:
                self._error = "Не удалось обновить фильтры. Повторим автоматически."
                self._retry_at = time.monotonic() + RETRY_SECONDS
        finally:
            with self._lock:
                self._updating = False
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)

    def status(self):
        with self._lock:
            return {
                "mode": "qt", "supported": True, "initialized": True,
                "installed": self._rules is not None, "enabled": self._enabled,
                "active": self._enabled and self._rules is not None,
                "error": self._error, "runtime": "Qt WebEngine", "version": "",
                "blocked": self._blocked, "updating": self._updating,
                "updatedAt": self._updated, "exceptions": list(self._exceptions),
            }

    def set_enabled(self, enabled):
        with self._lock:
            self._save({"web_player_linux_adblock": enabled})
            self._enabled = enabled
            if enabled:
                self._retry_at = 0
        self._wake.set()
        return self.status()

    def set_exception(self, value, add):
        with self._lock:
            try:
                if not isinstance(value, str) or len(value) > 2048:
                    raise ValueError("Укажите домен или адрес сайта.")
                host = site_host(value)
                exceptions = set(self._exceptions)
                if add:
                    exceptions.add(host)
                else:
                    exceptions.discard(host)
                if len(exceptions) > 200:
                    raise ValueError("Можно добавить не более 200 исключений.")
                ordered = sorted(exceptions)
                self._save({"web_player_linux_adblock_exceptions": ordered})
                self._exceptions = tuple(ordered)
            except ValueError as error:
                return {**self.status(), "exceptionError": str(error)}
        return self.status()

    def should_block(self, url, first_party, initiator, kind, headers=None):
        with self._lock:
            if not self._enabled or len(url) > 8192:
                return False
            rules, exceptions = self._rules, self._exceptions

        target = urlsplit(url)
        if target.scheme not in {"http", "https", "ws", "wss"} or self._internal(target):
            return False

        source = next(
            (context for context in (initiator, first_party)
             if not self._internal(urlsplit(context))), "",
        )
        # Internal UI assets and API calls are outside the filter. An embedded
        # external frame itself can match a rule; its subresources carry its origin.
        if not source:
            if kind not in {"document", "subdocument"}:
                return False
            source = url
        site = (urlsplit(source).hostname or "").rstrip(".")
        top = (urlsplit(first_party).hostname or "").rstrip(".")
        if source == initiator and site == top:
            source = first_party
        if any(on_domain(site, domain) or on_domain(top, domain) for domain in exceptions):
            return False

        player_ad = PLAYER_AD_RULES.blocks(url, source, kind)
        if not player_ad and (rules is None or kind == "media" or MEDIA_PATH.search(target.path) or (
            kind in {"xmlhttprequest", "other"} and MEDIA_ENDPOINT.search(target.path)
        )):
            return False
        if not player_ad and headers is not None and kind in {"xmlhttprequest", "other"}:
            request_headers = headers()
            accept = request_headers.get("accept", "").lower()
            if "range" in request_headers or any(
                mime in accept for mime in ("video/", "audio/", "mpegurl", "dash+xml", "text/vtt")
            ):
                return False
        if not player_ad and (rules is None or not rules.blocks(url, source, kind)):
            return False
        with self._lock:
            if not self._enabled or self._exceptions != exceptions:
                return False
            self._blocked += 1
        return True

    def _internal(self, url: SplitResult) -> bool:
        return _local((url.hostname or "").rstrip(".")) or (
            url.scheme, url.hostname, url.port
        ) == self._app_origin


qt_adblock: QtAdblock | None = None


def install_qt_adblock(app_url=""):
    """Wrap the interceptor pywebview attaches to every new BrowserView profile."""
    global qt_adblock
    from webview.platforms import qt

    if not qt.is_webengine or qt_adblock is not None:
        return
    from backend.core.settings import get_data_dir, load_settings, save_settings

    blocker = QtAdblock(get_data_dir(), load_settings, save_settings, app_url=app_url)
    qt.BrowserView.RequestInterceptor = interceptor_class(qt.BrowserView.RequestInterceptor, blocker)
    qt_adblock = blocker
    blocker.start()


def interceptor_class(base, blocker):
    """Compose with pywebview's request events and media diagnostics."""
    class AdblockInterceptor(base):
        def interceptRequest(self, info):
            try:
                kind = RESOURCE_TYPES.get(info.resourceType().name.removeprefix("ResourceType"), "other")

                def headers():
                    if not hasattr(info, "httpHeaders"):
                        return {}
                    return {bytes(key).decode("latin1").lower(): bytes(value).decode("latin1")
                            for key, value in info.httpHeaders().items()}

                if blocker.should_block(
                    bytes(info.requestUrl().toEncoded()).decode("ascii"),
                    bytes(info.firstPartyUrl().toEncoded()).decode("ascii"),
                    bytes(info.initiator().toEncoded()).decode("ascii"), kind, headers,
                ):
                    info.block(True)
                    return
            except (AttributeError, TypeError, RuntimeError, ValueError):
                log.debug("Could not classify Qt WebEngine request", exc_info=True)
            super().interceptRequest(info)

    return AdblockInterceptor
