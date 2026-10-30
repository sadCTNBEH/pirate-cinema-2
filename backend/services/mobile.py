"""Paired LAN Direct Play. No media files, disk buffers or transcoding."""
import asyncio
import ipaddress
import json
import logging
import re
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, field

import anyio
import httpx
from fastapi import HTTPException, Request
from starlette.background import BackgroundTask
from starlette.responses import Response, StreamingResponse

from backend.models.playback import PlaybackState

# HTTP debug/info records include private upstream URLs and media capabilities.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)


def local_peer(request):
    try:
        ip = ipaddress.ip_address(request.client.host)
        if getattr(ip, 'ipv4_mapped', None):
            ip = ip.ipv4_mapped
        return ip.is_loopback or any(ip in ipaddress.ip_network(n) for n in
            ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7', 'fe80::/10')
            if ip.version == ipaddress.ip_network(n).version)
    except (ValueError, AttributeError):
        return False


def check_request(request):
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


def compatible(data):
    """A deliberately narrow shared Safari/Chrome baseline, checked by ffprobe."""
    streams = data.get('streams', [])
    videos = [s for s in streams if s.get('codec_type') == 'video']
    audio = [s for s in streams if s.get('codec_type') == 'audio']
    return ('mp4' in data.get('format', {}).get('format_name', '').split(',')
            and len(videos) == 1 and videos[0].get('codec_name') == 'h264'
            and videos[0].get('pix_fmt') == 'yuv420p'
            and videos[0].get('profile') in ('Constrained Baseline', 'Baseline', 'Main', 'High')
            and 0 < videos[0].get('level', 999) <= 42
            and all(a.get('codec_name') == 'aac' and a.get('profile') == 'LC'
                    and 0 < a.get('channels', 99) <= 2 for a in audio))


async def probe(source):
    executable = shutil.which('ffprobe')
    if not executable:
        raise HTTPException(409, 'Для проверки кодеков нужен ffprobe из FFmpeg в PATH компьютера. Видео не преобразуется.')
    def run():
        try:
            result = subprocess.run([executable, '-v', 'quiet', '-max_alloc', '16777216',
                '-protocol_whitelist', 'http,https,tcp,tls', '-rw_timeout', '8000000',
                '-probesize', '2097152', '-analyzeduration', '3000000', '-max_streams', '32', '-threads', '1',
                '-show_entries', 'format=format_name:stream=codec_type,codec_name,pix_fmt,profile,level,channels',
                '-of', 'json', source], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=18, check=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode or len(result.stdout) > 65536:
                raise ValueError()
            return json.loads(result.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise HTTPException(422, 'Не удалось проверить видео за 18 секунд. Проверьте доступность раздачи и повторите.') from None
    task = asyncio.create_task(asyncio.to_thread(run))
    try:
        data = await asyncio.shield(task)
    except asyncio.CancelledError:
        # Keep the preparation slot until the bounded probe has exited.
        await asyncio.shield(task)
        raise
    if not compatible(data):
        raise HTTPException(415, 'Для телефона выберите MP4 с H.264 (8 бит, до Level 4.2) и AAC-LC стерео. MKV, HEVC, DTS и многоканальный звук требуют преобразования, которое здесь не включено.')


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

    async def close(self):
        self.expires = 0
        for upstream in list(self.connections):
            await upstream.aclose()
        self.connections.clear()


class MobileAccess:
    def __init__(self):
        self.code = secrets.token_urlsafe(24)
        self.pairs = {}
        self.sessions = {}
        self.preparing = asyncio.Semaphore(2)

    def prune(self):
        now = time.monotonic()
        self.pairs = {k: v for k, v in self.pairs.items() if v[1] > now}
        for token, session in list(self.sessions.items()):
            if session.expires < now:
                self.sessions.pop(token)
                asyncio.create_task(session.close())

    def pair(self, request, code):
        check_request(request)
        self.prune()
        if not secrets.compare_digest(code, self.code):
            raise HTTPException(403, 'Откройте актуальный QR-код или скопируйте полную ссылку с ПК')
        if len(self.pairs) >= 32:
            raise HTTPException(429, 'Слишком много подключений')
        token = secrets.token_urlsafe(32)
        self.pairs[token] = (request.client.host, time.monotonic() + 12 * 3600)
        return token

    def authorize(self, request):
        check_request(request)
        self.prune()
        token = request.cookies.get('pc_remote', '')
        pair = self.pairs.get(token)
        if not pair or pair[0] != request.client.host:
            raise HTTPException(401, 'Для просмотра откройте QR-код или полную ссылку из настроек ПК')
        return token

    def session(self, request, token):
        owner = self.authorize(request)
        session = self.sessions.get(token)
        if not session or session.owner != owner or session.host != request.client.host:
            raise HTTPException(403, 'Сессия видео завершена. Откройте видео снова.')
        return session

    async def media(self, request: Request, token: str):
        session = self.session(request, token)
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
            if upstream.status_code not in (200, 206, 416) or (value and upstream.status_code == 200):
                raise HTTPException(502, 'TorrServer не поддержал запрос видео или перемотку')
            session.connections.add(upstream)
            out = {k: v for k, v in upstream.headers.items() if k in
                   ('content-length', 'content-range', 'accept-ranges')}
            out.update({'Content-Type': 'video/mp4', 'Cache-Control': 'no-store',
                        'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer'})
            if request.method == 'HEAD' or upstream.status_code == 416:
                await close()
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


mobile_access = MobileAccess()
