"""Catalog service – fetches popular movies/series from Cinemeta (Stremio).
Mirrors catalog.rs: popular(), lookup(), clean_title()."""
import json
import re

from backend.core.settings.config import config
import httpx

CINEMETA = config.CINEMETA_URL
UA = config.USER_AGENT

_client: httpx.AsyncClient | None = None

def _get() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=config.CINEMETA_TIMEOUT, follow_redirects=True, headers={"user-agent": UA, "accept": "application/json"})
    return _client


def valid_imdb(id_: str) -> bool:
    m = id_.lstrip()
    return m.startswith("tt") and m[2:].isdigit() and 1 <= len(m[2:]) <= 12


def _parse_year(val) -> int | None:
    if val is None:
        return None
    text = str(val)
    m = re.search(r'(19|20)\d{2}', text)
    return int(m.group()) if m else None


def _parse_catalog(data: dict) -> list[dict]:
    items = []
    for item in (data.get("metas") or [])[:config.CATALOG_LIMIT]:
        id_ = item.get("imdb_id") or item.get("id") or ""
        title = (item.get("name") or item.get("title") or "").strip()
        if not valid_imdb(id_) or not title:
            continue
        items.append({
            "id": id_,
            "title": title,
            "original_title": title,
            "year": _parse_year(item.get("releaseInfo") or item.get("year")),
            "rating": _parse_rating(item.get("imdbRating")),
            "poster_url": item.get("poster"),
            "background_url": item.get("background"),
            "overview": item.get("description"),
            "genres": [g.strip() for g in (item.get("genres") or item.get("genre") or []) if g.strip()][:12],
        })
    return items


def _parse_rating(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


async def popular() -> list[dict]:
    """Fetch top movies from Cinemeta."""
    try:
        r = await _get().get(f"{CINEMETA}/catalog/movie/top.json")
        r.raise_for_status()
        return _parse_catalog(r.json())
    except (httpx.HTTPError, json.JSONDecodeError):
        return []


async def popular_series() -> list[dict]:
    """Fetch top series from Cinemeta."""
    try:
        r = await _get().get(f"{CINEMETA}/catalog/series/top.json")
        r.raise_for_status()
        return _parse_catalog(r.json())
    except (httpx.HTTPError, json.JSONDecodeError):
        return []


async def lookup(imdb_id: str, type_: str = "movie") -> dict | None:
    """Fetch detail for a single movie/series by IMDB id."""
    if not valid_imdb(imdb_id):
        return None
    try:
        r = await _get().get(f"{CINEMETA}/meta/{type_}/{imdb_id}.json")
        r.raise_for_status()
        data = r.json()
        meta = data.get("meta") or {}
        return {
            "id": imdb_id,
            "title": meta.get("name") or meta.get("title") or imdb_id,
            "year": _parse_year(meta.get("released") or meta.get("year")),
            "rating": _parse_rating(meta.get("imdbRating")),
            "poster_url": meta.get("poster"),
            "background_url": meta.get("background"),
            "overview": meta.get("description"),
            "genres": [g.strip() for g in (meta.get("genres") or []) if g.strip()],
            "type": meta.get("type", type_),
            "videos": meta.get("videos", []),
        }
    except (httpx.HTTPError, json.JSONDecodeError):
        return None


async def search_metadata(query: str, type_: str = "movie") -> list[dict]:
    """Search for movies/series by title."""
    try:
        r = await _get().get(f"{CINEMETA}/catalog/{type_}/top/search={query}.json")
        r.raise_for_status()
        return _parse_catalog(r.json())
    except (httpx.HTTPError, json.JSONDecodeError):
        return []



QUALITY_PATTERN = re.compile(
    r"\b(2160p|4K|1080p|720p|480p|HDR|SDR|WEB-?DL|WEB-?RIP|BluRay|BDRip|DVDRip|HDTV|"
    r"x264|x265|HEVC|AVC|H\.?264|H\.?265|DD5?\.?1|AAC|AC3|DTS|REMUX|PROPER|REPACK|"
    r"AMZN|NF|HULU|DSNP|ATVP|ViAplay|YTS|RARBG|MKV|AVI|MP4)\b",
    re.IGNORECASE
)

def clean_title(raw: str) -> tuple[str, int | None]:
    """Extract clean title and year from torrent release name."""
    year_match = re.search(r"\b(19|20)(\d{2})\b", raw)
    year = int(year_match.group()) if year_match else None

    title = raw
    if year_match:
        title = title[:year_match.start()]
    else:
        m = QUALITY_PATTERN.search(title)
        if m:
            title = title[:m.start()]

    title = re.sub(r'(?<=[a-zA-Z0-9])\.(?=[a-zA-Z0-9])', ' ', title)
    title = title.replace('_', ' ')
    title = re.sub(r'[\[\](){}]', ' ', title)
    title = re.sub(r'\s+', ' ', title).strip()
    return title, year

def title_candidates(raw: str) -> list[str]:
    """Split 'Russian / English' titles and return candidates (English first)."""
    parts = raw.split(" / ")
    candidates = []
    for p in parts[:2]:
        clean, _ = clean_title(p)
        if len(clean) >= 2:
            candidates.append(clean)
    candidates.reverse()  # English is usually second, prioritize it for Cinemeta
    return candidates
