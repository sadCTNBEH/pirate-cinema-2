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

QUANT_HEX: list[str] = [f"{(i // 32) * 36:02X}" for i in range(256)]
QUANT_BYTE: list[int] = [(i // 32) * 36 for i in range(256)]



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


def is_loopback_or_ts_stream(source: str) -> bool:
    if not isinstance(source, str) or not (source.startswith("http://") or source.startswith("https://")):
        return False
    try:
        parsed = urlsplit(source)
    except Exception:
        return False
    hostname = (parsed.hostname or "").lower()
    if hostname in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
        return True
    if parsed.path.startswith("/stream") and ("link=" in (parsed.query or "") or parsed.port == 8090):
        return True
    return False


def frame_key(source: Path | str, position: int) -> str:
    if isinstance(source, Path):
        stat = source.stat()
        identity = f"v1:{source}:{stat.st_size}:{stat.st_mtime_ns}:{position}:{WIDTH}:{HEIGHT}"
    else:
        identity = f"v1:{source}:{position}:{WIDTH}:{HEIGHT}"
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


def vector_frame(pixels: bytes) -> bytes:
    """Compact ASS paths, grouped by quantized color, sent over existing JSON IPC.

    MPV's file-based bitmap overlay requires mmap-able storage. ASS avoids a
    filesystem transport on both OSes and needs neither LuaJIT nor remote pointers.
    Optimized to eliminate inner function closures and use precalculated color tables.
    """
    groups: dict[str, list[str]] = {}
    row_bytes = WIDTH * 4
    for y in range(HEIGHT):
        row_offset = y * row_bytes
        x = 0
        while x < WIDTH:
            px = row_offset + x * 4
            b = QUANT_BYTE[pixels[px]]
            g = QUANT_BYTE[pixels[px + 1]]
            r = QUANT_BYTE[pixels[px + 2]]

            end = x + 1
            while end < WIDTH:
                next_px = row_offset + end * 4
                if (
                    QUANT_BYTE[pixels[next_px]] != b
                    or QUANT_BYTE[pixels[next_px + 1]] != g
                    or QUANT_BYTE[pixels[next_px + 2]] != r
                ):
                    break
                end += 1

            key = QUANT_HEX[pixels[px]] + QUANT_HEX[pixels[px + 1]] + QUANT_HEX[pixels[px + 2]]
            groups.setdefault(key, []).append(f"m {x} {y} l {end} {y} {end} {y+1} {x} {y+1}")
            x = end

    return json.dumps([[c, " ".join(paths)] for c, paths in groups.items()], separators=(",", ":")).encode()


class PreviewSession:
    """One replaceable pending request; stale work cannot publish into a new film."""

    interval = INTERVAL

    def __init__(self, source: str, publish):
        local = local_source(source)
        if local is not None:
            self.source = local
            self.is_stream = False
        elif is_loopback_or_ts_stream(source):
            self.source = source
            self.is_stream = True
        else:
            self.source = None
            self.is_stream = False
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
        self.duration = 0.0
        self.milestones: list[int] = []
        self.milestones_started = False
        self.local_dense_queue: list[int] = []
        self.local_dense_enqueued: set[int] = set()

    def set_duration(self, duration: float):
        try:
            dur = float(duration)
            if not math.isfinite(dur) or dur <= 10:
                return
        except (TypeError, ValueError):
            return
        with self.condition:
            if self.closed or self.source is None:
                return
            if self.duration == dur and self.milestones_started:
                return
            self.duration = dur
            self.milestones_started = True
            num_milestones = 7
            interval = self.interval
            points = []
            for i in range(1, num_milestones + 1):
                pos = (dur * i) / (num_milestones + 1)
                bucket = int(pos // interval) * interval
                if bucket not in points and 0 < bucket < dur:
                    points.append(bucket)
            self.milestones = points
            if self.thread is None:
                self.thread = threading.Thread(target=self._worker, name="ThumbnailPreview", daemon=True)
                self.thread.start()
            self.condition.notify()

    def update_cache_state(self, state: dict):
        if not isinstance(state, dict):
            return
        ranges = state.get("seekable-ranges")
        if not isinstance(ranges, list) or not ranges:
            cache_end = state.get("cache-end")
            reader_pts = state.get("reader-pts") or 0.0
            if isinstance(cache_end, (int, float)) and cache_end > reader_pts:
                ranges = [{"start": reader_pts, "end": cache_end}]
            else:
                return

        interval = self.interval
        step = 15
        new_dense = []
        with self.condition:
            if self.closed or self.source is None:
                return
            for r in ranges:
                if not isinstance(r, dict):
                    continue
                start = r.get("start")
                end = r.get("end")
                if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                    continue
                if end <= start or start < 0:
                    continue
                curr = int(math.ceil(start / step)) * step
                while curr < end:
                    bucket = int(curr // interval) * interval
                    if bucket not in self.local_dense_enqueued:
                        self.local_dense_enqueued.add(bucket)
                        new_dense.append(bucket)
                    curr += step
                    if len(new_dense) >= 32:
                        break
            if new_dense:
                self.local_dense_queue.extend(new_dense)
                if self.thread is None:
                    self.thread = threading.Thread(target=self._worker, name="ThumbnailPreview", daemon=True)
                    self.thread.start()
                self.condition.notify()

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
            proc = self.process
            self.process = None
            with suppress(OSError, subprocess.SubprocessError):
                proc.terminate()
                if getattr(proc, "stdout", None):
                    with suppress(OSError):
                        proc.stdout.close()

    def cancel(self):
        with self.condition:
            self._cancel_locked()

    def close(self):
        with self.condition:
            self.closed = True
            self.milestones.clear()
            self.local_dense_queue.clear()
            self.local_dense_enqueued.clear()
            self._cancel_locked()
            self.condition.notify()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=DECODE_TIMEOUT + 2)
        self.cache.clear()
        self.failed.clear()

    def _active(self, serial):
        return not self.closed and serial == self.serial

    def _worker(self):
        while True:
            task_type = None
            request_id = ""
            bucket = 0
            serial = 0
            with self.condition:
                while not self.closed:
                    if self.pending is not None:
                        request_id, bucket, serial = self.pending
                        self.pending = None
                        task_type = "pending"
                        self.current = (request_id, bucket)
                        break
                    if self.milestones:
                        bucket = self.milestones.pop(0)
                        task_type = "milestone"
                        request_id = "bg"
                        serial = self.serial
                        self.current = (request_id, bucket)
                        break
                    if self.local_dense_queue:
                        bucket = self.local_dense_queue.pop(0)
                        task_type = "dense"
                        request_id = "bg"
                        serial = self.serial
                        self.current = (request_id, bucket)
                        break
                    self.condition.wait()
                if self.closed:
                    return

            path = None
            try:
                path = self._generate(bucket, serial)
            except (OSError, ValueError, subprocess.SubprocessError):
                # Preview failures are deliberately silent and never stop playback.
                pass

            with self.condition:
                self.current = None
                if self.closed:
                    return
                if task_type == "pending":
                    if self._active(serial):
                        payload = path.decode() if path else ""
                        try:
                            self.publish(request_id, payload, str(bucket))
                        except TypeError:
                            self.publish(request_id, payload)
                else:
                    if path:
                        payload = path.decode()
                        try:
                            self.publish("bg", payload, str(bucket))
                        except TypeError:
                            self.publish("bg", payload)

    def _generate(self, bucket, serial):
        key = frame_key(self.source, bucket)
        return self._decode(self.source, key, serial, bucket)

    def _decode(self, source, key, serial, position=None):
        cache = self.cache
        if cached := cache.get(key):
            return cached
        if self.failed.get(key, 0) > time.monotonic():
            return None
        executable = None
        try:
            from backend.infrastructure.ffmpeg import get_ffmpeg
            executable = get_ffmpeg()
        except Exception:
            pass
        if not executable:
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
                args = [
                    executable,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-threads",
                    "1",
                    "-filter_threads",
                    "1",
                    "-protocol_whitelist",
                    "file,pipe,http,https,tcp,tls,crypto",
                    "-noaccurate_seek",
                    "-ss",
                    str(position),
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    "-an",
                    "-sn",
                    "-dn",
                    "-vf",
                    (
                        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:flags=fast_bilinear,"
                        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1"
                    ),
                    "-pix_fmt",
                    "bgra",
                    "-f",
                    "rawvideo",
                    "pipe:1",
                ]
                options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS} if os.name == "nt" else {}
                self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                                env=system_process_env(), **options)
                process = self.process
            try:
                pixels, _ = process.communicate(timeout=DECODE_TIMEOUT)
                result = process.returncode
            except subprocess.TimeoutExpired:
                process.kill()
                with suppress(Exception):
                    process.communicate(timeout=1)
                pixels, result = b"", -1
            finally:
                if getattr(process, "stdout", None):
                    with suppress(Exception):
                        process.stdout.close()
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
                    proc = self.process
                    self.process = None
                    with suppress(OSError, subprocess.SubprocessError):
                        proc.kill()
                        if getattr(proc, "stdout", None):
                            with suppress(Exception):
                                proc.stdout.close()
                        proc.wait(timeout=1)
            _decode_slot.release()
