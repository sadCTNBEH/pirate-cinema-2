"""Optional SubDL integration. Credentials stay in the backend environment."""
import io
import logging
import os
import re
import time
import uuid
import zipfile
from pathlib import Path

import httpx

from backend.core.settings import get_data_dir


class _RedactKey(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r'(api_key=)[^&\s"\']+', r'\1[redacted]', record.getMessage())
        record.args = ()
        return True


# httpx logs request URLs at INFO, including query credentials required by SubDL.
logging.getLogger('httpx').addFilter(_RedactKey())


class SubtitleService:
    def __init__(self, playback):
        self.playback = playback
        self.results = {}
        self.serial = 0

    def owner(self, hash, file_id):
        state = self.playback.active_states.get(hash)
        controller = self.playback.controllers.get(hash)
        if not state or state.file_id != file_id or not controller or not controller.is_running or self.playback.tv.state:
            raise ValueError('Видео изменилось или локальный плеер недоступен')
        return state, controller

    async def search(self, hash, file_id, title='', year=None, season=None, episode=None, language='RU,EN'):
        state, _controller = self.owner(hash, file_id)
        key = os.environ.get('SUBDL_API_KEY', '').strip()
        if not key:
            raise ValueError('Для поиска задайте SUBDL_API_KEY в .env и перезапустите приложение. Ключ: subdl.com/api-doc')
        self.serial += 1
        serial = self.serial
        self.results.clear()
        params = {'api_key': key, 'languages': language, 'subs_per_page': 30, 'unpack': 1, 'releases': 1,
                  'full_season': 0, 'client': 'custom_integration'}
        if title.strip():
            params['film_name'] = title.strip()
        else:
            params['file_name'] = state.file_name
        for name, value in (('year', year), ('season_number', season), ('episode_number', episode)):
            if value is not None:
                params[name] = value
        if season is not None:
            params['type'] = 'tv'
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get('https://api.subdl.com/api/v1/subtitles', params=params)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError):
            raise ValueError('SubDL недоступен или лимит запросов исчерпан. Повторите позже.') from None
        self.owner(hash, file_id)
        if self.playback.active_states.get(hash) is not state or serial != self.serial:
            raise ValueError('Поиск отменён: видео или запрос изменились')
        if not isinstance(data, dict) or not data.get('status'):
            raise ValueError('SubDL отклонил запрос. Проверьте ключ и лимит сервиса.')
        rows = []
        for subtitle in data.get('subtitles', []):
            if not isinstance(subtitle, dict):
                continue
            for item in subtitle.get('unpack_files') or [subtitle]:
                if not isinstance(item, dict):
                    continue
                lang = str(item.get('language', subtitle.get('language', ''))).upper()
                if lang not in ('RU', 'EN', 'RUSSIAN', 'ENGLISH'):
                    continue
                url = item.get('url', '')
                if not re.fullmatch(r'/subtitle/[A-Za-z0-9_./-]+', url) or '..' in url:
                    continue
                token = uuid.uuid4().hex
                label = str(item.get('release_name') or item.get('name') or subtitle.get('release_name') or 'SubDL')
                self.results[token] = (hash, file_id, state, time.monotonic(), url, label, None)
                rows.append({'id': token, 'language': lang, 'release': label})
        return rows

    async def attach(self, hash, file_id, token):
        state, controller = self.owner(hash, file_id)
        result = self.results.get(token)
        if not result or result[:2] != (hash, file_id) or result[2] is not state or time.monotonic()-result[3] > 1800:
            raise ValueError('Результат устарел. Повторите поиск.')
        _, _, _, _, url, label, content = result
        if content is None:
            try:
                async with (
                    httpx.AsyncClient(timeout=25, follow_redirects=False) as client,
                    client.stream('GET', 'https://dl.subdl.com'+url) as response,
                ):
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 8_000_000:
                            raise ValueError('Файл субтитров слишком большой')
                content = bytes(data)
            except httpx.HTTPError:
                raise ValueError('Не удалось скачать субтитры. Проверьте лимит SubDL.') from None
        self.owner(hash, file_id)
        if self.playback.active_states.get(hash) is not state:
            raise ValueError('Видео изменилось')
        if zipfile.is_zipfile(io.BytesIO(content)):
            choices = []
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    candidates = [info for info in archive.infolist() if Path(info.filename).suffix.lower() in ('.srt', '.ass') and not info.is_dir()]
                    if len(candidates) > 100 or sum(info.file_size for info in candidates) > 16_000_000:
                        raise ValueError('Архив субтитров слишком большой')
                    for info in candidates:
                        payload = archive.read(info)
                        self.validate(payload)
                        child = uuid.uuid4().hex
                        name = Path(info.filename).name
                        self.results[child] = (hash, file_id, state, time.monotonic(), '', name, payload)
                        choices.append({'id': child, 'language': '', 'release': name})
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
                raise ValueError('Повреждённый или неподдерживаемый архив субтитров') from None
            if not choices:
                raise ValueError('В архиве нет корректных SRT/ASS')
            if len(choices) > 1:
                return choices
            return await self.attach(hash, file_id, choices[0]['id'])
        suffix = self.validate(content)
        directory = get_data_dir() / 'subtitles'
        directory.mkdir(exist_ok=True)
        path = directory / (uuid.uuid4().hex + suffix)
        encoding = 'utf-16' if content.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        try:
            decoded = content.decode(encoding)
        except UnicodeError:
            decoded = content.decode('cp1251')
        path.write_text(decoded, encoding='utf-8')
        # Only a user choosing a result selects the newly added external track.
        controller.send_command(['sub-add', str(path), 'select', label])
        return []

    @staticmethod
    def validate(content):
        if len(content) > 4_000_000:
            raise ValueError('Файл субтитров слишком большой')
        text = None
        encodings = ('utf-16',) if content.startswith((b'\xff\xfe', b'\xfe\xff')) else ('utf-8-sig', 'cp1251')
        for encoding in encodings:
            try:
                text = content.decode(encoding)
                break
            except UnicodeError:
                pass
        if text and '[Script Info]' in text and '[Events]' in text and re.search(r'^Dialogue:', text, re.MULTILINE):
            return '.ass'
        if text and re.search(r'\d{2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[,.]\d{3}', text):
            return '.srt'
        raise ValueError('Файл не содержит корректных SRT/ASS субтитров')
