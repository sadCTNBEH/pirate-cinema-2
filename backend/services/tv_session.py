import asyncio
import json
import math
import time
import logging
from contextlib import suppress

from backend.services.tv import Relay, discover_cast, discover_dlna

logger = logging.getLogger(__name__)


def direct_play_type(receiver, container, tracks, file_name=''):
    """Container advertisement permits a DLNA attempt, not a codec guarantee."""
    video = next((t for t in tracks if t.get('type') == 'video' and not t.get('albumart')), {})
    audio = next((t for t in tracks if t.get('type') == 'audio'), {})
    fmt = (container or '').lower()
    description = f"{container or 'неизвестный контейнер'} / {video.get('codec', '?')} / {audio.get('codec', 'без аудио')}"
    if 'mp4' in fmt or 'mov' in fmt:
        candidates = ['video/mp4']
    elif 'matroska' in fmt or 'webm' in fmt or fmt == 'mkv':
        is_webm = file_name.lower().endswith('.webm') or fmt == 'webm'
        candidates = ['video/webm'] if is_webm else ['video/x-matroska', 'video/matroska']
    elif 'mpegts' in fmt:
        candidates = ['video/mp2t', 'video/mpeg']
    elif fmt in ('mpeg', 'mpegvideo'):
        candidates = ['video/mpeg']
    elif fmt == 'avi':
        candidates = ['video/x-msvideo', 'video/avi']
    else:
        candidates = []
    mime = next((c for c in candidates if c in receiver.formats), None)
    if not mime:
        raise ValueError(f'ТВ не объявляет поддержку контейнера: {description}. Выберите другой файл или смотрите на ПК.')
    if not video.get('codec'):
        raise ValueError(f'Не удалось определить видеокодек: {description}. Дождитесь начала видео на ПК и повторите.')
    if receiver.kind == 'Google Cast':
        supported = (mime == 'video/mp4' and video.get('codec') == 'h264' and
                     (not audio or audio.get('codec') in ('aac', 'mp3'))) or (
                     mime == 'video/webm' and video.get('codec') in ('vp8', 'vp9') and
                     (not audio or audio.get('codec') in ('opus', 'vorbis')))
        if not supported:
            raise ValueError(f'Формат вне профиля Google Cast: {description}. Используйте MP4/H.264/AAC или WebM/VP8–VP9/Opus.')
    return mime


class TVSession:
    def __init__(self, playback):
        self.playback = playback
        self.devices = {}
        self.receiver = self.relay = self.task = self.state = None
        self.error = None
        self.scanning = False
        self.connection = 'idle'
        self.lock = asyncio.Lock()

    def publish(self):
        payload = json.dumps(self.info(), ensure_ascii=False)
        for c in list(self.playback.controllers.values()):
            c.send_command(['script-message', 'cinema-cast', payload])

    def info(self):
        return {'connected': self.state is not None, 'position': self.state.timecode if self.state else None, 'paused': self.state.is_paused if self.state else None, 'device': self.receiver.name if self.receiver else None,
                'error': self.error, 'connection': self.connection, 'scanning': self.scanning, 'devices': [{'id': d.id, 'name': d.name, 'kind': d.kind} for d in self.devices.values()],
                'notice': 'Direct Play: кодеки, дорожки и субтитры зависят от ТВ. Поддержка контейнера DLNA не гарантирует декодирование. Автопереход серий на ТВ пока недоступен.'}

    async def discover(self):
        if self.scanning:
            return self.info()

        async with self.lock:
            self.scanning = True
            self.error = None
            self.publish()
            try:
                for d in self.devices.values():
                    if d is not self.receiver: await d.close()
                self.devices = {self.receiver.id: self.receiver} if self.receiver else {}
                results = await asyncio.gather(discover_cast(), discover_dlna(), return_exceptions=True)
                for result in results:
                    if isinstance(result, BaseException):
                        self.error = 'Поиск части устройств недоступен. Проверьте сеть и установку pychromecast.'
                    else:
                        for d in result:
                            if d.id in self.devices: await d.close()
                            else: self.devices[d.id] = d
            finally:
                self.scanning = False
                self.publish()
            return self.info()

    async def start(self, device_id):
        async with self.lock:
            if self.state: raise ValueError('Сначала отключите текущий ТВ')
            receiver = self.devices.get(device_id)
            if not receiver: raise ValueError('ТВ не найден. Повторите поиск.')
            p = self.playback
            state = next(iter(p.active_states.values()), None)
            controller = p.controllers.get(state.hash) if state else None
            if not state or not controller or not controller.is_running: raise ValueError('Сначала запустите видео на ПК')
            source = getattr(controller, 'media_url', '')
            tracks = state.track_list
            fmt = getattr(controller, 'media_format', '') or ''
            mime = direct_play_type(receiver, fmt, tracks, state.file_name)
            if not source.startswith(('http://', 'https://')): raise ValueError('Этот источник нельзя передать на ТВ')
            self.error = None
            self.receiver, self.state = receiver, state
            self.connection = 'connecting'
            self.publish()
            p._cancel_preparation()
            was_paused = state.is_paused
            controller.send_command(['set_property', 'pause', True])
            self.relay = Relay(source, receiver.host, mime)
            try:
                url = await self.relay.start()
                await receiver.start(url, mime, state.timecode)
                self.connection = 'playing'
                self.task = asyncio.create_task(self.poll())
            except Exception as error:
                detail = str(error) if isinstance(error, ValueError) else 'ТВ недоступен по сети. Проверьте подключение и брандмауэр Windows.'
                await self.release()
                self.connection = 'error'
                self.error = detail
                self.publish()
                controller.send_command(['set_property', 'pause', was_paused])
                raise ValueError(detail) from None
            self.publish()

    async def poll(self):
        started = time.monotonic()
        terminal_since = None
        previous_status = None
        try:
            while self.state:
                position, status = await self.receiver.status()
                if status != previous_status:
                    logger.info('TV playback state: %s, position=%s', status, position)
                    previous_status = status
                if self.relay.last_error:
                    raise ValueError(self.relay.last_error)
                if time.monotonic()-started > 15 and not self.relay.media_requested:
                    raise ValueError('ТВ не запросил видеопоток. Разрешите Python/Pirate Cinema доступ в частной сети в брандмауэре Windows.')
                if status in ('PLAYING', 'PAUSED', 'PAUSED_PLAYBACK') and position is not None and math.isfinite(position) and position >= 0:
                    self.state.timecode = int(min(position, self.state.duration) if self.state.duration else position)
                    self.playback._schedule_save(self.state)
                self.state.is_paused = status != 'PLAYING'
                self.connection = 'playing' if status == 'PLAYING' else 'paused' if status in ('PAUSED', 'PAUSED_PLAYBACK') else 'buffering'
                self.relay.expires = __import__('time').monotonic()+60
                self.publish()
                if status in ('STOPPED', 'IDLE'):
                    if terminal_since is None:
                        terminal_since = time.monotonic()
                    elif time.monotonic()-terminal_since >= 6:
                        if not self.relay.media_requested:
                            self.error = 'ТВ остановился, не запросив поток. Проверьте доступ к ПК в брандмауэре Windows.'
                        elif self.state.duration > 0 and self.state.timecode >= self.state.duration-5:
                            self.error = 'Видео на ТВ завершилось. Вернитесь на ПК для следующей серии.'
                        else:
                            self.error = 'ТВ остановил воспроизведение до конца видео. Возможен отказ декодера или остановка на ТВ. Вернитесь на ПК или повторите подключение.'
                        break
                else:
                    terminal_since = None
                await asyncio.sleep(2)
        except asyncio.CancelledError: raise
        except ValueError as error:
            self.error = str(error)
        except Exception:
            self.error = 'Связь с ТВ потеряна. Можно продолжить на ПК с подтверждённой позиции.'
        finally:
            if self.error: self.connection = 'error'
            if self.relay: await self.relay.close()
            self.relay = None
            self.publish()

    async def release(self):
        if self.task and self.task is not asyncio.current_task():
            self.task.cancel()
            with suppress(asyncio.CancelledError): await self.task
        self.task = None
        if self.receiver:
            with suppress(Exception): await self.receiver.command('stop', 0)
        if self.relay: await self.relay.close()
        self.relay = None
        self.state = None

    async def finish(self, resume=False):
        async with self.lock:
            state = self.state
            await self.release()
            if state:
                self.playback._schedule_save(state)
                c = self.playback.controllers.get(state.hash)
                if c and c.is_running:
                    c.send_command(['seek', state.timecode, 'absolute+exact'])
                    c.send_command(['set_property', 'pause', not resume])
            self.error = None
            self.connection = 'idle'
            self.receiver = None
            self.publish()

    async def command(self, cmd):
        if self.error or not self.relay: raise ValueError(self.error or 'ТВ отключён')
        action, value = None, 0
        if cmd[:2] == ['cycle', 'pause']: action = 'play' if self.state.is_paused else 'pause'
        elif cmd[0] == 'seek':
            action, value = 'seek', float(cmd[1])
            if len(cmd) < 3 or 'absolute' not in cmd[2]: value += self.state.timecode
            value = max(0, min(value, self.state.duration or value))
        elif cmd[:2] == ['set_property', 'pause']: action = 'pause' if cmd[2] else 'play'
        elif len(cmd) >= 3 and cmd[1] == 'volume':
            action, value = 'volume', float(cmd[2]) + (self.state.volume if cmd[0] == 'add' else 0)
            value = max(0, min(100, value))
        if not action or not math.isfinite(value): raise ValueError('Команда недоступна на ТВ')
        await self.receiver.command(action, value)
