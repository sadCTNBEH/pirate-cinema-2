"""TorrServer client – mirrors lib.rs: read_torrserver, search_torrserver,
search_torznab, add_magnet, remove_torrent, torrent_video_files, stream_url."""
import re
import asyncio
from typing import Optional
from urllib.parse import quote, urlencode
import httpx
import xml.etree.ElementTree as ET

TORRSERVER_URL = "http://127.0.0.1:8090"
VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts", ".m2ts"}

_client: Optional[httpx.AsyncClient] = None

def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=20.0, follow_redirects=True)
    return _client


def normalize_hash(value: str) -> Optional[str]:
    v = value.strip().lower()
    # hex
    if re.fullmatch(r'[0-9a-f]{40}', v):
        return v
    # base32 btih
    import base64
    try:
        decoded = base64.b32decode(v.upper() + "=" * (-len(v) % 8))
        if len(decoded) == 20:
            return decoded.hex()
    except Exception:
        pass
    return None


def magnet_info_hash(magnet: str) -> Optional[str]:
    m = re.search(r'xt=urn:btih:([0-9a-fA-F]{40}|[A-Za-z2-7]{32})', magnet)
    if not m:
        return None
    return normalize_hash(m.group(1))


async def probe(base_url: str = TORRSERVER_URL) -> bool:
    try:
        r = await get_client().get(f"{base_url.rstrip('/')}/echo", timeout=4.0)
        return r.status_code == 200
    except Exception:
        return False


async def read_torrserver(base_url: str = TORRSERVER_URL) -> dict:
    base = base_url.rstrip('/')
    version_r = await get_client().get(f"{base}/echo", timeout=6.0)
    version = version_r.text.strip()
    list_r = await get_client().post(f"{base}/torrents", json={"action": "list"}, timeout=6.0)
    torrents = []
    for t in list_r.json() or []:
        h = normalize_hash(t.get("hash", ""))
        if h:
            torrents.append({"hash": h, "title": t.get("title", h), "poster": t.get("poster", "")})
    return {"version": version, "torrents": torrents}


async def torrent_video_files(base_url: str, hash_: str) -> list:
    base = base_url.rstrip('/')
    h = normalize_hash(hash_) or hash_
    r = await get_client().post(f"{base}/torrents", json={"action": "get", "hash": h}, timeout=20.0)
    data = r.json()

    files = []
    # Try 'data' field first (Matrix format)
    raw_data = data.get("data", "")
    if raw_data:
        try:
            import json
            parsed = json.loads(raw_data)
            for f in parsed.get("TorrServer", {}).get("Files", []):
                path = f.get("path", "")
                ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
                if ext in VIDEO_EXTS:
                    files.append({"id": f["id"], "name": path.split("/")[-1], "length": f.get("length", 0)})
        except Exception:
            pass

    if not files:
        for f in data.get("file_stats") or []:
            path = f.get("path", "")
            ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if ext in VIDEO_EXTS:
                files.append({"id": f["id"], "name": path.split("/")[-1], "length": f.get("length", 0)})

    # Natural sort
    def nat_key(f):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', f["name"])]
    files.sort(key=nat_key)
    return files


def stream_url(base_url: str, hash_: str, file_id: int, file_name: str) -> str:
    h = normalize_hash(hash_) or hash_
    encoded_name = quote(file_name, safe="")
    return f"{base_url.rstrip('/')}/stream/{encoded_name}?link={h}&index={file_id}&play"


async def search_torrserver(base_url: str, query: str) -> list:
    base = base_url.rstrip('/')
    encoded = quote(query)
    r = await get_client().get(f"{base}/search?query={encoded}", timeout=20.0)
    results = []
    for item in r.json() or []:
        magnet = item.get("Magnet", "")
        h = magnet_info_hash(magnet) if magnet else normalize_hash(item.get("Hash", ""))
        if not h:
            continue
        results.append({
            "title": item.get("Title", ""),
            "hash": h,
            "seeders": item.get("Seed", 0),
            "magnet": magnet or f"magnet:?xt=urn:btih:{h}",
            "source": "TorrServer",
        })
    return results


async def search_torznab(base_url: str, torznab_url: str, api_key: str, query: str) -> list:
    params = {"t": "search", "q": query, "cat": "2000,2010,2020,2030,2040,2045,2050,2060"}
    if api_key and "apikey=" not in torznab_url.lower():
        params["apikey"] = api_key
    if "?" in torznab_url:
        url = f"{torznab_url}&{urlencode(params)}"
    else:
        url = f"{torznab_url}?{urlencode(params)}"
    r = await get_client().get(url, timeout=20.0)
    results = []
    try:
        root = ET.fromstring(r.text)
        ns = {"torznab": "http://torznab.com/schemas/2015/feed"}
        channel = root.find("channel")
        indexer_name = channel.findtext("title", "Torznab") if channel else "Torznab"
        for item in (channel or root).findall("item"):
            magnet = item.findtext("link", "")
            enclosure = item.find("enclosure")
            if enclosure is not None and not magnet:
                magnet = enclosure.get("url", "")
            h = magnet_info_hash(magnet) if magnet else None
            if not h:
                continue
            seeders_el = item.find(".//torznab:attr[@name='seeders']", ns)
            seeders = int(seeders_el.get("value", 0)) if seeders_el is not None else 0
            tracker_el = item.find(".//torznab:attr[@name='tracker']", ns)
            tracker = tracker_el.get("value", indexer_name) if tracker_el is not None else indexer_name
            results.append({
                "title": item.findtext("title", ""),
                "hash": h,
                "seeders": seeders,
                "magnet": magnet,
                "source": indexer_name,
                "tracker": tracker,
            })
    except Exception:
        pass
    return results


async def read_torznab_config(base_url: str) -> Optional[dict]:
    base = base_url.rstrip('/')
    try:
        r = await get_client().post(f"{base}/settings", json={"action": "get"}, timeout=6.0)
        data = r.json()
        providers = data.get("Providers", [])
        for p in providers:
            if p.get("Name", "").lower() in ("torznab", "jackett") and p.get("Enabled"):
                return {"url": p.get("Host", ""), "api_key": p.get("Token", "")}
    except Exception:
        pass
    return None


async def add_magnet(base_url: str, magnet: str, title: str) -> dict:
    base = base_url.rstrip('/')
    r = await get_client().post(f"{base}/torrents", json={
        "action": "add", "link": magnet, "title": title, "save_to_db": True
    }, timeout=20.0)
    data = r.json()
    h = normalize_hash(data.get("hash", "")) or ""
    return {"hash": h, "already_exists": data.get("status", "") == "exists"}


async def remove_torrent(base_url: str, hash_: str):
    h = normalize_hash(hash_)
    if not h:
        raise ValueError("Invalid hash")
    await get_client().post(f"{base_url.rstrip('/')}/torrents", json={"action": "rem", "hash": h}, timeout=20.0)


async def search_all(base_url: str, query: str) -> list:
    results = await search_torrserver(base_url, query)
    config = await read_torznab_config(base_url)
    if config and config.get("url"):
        torznab_results = await search_torznab(base_url, config["url"], config.get("api_key", ""), query)
        # Deduplicate by hash
        seen = {r["hash"] for r in results}
        for r in torznab_results:
            if r["hash"] not in seen:
                results.append(r)
                seen.add(r["hash"])
    results.sort(key=lambda r: r.get("seeders", 0), reverse=True)
    return results
