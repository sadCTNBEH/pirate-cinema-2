import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from difflib import SequenceMatcher
from pathlib import Path

from backend.exceptions import ExternalServiceError, NotFoundError
from backend.infrastructure.catalog.cache import MetadataCache
from backend.services.online.animego_worker import norm
from backend.services.online.providers.base import OnlineProvider


def worker_command():
    if getattr(sys, 'frozen', False):
        return sys.executable, ['--animego-worker'], None
    root = Path(__file__).resolve().parents[4]
    interpreter = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    return str(interpreter) if interpreter.is_file() else sys.executable, ['-m', 'backend.services.online.animego_worker'], str(root)


def choose_match(items, metadata):
    titles = [metadata.get(k) for k in ('title', 'title_ru', 'original_title')] + metadata.get('aliases', [])
    ranked = {}
    for item in items:
        year = str(metadata.get('year') or '')
        if year and item.get('year') and str(item['year']) != year:
            continue
        kind = str(item.get('type') or '').casefold()
        if metadata.get('type') == 'movie' and kind and kind not in ('фильм', 'movie'):
            continue
        if metadata.get('type') == 'series' and kind in ('фильм', 'movie'):
            continue
        names = [item.get('title'), item.get('original_title')]
        score = max((SequenceMatcher(None, norm(t), norm(n)).ratio() for t in titles for n in names if t and n), default=0)
        if score >= .90:
            ranked[str(item['id'])] = (score, item)
    ordered = sorted(ranked.values(), key=lambda x: x[0], reverse=True)
    if not ordered:
        raise NotFoundError('AnimeGo: совпадений по названиям, году и формату нет')
    if len(ordered) > 1 and ordered[0][0] - ordered[1][0] < .02:
        raise ExternalServiceError('AnimeGo: несколько равнозначных совпадений, выбор неоднозначен', status_code=409)
    return ordered[0][1]


class AnimegoProvider(OnlineProvider):
    name = 'animego'
    supports_search = False

    def __init__(self):
        self._cache = MetadataCache()
        self.cards = {}
        self.embeds = {}
        self._limit = asyncio.Semaphore(2)

    async def _call(self, method, data):
        data = dict(data)
        if method == 'search':
            data['query'] = ' '.join(data['query'].split()).casefold()
        key = 'animego:kodik-v2:' + hashlib.sha256(json.dumps([method, data], sort_keys=True).encode()).hexdigest()
        cached = self._cache.get(key, 120 if method in ('stream', 'embed') else 1800)
        if cached is not None:
            return cached['result']
        async with self._limit:
            interpreter, args, cwd = worker_command()
            process = await asyncio.create_subprocess_exec(interpreter, *args, cwd=cwd, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                creationflags=0x08000000 if os.name == 'nt' else 0)
            try:
                async with asyncio.timeout(30):
                    output, _ = await process.communicate(json.dumps({'source':'animego','method':method,'data':data}).encode())
                result = json.loads(output)
                if result.get('error'):
                    raise ExternalServiceError(f"[{result.get('code', 'upstream')}] {result['error']}", status_code=result.get('status', 503))
                if process.returncode:
                    raise ValueError()
                if result['result']:
                    self._cache.set(key, result)
                return result['result']
            except (TimeoutError, ValueError, KeyError):
                raise ExternalServiceError('AnimeGo: источник не ответил или вернул несовместимые данные', status_code=503) from None
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.communicate()

    async def catalog(self, metadata):
        titles = list(dict.fromkeys(t for t in [metadata.get('title_ru'), metadata.get('original_title'),
            *metadata.get('aliases', []), metadata.get('title')] if t))[:4]
        results, failures = [], []
        inspected = set()
        item = None
        async with asyncio.timeout(75):
            for title in titles:
                try:
                    results.extend(await self._call('search', {'query': title}))
                    item = choose_match(results, metadata)
                    break
                except NotFoundError:
                    # Search cards expose Russian names only. Read original names from
                    # at most three plausible cards across all aliases.
                    candidates = [r for r in results if str(r['id']) not in inspected
                        and (not metadata.get('year') or str(r.get('year')) == str(metadata['year']))
                        and (not metadata.get('type') or r.get('type') == metadata['type'])]
                    for candidate in candidates[:max(0, 3-len(inspected))]:
                        inspected.add(str(candidate['id']))
                        card = await self._call('card', {'url': candidate['link']})
                        candidate['original_title'] = card['original_title']
                    try:
                        item = choose_match(results, metadata)
                        break
                    except NotFoundError:
                        continue
                except ExternalServiceError as error:
                    if error.status_code == 409:
                        raise
                    failures.append(error)
        if item is None:
            if failures:
                raise failures[0]
            item = choose_match(results, metadata)
        return await self.catalog_card(item['link'])

    async def catalog_card(self, url):
        card = await self._call('card', {'url': url})
        self.cards[str(card['anime_id'])] = card['url']
        return card

    async def embed(self, anime_id, episode, translation_id, player):
        if str(player).casefold() != 'kodik':
            raise ExternalServiceError('AnimeGo: доступен только Kodik. Обновите список серий.', status_code=422)
        url = self.cards.get(str(anime_id))
        if not url:
            raise NotFoundError('AnimeGo: повторите поиск карточки перед просмотром')
        data = await self._call('embed', {'url': url, 'episode': int(episode),
            'translation_id': str(translation_id), 'player': player})
        self.embeds = {k:v for k,v in self.embeds.items() if v[0] > time.monotonic()}
        while len(self.embeds) >= 64:
            self.embeds.pop(next(iter(self.embeds)))
        token = uuid.uuid4().hex
        self.embeds[token] = (time.monotonic() + 1800, data)
        return {'url': '/api/online/animego/web/' + token, 'player': player, 'episode': episode}

    async def search(self, query):
        return []

    async def get_metadata(self, video_id):
        raise NotFoundError('AnimeGo: используйте карточку аниме и встроенный плеер')

    async def get_qualities(self, video_id):
        return []

    async def resolve_stream(self, video_id, quality=None):
        raise ExternalServiceError('AnimeGo доступен во встроенном веб-плеере', status_code=422)
