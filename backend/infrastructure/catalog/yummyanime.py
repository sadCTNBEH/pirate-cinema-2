"""YummyAnime public API metadata adapter: https://api.yani.tv/swagger.

The documented video endpoint supplies iframe players, not MPV streams.
Application credentials are kept server-side and are never returned to clients.
"""
import asyncio
import os
from datetime import datetime, timezone

import httpx

from backend.exceptions import ExternalServiceError, NotFoundError


class YummyAnimeProvider:
    DEFAULT_PUBLIC_KEY = "bz7uk_nr9bouyrn9"

    def __init__(self, token=None, client=None, private_key=None):
        self._token = token
        self._client = client
        self._private_key = private_key
        self._lock = asyncio.Semaphore(2)

    def _get_credentials(self):
        try:
            from backend.core.settings import load_settings
            settings = load_settings()
            token = (
                self._token
                or settings.get("yummyanime_public_key")
                or os.getenv("YUMMYANIME_APPLICATION_TOKEN")
                or self.DEFAULT_PUBLIC_KEY
            )
            priv = (
                self._private_key
                or settings.get("yummyanime_private_key")
                or os.getenv("YUMMYANIME_PRIVATE_KEY")
                or ""
            )
            return token, priv
        except Exception:  # noqa: BLE001
            token = self._token or os.getenv("YUMMYANIME_APPLICATION_TOKEN") or self.DEFAULT_PUBLIC_KEY
            priv = self._private_key or os.getenv("YUMMYANIME_PRIVATE_KEY") or ""
            return token, priv

    @property
    def configured(self):
        token, _ = self._get_credentials()
        return bool(token)

    async def _get(self, path, params=None):
        token, priv = self._get_credentials()
        if not token:
            raise ExternalServiceError('YummyAnime: токен приложения не настроен', status_code=503)
        async def request(client):
            headers = {'X-Application': token, 'Lang': 'ru', 'Accept': 'application/json'}
            if priv:
                headers['X-Application-Secret'] = priv
            response = await client.get('https://api.yani.tv' + path, params=params,
                headers=headers)
            if response.status_code == 404:
                raise NotFoundError('Аниме не найдено на YummyAnime')
            if response.status_code != 200:
                raise ExternalServiceError('YummyAnime временно недоступен', status_code=503)
            data = response.json()
            if 'response' not in data:
                raise ExternalServiceError('Некорректный ответ YummyAnime', status_code=503)
            return data['response']
        try:
            async with self._lock:
                if self._client:
                    return await request(self._client)
                async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
                    return await request(client)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            raise ExternalServiceError('YummyAnime временно недоступен', status_code=503) from error

    async def fetch(self, category='popular', search=None):
        params = {'limit': 24, 'sort': 'rating' if category == 'rated' else 'views',
                  'sort_forward': 'false'}
        if search:
            params['q'] = search
            params.pop('sort')
            params.pop('sort_forward')
        elif category == 'season':
            now = datetime.now(timezone.utc)
            params.update(from_year=now.year, to_year=now.year, season=(now.month - 1) // 3 + 1)
        return [self.normalize(item) for item in await self._get('/anime', params)]

    async def detail(self, anime_id):
        if not str(anime_id).isdigit():
            raise NotFoundError('Некорректный идентификатор YummyAnime')
        item = await self._get('/anime/' + str(anime_id))
        result = self.normalize(item)
        result['blocked'] = bool((item.get('blocked') or {}).get('blocked'))
        result['playback_notice'] = ('YummyAnime не предоставляет прямой видеопоток для MPV. '
            'Доступны существующие варианты поиска раздач.')
        return result

    async def for_shikimori(self, anime_id):
        items = await self._get('/anime', {'shikimori_ids': str(anime_id), 'limit': 2})
        matches = [item for item in items if str((item.get('remote_ids') or {}).get('shikimori_id')) == str(anime_id)]
        if len(matches) != 1:
            raise NotFoundError('Не удалось однозначно сопоставить YummyAnime и Shikimori')
        return {'anime_id': str(matches[0]['anime_id'])}

    async def parts(self, anime_id):
        if not str(anime_id).isdigit():
            raise NotFoundError('Некорректный идентификатор YummyAnime')
        item = await self._get('/anime/' + str(anime_id))
        parts = {}
        for entry in [item, *(item.get('viewing_order') or [])]:
            ident = str(entry.get('anime_id') or '')
            if ident.isdigit() and entry.get('title'):
                parts[ident] = {'id': ident, 'title': entry['title'], 'year': entry.get('year'),
                    'type': (entry.get('type') or {}).get('name', '')}
        return list(parts.values())

    async def players(self, anime_id):
        if not str(anime_id).isdigit():
            raise NotFoundError('Некорректный идентификатор YummyAnime')
        videos = await self._get('/anime/' + str(anime_id) + '/videos')
        return self.normalize_players(videos)

    @staticmethod
    def normalize_players(videos):
        from urllib.parse import urlsplit
        result = []
        seen = set()
        for video in videos:
            url = video.get('iframe_url') or ''
            if url.startswith('//'):
                url = 'https:' + url
            try:
                parsed = urlsplit(url)
                if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                    continue
            except ValueError:
                continue
            data = video.get('data') or {}
            if 'aksor' in str(data.get('player', '')).casefold() or parsed.hostname == 'aksor.tv' or parsed.hostname.endswith('.aksor.tv'):
                continue
            identity = str(video.get('video_id', ''))
            if not identity or identity in seen:
                continue
            seen.add(identity)
            result.append({'id': identity, 'player': data.get('player') or 'YummyAnime',
                'dubbing': data.get('dubbing') or 'Оригинал',
                'episode': str(video.get('number') or '1'), 'url': url})
        return result

    @staticmethod
    def normalize(item):
        titles = [item['title'], *(item.get('other_titles') or [])]
        episodes = item.get('episodes') or {}
        count = (episodes.get('aired') or episodes.get('count') or episodes.get('total') or 0) if isinstance(episodes, dict) else episodes
        count = int(count) if str(count).isdigit() else 0
        poster = (item.get('poster') or {}).get('big') or (item.get('poster') or {}).get('fullsize')
        if poster and poster.startswith('//'):
            poster = 'https:' + poster
        return {'id': 'yummy:' + str(item['anime_id']), 'title': item['title'],
            'title_ru': item['title'], 'original_title': next((x for x in titles[1:] if x.isascii()), item['title']),
            'aliases': list(dict.fromkeys(titles)), 'source': 'YummyAnime',
            'shikimori_id': (item.get('remote_ids') or {}).get('shikimori_id'),
            'type': 'movie' if (item.get('type') or {}).get('alias') in ('movie', 'shortfilm') else 'series',
            'year': item.get('year'), 'poster_url': poster,
            'rating': float((item.get('rating') or {}).get('average') or 0),
            'overview': item.get('description') or '',
            'genres': [g['title'] for g in item.get('genres', [])], 'episodes': count,
            'translations': [x['title'] for x in item.get('translates', [])],
            'blocked_in': item.get('blocked_in') or [],
            'videos': [{'season': 1, 'episode': n, 'title': f'Серия {n}'} for n in range(1, min(count, 3000) + 1)]}
