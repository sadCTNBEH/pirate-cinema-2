"""On-demand local thumbnails. Network sources must never reach the decoder."""

import hashlib
import math
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from backend.core.settings import get_data_dir
from backend.infrastructure.process_env import system_process_env

WIDTH, HEIGHT = 224, 126
FRAME_BYTES = WIDTH * HEIGHT * 4
INTERVAL = 5
CACHE_BYTES = 32 * 1024 * 1024
CACHE_ENTRIES = 256
CACHE_AGE = 7 * 86400
DECODE_TIMEOUT = 8
# Even if several native players are open, only one preview decoder may run.
_decode_slot = threading.BoundedSemaphore(1)
_cache_lock = threading.Lock()
_cache = None


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
    """Disk LRU; RAM contains only bounded path/stat metadata, never decoded frames."""

    def __init__(self, directory: Path, max_bytes=CACHE_BYTES, max_entries=CACHE_ENTRIES):
        self.directory = directory
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.lock = threading.RLock()
        directory.mkdir(parents=True, exist_ok=True)
        for path in directory.glob("*.part"):
            path.unlink(missing_ok=True)
        self._prune()

    def _prune(self):
        files = sorted(self.directory.glob("*.bgra"), key=lambda p: p.stat().st_mtime, reverse=True)
        total = 0
        for index, path in enumerate(files):
            stat = path.stat()
            total += stat.st_size
            if (index >= self.max_entries or total > self.max_bytes
                    or stat.st_size != FRAME_BYTES or time.time() - stat.st_mtime > CACHE_AGE):
                path.unlink(missing_ok=True)

    def get(self, key: str) -> Path | None:
        with self.lock:
            path = self.directory / f"{key}.bgra"
            if not path.is_file():
                return None
            stat = path.stat()
            if stat.st_size != FRAME_BYTES or time.time() - stat.st_mtime > CACHE_AGE:
                path.unlink(missing_ok=True)
                return None
            path.touch()
            return path

    def put(self, key: str, temporary: Path) -> Path | None:
        with self.lock:
            if temporary.stat().st_size != FRAME_BYTES:
                return None
            path = self.directory / f"{key}.bgra"
            temporary.replace(path)
            self._prune()
            return path if path.exists() else None


def thumbnail_cache() -> ThumbnailCache:
    global _cache
    with _cache_lock:
        if _cache is None:
            _cache = ThumbnailCache(get_data_dir() / "thumbnails")
        return _cache


def round_corners(path: Path):
    # Only the tiny output frame is read, never a source-resolution image.
    pixels = bytearray(path.read_bytes())
    if len(pixels) != FRAME_BYTES:
        return
    radius = 7
    for y in range(radius):
        for x in range(radius):
            alpha = round(255 * max(0, min(1, radius - math.hypot(radius-x-0.5, radius-y-0.5))))
            for px, py in ((x, y), (WIDTH-1-x, y), (x, HEIGHT-1-y), (WIDTH-1-x, HEIGHT-1-y)):
                offset = (py * WIDTH + px) * 4
                # MPV expects premultiplied BGRA.
                for channel in range(3):
                    pixels[offset+channel] = pixels[offset+channel] * alpha // 255
                pixels[offset+3] = alpha
    path.write_bytes(pixels)


class PreviewSession:
    """One replaceable pending request; stale work cannot publish into a new film."""

    def __init__(self, source: str, publish):
        self.source = local_source(source)
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
            bucket = int(position // INTERVAL) * INTERVAL
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
            self.thread.join(timeout=2)

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
                    self.publish(request_id, str(path) if path else "")

    def _generate(self, bucket, serial):
        cache = thumbnail_cache()
        key = frame_key(self.source, bucket)
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
        temporary = cache.directory / f"{uuid.uuid4().hex}.part"
        try:
            with self.condition:
                if not self._active(serial):
                    return None
                # Recheck under the global decode slot to prevent duplicate extraction.
                if cached := cache.get(key):
                    return cached
                args = [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-threads", "1", "-filter_threads", "1", "-protocol_whitelist", "file,pipe",
                        "-ss", str(bucket), "-i", str(self.source), "-map", "0:v:0",
                        "-frames:v", "1", "-an", "-sn", "-dn", "-vf",
                        (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                         f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1"),
                        "-pix_fmt", "bgra", "-f", "rawvideo", str(temporary)]
                options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS} if os.name == "nt" else {}
                self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                env=system_process_env(), **options)
                process = self.process
            try:
                result = process.wait(timeout=DECODE_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
                result = -1
            with self.condition:
                self.process = None
                if not self._active(serial):
                    return None
                if result != 0 or not temporary.is_file() or temporary.stat().st_size != FRAME_BYTES:
                    self.failed[key] = time.monotonic() + 30
                    while len(self.failed) > 32:
                        self.failed.popitem(last=False)
                    return None
                round_corners(temporary)
                return cache.put(key, temporary)
        finally:
            with self.condition:
                if self.process is not None:
                    with suppress(OSError, subprocess.SubprocessError):
                        self.process.kill()
                        self.process.wait(timeout=1)
                    self.process = None
            temporary.unlink(missing_ok=True)
            _decode_slot.release()
