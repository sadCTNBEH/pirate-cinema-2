"""One owner-scoped continuation offer, shared by MPV OSD and the player API."""
import asyncio
import json
import re
import sqlite3
from datetime import datetime, timezone

import anyio
import httpx

from backend.exceptions import AppException
from backend.models.playback import PlayCommand
from backend.services.torrent_selection import episode_info, playable


def catalog_next(meta, current):
    """Only explicit catalog entries with an elapsed release date are playable."""
    entries = {}
    for video in meta.get('videos', []):
        try:
            key = (int(video['season']), int(video['episode']))
            if key[0] > 0 and key[1] > 0:
                if key in entries:  # Ambiguous catalog mapping.
                    return None, 'Неоднозначные метаданные серии'
                entries[key] = video
        except (KeyError, TypeError, ValueError):
            continue
    if current not in entries:
        return None, 'Нет подтверждённых метаданных следующей серии'
    following = sorted(key for key in entries if key > current)
    if not following:
        return None, 'Следующая серия не найдена'
    key = following[0]
    # Do not jump over a missing episode or an unknown season boundary.
    if key != (current[0], current[1] + 1) and key != (current[0] + 1, 1):
        return None, 'Нет подтверждённых метаданных следующей серии'
    video = entries[key]
    try:
        released = datetime.fromisoformat(str(video['released']).replace('Z', '+00:00'))
        if released.tzinfo is None:
            released = released.replace(tzinfo=timezone.utc)
        if released > datetime.now(timezone.utc):
            return None, 'Следующая серия ещё не вышла'
    except (KeyError, ValueError, TypeError):
        return None, 'Дата выхода следующей серии не подтверждена'
    absolute = video.get('absolute_episode') or video.get('absolute') or video.get('absolute_number')
    return {'season': key[0], 'episode': key[1],
            'absolute': absolute if type(absolute) is int and absolute > 0 else None}, ''


def release_matches(item, meta, target):
    title = item.title
    if not playable({'name': title + '.mkv'}):
        return False
    normalized = ' '.join(re.findall(r'\w+', title.casefold()))
    aliases = [meta.get(k) for k in ('title', 'name', 'title_ru', 'original_title')]
    if not any((' ' + ' '.join(re.findall(r'\w+', a.casefold())) + ' ') in (' ' + normalized + ' ')
               for a in aliases if isinstance(a, str) and len(a.strip()) > 1):
        return False
    years = re.findall(r'\b(?:19|20)\d{2}\b', title)
    year = str(meta.get('year') or '')[:4]
    # Requiring a catalog year prevents an identically named remake being bound to this ID.
    if not re.fullmatch(r'(?:19|20)\d{2}', year) or year not in years:
        return False
    info = episode_info(title)
    if info['special'] or (info['season'] is not None and info['season'] != target['season']):
        return False
    if info['episode'] is not None:
        number = target['absolute'] if info['season'] is None and target['absolute'] else target['episode']
        if number not in info['episodes']:
            return False
    return bool(item.magnet or item.infohash)


COUNTDOWN_INTERVAL = 1


class Continuation:
    def __init__(self, service, search=None, magnet=None):
        self.service, self.search, self.magnet = service, search, magnet
        self.owner = None
        self.offer = None
        self.timer = None
        self.cancelled = False
        self.eof_seen = False
        self.busy = False
        self.serial = 0

    def reset(self):
        published = self.offer is not None
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        if self.timer and self.timer is not current:
            self.timer.get_loop().call_soon_threadsafe(self.timer.cancel)
        self.timer = None
        self.offer = None
        self.owner = None
        self.cancelled = self.eof_seen = self.busy = False
        self.serial += 1
        if published:
            self.publish()

    def valid(self, owner, serial):
        return (self.owner is owner and self.serial == serial
                and self.service.active_states.get(owner.hash) is owner)

    def cancel_for_seek(self):
        if self.timer:
            self.cancelled = True
            self.timer.get_loop().call_soon_threadsafe(self.timer.cancel)
            self.timer = None
            self.offer = None
            self.serial += 1
            self.publish()

    def publish(self):
        payload = dict(self.offer) if self.offer else {}
        payload['token'] = self.serial
        for c in list(self.service.controllers.values()):
            c.send_command(['script-message', 'cinema-continuation', json.dumps(payload, ensure_ascii=False)])

    def attach(self, state):
        if self.owner is not state:
            self.reset()
            self.owner = state

    def suggest(self, state):
        if self.service.active_states.get(state.hash) is not state:
            return
        info_current = episode_info(state.file_name)
        info_current.update({k: v for k, v in self.service._file_intents.get((state.hash, state.file_id), {}).items() if v is not None})
        if info_current.get('episode') is None:
            return
        self.attach(state)
        if self.cancelled or self.offer:
            return
        candidate = self.service._next_candidates.get(state.hash)
        info = episode_info(candidate[1]['file']['name']) if candidate and 'file' in candidate[1] else {}
        label = f"S{info['season']:02}E{info['episode']:02}" if info.get('season') is not None and info.get('episode') is not None else ''
        self.offer = {'status': 'offer', 'label': 'Следующая серия' + (': ' + label if label else ''),
                      'external': not bool(candidate), 'remaining': None}
        self.publish()

    async def eof(self, state):
        if self.service.active_states.get(state.hash) is not state:
            return
        self.attach(state)
        if self.eof_seen or self.cancelled:
            return
        self.eof_seen = True
        self.suggest(state)
        if not self.offer:
            return
        if not self.service._next_candidates.get(state.hash):
            await self.find()
        elif self.service._auto_next_enabled:
            self.timer = asyncio.create_task(self.countdown(state, self.serial))

    async def countdown(self, state, serial):
        try:
            for remaining in range(10, 0, -1):
                if not self.valid(state, serial) or self.cancelled or not self.service._auto_next_enabled:
                    return
                self.offer['remaining'] = remaining
                self.publish()
                await asyncio.sleep(COUNTDOWN_INTERVAL)
            if self.valid(state, serial) and not self.cancelled:
                await self.act('watch', serial)
        finally:
            self.timer = None

    async def act(self, action, token, index=None):
        state, serial = self.owner, self.serial
        if not state or token != serial or not self.valid(state, serial):
            return False
        if action == 'input' and index in ('confirm', 'up', 'down', 'left', 'right'):
            controller = self.service.controllers.get(state.hash)
            if controller:
                controller.send_command(['script-message', 'cinema-continuation-input', index])
            return True
        if action == 'cancel':
            self.cancelled = True
            if self.timer and self.timer is not asyncio.current_task():
                self.timer.cancel()
            self.offer = None
            self.serial += 1
            self.busy = False
            self.publish()
            return True
        if self.busy:
            return False
        if self.timer and self.timer is not asyncio.current_task():
            self.timer.cancel()
        self.busy = True
        try:
            if action == 'retry':
                await self.find()
                return True
            if action == 'watch':
                if self.service._next_candidates.get(state.hash):
                    return await self.service.play_next_file(state.hash, state.file_id)
                await self.find()
                return True
            if action == 'choose' and self.offer and self.offer.get('status') == 'results':
                if type(index) is not int or not 0 <= index < len(self.offer['results']):
                    return False
                result = self.offer['results'][index]
                target = self.offer['target']
                self.offer['status'] = 'connecting'
                self.offer['label'] = 'Проверяем видеофайл…'
                self.publish()
                # The first mutation of TorrServer happens only after this explicit choice.
                added = await self.magnet.add_magnet(result['magnet'] or 'magnet:?xt=urn:btih:' + result['infohash'], result['title'])
                if not self.valid(state, serial):
                    return False
                hash_ = added.get('hash')
                if not hash_:
                    raise ValueError('TorrServer не вернул раздачу')
                for attempt in range(8):
                    selection = await self.service.select_torrent_file(hash_, **target, release_title=result['title'])
                    if selection['metadata_ready'] or not self.valid(state, serial):
                        break
                    await asyncio.sleep(0.75)
                if not self.valid(state, serial):
                    return False
                if not selection['file']:
                    if selection.get('candidates'):
                        self.offer.update(status='files', label='Выберите видеофайл',
                                          files=selection['candidates'], new_hash=hash_, release_title=result['title'])
                        self.publish()
                        return True
                    raise ValueError(selection['reason'])
                return await self.launch_selection(selection['file'], hash_, state, serial)
            if action == 'file' and self.offer and self.offer.get('status') == 'files':
                if type(index) is not int or not 0 <= index < len(self.offer['files']):
                    return False
                hash_ = self.offer['new_hash']
                selection = await self.service.select_torrent_file(hash_, **self.offer['target'],
                    release_title=self.offer['release_title'], file_id=self.offer['files'][index]['id'])
                if self.valid(state, serial) and selection['file']:
                    return await self.launch_selection(selection['file'], hash_, state, serial)
        except (ValueError, OSError, AppException, httpx.HTTPError, sqlite3.Error) as error:
            if self.valid(state, serial):
                self.offer = {'status': 'empty', 'label': str(error)}
                self.publish()
        finally:
            if self.valid(state, serial):
                self.busy = False
        return False

    async def launch_selection(self, file, hash_, state, serial):
        identity, title, year = self.offer['media_id'], self.offer['meta_title'], self.offer.get('year')
        await anyio.to_thread.run_sync(self.service._metadata.bind_catalog_identity, hash_, identity)
        if not self.valid(state, serial):
            return False
        await anyio.to_thread.run_sync(self.service._metadata.save_full_metadata,
            hash_, title, '', year, None, '', '[]', None, identity)
        if not self.valid(state, serial):
            return False
        await self.service.launch(PlayCommand(hash_, file['id'], file['name'], start_time=0))
        return True

    async def find(self):
        state, serial = self.owner, self.serial
        if not state or not self.search or not self.service._metadata_service:
            return
        self.offer = {'status': 'searching', 'label': 'Ищем следующую серию…'}
        self.publish()
        try:
            media_id = await anyio.to_thread.run_sync(self.service._metadata.get_imdb_id, state.hash)
            intent = episode_info(state.file_name)
            intent.update({k: v for k, v in self.service._file_intents.get((state.hash, state.file_id), {}).items() if v is not None})
            if not media_id or intent.get('season') is None or intent.get('episode') is None:
                raise ValueError('Нет подтверждённых метаданных следующей серии')
            meta = await self.service._metadata_service.movie_meta(media_id, 'series')
            target, reason = catalog_next(meta, (intent['season'], intent['episode']))
            if not target:
                raise ValueError(reason)
            title = meta.get('original_title') or meta.get('title') or meta.get('name')
            suffix = f" S{target['season']:02}E{target['episode']:02}"
            results = await self.search.search_torrents(title + suffix,
                titles=[a + f" S{target['season']:02}" for a in (meta.get('title'), meta.get('title_ru'), title) if a])
            results = [r.model_dump() for r in results if r.infohash != state.hash and release_matches(r, meta, target)]
            if self.valid(state, serial) and not self.cancelled:
                self.offer = {'status': 'results' if results else 'empty',
                    'label': 'Следующая серия: ' + suffix.strip() if results else 'Следующая серия не найдена',
                    'target': target, 'results': results, 'media_id': media_id,
                    'meta_title': meta.get('title') or title, 'year': meta.get('year')}
        except (ValueError, OSError, AppException, httpx.HTTPError, sqlite3.Error) as error:
            if self.valid(state, serial):
                self.offer = {'status': 'empty', 'label': str(error)}
        finally:
            if self.valid(state, serial):
                self.publish()
