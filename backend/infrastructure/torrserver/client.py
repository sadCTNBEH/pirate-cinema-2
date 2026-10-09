import base64
import binascii
import json
import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

import httpx

from backend.core.enums import VideoExtension
from backend.core.settings.config import config

VIDEO_EXTS = VideoExtension.values()

logger = logging.getLogger("torrserver")
logger.setLevel(logging.DEBUG)

_client: httpx.AsyncClient | None = None


def get_torrserver_url(base_url: str | None = None) -> str:
    url = base_url or config.TORRSERVER_DEFAULT_URL
    return url.rstrip("/")


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=config.TORRSERVER_HTTP_TIMEOUT,
            follow_redirects=True,
        )
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


async def read_torrserver(base_url: str | None = None) -> dict:
    url = get_torrserver_url(base_url)
    if not url:
        return {}
    try:
        version_r = await get_client().get(f"{url}/echo", timeout=6.0)
        version = version_r.text.strip()
        list_r = await get_client().post(
            f"{url}/torrents", json={"action": "list"}, timeout=6.0
        )
        raw_torrents = list_r.json()
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        logger.error("Failed to read torrents list from TorrServer: %s", e)
        return {"version": "", "torrents": []}

    torrents = []
    if isinstance(raw_torrents, list):
        for t in raw_torrents:
            if isinstance(t, dict):
                h = normalize_hash(t.get("hash", ""))
                if h:
                    torrents.append(
                        {
                            "hash": h,
                            "title": t.get("title", h),
                            "poster": t.get("poster", ""),
                        }
                    )
    return {"version": version, "torrents": torrents}


async def torrent_video_files(base_url: str | None, hash_: str) -> list:
    url = get_torrserver_url(base_url)
    h = normalize_hash(hash_) or hash_
    r = await get_client().post(
        f"{url}/torrents",
        json={"action": "get", "hash": h},
        timeout=config.TORRSERVER_HTTP_TIMEOUT,
    )
    
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
                    ext = (
                        "." + path.rsplit(".", 1)[-1].lower()
                        if "." in path
                        else ""
                    )
                    if ext in VIDEO_EXTS:
                        files.append(
                            {
                                "id": file_id,
                                "name": path.split("/")[-1],
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
                ext = (
                    "." + path.rsplit(".", 1)[-1].lower()
                    if "." in path
                    else ""
                )
                if ext in VIDEO_EXTS:
                    files.append(
                        {
                            "id": file_id,
                            "name": path.split("/")[-1],
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
    except httpx.HTTPError as e:
        logger.warning("TorrServer search failed: %s", e)
        return []

    try:
        raw_items = r.json()
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON from TorrServer search: %s", e)
        return []

    if not isinstance(raw_items, list):
        return []

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
                    int(seeders_el.get("value", 0))
                    if seeders_el is not None
                    else 0
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
        if data.get("EnableTorznabSearch") and isinstance(torznab_urls, list) and torznab_urls:
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
                if (name in ("torznab", "jackett", "rutor") or p.get("Host")) and p.get("Enabled"):
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


async def remove_torrent(base_url: str | None, hash_: str) -> None:
    url = get_torrserver_url(base_url)
    h = normalize_hash(hash_)
    if not h:
        raise ValueError("Invalid hash")
    await get_client().post(
        f"{url}/torrents",
        json={"action": "rem", "hash": h},
        timeout=config.TORRSERVER_HTTP_TIMEOUT,
    )


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
            torznab_results = await search_torznab(
                url, jackett_url, jackett_key, query
            )
            seen = {r["hash"] for r in results if isinstance(r, dict) and "hash" in r}
            for r in torznab_results:
                if isinstance(r, dict) and r.get("hash") not in seen:
                    results.append(r)
                    seen.add(r["hash"])
        except httpx.HTTPError as e:
            logger.warning("Torznab search request failed: %s", e)

    results.sort(key=lambda r: r.get("seeders", 0) if isinstance(r, dict) else 0, reverse=True)
    return results
