"""Shikimori documented GraphQL metadata API; never returns playback URLs.

Schema: https://shikimori.io/api/doc/graphql
"""
import asyncio
import json
import time
from datetime import datetime, timezone

import httpx

from backend.exceptions import ExternalServiceError


class AnimeProvider:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._next_request = 0.0

    async def fetch(self, category="popular", search=None, ids=None):
        args = ['limit: 24', 'censored: true']
        if ids:
            args.append('ids: ' + json.dumps(ids))
        elif search:
            args.append('search: ' + json.dumps(search, ensure_ascii=True))
        else:
            args.append('order: ranked' if category == 'rated' else 'order: popularity')
            if category == 'season':
                now = datetime.now(timezone.utc)
                season = ['winter', 'spring', 'summer', 'fall'][(now.month - 1) // 3]
                args.append('season: ' + json.dumps(f'{season}_{now.year}'))
        query = '''{ animes(%s) { id name russian english japanese synonyms kind score
            episodes episodesAired airedOn { year } poster { originalUrl }
            description genres { name russian } } }''' % ', '.join(args)
        # At most one request/second across this provider; no retry storms on 429.
        async with self._lock:
            await asyncio.sleep(max(0, self._next_request - time.monotonic()))
            self._next_request = time.monotonic() + 1
            async with httpx.AsyncClient(timeout=12, headers={'User-Agent': 'PirateCinema2/2.0'}) as client:
                response = await client.post('https://shikimori.io/api/graphql', json={'query': query})
                response.raise_for_status()
                payload = response.json()
                if payload.get('errors'):
                    raise ExternalServiceError('Shikimori metadata query failed', status_code=503)
        return [self.normalize(item) for item in payload['data']['animes']]

    @staticmethod
    def normalize(item):
        count = item.get('episodesAired') or item.get('episodes') or 0
        series = item.get('kind') != 'movie'
        return {
            'id': 'shikimori:' + str(item['id']),
            'title': item.get('russian') or item['name'],
            'title_ru': item.get('russian'), 'original_title': item['name'],
            'aliases': list(dict.fromkeys(x for x in [item['name'], item.get('russian'),
                item.get('english'), item.get('japanese'), *(item.get('synonyms') or [])] if x)),
            'type': 'series' if series else 'movie',
            'poster_url': (item.get('poster') or {}).get('originalUrl'),
            'year': (item.get('airedOn') or {}).get('year'),
            'rating': float(item.get('score') or 0),
            'overview': item.get('description') or '',
            'genres': [g.get('russian') or g['name'] for g in item.get('genres', [])],
            'episodes': item.get('episodes') or count,
            'videos': [{'season': 1, 'episode': n, 'title': f'Серия {n}'}
                       for n in range(1, min(count, 3000) + 1)] if series else [],
        }


