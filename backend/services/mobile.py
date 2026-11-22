"""Paired LAN Mobile Playback with Direct Play and in-memory HLS transcoding."""
import asyncio
import hashlib
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import subprocess
import tempfile
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

# Registry of active FFmpeg processes for immediate orphan-free termination
ACTIVE_FFMPEG_PROCESSES: set[asyncio.subprocess.Process] = set()


def cleanup_all_ffmpeg() -> None:
    """Kill all tracked active FFmpeg processes immediately."""
    for proc in list(ACTIVE_FFMPEG_PROCESSES):
        if proc.returncode is None:
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass
    ACTIVE_FFMPEG_PROCESSES.clear()


import atexit
atexit.register(cleanup_all_ffmpeg)


def normalize_ip(host: str | None) -> str:
    """Normalize IPv4, IPv6, and IPv4-mapped IPv6 addresses to canonical string form."""
    if not host:
        return ""
    host = host.strip()
    try:
        ip = ipaddress.ip_address(host)
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        return str(ip)
    except ValueError:
        return host.lower()


def same_host(host1: str | None, host2: str | None) -> bool:
    """Check whether two host strings represent the same device or loopback."""
    if not host1 or not host2:
        return False
    h1 = normalize_ip(host1)
    h2 = normalize_ip(host2)
    if h1 == h2:
        return True
    loopbacks = {"127.0.0.1", "::1", "localhost"}
    if h1 in loopbacks and h2 in loopbacks:
        return True
    try:
        ip1 = ipaddress.ip_address(h1)
        ip2 = ipaddress.ip_address(h2)
        if ip1.is_loopback and ip2.is_loopback:
            return True
    except ValueError:
        pass
    return False


def local_peer(request: Request) -> bool:
    try:
        raw_host = request.client.host if request.client else ""
        ip = ipaddress.ip_address(raw_host)
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
        logger.warning(
            "[Mobile check_request] Rejected non-local peer: %s",
            request.client.host if request.client else None,
        )
        raise HTTPException(403, 'Доступ разрешён только из локальной сети')
    origin = request.headers.get('origin')
    if origin:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        origin_host = parsed.hostname or ''
        is_same = origin.rstrip('/') == str(request.base_url).rstrip('/')
        is_local = False
        try:
            addr = ipaddress.ip_address(origin_host)
            if getattr(addr, 'ipv4_mapped', None):
                addr = addr.ipv4_mapped
            is_local = addr.is_loopback or (addr.is_private and not addr.is_global)
        except ValueError:
            import socket
            name = socket.gethostname().lower().removesuffix('.local')
            from backend.services.remote import get_local_hostname
            is_local = origin_host.lower() in ('localhost', name, name + '.local', get_local_hostname().lower())
        if not (is_same or is_local):
            logger.warning(
                "[Mobile check_request] Rejected origin: origin=%s, base_url=%s",
                origin,
                request.base_url,
            )
            raise HTTPException(403, 'Откройте пульт на этом компьютере')
    if request.headers.get('sec-fetch-site') == 'cross-site' and not origin:
        logger.warning("[Mobile check_request] Rejected sec-fetch-site cross-site without origin")
        raise HTTPException(403, 'Недопустимый источник запроса')
    # Prevent DNS rebinding from treating an attacker's origin as the PC UI.
    import socket
    host = request.url.hostname or ''
    try:
        address = ipaddress.ip_address(host)
        if getattr(address, 'ipv4_mapped', None):
            address = address.ipv4_mapped
        allowed = address.is_loopback or address.is_private and not address.is_global
    except ValueError:
        name = socket.gethostname().lower().removesuffix('.local')
        from backend.services.remote import get_local_hostname
        allowed = host.lower() in ('localhost', name, name + '.local', get_local_hostname().lower())
    if not allowed:
        logger.warning("[Mobile check_request] Rejected host header: %s", host)
        raise HTTPException(403, 'Используйте LAN-IP или локальное имя компьютера')


def select_playback_mode(data: dict[str, Any]) -> dict[str, Any]:
    """Determine playback strategy: direct play, remux, or HLS transcode.

    - Direct Play: MP4 / H.264 / AAC
    - Remux: MKV / H.264 / AAC (container remux without CPU-heavy transcoding)
    - HLS / Transcode: heavy or incompatible codecs (HEVC, 10-bit H.264, VP9, AV1, AC3, DTS, etc.)
    """
    return analyze_compatibility(data)


def compatible(data: dict[str, Any]) -> bool:
    """A deliberately narrow shared Safari/Chrome baseline for Direct Play."""
    analysis = select_playback_mode(data)
    return analysis.get('mode') == 'direct'


async def probe(source: str) -> dict[str, Any]:
    """Inspect source container/codecs via ffprobe and determine playback mode (direct/remux/transcode)."""
    from backend.services.remote import validate_media_path
    try:
        validate_media_path(source)
    except ValueError as err:
        raise HTTPException(403, f"Доступ к медиафайлу запрещён: {err}") from err

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

    analysis = select_playback_mode(data)
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

    # Streaming state
    mode: str = 'direct'  # 'direct', 'remux', or 'transcode'
    duration: float = 0.0
    segment_duration: float = 6.0
    audio_track_idx: int = 0
    copy_video: bool = False
    copy_audio: bool = False
    segments: dict[int, bytes] = field(default_factory=dict)
    segment_events: dict[int, asyncio.Event] = field(default_factory=dict)
    ffmpeg_process: asyncio.subprocess.Process | None = None
    ffmpeg_waiter: asyncio.Task | None = None
    _stderr_task: asyncio.Task | None = None
    _ffmpeg_error: str | None = None
    _stderr_buffer: list[str] = field(default_factory=list)
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
        if proc:
            ACTIVE_FFMPEG_PROCESSES.discard(proc)
            if proc.returncode is None:
                try:
                    proc.kill()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=1.0)
                    except (asyncio.TimeoutError, Exception):
                        pass
                except (ProcessLookupError, OSError):
                    pass
        if self._stderr_task:
            try:
                self._stderr_task.cancel()
            except Exception:
                pass
            self._stderr_task = None
        if self.ffmpeg_waiter:
            try:
                self.ffmpeg_waiter.cancel()
                await self.ffmpeg_waiter
            except (asyncio.CancelledError, Exception):
                pass
            self.ffmpeg_waiter = None
        if getattr(self, "_temp_playlist", None):
            try:
                self._temp_playlist.unlink(missing_ok=True)
            except OSError:
                pass

    def receive_segment(self, seq: int, data: bytes) -> None:
        logger.info("[Mobile HLS] Received segment %d (%d bytes)", seq, len(data))
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
        self._temp_playlist = Path(tempfile.gettempdir()) / f"pirate_hls_{token[:8]}.m3u8"
        sink_playlist_url = str(self._temp_playlist)

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
            copy_video=self.copy_video,
            copy_audio=self.copy_audio,
        )
        logger.info(
            "[Mobile FFmpeg] Spawning FFmpeg for seq=%d (start=%.2fs, count=%d, sink_port=%d)",
            start_seq,
            start_time,
            self.BUFFER_AHEAD + 1,
            app_port,
        )
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            await asyncio.wait_for(HLS_TRANSCODE_SEMAPHORE.acquire(), timeout=10)
        except asyncio.TimeoutError:
            logger.warning("[Mobile FFmpeg] Concurrency limit reached, acquire timeout")
            raise HTTPException(429, 'Подготовка другого видео ещё идёт. Повторите через несколько секунд.') from None
        try:
            self._ffmpeg_error = None
            self._stderr_buffer = []
            self.ffmpeg_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
            )
            ACTIVE_FFMPEG_PROCESSES.add(self.ffmpeg_process)
        except BaseException as err:
            HLS_TRANSCODE_SEMAPHORE.release()
            logger.error("[Mobile FFmpeg] Process spawn failed: %s", err)
            raise

        async def read_stderr(proc):
            try:
                while proc.stderr and not proc.stderr.at_eof():
                    line = await proc.stderr.readline()
                    if not line:
                        break
                    text = line.decode('utf-8', errors='replace').strip()
                    if text:
                        self._stderr_buffer.append(text)
                        if len(self._stderr_buffer) > 40:
                            self._stderr_buffer.pop(0)
                        logger.debug("[FFmpeg mobile %s] %s", token[:8], text)
            except Exception:
                pass

        self._stderr_task = asyncio.create_task(read_stderr(self.ffmpeg_process))

        semaphore_released = False
        async def reap(proc):
            nonlocal semaphore_released
            try:
                ret = await proc.wait()
                if self._stderr_task:
                    try:
                        await asyncio.wait_for(self._stderr_task, timeout=0.5)
                    except Exception:
                        pass
                if self.ffmpeg_process is proc and ret != 0:
                    err_summary = "\n".join(self._stderr_buffer[-8:]) or f"FFmpeg exited with code {ret}"
                    self._ffmpeg_error = err_summary
                    logger.error("[Mobile FFmpeg %s] Process failed (code %s): %s", token[:8], ret, err_summary)
                    for ev in list(self.segment_events.values()):
                        ev.set()
                elif self.ffmpeg_process is proc:
                    logger.info("[Mobile FFmpeg %s] Process completed successfully", token[:8])
                    # Unblock any segment requests waiting on this completed transcode run
                    for ev in list(self.segment_events.values()):
                        ev.set()
            except (asyncio.CancelledError, Exception) as e:
                logger.debug("[Mobile FFmpeg] Wait cancelled or failed: %s", e)
            finally:
                ACTIVE_FFMPEG_PROCESSES.discard(proc)
                if not semaphore_released:
                    semaphore_released = True
                    try:
                        HLS_TRANSCODE_SEMAPHORE.release()
                    except ValueError:
                        pass

        self.ffmpeg_waiter = asyncio.create_task(reap(self.ffmpeg_process))
        self.current_range = (start_seq, start_seq + self.BUFFER_AHEAD)

    async def get_segment(self, seq: int, app_port: int, token: str, timeout: float = 35.0) -> bytes:
        if seq < 0 or (self.duration > 0 and seq >= math.ceil(self.duration / self.segment_duration)):
            raise HTTPException(404, 'Сегмент не найден')
        self.last_requested_seq = seq
        self.expires = time.monotonic() + 180

        highest_cached = seq - 1
        while highest_cached + 1 in self.segments:
            highest_cached += 1
        ahead_count = highest_cached - seq + 1

        logger.info(
            "[Mobile HLS] get_segment seq=%d (cached=%s, ahead=%d, ffmpeg_active=%s, range=%s)",
            seq,
            seq in self.segments,
            ahead_count,
            self.ffmpeg_process is not None and self.ffmpeg_process.returncode is None,
            self.current_range,
        )

        async with self.lock:
            if self.expires <= time.monotonic():
                raise HTTPException(403, 'Сессия видео завершена')
            if seq in self.segments:
                # If buffer ahead is getting low (< 3 segments), top up in background
                if ahead_count < 3 and (self.ffmpeg_process is None or self.ffmpeg_process.returncode is not None):
                    start_from = highest_cached + 1
                    total_segs = max(1, math.ceil(self.duration / self.segment_duration)) if self.duration > 0 else start_from + 1
                    if start_from < total_segs:
                        logger.info("[Mobile HLS] Prefetching segments from seq=%d", start_from)
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
                logger.info("[Mobile HLS] Starting FFmpeg for needed seq=%d", seq)
                await self._stop_ffmpeg()
                await self._start_ffmpeg(start_seq=seq, app_port=app_port, token=token)

        ev = self.segment_events.setdefault(seq, asyncio.Event())
        if seq in self.segments:
            return self.segments[seq]
        if self._ffmpeg_error:
            logger.error("[Mobile HLS] Segment %d requested but FFmpeg has error: %s", seq, self._ffmpeg_error)
            raise HTTPException(500, f'Ошибка транскодирования: {self._ffmpeg_error}')

        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            err = f" (FFmpeg error: {self._ffmpeg_error})" if self._ffmpeg_error else ""
            logger.error("[Mobile HLS] Таймаут подготовки сегмента %d%s", seq, err)
            raise HTTPException(504, f'Таймаут подготовки HLS-сегмента {seq}{err}')
        except (asyncio.CancelledError, GeneratorExit):
            await self._stop_ffmpeg()
            raise

        if seq not in self.segments:
            # If FFmpeg completed or dropped this segment, retry spawning FFmpeg once for this exact segment
            if not getattr(self, "_retried_seqs", None):
                self._retried_seqs = set()
            if seq not in self._retried_seqs:
                self._retried_seqs.add(seq)
                logger.info("[Mobile HLS] Retrying FFmpeg for missing seq=%d", seq)
                async with self.lock:
                    await self._stop_ffmpeg()
                    await self._start_ffmpeg(start_seq=seq, app_port=app_port, token=token)
                ev = self.segment_events.setdefault(seq, asyncio.Event())
                ev.clear()
                try:
                    await asyncio.wait_for(ev.wait(), timeout=15.0)
                except asyncio.TimeoutError:
                    pass
            if seq in self.segments:
                return self.segments[seq]

            err = f": {self._ffmpeg_error}" if self._ffmpeg_error else ""
            logger.error("[Mobile HLS] HLS-сегмент %d не был сформирован%s", seq, err)
            raise HTTPException(500, f'HLS-сегмент {seq} не был сформирован{err}')

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
        self.default_session_ttl: float = 12 * 3600  # 12 hours

    def generate_token(self, host: str, ttl: float | None = None) -> str:
        """Generate a cryptographically secure session token with limited lifetime."""
        lifespan = ttl if ttl is not None else self.default_session_ttl
        token = secrets.token_urlsafe(32)
        norm_host = normalize_ip(host)
        # Evict oldest pairs if reaching capacity limit rather than failing permanently
        while len(self.pairs) >= 32:
            oldest_k = min(self.pairs.keys(), key=lambda k: self.pairs[k][1])
            self.pairs.pop(oldest_k, None)
        while len(self._saved_pairs) >= 32:
            oldest_k = min(self._saved_pairs.keys(), key=lambda k: self._saved_pairs[k].get('expires', 0))
            self._saved_pairs.pop(oldest_k, None)
        self.pairs[token] = (norm_host, time.monotonic() + lifespan)
        self._save_pair(token, norm_host, lifespan)
        logger.info("[Mobile Auth] Generated pairing token for host %s", norm_host)
        return token

    def validate_token(self, token: str, host: str) -> bool:
        """Validate that token exists, belongs to host, and is not expired."""
        if not token or not host:
            return False
        return self._valid_pair(token, host)

    def is_token_expired(self, token: str) -> bool:
        """Check whether a given token is expired or non-existent."""
        if not token:
            return True
        now_mono = time.monotonic()
        pair = self.pairs.get(token)
        if pair:
            return pair[1] <= now_mono
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        saved = self._saved_pairs.get(token_hash)
        if saved:
            return saved.get("expires", 0) <= time.time()
        return True

    def revoke_token(self, token: str) -> bool:
        """Explicitly revoke a session token."""
        found = False
        if token in self.pairs:
            del self.pairs[token]
            found = True
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        if token_hash in self._saved_pairs:
            del self._saved_pairs[token_hash]
            found = True
            if self._pair_file:
                try:
                    self._pair_file.write_text(json.dumps(self._saved_pairs), encoding="utf-8")
                except OSError:
                    pass
        return found

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

    def _save_pair(self, token: str, host: str, lifespan: float = 12 * 3600) -> None:
        if self._pair_file is None:
            return
        norm_host = normalize_ip(host)
        self._saved_pairs[hashlib.sha256(token.encode()).hexdigest()] = {
            'host': norm_host, 'expires': time.time() + lifespan,
        }
        try:
            temporary = self._pair_file.with_suffix('.tmp')
            temporary.write_text(json.dumps(self._saved_pairs), encoding='utf-8')
            temporary.replace(self._pair_file)
        except OSError:
            logger.warning('Could not save mobile pairing records')

    def _valid_pair(self, token: str, host: str) -> bool:
        pair = self.pairs.get(token)
        if pair and same_host(pair[0], host) and pair[1] > time.monotonic():
            return True
        saved = self._saved_pairs.get(hashlib.sha256(token.encode()).hexdigest())
        if saved and same_host(saved.get('host'), host) and saved['expires'] > time.time():
            self.pairs[token] = (normalize_ip(host), time.monotonic() + saved['expires'] - time.time())
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
        prev_len = len(self._saved_pairs)
        self._saved_pairs = {k: v for k, v in self._saved_pairs.items() if v.get('expires', 0) > time.time()}
        if len(self._saved_pairs) != prev_len and self._pair_file:
            try:
                self._pair_file.write_text(json.dumps(self._saved_pairs), encoding="utf-8")
            except OSError:
                pass
        for token, session in list(self.sessions.items()):
            if session.expires < now:
                self.sessions.pop(token)
                asyncio.create_task(session.close())

    def pair(self, request: Request, code: str) -> str:
        check_request(request)
        self.prune()
        if not secrets.compare_digest(code, self.code):
            raise HTTPException(403, 'Откройте актуальный QR-код или скопируйте полную ссылку с ПК')
        # Evict oldest pairs if reaching capacity limit rather than failing permanently
        while len(self.pairs) >= 32:
            oldest_k = min(self.pairs.keys(), key=lambda k: self.pairs[k][1])
            self.pairs.pop(oldest_k, None)
        while len(self._saved_pairs) >= 32:
            oldest_k = min(self._saved_pairs.keys(), key=lambda k: self._saved_pairs[k].get('expires', 0))
            self._saved_pairs.pop(oldest_k, None)
        return self.generate_token(request.client.host)

    def authorize(self, request: Request, token_param: str | None = None) -> str:
        check_request(request)
        self.prune()
        for token in self._credentials(request) + ([token_param] if token_param else []):
            if self.validate_token(token, request.client.host):
                return token
        raise HTTPException(401, 'Телефон не подключён к ПК. Отсканируйте актуальный QR-код в настройках ПК и откройте полный адрес, включая часть после #.')

    def session(self, request: Request, token: str, is_hls_child: bool = False) -> MobileSession:
        check_request(request)
        self.prune()
        session = self.sessions.get(token)
        client_host = request.client.host if request.client else None
        if not session or not same_host(session.host, client_host) or session.expires <= time.monotonic():
            logger.warning(
                "[Mobile Session] Access denied for token %s: session_found=%s, session_host=%s, client_host=%s, expired=%s",
                token[:8],
                bool(session),
                session.host if session else None,
                client_host,
                session.expires <= time.monotonic() if session else None,
            )
            raise HTTPException(403, 'Сессия видео завершена. Откройте видео снова.')
        candidates = self._credentials(request)
        if not candidates and is_hls_child:
            return session
        if not any(token == session.owner and self._valid_pair(token, client_host or "") for token in candidates):
            logger.warning(
                "[Mobile Session] Authorization failed for token %s: owner=%s, candidates=%s, client=%s",
                token[:8],
                session.owner[:8],
                candidates,
                client_host,
            )
            raise HTTPException(401, 'Подключение телефона истекло. Вернитесь к пульту и откройте видео снова.')
        return session

    async def media(self, request: Request, token: str):
        if request.method == 'OPTIONS':
            return Response(
                status_code=204,
                headers={
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
                    'Access-Control-Allow-Headers': '*',
                },
            )
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
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(45.0, connect=10.0),
            trust_env=False,
            follow_redirects=False,
        )
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
                logger.error("[Mobile Media] TorrServer rejected stream request (status %s, range=%s)", upstream.status_code, value)
                raise HTTPException(502, 'TorrServer не поддержал запрос видео или перемотку')
            session.connections.add(upstream)
            out = {k.lower(): v for k, v in upstream.headers.items() if k.lower() in
                   ('content-length', 'content-range', 'accept-ranges')}
            out['content-type'] = 'video/mp4'
            out['cache-control'] = 'no-store'
            out['accept-ranges'] = 'bytes'
            out['x-content-type-options'] = 'nosniff'
            out['referrer-policy'] = 'no-referrer'
            out['access-control-allow-origin'] = '*'
            out['access-control-allow-methods'] = 'GET, HEAD, OPTIONS'
            out['access-control-allow-headers'] = '*'

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
                logger.error("[Mobile Media] Upstream TorrServer request failed (%s): %s", type(error).__name__, error)
                raise HTTPException(502, 'TorrServer недоступен') from None
            raise

    async def remux(self, request: Request, token: str):
        """Serve remuxed stream with proper video/mp4 and byte range headers."""
        return await self.media(request, token)

    async def hls_playlist(self, request: Request, token: str):
        if request.method == 'OPTIONS':
            return Response(
                status_code=204,
                headers={
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
                    'Access-Control-Allow-Headers': '*',
                },
            )
        logger.info(
            "[Mobile HLS] Playlist requested by %s for token %s",
            request.client.host if request.client else "unknown",
            token[:8],
        )
        session = self.session(request, token, is_hls_child=True)
        session.expires = time.monotonic() + 180
        playlist_content = session.generate_vod_playlist(request.query_params.get('auth'))
        headers = {
            'content-type': 'application/vnd.apple.mpegurl',
            'cache-control': 'no-cache, no-store',
            'access-control-allow-origin': '*',
            'access-control-allow-methods': 'GET, HEAD, OPTIONS',
            'access-control-allow-headers': '*',
        }
        return Response(content=playlist_content, media_type='application/vnd.apple.mpegurl', headers=headers)

    async def hls_segment(self, request: Request, token: str, name: str):
        if request.method == 'OPTIONS':
            return Response(
                status_code=204,
                headers={
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
                    'Access-Control-Allow-Headers': '*',
                },
            )
        session = self.session(request, token, is_hls_child=True)
        session.expires = time.monotonic() + 180
        if not (name.startswith('seg_') and name.endswith('.ts')):
            logger.warning("[Mobile HLS] Invalid segment name requested: %s", name)
            raise HTTPException(404, 'Сегмент не найден')
        try:
            seq = int(name[4:-3])
        except ValueError:
            logger.warning("[Mobile HLS] Non-integer segment index requested: %s", name)
            raise HTTPException(404, 'Некорректный сегмент')

        port = request.url.port or config.APP_PORT
        try:
            data = await session.get_segment(seq, app_port=port, token=token, timeout=35.0)
        except (asyncio.CancelledError, GeneratorExit):
            await session._stop_ffmpeg()
            raise
        headers = {
            'content-type': 'video/MP2T',
            'content-length': str(len(data)),
            'cache-control': 'no-store',
            'accept-ranges': 'bytes',
            'access-control-allow-origin': '*',
            'access-control-allow-methods': 'GET, HEAD, OPTIONS',
            'access-control-allow-headers': '*',
        }
        return Response(content=data, media_type='video/MP2T', headers=headers)

    async def hls_sink(self, request: Request, token: str, name: str):
        client_ip = request.client.host if request.client else ""
        try:
            addr = ipaddress.ip_address(client_ip)
            if getattr(addr, "ipv4_mapped", None):
                addr = addr.ipv4_mapped
            is_local = addr.is_loopback or client_ip in ('127.0.0.1', '::1', 'localhost', '::ffff:127.0.0.1')
        except ValueError:
            is_local = client_ip in ('127.0.0.1', '::1', 'localhost')
        if not is_local:
            logger.warning("[Mobile HLS Sink] Rejected non-local sink caller: %s", client_ip)
            raise HTTPException(403, 'Sink доступен только локально')
        session = self.sessions.get(token)
        if not session:
            logger.warning("[Mobile HLS Sink] Session not found for token %s", token[:8])
            return Response(status_code=404, headers={"Connection": "close"})
        try:
            chunks = []
            async for chunk in request.stream():
                chunks.append(chunk)
            data = b"".join(chunks)
        except Exception as e:
            logger.warning("[Mobile HLS Sink] Error reading body for %s: %r", name, e)
            return Response(status_code=499, headers={"Connection": "close"})
        if name.startswith('seg_') and name.endswith('.ts'):
            try:
                seq = int(name[4:-3])
                session.receive_segment(seq, data)
            except ValueError:
                pass
        return Response(status_code=200, headers={"Connection": "close"})


mobile_access = MobileAccess()
