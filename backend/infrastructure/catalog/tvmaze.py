import json
import logging
import re
from typing import Any

import httpx

from backend.core.settings.config import config

logger = logging.getLogger(__name__)

TVMAZE_BASE = "https://api.tvmaze.com"
USER_AGENT = "PirateCinema/2.0 (local desktop app)"


def strip_html(text: str | None) -> str:
    """Remove HTML tags and normalize whitespace."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", clean).strip()


def parse_year(val: Any) -> int | None:
    if val is None:
        return None
    m = re.search(r"(19|20)\d{2}", str(val))
    return int(m.group()) if m else None


class TVmazeProvider:
    """Metadata provider querying TVmaze for television shows and episode structures."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
    ):
        self._client = client
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "tvmaze"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None and not self._client.is_closed:
            return self._client
        return httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )

    async def lookup(self, imdb_id: str) -> dict[str, Any] | None:
        """Lookup series details and episode guide by IMDB id."""
        clean_id = imdb_id.strip()
        if not (clean_id.startswith("tt") and clean_id[2:].isdigit()):
            return None

        client_owner = self._client is None
        client = await self._get_client()

        try:
            # 1. Fetch show data
            url = f"{TVMAZE_BASE}/lookup/shows"
            r = await client.get(url, params={"imdb": clean_id})
            if r.status_code == 404:
                return None
            r.raise_for_status()
            show = r.json()

            show_id = show.get("id")
            name = (show.get("name") or "").strip()
            genres = [g.strip() for g in (show.get("genres") or []) if g.strip()]

            rating_val = None
            if isinstance(show.get("rating"), dict):
                try:
                    rating_val = (
                        float(show["rating"].get("average"))
                        if show["rating"].get("average")
                        else None
                    )
                except (ValueError, TypeError):
                    rating_val = None

            image_dict = show.get("image") or {}
            poster_url = image_dict.get("original") or image_dict.get("medium")

            # 2. Fetch episodes if available
            videos: list[dict[str, Any]] = []
            if show_id:
                try:
                    ep_resp = await client.get(
                        f"{TVMAZE_BASE}/shows/{show_id}/episodes"
                    )
                    if ep_resp.status_code == 200:
                        episodes_raw = ep_resp.json()
                        if isinstance(episodes_raw, list):
                            for ep in episodes_raw:
                                season_num = ep.get("season", 1)
                                ep_num = ep.get("number", 1)
                                videos.append(
                                    {
                                        "id": f"{clean_id}:{season_num}:{ep_num}",
                                        "title": ep.get("name") or f"Episode {ep_num}",
                                        "season": season_num,
                                        "episode": ep_num,
                                        "released": ep.get("airdate"),
                                        "overview": strip_html(ep.get("summary")),
                                    }
                                )
                except (
                    httpx.HTTPError,
                    json.JSONDecodeError,
                    KeyError,
                    ValueError,
                ) as ep_err:
                    logger.debug(
                        "Could not fetch episodes for TVmaze show %s: %s",
                        show_id,
                        ep_err,
                    )

            return {
                "id": clean_id,
                "title": name or clean_id,
                "original_title": name or clean_id,
                "year": parse_year(show.get("premiered")),
                "rating": rating_val,
                "poster_url": poster_url,
                "background_url": None,
                "overview": strip_html(show.get("summary")),
                "overview_ru": None,
                "genres": genres,
                "source": self.name,
                "type": "series",
                "videos": videos,
            }

        except httpx.HTTPError as e:
            logger.warning("TVmaze lookup error for %s: %s", clean_id, e)
            return None
        except Exception:
            logger.exception("Unexpected error querying TVmaze for %s", clean_id)
            return None
        finally:
            if client_owner and not client.is_closed:
                await client.aclose()

    async def search(self, query: str) -> list[dict[str, Any]]:
        """Search shows by title query."""
        clean_q = query.strip()
        if not clean_q:
            return []

        if " / " in clean_q:
            parts = [p.strip() for p in clean_q.split(" / ") if p.strip()]
            ascii_parts = [p for p in parts if p.isascii()]
            clean_q = ascii_parts[0] if ascii_parts else parts[0]

        client_owner = self._client is None
        client = await self._get_client()

        try:
            r = await client.get(f"{TVMAZE_BASE}/search/shows", params={"q": clean_q})
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list):
                return []

            results: list[dict[str, Any]] = []
            for item in data[: config.CATALOG_LIMIT]:
                show = item.get("show") or {}
                externals = show.get("externals") or {}
                imdb_id = externals.get("imdb") or f"tvm-{show.get('id')}"
                name = (show.get("name") or "").strip()
                if not name:
                    continue

                rating_val = None
                if isinstance(show.get("rating"), dict):
                    try:
                        rating_val = (
                            float(show["rating"].get("average"))
                            if show["rating"].get("average")
                            else None
                        )
                    except (ValueError, TypeError):
                        rating_val = None

                image_dict = show.get("image") or {}
                poster_url = image_dict.get("original") or image_dict.get("medium")

                results.append(
                    {
                        "id": imdb_id,
                        "title": name,
                        "original_title": name,
                        "year": parse_year(show.get("premiered")),
                        "rating": rating_val,
                        "poster_url": poster_url,
                        "background_url": None,
                        "overview": strip_html(show.get("summary")),
                        "overview_ru": None,
                        "genres": [
                            g.strip() for g in (show.get("genres") or []) if g.strip()
                        ],
                        "source": self.name,
                        "type": "series",
                    }
                )
            return results

        except httpx.HTTPError as e:
            logger.warning("TVmaze search error for query '%s': %s", clean_q, e)
            return []
        except Exception:
            logger.exception("Unexpected error during TVmaze search")
            return []
        finally:
            if client_owner and not client.is_closed:
                await client.aclose()
