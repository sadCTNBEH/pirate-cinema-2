"""Read-only IntroDB integration. Timings are never inferred from segment lengths."""
import asyncio
import math
import re
import time

import httpx


class IntroDB:
    def __init__(self, repository, transport=None):
        self.repository = repository
        self.transport = transport
        self.retry_at = 0.0
        self._lock = asyncio.Lock()

    async def segments(self, imdb_id, season=None, episode=None, *, movie=False):
        if not isinstance(imdb_id, str) or not re.fullmatch(r"tt\d{7,10}", imdb_id):
            return []
        if not movie and (type(season) is not int or type(episode) is not int or season < 0 or episode < 1):
            return []
        key = f"introdb:v1:{imdb_id}:" + ("movie" if movie else f"{season}:{episode}")
        async with self._lock:
            cached = await asyncio.to_thread(self.repository.get_cached_metadata, key, 86400)
            if isinstance(cached, dict):
                return self.validate(cached)
            if time.monotonic() < self.retry_at:
                return []
            params = {"imdb_id": imdb_id}
            params.update({"is_movie": "true"} if movie else {"season": season, "episode": episode})
            try:
                async with httpx.AsyncClient(timeout=5, transport=self.transport, trust_env=False) as client:
                    response = await client.get("https://api.introdb.app/segments", params=params)
                if response.status_code == 429:
                    try:
                        delay = float(response.headers.get("Retry-After", 60))
                    except ValueError:
                        delay = 60
                    self.retry_at = time.monotonic() + min(3600, max(60, delay))
                    return []
                if response.status_code == 404:
                    data = {}
                else:
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, dict) or data.get("imdb_id") != imdb_id:
                        return []
                    if (movie and data.get("is_movie") is not True) or (not movie and (
                        data.get("season") != season or data.get("episode") != episode or data.get("is_movie") is not False
                    )):
                        return []
                await asyncio.to_thread(self.repository.save_cached_metadata, key, data, imdb_id)
                return self.validate(data)
            except (httpx.HTTPError, ValueError, TypeError):
                self.retry_at = time.monotonic() + 60
                return []

    @staticmethod
    def validate(data):
        result = []
        for kind in ("intro", "recap", "outro"):
            segment = data.get(kind)
            if not isinstance(segment, dict):
                continue
            start, end, confidence = (segment.get(k) for k in ("start_sec", "end_sec", "confidence"))
            if not all(type(v) in (int, float) and math.isfinite(v) for v in (start, end, confidence)):
                continue
            if 0 <= start < end and 0.9 <= confidence <= 1:
                # post_credits is a scene, never a skip target. Do not jump over it.
                scene = data.get("post_credits")
                if kind == "outro" and isinstance(scene, dict):
                    boundary = scene.get("start_sec")
                    if type(boundary) not in (int, float) or not math.isfinite(boundary) or boundary <= start:
                        continue
                    end = min(end, boundary)
                result.append({"kind": kind, "start": start, "end": end, "source": "introdb"})
        # Conflicting community intervals are not safe to expose.
        return [s for s in result if not any(s is not other and s["start"] < other["end"] and other["start"] < s["end"] for other in result)]
