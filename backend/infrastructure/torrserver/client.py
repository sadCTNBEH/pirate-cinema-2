import asyncio
import base64
import binascii
import hashlib
import inspect
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections.abc import Callable
from copy import deepcopy
from typing import Any
from urllib.parse import quote

import httpx

from backend.core.enums import VideoExtension
from backend.core.settings.config import config

VIDEO_EXTS = VideoExtension.values()

logger = logging.getLogger("torrserver")
logger.setLevel(logging.DEBUG)

_client: httpx.AsyncClient | None = None
_client_loop: Any = None


def get_torrserver_url(base_url: str | None = None) -> str:
    url = base_url or config.TORRSERVER_DEFAULT_URL
    return url.rstrip("/")


def get_client() -> httpx.AsyncClient:
    global _client, _client_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if (
        _client is None
        or _client.is_closed
        or (_client_loop is not None and _client_loop != current_loop)
    ):
        _client = httpx.AsyncClient(
            timeout=config.TORRSERVER_HTTP_TIMEOUT,
            follow_redirects=True,
            trust_env=False,
        )
        _client_loop = current_loop
    return _client


def normalize_hash(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", v):
        return v
    try:
        decoded = base64.b32decode(v.upper() + "=" * (-len(v) % 8))
        if len(decoded) == 20:
            return decoded.hex()
    except (binascii.Error, ValueError):
        pass
    return None


def magnet_info_hash(magnet: str) -> str | None:
    if not isinstance(magnet, str):
        return None
    m = re.search(r"xt=urn:btih:([0-9a-fA-F]{40}|[A-Za-z2-7]{32})", magnet)
    if not m:
        return None
    return normalize_hash(m.group(1))


async def probe(base_url: str | None = None) -> bool:
    url = get_torrserver_url(base_url)
    if not url:
        return False
    try:
        r = await get_client().get(f"{url}/echo", timeout=4.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


async def get_torrents(base_url: str | None = None) -> list[dict]:
    """Fetch list of torrents from TorrServer."""
    url = get_torrserver_url(base_url)
    if not url:
        return []

    list_r = await get_client().post(
        f"{url}/torrents", json={"action": "list"}, timeout=6.0
    )
    list_r.raise_for_status()
    raw_torrents = list_r.json()

    torrents = []
    if isinstance(raw_torrents, list):
        for t in raw_torrents:
            if isinstance(t, dict):
                h = normalize_hash(t.get("hash", ""))
                if h:
                    total_vids = 0
                    raw_data = t.get("data", "")
                    if isinstance(raw_data, str) and raw_data:
                        try:
                            parsed_data = json.loads(raw_data)
                            if isinstance(parsed_data, dict):
                                files_list = (
                                    parsed_data.get("TorrServer", {}).get("Files", [])
                                    or []
                                )
                                for f in files_list:
                                    p = f.get("path", "")
                                    ext = (
                                        "." + p.rsplit(".", 1)[-1].lower()
                                        if "." in p
                                        else ""
                                    )
                                    if ext in VIDEO_EXTS:
                                        total_vids += 1
                        except (json.JSONDecodeError, KeyError, AttributeError):
                            pass

                    if total_vids == 0:
                        file_stats = t.get("file_stats")
                        if isinstance(file_stats, list):
                            for f in file_stats:
                                if isinstance(f, dict):
                                    p = f.get("path", "")
                                    ext = (
                                        "." + p.rsplit(".", 1)[-1].lower()
                                        if "." in p
                                        else ""
                                    )
                                    if ext in VIDEO_EXTS:
                                        total_vids += 1

                    torrents.append(
                        {
                            "hash": h,
                            "title": t.get("title", h),
                            "poster": t.get("poster", ""),
                            "total_files": total_vids,
                        }
                    )
    return torrents


async def read_torrserver(base_url: str | None = None) -> dict:
    url = get_torrserver_url(base_url)
    if not url:
        return {}
    try:
        version_r = await get_client().get(f"{url}/echo", timeout=6.0)
        version = version_r.text.strip()
        torrents = await get_torrents(base_url)
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        logger.error("Failed to read torrents list from TorrServer: %s", e)
        return {"version": "", "torrents": []}

    return {"version": version, "torrents": torrents}


_file_cache: dict[tuple[str, str], tuple[float, list]] = {}
_file_pending: dict[tuple, asyncio.Task] = {}


async def torrent_video_files(base_url: str | None, hash_: str) -> list:
    key = (get_torrserver_url(base_url), normalize_hash(hash_) or hash_)
    cached = _file_cache.get(key)
    if cached and time.monotonic() - cached[0] < 1800:
        return deepcopy(cached[1])
    pending_key = (asyncio.get_running_loop(), *key)
    task = _file_pending.get(pending_key)
    if task is None:
        async def fetch():
            try:
                async with asyncio.timeout(7):
                    files = await _fetch_video_files(base_url, hash_)
                if files:
                    if len(_file_cache) >= 256:
                        _file_cache.pop(next(iter(_file_cache)))
                    _file_cache[key] = (time.monotonic(), files)
                return files
            except TimeoutError as error:
                raise httpx.ReadTimeout('TorrServer file metadata timed out') from error
            finally:
                _file_pending.pop(pending_key, None)
        task = asyncio.create_task(fetch())
        _file_pending[pending_key] = task
    return deepcopy(await asyncio.shield(task))


async def _fetch_video_files(base_url: str | None, hash_: str) -> list:
    if not hash_ or str(hash_).startswith("online:"):
        return []
    url = get_torrserver_url(base_url)
    h = normalize_hash(hash_)
    if not h:
        return []
    r = await get_client().post(
        f"{url}/torrents",
        json={"action": "get", "hash": h},
        timeout=config.TORRSERVER_HTTP_TIMEOUT,
    )
    if r.status_code == 404:
        # Раздача ещё не добавлена в TorrServer — автоматически регистрируем инфохеш для DHT-парсинга
        try:
            await get_client().post(
                f"{url}/torrents",
                json={"action": "add", "link": h, "title": h, "save_to_db": True},
                timeout=config.TORRSERVER_HTTP_TIMEOUT,
            )
        except httpx.HTTPError as e:
            logger.debug("Auto-add missing torrent %s on 404 failed: %s", h, e)
        return []

    r.raise_for_status()

    if not r.text.strip() or r.text.strip() == "null":
        return []

    try:
        data = r.json()
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON from TorrServer: {e}. Response text: {r.text}")
        return []

    if isinstance(data, list):
        if not data:
            return []
        data = data[0]

    if not isinstance(data, dict):
        return []

    files = []
    raw_data = data.get("data", "")
    if isinstance(raw_data, str) and raw_data:
        try:
            parsed = json.loads(raw_data)
            if isinstance(parsed, dict):
                for f in parsed.get("TorrServer", {}).get("Files", []) or []:
                    if not isinstance(f, dict):
                        continue
                    file_id = f.get("id")
                    if file_id is None:
                        continue

                    path = f.get("path", "")
                    ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
                    if ext in VIDEO_EXTS:
                        files.append(
                            {
                                "id": file_id,
                                "path": path.replace("\\", "/"),
                                "name": path.replace("\\", "/").split("/")[-1],
                                "length": f.get("length", 0),
                            }
                        )
        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            logger.warning("Failed to parse Matrix format TorrServer files: %s", e)

    if not files:
        file_stats = data.get("file_stats")
        if isinstance(file_stats, list):
            for f in file_stats:
                if not isinstance(f, dict):
                    continue
                file_id = f.get("id")
                if file_id is None:
                    continue
                path = f.get("path", "")
                ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
                if ext in VIDEO_EXTS:
                    files.append(
                        {
                            "id": file_id,
                            "path": path.replace("\\", "/"),
                            "name": path.replace("\\", "/").split("/")[-1],
                            "length": f.get("length", 0),
                        }
                    )

    def nat_key(f):
        return [
            int(c) if c.isdigit() else c.lower()
            for c in re.split(r"(\d+)", f.get("name", ""))
        ]

    files.sort(key=nat_key)
    return files


def stream_url(base_url: str | None, hash_: str, file_id: int, file_name: str) -> str:
    url = get_torrserver_url(base_url)
    h = normalize_hash(hash_) or hash_
    encoded_name = quote(file_name, safe="")
    return f"{url}/stream/{encoded_name}?link={h}&index={file_id}&play"


async def search_torrserver(base_url: str | None, query: str) -> list:
    url = get_torrserver_url(base_url)
    encoded = quote(query)
    try:
        r = await get_client().get(
            f"{url}/search/?query={encoded}",
            timeout=config.TORRSERVER_HTTP_TIMEOUT,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise RuntimeError("TorrServer search request failed") from e

    try:
        raw_items = r.json()
    except json.JSONDecodeError as e:
        raise RuntimeError("Invalid TorrServer search JSON") from e

    if not isinstance(raw_items, list):
        raise TypeError("Invalid TorrServer search response")

    results = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        magnet = item.get("Magnet", "")
        h = magnet_info_hash(magnet) if magnet else normalize_hash(item.get("Hash", ""))
        if not h:
            continue
        results.append(
            {
                "title": item.get("Title", ""),
                "hash": h,
                "seeders": item.get("Seed", 0),
                "size": item.get("Size") or item.get("size") or item.get("Length"),
                "magnet": magnet or f"magnet:?xt=urn:btih:{h}",
                "source": "TorrServer",
            }
        )
    return results


async def search_torznab(
    base_url: str | None, torznab_url: str, api_key: str, query: str
) -> list:
    params = {
        "t": "search",
        "q": query,
        "cat": "2000,2010,2020,2030,2040,2045,2050,2060",
    }
    if api_key and "apikey=" not in torznab_url.lower():
        params["apikey"] = api_key

    r = await get_client().get(
        torznab_url,
        params=params,
        timeout=config.TORRSERVER_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    results = []

    try:
        root = ET.fromstring(r.text)
        ns = {"torznab": "http://torznab.com/schemas/2015/feed"}
        channel = root.find("channel")
        indexer_name = (
            channel.findtext("title", "Torznab") if channel is not None else "Torznab"
        )
        items = (channel if channel is not None else root).findall("item")

        for item in items:
            magnet = item.findtext("link", "")
            enclosure = item.find("enclosure")
            if enclosure is not None and not magnet:
                magnet = enclosure.get("url", "")
            h = magnet_info_hash(magnet) if magnet else None
            if not h:
                continue

            seeders_el = item.find(".//torznab:attr[@name='seeders']", ns)
            try:
                seeders = (
                    int(seeders_el.get("value", 0)) if seeders_el is not None else 0
                )
            except (ValueError, TypeError):
                seeders = 0

            tracker_el = item.find(".//torznab:attr[@name='tracker']", ns)
            tracker = (
                tracker_el.get("value", indexer_name)
                if tracker_el is not None
                else indexer_name
            )

            results.append(
                {
                    "title": item.findtext("title", ""),
                    "hash": h,
                    "seeders": seeders,
                    "magnet": magnet,
                    "source": indexer_name,
                    "tracker": tracker,
                }
            )
    except (ET.ParseError, ValueError, AttributeError) as e:
        logger.warning("Failed to parse Torznab XML response: %s", e)

    return results


async def read_torznab_config(base_url: str | None = None) -> dict | None:
    url = get_torrserver_url(base_url)
    try:
        r = await get_client().post(
            f"{url}/settings", json={"action": "get"}, timeout=6.0
        )
        r.raise_for_status()
        data = r.json()

        if not isinstance(data, dict):
            return None

        # 1. Матрикс TorznabUrls
        torznab_urls = data.get("TorznabUrls")
        if (
            data.get("EnableTorznabSearch")
            and isinstance(torznab_urls, list)
            and torznab_urls
        ):
            first_url = torznab_urls[0]
            if isinstance(first_url, str) and first_url:
                return {"url": first_url, "api_key": ""}

        # 2. Providers list (старые версии TorrServer)
        providers = data.get("Providers", [])
        if isinstance(providers, list):
            for p in providers:
                if not isinstance(p, dict):
                    continue
                name = (p.get("Name") or "").lower()
                if (name in ("torznab", "jackett", "rutor") or p.get("Host")) and p.get(
                    "Enabled"
                ):
                    return {"url": p.get("Host", ""), "api_key": p.get("Token", "")}
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        logger.debug("Could not read Torznab config: %s", e)
        return None

    return None


async def add_magnet(base_url: str | None, magnet: str, title: str) -> dict:
    url = get_torrserver_url(base_url)
    r = await get_client().post(
        f"{url}/torrents",
        json={
            "action": "add",
            "link": magnet,
            "title": title,
            "save_to_db": True,
        },
        timeout=config.TORRSERVER_HTTP_TIMEOUT,
    )
    r.raise_for_status()

    try:
        data = r.json()
    except json.JSONDecodeError as e:
        logger.error("Failed to parse add_magnet response: %s", e)
        return {"hash": "", "already_exists": False}

    if isinstance(data, list):
        if not data:
            return {"hash": "", "already_exists": False}
        data = data[0]

    if not isinstance(data, dict):
        return {"hash": "", "already_exists": False}

    h = normalize_hash(data.get("hash", "")) or ""
    return {"hash": h, "already_exists": data.get("status", "") == "exists"}


async def save_torrent_to_db(base_url: str | None, hash_: str, title: str = "") -> None:
    if not hash_ or str(hash_).startswith("online:"):
        return
    url = get_torrserver_url(base_url)
    h = normalize_hash(hash_)
    if not url or not h:
        return
    client = get_client()
    try:
        await client.post(
            f"{url}/torrents",
            json={"action": "set", "hash": h, "save_to_db": True},
            timeout=config.TORRSERVER_HTTP_TIMEOUT,
        )
    except httpx.HTTPError:
        pass
    try:
        await client.post(
            f"{url}/torrents",
            json={"action": "add", "link": h, "title": title or h, "save_to_db": True},
            timeout=config.TORRSERVER_HTTP_TIMEOUT,
        )
    except httpx.HTTPError:
        pass


async def remove_torrent(base_url: str | None, hash_: str) -> None:
    _file_cache.pop((get_torrserver_url(base_url), normalize_hash(hash_) or hash_), None)
    if not hash_ or str(hash_).startswith("online:"):
        return
    url = get_torrserver_url(base_url)
    h = normalize_hash(hash_)
    if not h:
        return
    r = await get_client().post(
        f"{url}/torrents",
        json={"action": "rem", "hash": h},
        timeout=config.TORRSERVER_HTTP_TIMEOUT,
    )
    r.raise_for_status()


async def search_all(base_url: str | None, query: str) -> list:
    from backend.core.settings import load_settings

    url = get_torrserver_url(base_url)
    results = await search_torrserver(url, query)

    prefs = load_settings()
    jackett_url = prefs.get("jackett_url")
    jackett_key = prefs.get("jackett_api_key", "")

    if not jackett_url:
        torznab_cfg = await read_torznab_config(url)
        if torznab_cfg and torznab_cfg.get("url"):
            jackett_url = torznab_cfg["url"]
            jackett_key = torznab_cfg.get("api_key", "")

    if jackett_url:
        try:
            torznab_results = await search_torznab(url, jackett_url, jackett_key, query)
            seen = {r["hash"] for r in results if isinstance(r, dict) and "hash" in r}
            for r in torznab_results:
                if isinstance(r, dict) and r.get("hash") not in seen:
                    results.append(r)
                    seen.add(r["hash"])
        except httpx.HTTPError as e:
            logger.warning("Torznab search request failed: %s", e)

    results.sort(
        key=lambda r: r.get("seeders", 0) if isinstance(r, dict) else 0, reverse=True
    )
    return results


RAM_CACHE_LIMIT = 256 * 1024 * 1024


def ram_cache_verified(settings) -> bool:
    return (isinstance(settings, dict) and settings.get('UseDisk') is False
            and type(settings.get('CacheSize')) is int
            and 0 < settings['CacheSize'] <= RAM_CACHE_LIMIT)


async def require_ram_cache(base_url: str | None = None) -> None:
    """Strict playback gate. Read external settings; never modify them."""
    from backend.exceptions import ExternalServiceError
    try:
        response = await get_client().post(f'{get_torrserver_url(base_url)}/settings',
                                           json={'action': 'get'}, timeout=4.0)
        response.raise_for_status()
        verified = ram_cache_verified(response.json())
    except (httpx.HTTPError, ValueError):
        verified = False
    if not verified:
        raise ExternalServiceError(
            'RAM-only кеш TorrServer не подтверждён. В настройках сервера отключите UseDisk '
            'и установите CacheSize от 1 до 256 MiB, затем повторите запуск. '
            'Настройки внешнего сервера приложение не изменяет.', status_code=409)


# ─── Universal Torrent Engine Abstraction (G-011) ───


class AwaitableStr(str):
    """String subclass that is awaitable, allowing get_stream_url to work both sync and async."""

    def __await__(self):
        async def _wrapper():
            return str(self)

        return _wrapper().__await__()


class TorrentEngine(ABC):
    """Universal interface for torrent streaming engines."""

    @abstractmethod
    async def add_torrent(
        self, torrent: str, title: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        """Add a torrent (magnet URI, hash, or link) to the engine.

        Returns a dictionary with at least 'hash' and 'already_exists'.
        """
        ...

    @abstractmethod
    async def remove_torrent(self, hash_: str, **kwargs: Any) -> Any:
        """Remove a torrent from the engine by its hash."""
        ...

    @abstractmethod
    async def get_files(
        self, hash_: str, **kwargs: Any
    ) -> list[dict[str, Any]]:
        """Get video/media files available in the torrent."""
        ...

    @abstractmethod
    def get_stream_url(
        self,
        hash_: str,
        file_id: int | str = 0,
        file_name: str = "",
        **kwargs: Any,
    ) -> str:
        """Get playable HTTP stream URL for a specific file in the torrent."""
        ...

    @abstractmethod
    async def get_stats(
        self, hash_: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        """Get engine or torrent statistics."""
        ...


ITorrentEngine = TorrentEngine


async def get_stats(base_url: str | None = None, hash_: str = "") -> dict[str, Any]:
    """Fetch torrent stats or TorrServer general stats."""
    url = get_torrserver_url(base_url)
    if not url:
        return {"status": "offline", "error": "No base URL"}

    h = normalize_hash(hash_) if hash_ else None
    if h:
        try:
            r = await get_client().post(
                f"{url}/torrents",
                json={"action": "get", "hash": h},
                timeout=config.TORRSERVER_HTTP_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    data = data[0]
                if isinstance(data, dict):
                    return {
                        "hash": h,
                        "title": data.get("title", ""),
                        "stat": data.get("stat", 0),
                        "stat_string": data.get("stat_string", ""),
                        "download_speed": data.get("download_speed", 0.0),
                        "upload_speed": data.get("upload_speed", 0.0),
                        "connected_seeders": data.get("connected_seeders", 0),
                        "active_peers": data.get("active_peers", 0),
                        "total_peers": data.get("total_peers", 0),
                        "bytes_read": data.get("bytes_read", 0),
                        "bytes_written": data.get("bytes_written", 0),
                        "size": data.get("torrent_size") or data.get("size", 0),
                        "loaded_size": data.get("loaded_size", 0),
                        "raw": data,
                    }
            return {"hash": h, "stat": 0, "stat_string": "Torrent not found"}
        except Exception as e:
            logger.debug("Failed to get stats for torrent %s: %s", h, e)
            return {"hash": h, "stat": 0, "stat_string": f"Error: {e}"}

    try:
        res = await read_torrserver(url)
        return {
            "status": "online" if res.get("version") else "unknown",
            "version": res.get("version", ""),
            "torrents_count": len(res.get("torrents", [])),
            "torrents": res.get("torrents", []),
        }
    except Exception as e:
        return {"status": "offline", "error": str(e)}


async def add_torrent(
    base_url: str | None = None,
    torrent: str = "",
    title: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Module-level helper to add torrent matching TorrentEngine signature."""
    return await add_magnet(base_url, torrent, title)


async def get_files(
    base_url: str | None = None,
    hash_: str = "",
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Module-level helper to get files matching TorrentEngine signature."""
    return await torrent_video_files(base_url, hash_)


def get_stream_url(
    base_url: str | None = None,
    hash_: str = "",
    file_id: int | str = 0,
    file_name: str = "",
    **kwargs: Any,
) -> AwaitableStr:
    """Module-level helper to get stream URL matching TorrentEngine signature."""
    fid = int(file_id) if str(file_id).isdigit() else 0
    return AwaitableStr(stream_url(base_url, hash_, fid, file_name))


class TorrServerAdapter(TorrentEngine):
    """Adapter wrapping TorrServer client into the universal TorrentEngine interface."""

    def __init__(
        self,
        base_url: str | Callable[[], str] | None = None,
        client: Any = None,
    ):
        self._base_url = base_url
        self._client = client

    def _get_base_url(self) -> str:
        if callable(self._base_url):
            try:
                res = self._base_url()
                return str(res) if res else get_torrserver_url()
            except Exception:
                return get_torrserver_url()
        if isinstance(self._base_url, str) and self._base_url:
            return self._base_url
        return get_torrserver_url()

    async def add_torrent(
        self,
        torrent: str,
        title: str = "",
        base_url: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        url = base_url or self._get_base_url()
        client_obj = self._client
        if client_obj is not None:
            if isinstance(client_obj, TorrentEngine):
                return await client_obj.add_torrent(torrent, title=title, **kwargs)
            # Prioritize legacy client methods if mocked or present on client module/mock
            if hasattr(client_obj, "add_magnet"):
                res = client_obj.add_magnet(url, torrent, title)
                if inspect.isawaitable(res):
                    return await res
                return res
            if hasattr(client_obj, "add_torrent"):
                res = client_obj.add_torrent(torrent, title=title, **kwargs)
                if inspect.isawaitable(res):
                    return await res
                return res
        return await add_magnet(url, torrent, title)

    async def add_magnet(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Backwards-compatible alias supporting (base_url, magnet, title) or (magnet, title)."""
        if len(args) >= 3:
            return await self.add_torrent(torrent=args[1], title=args[2], base_url=args[0], **kwargs)
        if len(args) == 2:
            return await self.add_torrent(torrent=args[0], title=args[1], **kwargs)
        if len(args) == 1:
            return await self.add_torrent(torrent=args[0], **kwargs)
        return await self.add_torrent(**kwargs)

    async def remove_torrent(self, *args: Any, **kwargs: Any) -> Any:
        """Remove torrent supporting both remove_torrent(hash) and remove_torrent(base_url, hash)."""
        if len(args) >= 2:
            url = args[0]
            hash_ = args[1]
        elif len(args) == 1:
            url = kwargs.get("base_url") or self._get_base_url()
            hash_ = args[0]
        else:
            url = kwargs.get("base_url") or self._get_base_url()
            hash_ = kwargs.get("hash_") or kwargs.get("hash", "")

        client_obj = self._client
        if client_obj is not None:
            if isinstance(client_obj, TorrentEngine):
                return await client_obj.remove_torrent(hash_, **kwargs)
            if hasattr(client_obj, "remove_torrent"):
                try:
                    sig = inspect.signature(client_obj.remove_torrent)
                    params_count = len(sig.parameters)
                except (ValueError, TypeError):
                    params_count = 2

                if params_count >= 2:
                    res = client_obj.remove_torrent(url, hash_)
                else:
                    res = client_obj.remove_torrent(hash_)
                if inspect.isawaitable(res):
                    await res
                return {"status": "removed"}

        await remove_torrent(url, hash_)
        return {"status": "removed"}

    async def get_files(
        self,
        hash_: str,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        url = base_url or self._get_base_url()
        client_obj = self._client
        if client_obj is not None:
            if isinstance(client_obj, TorrentEngine):
                return await client_obj.get_files(hash_, **kwargs)
            if hasattr(client_obj, "torrent_video_files"):
                res = client_obj.torrent_video_files(url, hash_)
                if inspect.isawaitable(res):
                    return await res
                return res
            if hasattr(client_obj, "get_files"):
                res = client_obj.get_files(hash_, **kwargs)
                if inspect.isawaitable(res):
                    return await res
                return res
        return await torrent_video_files(url, hash_)

    async def torrent_video_files(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """Backwards-compatible alias for torrent_video_files(base_url, hash_) or torrent_video_files(hash_)."""
        if len(args) >= 2:
            return await self.get_files(hash_=args[1], base_url=args[0], **kwargs)
        if len(args) == 1:
            return await self.get_files(hash_=args[0], **kwargs)
        return await self.get_files(**kwargs)

    def get_stream_url(
        self,
        hash_: str,
        file_id: int | str = 0,
        file_name: str = "",
        base_url: str | None = None,
        **kwargs: Any,
    ) -> AwaitableStr:
        url = get_torrserver_url(base_url or self._get_base_url())
        client_obj = self._client
        if client_obj is not None:
            if isinstance(client_obj, TorrentEngine):
                return AwaitableStr(client_obj.get_stream_url(hash_, file_id=file_id, file_name=file_name, **kwargs))
            if hasattr(client_obj, "stream_url"):
                return AwaitableStr(client_obj.stream_url(url, hash_, int(file_id) if str(file_id).isdigit() else 0, file_name))
            if hasattr(client_obj, "get_stream_url"):
                return AwaitableStr(client_obj.get_stream_url(hash_, file_id=file_id, file_name=file_name, **kwargs))
        fid = int(file_id) if str(file_id).isdigit() else 0
        return AwaitableStr(stream_url(url, hash_, fid, file_name))

    def stream_url(self, *args: Any, **kwargs: Any) -> str:
        """Backwards-compatible alias for stream_url(base_url, hash_, file_id, file_name)."""
        if len(args) >= 4:
            return self.get_stream_url(base_url=args[0], hash_=args[1], file_id=args[2], file_name=args[3])
        if len(args) == 3:
            return self.get_stream_url(hash_=args[0], file_id=args[1], file_name=args[2])
        return self.get_stream_url(**kwargs)

    async def get_stats(
        self,
        hash_: str = "",
        base_url: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        url = get_torrserver_url(base_url or self._get_base_url())
        return await get_stats(url, hash_=hash_)

    async def probe(self, base_url: str | None = None) -> bool:
        url = base_url or self._get_base_url()
        client_obj = self._client
        if client_obj is not None and hasattr(client_obj, "probe"):
            res = client_obj.probe(url)
            if inspect.isawaitable(res):
                return await res
            return res
        return await probe(url)

    async def read_torrserver(self, base_url: str | None = None) -> dict[str, Any]:
        url = base_url or self._get_base_url()
        client_obj = self._client
        if client_obj is not None and hasattr(client_obj, "read_torrserver"):
            res = client_obj.read_torrserver(url)
            if inspect.isawaitable(res):
                return await res
            return res
        return await read_torrserver(url)

    async def save_torrent_to_db(self, *args: Any, **kwargs: Any) -> None:
        if len(args) >= 3:
            url, hash_, title = args[0], args[1], args[2]
        elif len(args) == 2:
            url, hash_, title = self._get_base_url(), args[0], args[1]
        elif len(args) == 1:
            url, hash_, title = self._get_base_url(), args[0], ""
        else:
            url = kwargs.get("base_url") or self._get_base_url()
            hash_ = kwargs.get("hash_") or kwargs.get("hash", "")
            title = kwargs.get("title", "")

        client_obj = self._client
        if client_obj is not None and hasattr(client_obj, "save_torrent_to_db"):
            res = client_obj.save_torrent_to_db(url, hash_, title)
            if inspect.isawaitable(res):
                await res
            return
        await save_torrent_to_db(url, hash_, title)

    async def require_ram_cache(self, base_url: str | None = None) -> None:
        url = base_url or self._get_base_url()
        client_obj = self._client
        if client_obj is not None and hasattr(client_obj, "require_ram_cache"):
            res = client_obj.require_ram_cache(url)
            if inspect.isawaitable(res):
                await res
            return
        await require_ram_cache(url)

    async def search_torrserver(self, query: str, base_url: str | None = None) -> list[dict[str, Any]]:
        url = base_url or self._get_base_url()
        return await search_torrserver(url, query)

    async def search_all(self, query: str, base_url: str | None = None) -> list[dict[str, Any]]:
        url = base_url or self._get_base_url()
        return await search_all(url, query)


class FakeTorrentEngine(TorrentEngine):
    """In-memory fake torrent engine for offline testing without a real TorrServer."""

    def __init__(
        self,
        base_url: str = "http://fake-engine:8090",
        initial_torrents: dict[str, dict[str, Any]] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.torrents: dict[str, dict[str, Any]] = (
            deepcopy(initial_torrents) if initial_torrents else {}
        )
        self.files: dict[str, list[dict[str, Any]]] = {}
        self.stats: dict[str, dict[str, Any]] = {}

    def _normalize(self, value: str) -> str:
        if not value:
            return "0" * 40
        h = normalize_hash(value) or magnet_info_hash(value)
        if h:
            return h
        return hashlib.sha1(value.encode("utf-8")).hexdigest()

    async def add_torrent(
        self, torrent: str, title: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        h = self._normalize(torrent)
        already_exists = h in self.torrents
        effective_title = title or f"Fake Torrent {h[:8]}"
        self.torrents[h] = {
            "hash": h,
            "title": effective_title,
            "link": torrent,
            "already_exists": already_exists,
        }
        if h not in self.files:
            self.files[h] = [
                {
                    "id": 1,
                    "name": f"{effective_title}.mp4",
                    "path": f"{effective_title}.mp4",
                    "length": 104857600,
                }
            ]
        if h not in self.stats:
            self.stats[h] = {
                "hash": h,
                "title": effective_title,
                "stat": 1,
                "stat_string": "Torrent working (fake)",
                "download_speed": 10485760.0,
                "upload_speed": 524288.0,
                "connected_seeders": 42,
                "active_peers": 20,
                "total_peers": 50,
                "bytes_read": 104857600,
                "bytes_written": 0,
                "size": 104857600,
                "loaded_size": 104857600,
            }
        return {"hash": h, "already_exists": already_exists}

    async def add_magnet(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if len(args) >= 3 and isinstance(args[0], str) and (args[0].startswith("http://") or args[0].startswith("https://")):
            return await self.add_torrent(torrent=args[1], title=args[2], **kwargs)
        if len(args) >= 2:
            return await self.add_torrent(torrent=args[0], title=args[1], **kwargs)
        if len(args) == 1:
            return await self.add_torrent(torrent=args[0], **kwargs)
        return await self.add_torrent(**kwargs)

    async def remove_torrent(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        if len(args) >= 2:
            hash_ = args[1]
        elif len(args) == 1:
            hash_ = args[0]
        else:
            hash_ = kwargs.get("hash_") or kwargs.get("hash", "")
        h = self._normalize(hash_)
        self.torrents.pop(h, None)
        self.files.pop(h, None)
        self.stats.pop(h, None)
        return {"status": "removed"}

    async def get_files(
        self, hash_: str, **kwargs: Any
    ) -> list[dict[str, Any]]:
        h = self._normalize(hash_)
        if h in self.files:
            return deepcopy(self.files[h])
        return [
            {
                "id": 1,
                "name": "sample.mp4",
                "path": "sample.mp4",
                "length": 104857600,
            }
        ]

    async def torrent_video_files(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        if len(args) >= 2:
            return await self.get_files(args[1], **kwargs)
        if len(args) == 1:
            return await self.get_files(args[0], **kwargs)
        return await self.get_files(**kwargs)

    def get_stream_url(
        self,
        hash_: str,
        file_id: int | str = 0,
        file_name: str = "",
        **kwargs: Any,
    ) -> AwaitableStr:
        h = self._normalize(hash_)
        encoded_name = quote(file_name or "video.mp4", safe="")
        return AwaitableStr(
            f"{self.base_url}/stream/{encoded_name}?link={h}&index={file_id}&play"
        )

    def stream_url(self, *args: Any, **kwargs: Any) -> str:
        if len(args) >= 4:
            return self.get_stream_url(hash_=args[1], file_id=args[2], file_name=args[3])
        if len(args) >= 3:
            return self.get_stream_url(hash_=args[0], file_id=args[1], file_name=args[2])
        return self.get_stream_url(**kwargs)

    async def get_stats(
        self, hash_: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        if hash_:
            h = self._normalize(hash_)
            if h in self.stats:
                return deepcopy(self.stats[h])
            return {
                "hash": h,
                "title": "",
                "stat": 1,
                "stat_string": "Torrent working (fake)",
                "download_speed": 1048576.0,
                "upload_speed": 0.0,
                "connected_seeders": 10,
                "active_peers": 5,
                "total_peers": 10,
                "bytes_read": 1048576,
                "bytes_written": 0,
                "size": 104857600,
                "loaded_size": 104857600,
            }
        return {
            "status": "online",
            "version": "FakeTorrentEngine/1.0",
            "torrents_count": len(self.torrents),
            "torrents": list(self.torrents.values()),
        }

    async def probe(self, *args: Any, **kwargs: Any) -> bool:
        return True

    async def require_ram_cache(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def save_torrent_to_db(self, *args: Any, **kwargs: Any) -> None:
        pass

    def add_fake_file(
        self,
        hash_: str,
        file_id: int,
        name: str,
        length: int = 104857600,
        path: str = "",
    ) -> None:
        h = self._normalize(hash_)
        if h not in self.files:
            self.files[h] = []
        self.files[h].append(
            {
                "id": file_id,
                "name": name,
                "path": path or name,
                "length": length,
            }
        )

    def set_fake_stats(self, hash_: str, stats: dict[str, Any]) -> None:
        h = self._normalize(hash_)
        self.stats[h] = stats

    def reset(self) -> None:
        self.torrents.clear()
        self.files.clear()
        self.stats.clear()
