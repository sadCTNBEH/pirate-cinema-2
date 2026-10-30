"""Bounded local-file previews: FFmpeg stdout → Python RAM → ASS over IPC."""

import hashlib
import json
import math
import os
import shutil
import subprocess
import threading
import time
from collections import OrderedDict
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from backend.infrastructure.process_env import system_process_env

WIDTH, HEIGHT = 112, 63
FRAME_BYTES = WIDTH * HEIGHT * 4
INTERVAL = 5
CACHE_BYTES = 32 * 1024 * 1024
CACHE_ENTRIES = 256
DECODE_TIMEOUT = 8
# One decoder across all sessions. Frames and vector previews remain in Python RAM.
_decode_slot = threading.BoundedSemaphore(1)


def local_source(source: str) -> Path | None:
    if source.startswith("file:"):
        parsed = urlsplit(source)
        if parsed.netloc or parsed.query or parsed.fragment:
            return None
        source = url2pathname(parsed.path)
    if "://" in source or source.startswith(("\\\\", "//")):
        return None
    path = Path(source)
    if not path.is_absolute() or path.suffix.lower() not in {
        ".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v", ".ts", ".mpg", ".mpeg",
    }:
        return None
    if os.name == "nt":
        import ctypes

        if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) == 4:
            return None
    try:
        path = path.resolve(strict=True)
        return path if path.is_file() else None
    except (OSError, ValueError):
        return None


def frame_key(source: Path, position: int) -> str:
    stat = source.stat()
    identity = f"v1:{source}:{stat.st_size}:{stat.st_mtime_ns}:{position}:{WIDTH}:{HEIGHT}"
    return hashlib.sha256(identity.encode()).hexdigest()


class ThumbnailCache:
    """Session-owned byte-bounded LRU. Never opens or removes a file."""

    def __init__(self, max_bytes=CACHE_BYTES, max_entries=CACHE_ENTRIES):
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.frames = OrderedDict()
        self.size = 0
        self.lock = threading.RLock()

    def get(self, key):
        with self.lock:
            value = self.frames.get(key)
            if value is not None:
                self.frames.move_to_end(key)
            return value

    def put(self, key, frame):
        if not isinstance(frame, bytes) or len(frame) > self.max_bytes:
            return None
        with self.lock:
            old = self.frames.pop(key, b'')
            self.size += len(frame) - len(old)
            self.frames[key] = frame
            while self.size > self.max_bytes or len(self.frames) > self.max_entries:
                self.size -= len(self.frames.popitem(last=False)[1])
            return self.frames.get(key)

    def clear(self):
        with self.lock:
            self.frames.clear()
            self.size = 0


def vector_frame(pixels):
    """Compact ASS paths, grouped by quantized color, sent over existing JSON IPC.

    MPV's file-based bitmap overlay requires mmap-able storage. ASS avoids a
    filesystem transport on both OSes and needs neither LuaJIT nor remote pointers.
    """
    groups = {}
    for y in range(HEIGHT):
        x = 0
        while x < WIDTH:
            def color_at(column, row=y):
                offset = (row * WIDTH + column) * 4
                return tuple((v // 32) * 36 for v in pixels[offset:offset+3])
            color = color_at(x)
            end = x + 1
            while end < WIDTH and color_at(end) == color:
                end += 1
            key = ''.join(f'{channel:02X}' for channel in color)
            groups.setdefault(key, []).append(f'm {x} {y} l {end} {y} {end} {y+1} {x} {y+1}')
            x = end
    return json.dumps([[c, ' '.join(paths)] for c, paths in groups.items()], separators=(',', ':')).encode()


class PreviewSession:
    """One replaceable pending request; stale work cannot publish into a new film."""

    interval = INTERVAL

    def __init__(self, source: str, publish):
        self.source = local_source(source)
        self.cache = ThumbnailCache()
        self.publish = publish
        self.condition = threading.Condition()
        self.closed = False
        self.serial = 0
        self.pending = None
        self.current = None
        self.process = None
        self.thread = None
        self.failed = OrderedDict()

    def request(self, request_id: str, seconds: str):
        try:
            position = float(seconds)
            if not math.isfinite(position) or position < 0 or position > 7 * 86400:
                return
            bucket = int(position // self.interval) * self.interval
        except (TypeError, ValueError, OverflowError):
            return
        with self.condition:
            if self.closed or self.source is None:
                return
            # Lua deduplicates buckets; keep this guard for duplicated IPC messages.
            if self.current == (request_id, bucket) or self.pending == (request_id, bucket, self.serial):
                return
            self._cancel_locked()
            self.pending = (request_id, bucket, self.serial)
            if self.thread is None:
                self.thread = threading.Thread(target=self._worker, name="ThumbnailPreview", daemon=True)
                self.thread.start()
            self.condition.notify()

    def _cancel_locked(self):
        self.serial += 1
        self.pending = None
        if self.process is not None:
            with suppress(OSError):
                self.process.terminate()

    def cancel(self):
        with self.condition:
            self._cancel_locked()

    def close(self):
        with self.condition:
            self.closed = True
            self._cancel_locked()
            self.condition.notify()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=DECODE_TIMEOUT + 2)
        self.cache.clear()

    def _active(self, serial):
        return not self.closed and serial == self.serial

    def _worker(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                request_id, bucket, serial = self.pending
                self.pending = None
                self.current = (request_id, bucket)
            path = None
            try:
                path = self._generate(bucket, serial)
            except (OSError, ValueError, subprocess.SubprocessError):
                # Preview failures are deliberately silent and never stop playback.
                pass
            with self.condition:
                self.current = None
                if self._active(serial):
                    self.publish(request_id, path.decode() if path else "")

    def _generate(self, bucket, serial):
        key = frame_key(self.source, bucket)
        return self._decode(self.source, key, serial, bucket)

    def _decode(self, source, key, serial, position=None):
        cache = self.cache
        if cached := cache.get(key):
            return cached
        if self.failed.get(key, 0) > time.monotonic():
            return None
        executable = shutil.which("ffmpeg")
        if not executable:
            return None
        while not _decode_slot.acquire(timeout=0.1):
            if not self._active(serial):
                return None

        try:
            with self.condition:
                if not self._active(serial):
                    return None
                # Recheck under the global decode slot to prevent duplicate extraction.
                if cached := cache.get(key):
                    return cached
                args = [executable, "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-threads", "1", "-filter_threads", "1", "-protocol_whitelist", "file,pipe"]
                args.extend(["-ss", str(position)])
                args.extend(["-i", str(source), "-map", "0:v:0",
                        "-frames:v", "1", "-an", "-sn", "-dn", "-vf",
                        (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                         f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1"),
                        "-pix_fmt", "bgra", "-f", "rawvideo", "pipe:1"])
                options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS} if os.name == "nt" else {}
                self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                                env=system_process_env(), **options)
                process = self.process
            try:
                pixels, _ = process.communicate(timeout=DECODE_TIMEOUT)
                result = process.returncode
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=1)
                pixels, result = b"", -1
            with self.condition:
                self.process = None
                if not self._active(serial):
                    return None
                if result != 0 or len(pixels) != FRAME_BYTES:
                    self.failed[key] = time.monotonic() + 30
                    while len(self.failed) > 32:
                        self.failed.popitem(last=False)
                    return None
                return cache.put(key, vector_frame(pixels))
        finally:
            with self.condition:
                if self.process is not None:
                    with suppress(OSError, subprocess.SubprocessError):
                        self.process.kill()
                        self.process.wait(timeout=1)
                    self.process = None
            _decode_slot.release()
