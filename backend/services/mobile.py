"""Paired LAN Mobile Playback with Direct Play and in-memory HLS transcoding."""
import asyncio
import hashlib
import ipaddress
import json
import logging
import math
import re
import secrets
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
import httpx
from fastapi import HTTPException, Request
from starlette.background import BackgroundTask
from starlette.responses import Response, StreamingResponse

from backend.core.settings import config
from backend.infrastructure.ffmpeg import (
    analyze_compatibility,
    build_hls_command,
    get_ffmpeg,
    get_ffprobe,
    probe_media,
)
from backend.models.playback import PlaybackState

# HTTP debug/info records include private upstream URLs and media capabilities.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logger = logging.getLogger('mobile')

# Global concurrency guard for CPU/RAM bound transcode/remux sessions
HLS_TRANSCODE_SEMAPHORE = asyncio.Semaphore(1)


def local_peer(request: Request) -> bool:
    try:
        ip = ipaddress.ip_address(request.client.host)
        if getattr(ip, 'ipv4_mapped', None):
            ip = ip.ipv4_mapped
        return ip.is_loopback or any(
            ip in ipaddress.ip_network(n)
            for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7', 'fe80::/10')
            if ip.version == ipaddress.ip_network(n).version
        )
    except (ValueError, AttributeError):
        return False


def check_request(request: Request) -> None:
    if not local_peer(request):
        raise HTTPException(403, 'Доступ разрешён только из локальной сети')
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Откройте пульт на этом компьютере')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Недопустимый источник запроса')
    # Prevent DNS rebinding from treating an attacker's origin as the PC UI.
    import socket
    host = request.url.hostname or ''
    try:
        address = ipaddress.ip_address(host)
        allowed = address.is_loopback or address.is_private and not address.is_global
    except ValueError:
        name = socket.gethostname().lower().removesuffix('.local')
        from backend.services.remote import get_local_hostname
        allowed = host.lower() in ('localhost', name, name + '.local', get_local_hostname())
    if not allowed:
        raise HTTPException(403, 'Используйте LAN-IP или локальное имя компьютера')


def compatible(data: dict[str, Any]) -> bool:
    """A deliberately narrow shared Safari/Chrome baseline for Direct Play."""
    analysis = analyze_compatibility(data)
    return analysis.get('mode') == 'direct'


async def probe(source: str) -> dict[str, Any]:
    """Inspect source container/codecs via ffprobe and determine playback mode (direct/remux/transcode)."""
    ffprobe_bin = get_ffprobe()
    if not ffprobe_bin:
        raise HTTPException(
            409,
            'Для проверки и подготовки видео необходим ffprobe/ffmpeg. Поместите их в папку vendor/ffmpeg или установите в PATH.'
        )
    try:
        data = await probe_media(source, timeout=18.0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise HTTPException(
            422,
            'Не удалось проверить видео за 18 секунд. Проверьте доступность раздачи и повторите.'
        ) from None

    analysis = analyze_compatibility(data)
    if analysis.get('mode') == 'unsupported':
        raise HTTPException(
            415,
            f"Неподдерживаемый формат видео: {analysis.get('reason', 'видеопоток не распознан')}"
        )
    if analysis['mode'] != 'direct' and not get_ffmpeg():
        raise HTTPException(409, 'Для подготовки видео необходим FFmpeg. Перезапустите приложение после установки FFmpeg.')
    if analysis['mode'] != 'direct' and analysis['duration'] <= 0:
        raise HTTPException(422, 'Не удалось определить длительность видео. Дождитесь загрузки раздачи и повторите.')
    return analysis


@dataclass
class MobileSession:
    owner: str
    host: str
    source: str
    state: PlaybackState
    size: int = 0
    expires: float = field(default_factory=lambda: time.monotonic() + 180)
    sequence: int = -1
    connections: set = field(default_factory=set)
    progress_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(4))

    # In-memory HLS state
    mode: str = 'direct'  # 'direct' or 'transcode'
    duration: float = 0.0
    segment_duration: float = 6.0
    audio_track_idx: int = 0
    segments: dict[int, bytes] = field(default_factory=dict)
    segment_events: dict[int, asyncio.Event] = field(default_factory=dict)
    ffmpeg_process: asyncio.subprocess.Process | None = None
    ffmpeg_waiter: asyncio.Task | None = None
    current_range: tuple[int, int] | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_requested_seq: int = 0
    BUFFER_AHEAD: int = 6
    MAX_CACHED_SEGMENTS: int = 15

    async def close(self) -> None:
        self.expires = 0
        async with self.lock:
            await self._stop_ffmpeg()
        for upstream in list(self.connections):
            await upstream.aclose()
        self.connections.clear()
        self.segments.clear()
        self.segment_events.clear()

    async def _stop_ffmpeg(self) -> None:
        proc = self.ffmpeg_process
        self.ffmpeg_process = None
        self.current_range = None
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            except (ProcessLookupError, OSError):
                pass
        if self.ffmpeg_waiter:
            await self.ffmpeg_waiter
            self.ffmpeg_waiter = None

    def receive_segment(self, seq: int, data: bytes) -> None:
        self.segments[seq] = data
        ev = self.segment_events.get(seq)
        if ev:
            ev.set()

        # Memory bound: safely evict older segments that have already been passed by the client
        if len(self.segments) > self.MAX_CACHED_SEGMENTS:
            old_keys = sorted([k for k in self.segments if k < self.last_requested_seq])
            while len(self.segments) > self.MAX_CACHED_SEGMENTS and old_keys:
                evicted = old_keys.pop(0)
                self.segments.pop(evicted, None)
                self.segment_events.pop(evicted, None)

            if len(self.segments) > self.MAX_CACHED_SEGMENTS:
                sorted_keys = sorted(
                    self.segments.keys(),
                    key=lambda k: 0 if self.last_requested_seq <= k <= self.last_requested_seq + self.BUFFER_AHEAD else abs(k - self.last_requested_seq)
                )
                while len(self.segments) > self.MAX_CACHED_SEGMENTS:
                    evicted = sorted_keys.pop()
                    if self.last_requested_seq <= evicted <= self.last_requested_seq + self.BUFFER_AHEAD:
                        break
                    self.segments.pop(evicted, None)
                    self.segment_events.pop(evicted, None)

    async def _start_ffmpeg(self, start_seq: int, app_port: int, token: str) -> None:
        ffmpeg_bin = get_ffmpeg()
        if not ffmpeg_bin:
            raise HTTPException(
                409,
                'FFmpeg не найден на сервере. Установите ffmpeg или поместите в vendor/ffmpeg.'
            )
        start_time = max(0.0, start_seq * self.segment_duration)
        sink_segment_url = f"http://127.0.0.1:{app_port}/api/remote/mobile/{token}/hls_sink/seg_%d.ts"
        sink_playlist_url = f"http://127.0.0.1:{app_port}/api/remote/mobile/{token}/hls_sink/live.m3u8"

        cmd = build_hls_command(
            ffmpeg_bin=ffmpeg_bin,
            source=self.source,
            start_time=start_time,
            start_number=start_seq,
            segment_duration=self.segment_duration,
            sink_segment_url=sink_segment_url,
            sink_playlist_url=sink_playlist_url,
            audio_track_idx=self.audio_track_idx,
            segment_count=self.BUFFER_AHEAD + 1,
        )
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            await asyncio.wait_for(HLS_TRANSCODE_SEMAPHORE.acquire(), timeout=10)
        except asyncio.TimeoutError:
            raise HTTPException(429, 'Подготовка другого видео ещё идёт. Повторите через несколько секунд.') from None
        try:
            self.ffmpeg_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except BaseException:
            HLS_TRANSCODE_SEMAPHORE.release()
            raise
        async def reap(proc):
            try:
                await proc.wait()
            finally:
                HLS_TRANSCODE_SEMAPHORE.release()
        self.ffmpeg_waiter = asyncio.create_task(reap(self.ffmpeg_process))
        self.current_range = (start_seq, start_seq + self.BUFFER_AHEAD)

    async def get_segment(self, seq: int, app_port: int, token: str, timeout: float = 25.0) -> bytes:
        if seq < 0 or (self.duration > 0 and seq >= math.ceil(self.duration / self.segment_duration)):
            raise HTTPException(404, 'Сегмент не найден')
        self.last_requested_seq = seq
        self.expires = time.monotonic() + 180

        highest_cached = seq - 1
        while highest_cached + 1 in self.segments:
            highest_cached += 1
        ahead_count = highest_cached - seq + 1

        async with self.lock:
            if self.expires <= time.monotonic():
                raise HTTPException(403, 'Сессия видео завершена')
            if seq in self.segments:
                # If buffer ahead is getting low (< 3 segments), top up in background
                if ahead_count < 3 and (self.ffmpeg_process is None or self.ffmpeg_process.returncode is not None):
                    start_from = highest_cached + 1
                    total_segs = max(1, math.ceil(self.duration / self.segment_duration)) if self.duration > 0 else start_from + 1
                    if start_from < total_segs:
                        await self._start_ffmpeg(start_seq=start_from, app_port=app_port, token=token)
                return self.segments[seq]

            need_start = False
            if self.ffmpeg_process is None or self.ffmpeg_process.returncode is not None:
                need_start = True
            elif self.current_range is not None:
                cur_start, cur_end = self.current_range
                if seq < cur_start or seq > cur_end:
                    need_start = True

            if need_start:
                await self._stop_ffmpeg()
                await self._start_ffmpeg(start_seq=seq, app_port=app_port, token=token)

        ev = self.segment_events.setdefault(seq, asyncio.Event())
        if seq in self.segments:
            return self.segments[seq]
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise HTTPException(504, f'Таймаут подготовки HLS-сегмента {seq}')

        if seq not in self.segments:
            raise HTTPException(500, f'HLS-сегмент {seq} не был сформирован')

        return self.segments[seq]

    def generate_vod_playlist(self, auth_token: str | None = None) -> str:
        """Build the VOD timeline for independently encoded, fixed-duration segments."""
        target_dur = max(10, int(self.segment_duration * 2))
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{target_dur}",
            "#EXT-X-MEDIA-SEQUENCE:0",
            "#EXT-X-PLAYLIST-TYPE:VOD",
        ]
        total_segments = max(1, math.ceil(self.duration / self.segment_duration)) if self.duration > 0 else 1
        auth_query = f"?auth={auth_token}" if auth_token else ""
        for i in range(total_segments):
            if self.duration > 0:
                seg_dur = min(self.segment_duration, max(0.1, self.duration - i * self.segment_duration))
            else:
                seg_dur = self.segment_duration
            lines.append(f"#EXTINF:{seg_dur:.6f},")
            lines.append(f"seg_{i}.ts{auth_query}")
        lines.append("#EXT-X-ENDLIST")
        return "\n".join(lines) + "\n"


class MobileAccess:
    def __init__(self):
        self.code = secrets.token_urlsafe(24)
        self.pairs = {}
        self.sessions = {}
        self.preparing = asyncio.Semaphore(2)
        self._pair_file: Path | None = None
        self._saved_pairs: dict = {}

    def enable_persistence(self, path: Path) -> None:
        """Keep hashed device credentials valid across PC restarts until their original expiry."""
        self._pair_file = path
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            self._saved_pairs = {
                key: value for key, value in data.items()
                if isinstance(key, str) and isinstance(value, dict)
                and isinstance(value.get('host'), str)
                and isinstance(value.get('expires'), (int, float))
                and value['expires'] > time.time()
            } if isinstance(data, dict) else {}
        except FileNotFoundError:
            self._saved_pairs = {}
        except (OSError, ValueError):
            self._saved_pairs = {}
            logger.warning('Could not restore mobile pairing records')

    def _save_pair(self, token: str, host: str) -> None:
        if self._pair_file is None:
            return
        self._saved_pairs[hashlib.sha256(token.encode()).hexdigest()] = {
            'host': host, 'expires': time.time() + 12 * 3600,
        }
        try:
            temporary = self._pair_file.with_suffix('.tmp')
            temporary.write_text(json.dumps(self._saved_pairs), encoding='utf-8')
            temporary.replace(self._pair_file)
        except OSError:
            logger.warning('Could not save mobile pairing records')

    def _valid_pair(self, token: str, host: str) -> bool:
        pair = self.pairs.get(token)
        if pair and pair[0] == host and pair[1] > time.monotonic():
            return True
        saved = self._saved_pairs.get(hashlib.sha256(token.encode()).hexdigest())
        if saved and saved['host'] == host and saved['expires'] > time.time():
            self.pairs[token] = (host, time.monotonic() + saved['expires'] - time.time())
            return True
        return False

    @staticmethod
    def _credentials(request: Request) -> list[str]:
        # An expired tab header must not mask a newer cookie from another tab.
        return [value for value in (
            request.headers.get('x-remote-token'),
            request.query_params.get('auth'),
            request.cookies.get('pc_remote'),
        ) if value]

    def prune(self):
        now = time.monotonic()
        self.pairs = {k: v for k, v in self.pairs.items() if v[1] > now}
        self._saved_pairs = {k: v for k, v in self._saved_pairs.items() if v['expires'] > time.time()}
        for token, session in list(self.sessions.items()):
            if session.expires < now:
                self.sessions.pop(token)
                asyncio.create_task(session.close())

    def pair(self, request: Request, code: str) -> str:
        check_request(request)
        self.prune()
        if not secrets.compare_digest(code, self.code):
            raise HTTPException(403, 'Откройте актуальный QR-код или скопируйте полную ссылку с ПК')
        if len(self.pairs) >= 32 or len(self._saved_pairs) >= 32:
            raise HTTPException(429, 'Слишком много подключений')
        token = secrets.token_urlsafe(32)
        self.pairs[token] = (request.client.host, time.monotonic() + 12 * 3600)
        self._save_pair(token, request.client.host)
        return token

    def authorize(self, request: Request, token_param: str | None = None) -> str:
        check_request(request)
        self.prune()
        for token in self._credentials(request) + ([token_param] if token_param else []):
            if self._valid_pair(token, request.client.host):
                return token
        raise HTTPException(401, 'Телефон не подключён к ПК. Отсканируйте актуальный QR-код в настройках ПК и откройте полный адрес, включая часть после #.')

    def session(self, request: Request, token: str, is_hls_child: bool = False) -> MobileSession:
        check_request(request)
        self.prune()
        session = self.sessions.get(token)
        if not session or session.host != request.client.host or session.expires <= time.monotonic():
            raise HTTPException(403, 'Сессия видео завершена. Откройте видео снова.')
        candidates = self._credentials(request)
        if not candidates and is_hls_child:
            return session
        if not any(token == session.owner and self._valid_pair(token, request.client.host) for token in candidates):
            raise HTTPException(401, 'Подключение телефона истекло. Вернитесь к пульту и откройте видео снова.')
        return session

    async def media(self, request: Request, token: str):
        session = self.session(request, token)
        session.expires = time.monotonic() + 180
        value = request.headers.get('range')
        if value and not re.fullmatch(r'bytes=(?:\d+-\d*|-\d+)', value):
            headers = {'Cache-Control': 'no-store'}
            if session.size > 0:
                headers['Content-Range'] = f'bytes */{session.size}'
            return Response(status_code=416, headers=headers)
        # Per-request clients make disconnect cleanup independent of other seeks.
        if session.slots.locked():
            raise HTTPException(429, 'Слишком много запросов потока')
        await session.slots.acquire()
        client = httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5), trust_env=False, follow_redirects=False)
        upstream = None
        closed = False

        async def close():
            nonlocal closed
            if closed:
                return
            closed = True
            with anyio.CancelScope(shield=True):
                try:
                    if upstream is not None:
                        session.connections.discard(upstream)
                        await upstream.aclose()
                    await client.aclose()
                finally:
                    session.slots.release()

        try:
            headers = {'Accept-Encoding': 'identity'}
            if value:
                headers['Range'] = value
            upstream = await client.send(client.build_request(request.method, session.source, headers=headers), stream=True)
            if upstream.status_code not in (200, 206, 416) or (value and upstream.status_code == 200 and not value.startswith('bytes=0-')):
                raise HTTPException(502, 'TorrServer не поддержал запрос видео или перемотку')
            session.connections.add(upstream)
            out = {k.lower(): v for k, v in upstream.headers.items() if k.lower() in
                   ('content-length', 'content-range', 'accept-ranges')}
            out['content-type'] = 'video/mp4'
            out['cache-control'] = 'no-store'
            out['accept-ranges'] = 'bytes'
            out['x-content-type-options'] = 'nosniff'
            out['referrer-policy'] = 'no-referrer'

            if request.method == 'HEAD' or upstream.status_code == 416:
                await close()
                if session.size > 0 and 'content-length' not in out:
                    out['content-length'] = str(session.size)
                return Response(status_code=upstream.status_code, headers=out)
            async def chunks():
                try:
                    async for chunk in upstream.aiter_raw(65536):
                        if session.expires <= time.monotonic():
                            break
                        yield chunk
                finally:
                    await close()
            return StreamingResponse(chunks(), status_code=upstream.status_code, headers=out,
                                     background=BackgroundTask(close))
        except BaseException as error:
            await close()
            if isinstance(error, httpx.HTTPError):
                raise HTTPException(502, 'TorrServer недоступен') from None
            raise

    async def hls_playlist(self, request: Request, token: str):
        session = self.session(request, token, is_hls_child=True)
        session.expires = time.monotonic() + 180
        playlist_content = session.generate_vod_playlist(request.query_params.get('auth'))
        headers = {
            'content-type': 'application/vnd.apple.mpegurl',
            'cache-control': 'no-cache, no-store',
            'access-control-allow-origin': '*',
        }
        return Response(content=playlist_content, media_type='application/vnd.apple.mpegurl', headers=headers)

    async def hls_segment(self, request: Request, token: str, name: str):
        session = self.session(request, token, is_hls_child=True)
        session.expires = time.monotonic() + 180
        if not (name.startswith('seg_') and name.endswith('.ts')):
            raise HTTPException(404, 'Сегмент не найден')
        try:
            seq = int(name[4:-3])
        except ValueError:
            raise HTTPException(404, 'Некорректный сегмент')

        port = request.url.port or config.APP_PORT
        data = await session.get_segment(seq, app_port=port, token=token)
        headers = {
            'content-type': 'video/MP2T',
            'content-length': str(len(data)),
            'cache-control': 'no-store',
            'accept-ranges': 'bytes',
        }
        return Response(content=data, media_type='video/MP2T', headers=headers)

    async def hls_sink(self, request: Request, token: str, name: str):
        client_ip = request.client.host
        if client_ip not in ('127.0.0.1', '::1', 'localhost'):
            raise HTTPException(403, 'Sink доступен только локально')
        session = self.sessions.get(token)
        if not session:
            return Response(status_code=404)
        data = await request.body()
        if name.startswith('seg_') and name.endswith('.ts'):
            try:
                seq = int(name[4:-3])
                session.receive_segment(seq, data)
            except ValueError:
                pass
        return Response(status_code=200)


mobile_access = MobileAccess()
