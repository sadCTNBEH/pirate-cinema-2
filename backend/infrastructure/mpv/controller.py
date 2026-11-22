import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import anyio

from backend.core.settings import BASE_DIR, config, get_data_dir, load_settings
from backend.core.settings.user import save_track_preferences
from backend.infrastructure.mpv.preview import PreviewSession
from backend.infrastructure.mpv.tracks import TrackSelection
from backend.infrastructure.process_env import system_process_env
from backend.infrastructure.source_routing import direct_process_env

logger = logging.getLogger("mpv")
logger.setLevel(logging.DEBUG)
PROGRESSCALLBACK = Callable[[str, Any], None]
ENDCALLBACK = Callable[[str | None], None]

_LANG_MAP: dict[str, str] = {
    "ru": "ru", "rus": "ru", "russian": "ru", "русский": "ru",
    "en": "en", "eng": "en", "english": "en", "английский": "en",
    "ja": "ja", "jpn": "ja", "japanese": "ja", "японский": "ja",
    "de": "de", "deu": "de", "ger": "de", "german": "de",
    "fr": "fr", "fra": "fr", "fre": "fr", "french": "fr",
    "es": "es", "spa": "es", "spanish": "es",
    "it": "it", "ita": "it", "italian": "it",
    "zh": "zh", "zho": "zh", "chi": "zh", "chinese": "zh",
    "ko": "ko", "kor": "ko", "korean": "ko",
    "uk": "uk", "ukr": "uk", "ukrainian": "uk",
}


def normalize_track_lang(val: Any) -> str:
    """Normalize common ISO 639-1 / 639-2 language codes and names."""
    if not val:
        return ""
    code = str(val).strip().casefold().replace("_", "-")
    base = code.split("-")[0]
    return _LANG_MAP.get(code, _LANG_MAP.get(base, base))



def resolve_cinema_lua_path() -> Path | None:
    """Locate cinema.lua across development and packaged (PyInstaller, AppImage) layouts."""
    candidates = [
        Path(__file__).with_name("cinema.lua"),
        Path(sys.executable).parent / "cinema.lua",
        Path(sys.executable).parent / "_internal" / "backend" / "infrastructure" / "mpv" / "cinema.lua",
        Path(sys._MEIPASS) / "backend" / "infrastructure" / "mpv" / "cinema.lua" if hasattr(sys, "_MEIPASS") else None,
        Path(sys._MEIPASS) / "cinema.lua" if hasattr(sys, "_MEIPASS") else None,
        Path(os.environ["APPDIR"]) / "cinema.lua" if "APPDIR" in os.environ else None,
        Path(os.environ["APPDIR"]) / "_internal" / "backend" / "infrastructure" / "mpv" / "cinema.lua" if "APPDIR" in os.environ else None,
        BASE_DIR / "backend" / "infrastructure" / "mpv" / "cinema.lua",
        BASE_DIR / "cinema.lua",
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c).resolve()
    return None



if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    class WindowsPipe:
        """Asynchronous Win32 named pipe wrapper with overlapped I/O for concurrent read/write."""

        def __init__(self, pipe_name: str) -> None:
            self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            signatures = {
                "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
                "CreateEventW": ([ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
                "ReadFile": ([wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)], wintypes.BOOL),
                "WriteFile": ([wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)], wintypes.BOOL),
                "GetOverlappedResult": ([wintypes.HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(wintypes.DWORD), wintypes.BOOL], wintypes.BOOL),
                "CancelIoEx": ([wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)], wintypes.BOOL),
                "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
                "ResetEvent": ([wintypes.HANDLE], wintypes.BOOL),
            }
            for name, (argtypes, restype) in signatures.items():
                function = getattr(self.k32, name)
                function.argtypes = argtypes
                function.restype = restype
            self.handle = self.k32.CreateFileW(
                pipe_name,
                0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
                0,
                None,
                3,  # OPEN_EXISTING
                0x40000000,  # FILE_FLAG_OVERLAPPED
                None,
            )
            if self.handle == ctypes.c_void_p(-1).value or not self.handle:
                raise OSError(f"Failed to open pipe {pipe_name}")
            self._read_ov = OVERLAPPED()
            self._read_ov.hEvent = self.k32.CreateEventW(None, True, False, None)
            self._write_ov = OVERLAPPED()
            self._write_ov.hEvent = self.k32.CreateEventW(None, True, False, None)
            self._buf = bytearray()
            self._closed = False
            self._cancelled = False
            self._write_lock = threading.Lock()
            self._read_lock = threading.Lock()
            self._close_lock = threading.Lock()
            if not self._read_ov.hEvent or not self._write_ov.hEvent:
                self.close()
                raise OSError("Failed to create MPV IPC events")

        def write(self, data: bytes) -> None:
            with self._write_lock:
                if self._closed or self._cancelled:
                    return
                written = wintypes.DWORD()
                self.k32.ResetEvent(self._write_ov.hEvent)
                ret = self.k32.WriteFile(
                    self.handle, data, len(data), ctypes.byref(written), ctypes.byref(self._write_ov)
                )
                if not ret:
                    err = ctypes.get_last_error()
                    if err == 997:  # ERROR_IO_PENDING
                        if self._cancelled:
                            # Cancellation may have raced the WriteFile call itself.
                            self.k32.CancelIoEx(self.handle, ctypes.byref(self._write_ov))
                        completed = self.k32.GetOverlappedResult(
                            self.handle, ctypes.byref(self._write_ov), ctypes.byref(written), True
                        )
                        if not completed and not self._closed:
                            raise ctypes.WinError(ctypes.get_last_error())
                    else:
                        raise OSError(f"WriteFile failed with error {err}")

        def flush(self) -> None:
            pass

        def cancel_pending(self) -> None:
            self._cancelled = True
            if not self._closed:
                self.k32.CancelIoEx(self.handle, None)

        def readline(self) -> bytes:
            with self._read_lock:
                return self._readline()

        def _readline(self) -> bytes:
            while not self._closed:
                nl = self._buf.find(b"\n")
                if nl != -1:
                    line = bytes(self._buf[: nl + 1])
                    del self._buf[: nl + 1]
                    return line

                read_buf = ctypes.create_string_buffer(4096)
                read_bytes = wintypes.DWORD()
                self.k32.ResetEvent(self._read_ov.hEvent)
                ret = self.k32.ReadFile(
                    self.handle, read_buf, 4096, ctypes.byref(read_bytes), ctypes.byref(self._read_ov)
                )
                if not ret:
                    err = ctypes.get_last_error()
                    if err == 997:  # ERROR_IO_PENDING
                        # Keep both the buffer and OVERLAPPED alive until Windows finishes.
                        if not self.k32.GetOverlappedResult(
                            self.handle, ctypes.byref(self._read_ov), ctypes.byref(read_bytes), True
                        ):
                            break
                    else:
                        break
                if read_bytes.value > 0:
                    self._buf.extend(read_buf.raw[: read_bytes.value])
                else:
                    # MPV can issue a zero-length pipe write before an async reply.
                    # A successful empty read is not EOF on a Win32 named pipe;
                    # disconnection is reported by ReadFile/GetOverlappedResult.
                    continue
            return b""

        def close(self) -> None:
            with self._close_lock:
                if self._closed:
                    return
                self._closed = True
                # CancelIo only cancels operations issued by the calling thread.
                # Cancel and drain each operation before releasing buffers or handles.
                while not self._read_lock.acquire(timeout=0.05):
                    self.k32.CancelIoEx(self.handle, None)
                try:
                    while not self._write_lock.acquire(timeout=0.05):
                        self.k32.CancelIoEx(self.handle, None)
                    try:
                        self.k32.CloseHandle(self.handle)
                        self.k32.CloseHandle(self._read_ov.hEvent)
                        self.k32.CloseHandle(self._write_ov.hEvent)
                    finally:
                        self._write_lock.release()
                finally:
                    self._read_lock.release()


class _StopAwaitable:
    def __init__(self, controller: "MPVController") -> None:
        self._controller = controller

    def __await__(self):
        async def _coro():
            async with self._controller.control_lock:
                return None
        return _coro().__await__()


@runtime_checkable
class IMPVController(Protocol):
    """Protocol defining the interface for MPV player controllers."""

    def start_file(
        self,
        url: str,
        title: str = "",
        start_time: int = 0,
        audio_track: int = 0,
        subtitle_track: int = 0,
        wid: int | None = None,
        mpv_path: str | Path | None = None,
        load_only: bool = False,
        **kwargs: Any,
    ) -> None: ...

    def set_property(self, name: str, value: Any) -> None: ...

    def get_property(self, name: str, request_id: int | None = None) -> Any: ...

    def stop(self) -> Any: ...


class MPVController:
    _global_control_lock: asyncio.Lock | None = None
    _lock_loop: Any = None

    @classmethod
    def get_global_lock(cls) -> asyncio.Lock:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if getattr(cls, "_global_control_lock", None) is None or getattr(cls, "_lock_loop", None) is not loop:
            cls._global_control_lock = asyncio.Lock()
            cls._lock_loop = loop
        return cls._global_control_lock

    @property
    def control_lock(self) -> asyncio.Lock:
        if getattr(self, "_instance_control_lock", None) is not None:
            return self._instance_control_lock
        return self.get_global_lock()

    @control_lock.setter
    def control_lock(self, lock: asyncio.Lock) -> None:
        self._instance_control_lock = lock

    async def start(
        self,
        mpv_path: str | Path,
        url: str,
        title: str,
        start_time: int = 0,
        audio_track: int = 0,
        subtitle_track: int = 0,
        wid: int | None = None,
    ) -> None:
        """Asynchronously launch MPV process, serialized with stop via asyncio.Lock."""
        async with self.control_lock:
            await anyio.to_thread.run_sync(
                lambda: self.launch(mpv_path, url, title, start_time, audio_track, subtitle_track, wid)
            )

    async def stop_async(self) -> None:
        """Asynchronously stop MPV process, serialized with start via asyncio.Lock."""
        async with self.control_lock:
            await anyio.to_thread.run_sync(self._stop_internal)

    def start_file(
        self,
        url: str,
        title: str = "",
        start_time: int = 0,
        audio_track: int = 0,
        subtitle_track: int = 0,
        wid: int | None = None,
        mpv_path: str | Path | None = None,
        load_only: bool = False,
        **kwargs: Any,
    ) -> None:
        """Start playing a file by loading it into the running player or launching a new process."""
        can_reuse = self.is_running and self.process is not None and self.process.poll() is None
        if wid is not None and self._wid is not None and wid != self._wid:
            can_reuse = False
        if load_only or can_reuse:
            self.load_file(
                url=url,
                title=title,
                start_time=start_time,
                audio_track=audio_track,
                subtitle_track=subtitle_track,
            )
        else:
            if mpv_path is None:
                from backend.core.settings import load_settings, resolve_mpv_binary

                mpv_path = resolve_mpv_binary(load_settings())
            self.launch(
                mpv_path=mpv_path,
                url=url,
                title=title,
                start_time=start_time,
                audio_track=audio_track,
                subtitle_track=subtitle_track,
                wid=wid,
                **kwargs,
            )

    def next_track(
        self,
        url: str,
        title: str = "",
        start_time: int = 0,
        audio_track: int | str | None = None,
        subtitle_track: int | str | None = None,
        **kwargs: Any,
    ) -> None:
        """Switch to next episode/file, preserving user audio and subtitle track preferences."""
        if audio_track is not None and audio_track not in (0, "0"):
            self._record_audio_preference(audio_track)
        if subtitle_track is not None:
            self._record_subtitle_preference(subtitle_track)

        self._pending_track_resolution = True

        resolved_sub = subtitle_track
        if resolved_sub is None and self._saved_sub_pref:
            if self._saved_sub_pref.get("mode") == "off":
                resolved_sub = "no"

        self.start_file(
            url=url,
            title=title,
            start_time=start_time,
            audio_track=int(audio_track) if isinstance(audio_track, int) or (isinstance(audio_track, str) and audio_track.isdigit()) else 0,
            subtitle_track=int(resolved_sub) if isinstance(resolved_sub, int) or (isinstance(resolved_sub, str) and resolved_sub.isdigit()) else 0,
            load_only=True,
            **kwargs,
        )

    def set_property(self, name: str, value: Any) -> None:
        """Set an MPV property via IPC."""
        if hasattr(self, "_properties"):
            self._properties[name] = value
        if name == "aid" and value is not None:
            self._record_audio_preference(value)
        elif name == "sid" and value is not None:
            self._record_subtitle_preference(value)
        self.send_command(["set_property", name, value])

    def get_property(self, name: str, request_id: int | None = None) -> Any:
        """Get an MPV property via IPC or local cache."""
        if request_id is not None:
            self.send_command(["get_property", name], request_id=request_id)
            return None
        return getattr(self, "_properties", {}).get(name)

    def seek(self, position: float | int, reference: str = "absolute+exact") -> None:
        """Seek MPV playback position."""
        self.send_command(["seek", position, reference])

    def set_next_available(self, has_next: bool) -> None:
        """Notify the MPV OSD script if a next episode is available."""
        self.send_command(["script-message", "cinema-next", "yes" if has_next else "no"])

    def send_subtitles_menu(self, payload: dict[str, Any]) -> None:
        """Send subtitles payload to MPV OSD script."""
        self.send_command(["script-message", "cinema-subtitles", json.dumps(payload, ensure_ascii=False)])

    def open_menu(self) -> None:
        """Open cinema.lua menu via script-message."""
        self.send_command(["script-message", "cinema-open-menu"])

    def send_menu_input(self, action: str) -> None:
        """Send continuation menu input to cinema.lua."""
        self.send_command(["script-message", "cinema-continuation-input", action])

    def set_osd_fullscreen(self, is_fs: bool) -> None:
        """Inform cinema.lua OSD of host fullscreen toggle."""
        self.send_command(["script-message", "cinema-fullscreen", "yes" if is_fs else "no"])

    def step_frame(self, backward: bool = False) -> None:
        """Step one video frame forward or backward."""
        self.send_command(["frame-back-step" if backward else "frame-step"])

    def prepare_media_switch(self) -> None:
        """Prepare controller state for switching to a new media file."""
        self._awaiting_media = True

    def command(self, cmd: list[Any]) -> None:
        """Send a generic command to MPV IPC."""
        self.send_command(cmd)

    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self._owned_pid: int | None = None
        self.pipe: Any = None
        self.pipe_name: str | None = None
        self.thread: threading.Thread | None = None

        self.on_progress: PROGRESSCALLBACK | None = None
        self.on_end: ENDCALLBACK | None = None

        self.is_running = False
        self.log_file: Any = None
        self._lock = threading.Lock()
        self._subtitle_lock = threading.Lock()
        self._properties: dict[str, Any] = {}
        self._wid: int | None = None
        self._custom_osd: bool = False
        self._osd_ready: bool = False
        self._stop_requested = threading.Event()
        self.last_error: str | None = None
        self._preview: PreviewSession | None = None
        self._preview_cache_state: dict = {}
        self._cache_properties = {}
        self._cache_ready = threading.Event()
        self._tracks: TrackSelection | None = None
        self._default_languages = {}
        self._managed_languages = set()
        self._language_defaults_ready = threading.Event()
        self._segment_payload = None
        self._debug_mode = False
        self._seek_step = 10
        self._loadfile_has_index = True
        self._loadfile_signature_ready = threading.Event()
        self._hwdec_mode: str = config.MPV_HWDEC
        self._hwdec_fallback_done: bool = False
        self._current_title: str = ""
        self._current_start_time: int = 0
        self._current_audio_track: int = 0
        self._current_subtitle_track: int = 0
        self._saved_audio_pref: dict[str, Any] | None = None
        self._saved_sub_pref: dict[str, Any] | None = None
        self._pending_track_resolution: bool = False

    @property
    def current_codec(self) -> str | None:
        """Return currently observed video codec format."""
        return self._properties.get("video-format") or self._properties.get("video-codec")

    @property
    def dropped_frames(self) -> int:
        """Return total dropped frames reported by decoder or video output."""
        drops = self._properties.get("decoder-frame-drop-count")
        if drops is None:
            drops = self._properties.get("frame-drop-count")
        try:
            return int(drops) if drops is not None else 0
        except (ValueError, TypeError):
            return 0

    @property
    def is_hwdec_active(self) -> bool:
        """Return True if hardware decoding is actively engaged."""
        hwdec_cur = self._properties.get("hwdec-current")
        return bool(hwdec_cur and hwdec_cur != "no")

    def get_playback_metrics(self) -> dict[str, Any]:
        """Return basic playback metrics for system diagnostics."""
        return {
            "codec": self.current_codec,
            "dropped_frames": self.dropped_frames,
            "hwdec_active": self.is_hwdec_active,
        }

    def _record_audio_preference(self, track_id: Any) -> None:
        if track_id in (0, "0", "no", "off", None, False):
            self._saved_audio_pref = {"mode": "auto", "id": None, "lang": None, "index": 0}
            return
        track_list = self._properties.get("track-list") or []
        audio_tracks = [t for t in track_list if isinstance(t, dict) and t.get("type") == "audio"]
        matched_idx = None
        matched_lang = None
        for idx, t in enumerate(audio_tracks):
            if str(t.get("id")) == str(track_id):
                matched_idx = idx
                matched_lang = normalize_track_lang(t.get("lang"))
                break
        self._saved_audio_pref = {
            "mode": "track",
            "id": track_id,
            "lang": matched_lang,
            "index": matched_idx if matched_idx is not None else 0,
        }

    def _record_subtitle_preference(self, track_id: Any) -> None:
        if track_id in (0, "0", "no", "off", False, None):
            self._saved_sub_pref = {"mode": "off", "id": "no", "lang": None, "index": None}
            return
        track_list = self._properties.get("track-list") or []
        sub_tracks = [t for t in track_list if isinstance(t, dict) and t.get("type") == "sub"]
        matched_idx = None
        matched_lang = None
        for idx, t in enumerate(sub_tracks):
            if str(t.get("id")) == str(track_id):
                matched_idx = idx
                matched_lang = normalize_track_lang(t.get("lang"))
                break
        self._saved_sub_pref = {
            "mode": "track",
            "id": track_id,
            "lang": matched_lang,
            "index": matched_idx if matched_idx is not None else 0,
        }

    def _find_matching_track(
        self,
        tracks: list[dict[str, Any]],
        track_type: str,
        pref: dict[str, Any] | None,
    ) -> Any | None:
        """Find matching track ID by language first, then by relative index."""
        if not pref or not tracks:
            return None
        if pref.get("mode") == "off":
            return "no"

        candidates = [t for t in tracks if isinstance(t, dict) and t.get("type") == track_type]
        if not candidates:
            return None

        target_lang = pref.get("lang")
        target_idx = pref.get("index")

        # 1. Match by normalized language if known
        if target_lang:
            norm_target = normalize_track_lang(target_lang)
            for cand in candidates:
                cand_lang = normalize_track_lang(cand.get("lang"))
                if cand_lang and cand_lang == norm_target:
                    return cand.get("id")

        # 2. Match by relative index
        if target_idx is not None and 0 <= target_idx < len(candidates):
            return candidates[target_idx].get("id")

        return candidates[0].get("id")

    def _apply_preserved_track_preferences(self, tracks: list[dict[str, Any]]) -> None:
        """Apply remembered audio and subtitle preferences to the newly loaded track list."""
        self._pending_track_resolution = False
        if not tracks:
            return

        if self._saved_audio_pref and self._saved_audio_pref.get("mode") != "auto":
            matched_aid = self._find_matching_track(tracks, "audio", self._saved_audio_pref)
            if matched_aid is not None:
                current_aid = self._properties.get("aid")
                if str(current_aid) != str(matched_aid):
                    logger.info("[MPV] Auto-selecting preserved audio track %s (pref=%s)", matched_aid, self._saved_audio_pref)
                    self.set_property("aid", matched_aid)

        if self._saved_sub_pref:
            if self._saved_sub_pref.get("mode") == "off":
                current_sid = self._properties.get("sid")
                if current_sid not in ("no", False, None):
                    logger.info("[MPV] Auto-disabling subtitles as preserved preference")
                    self.set_property("sid", "no")
            else:
                matched_sid = self._find_matching_track(tracks, "sub", self._saved_sub_pref)
                if matched_sid is not None:
                    current_sid = self._properties.get("sid")
                    if str(current_sid) != str(matched_sid):
                        logger.info("[MPV] Auto-selecting preserved subtitle track %s (pref=%s)", matched_sid, self._saved_sub_pref)
                        self.set_property("sid", matched_sid)

    def set_segments(self, segments, auto_skip=False):
        self._segment_payload = json.dumps({'path': self.media_url, 'segments': segments, 'auto': auto_skip})
        self.send_command(['script-message', 'cinema-segments', self._segment_payload])

    def set_auto_skip(self, enabled):
        if self._segment_payload:
            payload = json.loads(self._segment_payload)
            payload['auto'] = enabled
            self._segment_payload = json.dumps(payload)
        self.send_command(['script-message', 'cinema-auto-skip', 'yes' if enabled else 'no'])

    def set_seek_step(self, seconds: int) -> None:
        self._seek_step = seconds
        self.send_command(["script-message", "cinema-seek-step", str(seconds)])

    def apply_subtitle_settings(self, fields: set[str] | None = None) -> None:
        # Serialize startup and live updates, reading the latest saved preferences each time.
        with self._subtitle_lock:
            if not self.is_running:
                return
            settings = load_settings()["subtitle_settings"]
            for field, prop in (
                ("font", "sub-font"),
                ("font_size", "sub-font-size"),
                ("color", "sub-color"),
                ("border_size", "sub-border-size"),
                ("border_color", "sub-border-color"),
                ("shadow_offset", "sub-shadow-offset"),
                ("position", "sub-pos"),
                ("speed", "sub-speed"),
            ):
                if fields is None or field in fields:
                    self.send_command(["set_property", prop, settings[field]])

    def set_debug_mode(self, enabled: bool) -> None:
        self._debug_mode = bool(enabled)
        self.send_command(['script-message', 'cinema-debug-mode', 'yes' if enabled else 'no'])

    def configure_tracks(self, prefs, explicit_audio=None, explicit_sub=None):
        if self._tracks is None:
            self._tracks = TrackSelection(lambda command: self.send_command(command),
                                          save_track_preferences)
        self._tracks.configure(prefs, explicit_audio, explicit_sub)

    def manual_track_command(self, command):
        if self._tracks:
            self._tracks.manual_command(command)

    @property
    def is_embedded(self) -> bool:
        return self._wid is not None

    def get_pid(self) -> int | None:
        """Return PID of the running MPV process, if owned and alive."""
        if self.process is not None and self.process.poll() is None:
            return getattr(self.process, "pid", None)
        return None

    def is_owned(self) -> bool:
        """Check if the MPV process is owned by this controller instance."""
        if self.process is None:
            return False
        proc_pid = getattr(self.process, "pid", None)
        return proc_pid is not None and (self._owned_pid is None or proc_pid == self._owned_pid)

    def cancel_start(self) -> None:
        self._stop_requested.set()

    def _open_pipe(self, pipe_name: str) -> Any:
        if os.name == "nt":
            return WindowsPipe(pipe_name)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(pipe_name)
        except OSError:
            sock.close()
            raise
        return sock

    def configure_network(self, proxy, headers=None):
        self._network_proxy = proxy
        self._network_headers = headers or {}
        if self.is_running:
            self.send_command(["set_property", "http-proxy", proxy])
            self.send_command(["set_property", "http-header-fields", [f"{k}: {v}" for k, v in self._network_headers.items()]])

    def configure_sync(self, sub_delay: float, audio_delay: float) -> None:
        self._sync_delays = (sub_delay, audio_delay)

    def _spawn_and_connect(self, args: list[str], log_path: Path) -> Any:
        try:
            self.log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
            self.process = subprocess.Popen(
                args,
                stdout=self.log_file,
                stderr=subprocess.STDOUT,
                env=direct_process_env(system_process_env()),
            )
            self._owned_pid = getattr(self.process, "pid", None)
            logger.info("[MPV] Process started with PID %s", self.process.pid)
        except OSError:
            if self.log_file:
                self.log_file.close()
                self.log_file = None
            logger.exception("[MPV] Failed to start process")
            raise

        deadline = time.time() + config.MPV_PIPE_TIMEOUT
        connected_pipe = None

        while time.time() < deadline and not self._stop_requested.is_set():
            if self.process.poll() is not None:
                break
            try:
                connected_pipe = self._open_pipe(self.pipe_name)
                break
            except OSError:
                time.sleep(0.1)

        if self._stop_requested.is_set():
            if connected_pipe:
                connected_pipe.close()
            self.stop()
            raise RuntimeError("MPV launch cancelled")
        if not connected_pipe:
            if self.log_file:
                self.log_file.flush()
            details = ""
            try:
                with log_path.open("rb") as stream:
                    stream.seek(0, os.SEEK_END)
                    stream.seek(max(0, stream.tell() - 2048))
                    details = stream.read().decode("utf-8", errors="replace").strip()
            except OSError as e:
                details = str(e)
            self.stop()
            raise RuntimeError(f"Failed to connect to MPV IPC. Log: {log_path}\n{details}")
        return connected_pipe

    def _trigger_hwdec_fallback(self) -> None:
        """Switch hardware decoding to software decoding seamlessly via IPC without recreating the process."""
        self._hwdec_fallback_done = True
        self._hwdec_mode = "no"
        logger.info("[MPV] Applying runtime software decoding fallback via IPC: set_property hwdec no")
        self.send_command(["set_property", "hwdec", "no"])
        if self.media_url:
            last_pos = (
                self._properties.get("time-pos")
                or self._properties.get("playback-time")
                or getattr(self, "_current_start_time", 0)
            )
            start_pos = max(0, int(float(last_pos))) if last_pos is not None else 0
            logger.info("[MPV] Reloading %s at %ss in software decoding mode", self.media_url, start_pos)
            self.load_file(
                url=self.media_url,
                title=getattr(self, "_current_title", ""),
                start_time=start_pos,
                audio_track=getattr(self, "_current_audio_track", 0),
                subtitle_track=getattr(self, "_current_subtitle_track", 0),
            )

    def launch(
        self,
        mpv_path: str | Path,
        url: str,
        title: str,
        start_time: int = 0,
        audio_track: int = 0,
        subtitle_track: int = 0,
        wid: int | None = None,
        extra_options: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        if self.is_running or self.process is not None:
            self.stop()
        self._stop_requested.clear()
        self.last_error = None
        self._wid = wid
        self._hwdec_fallback_done = False
        lua_script = resolve_cinema_lua_path()
        custom_osd = (lua_script is not None and os.environ.get("CINEMA_MPV_OSC") != "legacy")
        self._custom_osd = custom_osd
        self._osd_ready = False

        if custom_osd:
            logger.info("[MPV] Custom OSD script located: %s", lua_script)
        else:
            logger.info(
                "[MPV] Standard OSC requested or cinema.lua missing (script=%s, CINEMA_MPV_OSC=%r)",
                lua_script,
                os.environ.get("CINEMA_MPV_OSC"),
            )

        pipe_id = str(uuid.uuid4())
        if os.name == "nt":
            self.pipe_name = f"\\\\.\\pipe\\mpv-ipc-{pipe_id}"
        else:
            self.pipe_name = f"/tmp/mpv-ipc-{pipe_id}"

        if wid is not None:
            base_args = [a for a in config.MPV_ARGS if a != "--fs" and not a.startswith("--msg-level=")]
            base_args.extend(
                [
                    f"--wid={wid}",
                    "--osc=no" if custom_osd else "--osc=yes",
                    "--input-cursor=yes",
                    "--input-default-bindings=yes",
                    "--input-vo-keyboard=no" if os.name == "nt" else "--input-vo-keyboard=yes",
                    "--window-dragging=no",
                    "--keepaspect=yes",
                    "--cursor-autohide=no" if custom_osd else "--cursor-autohide=1500",
                    "--cursor-autohide-fs-only=no",
                    "--msg-level=all=warn,cplayer=info,lua=warn,cinema=warn",
                    "--script-opts=osc-visibility=auto,osc-deadzonesize=0,osc-layout=bottombar,osc-boxalpha=80,osc-idlescreen=no,osc-windowcontrols=auto",
                ]
            )
            if os.name == "nt":
                base_args.append("--input-builtin-dragging=no")
            if sys.platform.startswith("linux"):
                base_args.append("--gpu-context=x11egl")
            if custom_osd:
                base_args.append(f"--script={lua_script}")
            args = [str(mpv_path), *base_args, f"--input-ipc-server={self.pipe_name}"]
        else:
            base_args = [a for a in config.MPV_ARGS if not a.startswith("--msg-level=")]
            base_args.append("--msg-level=all=warn,cplayer=info,lua=warn,cinema=warn")
            if sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
                base_args.append("--gpu-context=x11egl")
            args = [str(mpv_path), *base_args, f"--input-ipc-server={self.pipe_name}"]
            if custom_osd:
                args.extend(["--osc=no", f"--script={lua_script}"])
            else:
                args.append("--osc=yes")

        if custom_osd and lua_script is not None:
            if f"--script={lua_script}" not in args:
                args.append(f"--script={lua_script}")
            if wid is not None or sys.platform.startswith("linux"):
                args.append("--input-doubleclick-time=0")
            if sys.platform.startswith("linux"):
                # Keep script bindings enabled while excluding mpv's default actions and seek bar.
                args.extend(["--input-builtin-bindings=no", "--osd-bar=no"])
                font_dir = lua_script.with_name("osd-font")
                if (font_dir / "subfont.ttf").is_file():
                    # MPV 0.34 looks up subfont.ttf in its config directory. Use an
                    # app-owned directory and keep system font lookup for other glyphs.
                    args.extend(["--config=yes", f"--config-dir={font_dir}", "--osd-font=DejaVu Sans"])
                else:
                    logger.warning("[MPV] Bundled OSD font missing in %s; using system fonts", font_dir)

        if os.name == "nt":
            windows_args = list(config.MPV_WIN_EXTRA_ARGS)
            if wid is not None:
                # OpenGL's embedded fullscreen path can lose the native cursor.
                # Use the verified Windows renderer without changing decoding options.
                windows_args = [arg for arg in windows_args
                                if not arg.startswith(("--gpu-api=", "--gpu-context="))]
                windows_args.extend(["--gpu-api=d3d11", "--gpu-context=d3d11"])
            for warg in windows_args:
                if warg.startswith("--hwdec="):
                    args = [a for a in args if not a.startswith("--hwdec=")]
                args.append(warg)

        # Ensure optimal startup options if not already present
        if not any(a.startswith("--hwdec=") for a in args):
            args.append(f"--hwdec={config.MPV_HWDEC}")
        if not any(a.startswith("--demuxer-max-bytes=") for a in args):
            args.append(f"--demuxer-max-bytes={config.MPV_DEMUXER_MAX_BYTES}")
        if not any(a.startswith("--demuxer-readahead-secs=") for a in args):
            args.append(f"--demuxer-readahead-secs={config.MPV_DEMUXER_READAHEAD_SECS}")
        if not any(a.startswith("--tone-mapping=") for a in args):
            args.append("--tone-mapping=bt.2390")
        if not any(a.startswith("--hdr-compute-peak=") for a in args):
            args.append("--hdr-compute-peak=yes")

        if extra_options:
            for opt in extra_options:
                if opt.startswith("--hwdec="):
                    args = [a for a in args if not a.startswith("--hwdec=")]
                args.append(opt)

        args.append('--http-proxy=' + getattr(self, '_network_proxy', ''))
        if getattr(self, '_network_headers', None):
            args.append('--http-header-fields-clr')
            args.extend(f'--http-header-fields-append={key}: {value}'
                        for key, value in self._network_headers.items())

        hwdec_arg = next((a for a in args if a.startswith("--hwdec=")), "--hwdec=auto-safe")
        self._hwdec_mode = hwdec_arg.split("=", 1)[1] if "=" in hwdec_arg else "auto-safe"

        logger.info("[MPV] Launching player (hwdec=%s)", self._hwdec_mode)
        log_path = get_data_dir() / "mpv_debug.log"
        connected_pipe = None
        try:
            connected_pipe = self._spawn_and_connect(args, log_path)
        except (OSError, RuntimeError) as e:
            if not self._stop_requested.is_set() and self._hwdec_mode != "no":
                logger.warning(
                    "[MPV] Launch failed with hwdec=%s (%s). Retrying with software decoding fallback (--hwdec=no)",
                    self._hwdec_mode,
                    e,
                )
                self._stop_internal()
                self._stop_requested.clear()
                self._hwdec_mode = "no"
                self._hwdec_fallback_done = True
                fallback_args = [a for a in args if not a.startswith("--hwdec=")]
                fallback_args.append("--hwdec=no")
                connected_pipe = self._spawn_and_connect(fallback_args, log_path)
            else:
                raise

        self.pipe = connected_pipe
        self.is_running = True

        self.send_command(["observe_property", 1, "time-pos"])
        self.send_command(["observe_property", 2, "duration"])
        self.send_command(["observe_property", 3, "aid"])
        self.send_command(["observe_property", 4, "sid"])
        self.send_command(["observe_property", 5, "eof-reached"])
        self.send_command(["observe_property", 6, "fullscreen"])
        self.send_command(["observe_property", 7, "pause"])
        self.send_command(["observe_property", 8, "volume"])
        self.send_command(["observe_property", 9, "playback-time"])
        self.send_command(["observe_property", 10, "track-list"])
        self.send_command(["observe_property", 11, "mute"])
        self.send_command(["observe_property", 12, "paused-for-cache"])
        self.send_command(["observe_property", 13, "demuxer-cache-state"])
        self.send_command(["observe_property", 14, "file-format"])
        self.send_command(["observe_property", 15, "chapter-list"])
        self.send_command(["observe_property", 16, "sub-delay"])
        self.send_command(["observe_property", 17, "audio-delay"])
        self.send_command(["observe_property", 18, "hwdec-current"])
        self.send_command(["observe_property", 19, "video-format"])
        self.send_command(["observe_property", 20, "decoder-frame-drop-count"])
        self.send_command(["observe_property", 21, "frame-drop-count"])

        if self._tracks:
            # Capture the MPV profile's own language order before applying application preferences.
            self._default_languages.clear()
            self._managed_languages.clear()
            self._language_defaults_ready.clear()
            self.thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.thread.start()
            for request, prop in ((8001, "alang"), (8002, "slang")):
                self.send_command(["get_property", prop], request_id=request)
            options = self._tracks.options()
            if any(options[prop] for prop in ("alang", "slang")):
                self._language_defaults_ready.wait(0.2)
        if not self._tracks:
            self.thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.thread.start()
        self._verify_cache()
        self._detect_loadfile_signature()
        self.apply_subtitle_settings()
        self.load_file(url=url, title=title, start_time=start_time,
                       audio_track=audio_track, subtitle_track=subtitle_track)

        self._wid = wid
        if wid is not None and os.name == "nt":
            self._enable_mpv_mouse(wid)

    def _verify_cache(self):
        self._cache_properties = {}
        self._cache_ready = threading.Event()
        for index, prop in enumerate(('cache', 'cache-on-disk', 'demuxer-max-bytes', 'demuxer-max-back-bytes')):
            self.send_command(['get_property', 'options/' + prop], request_id=8100+index)
        if not self._cache_ready.wait(3) or not self._cache_policy_valid():
            self.stop()
            raise RuntimeError('MPV: не удалось подтвердить ограниченный RAM-only кеш')

    def _cache_policy_valid(self):
        props = self._cache_properties
        return (props.get(8100) in ('yes', True) and props.get(8101) is False
                and type(props.get(8102)) in (int, float) and 0 < props[8102] <= 128*1024*1024
                and type(props.get(8103)) in (int, float) and 0 < props[8103] <= 32*1024*1024)

    def _detect_loadfile_signature(self) -> None:
        self._loadfile_has_index = True
        self._loadfile_signature_ready.clear()
        self.send_command(["get_property", "command-list"], request_id=8104)
        self._loadfile_signature_ready.wait(1)

    def _enable_mpv_mouse(self, wid: int) -> None:
        if os.name != "nt":
            return

        def _worker():
            import ctypes
            try:
                user32 = ctypes.windll.user32
                user32.FindWindowExW.restype = ctypes.c_void_p
                user32.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
                for _ in range(60):
                    time.sleep(0.1)
                    if not self.is_running:
                        break
                    ch = user32.FindWindowExW(int(wid), None, "mpv", None)
                    if ch:
                        style = user32.GetWindowLongW(ch, -16)
                        if (style & 0x08000000) or not user32.IsWindowEnabled(ch):
                            user32.EnableWindow(ch, True)
                            user32.SetWindowLongW(ch, -16, style & ~0x08000000)
                            user32.SetWindowPos(ch, 0, 0, 0, 0, 0, 0x0027)
                            logger.info("[MPV] Enabled mouse input on child window %s", hex(ch))
            except Exception as e:
                logger.debug("[MPV] Error enabling child window mouse input: %s", e, exc_info=True)

        threading.Thread(target=_worker, daemon=True, name="EnableMpvMouse").start()

    def load_file(
        self,
        url: str,
        title: str,
        start_time: int = 0,
        audio_track: int = 0,
        subtitle_track: int = 0,
    ) -> None:
        self._current_title = title
        self._current_start_time = start_time
        self._current_audio_track = audio_track
        self._current_subtitle_track = subtitle_track
        self._pending_track_resolution = True
        if audio_track and audio_track not in (0, "0"):
            self._record_audio_preference(audio_track)
        if subtitle_track not in (0, "0", None):
            self._record_subtitle_preference(subtitle_track)
        self._stop_requested.clear()
        self.last_error = None
        self._segment_payload = None
        # Discard queued observations from the replaced file until its replacement
        # has loaded and an ordered IPC path response confirms the source.
        self._awaiting_media = True
        self._media_probe = getattr(self, '_media_probe', 100000) + 10
        self.media_url = url
        self.media_format = None
        if self._preview:
            self._preview.close()
            self._preview = None
        # Linux also runs cinema.lua in the standalone native MPV window.
        if getattr(self, '_custom_osd', self.is_embedded):
            self.send_command(["script-message", "cinema-preview-reset"])
            self._preview_cache_state = {}
            try:
                def publish(request_id, path, bucket=""):
                    self.send_command(["script-message", "cinema-preview-result", request_id, path, str(bucket)])
                self._preview = PreviewSession(url, publish)
                mode = "local" if (self._preview.source and not self._preview.is_stream) else ("stream" if self._preview.source else "disabled")
                self.send_command(["script-message", "cinema-preview-mode", mode])
            except (OSError, ValueError):
                pass
        opts = ["pause=no", f"start={start_time}"]
        sub_delay, audio_delay = getattr(self, '_sync_delays', (0.0, 0.0))
        opts.extend((f'sub-delay={sub_delay}', f'audio-delay={audio_delay}'))
        self.send_command(["set_property", "start", "none"])
        self.send_command(["set_property", "force-media-title", title])
        if self._tracks:
            options = self._tracks.options()
            # Language lists contain commas; set them separately from loadfile's option string.
            for prop in ("alang", "slang"):
                if options[prop]:
                    self._managed_languages.add(prop)
                    self.send_command(["set_property", prop, options[prop]])
                elif prop in self._managed_languages:
                    self.send_command(["set_property", prop, self._default_languages.get(prop, "")])
                    self._managed_languages.discard(prop)
            opts.extend(f"{prop}={options[prop]}" for prop in ("aid", "sid"))
        else:
            if audio_track:
                opts.append(f"aid={audio_track}")
                self.send_command(["set_property", "aid", audio_track])
            if subtitle_track:
                opts.append(f"sid={subtitle_track}")
                self.send_command(["set_property", "sid", subtitle_track])
        opts_str = ",".join(opts)

        command = ["loadfile", url, "replace"]
        if self._loadfile_has_index:
            command.append(-1)
        command.append(opts_str)
        self.send_command(command)
        self.send_command(["set_property", "pause", False])
        self.send_command(["script-message", "cinema-debug-mode", "yes" if self._debug_mode else "no"])
        self.set_seek_step(self._seek_step)
        if self._wid is not None and os.name == "nt":
            self._enable_mpv_mouse(self._wid)

    def send_command(self, command: list[Any], request_id: int | None = None) -> None:
        if not self.pipe or not self.is_running:
            return

        message = {"command": command}
        if request_id is not None:
            message["request_id"] = request_id
            message["async"] = True
        payload = (json.dumps(message) + "\n").encode("utf-8")
        try:
            with self._lock:
                pipe = self.pipe
                if not pipe or not self.is_running:
                    return
                if os.name == "nt":
                    pipe.write(payload)
                    pipe.flush()
                else:
                    pipe.sendall(payload)
        except OSError as e:
            logger.error("[MPV] Failed command %s (%s)", command[0] if command else "unknown", type(e).__name__)
            self.last_error = f"Ошибка IPC MPV: {e}"
            with suppress(OSError):
                if os.name != 'nt' and isinstance(self.pipe, socket.socket):
                    self.pipe.shutdown(socket.SHUT_RDWR)
                if self.pipe:
                    self.pipe.close()  # Wake the reader; it classifies and handles the failure once.

    def _reader_loop(self) -> None:
        logger.info("[MPV] Reader loop started.")
        f = self.pipe if os.name == "nt" else self.pipe.makefile("rb")
        terminal_event = False
        shutdown_seen = False

        try:
            while self.is_running:
                line = f.readline()
                if not line:
                    break

                try:
                    data = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                cache_id = data.get('request_id')
                if isinstance(cache_id, int) and 8100 <= cache_id <= 8103:
                    if data.get('error') == 'success':
                        self._cache_properties[cache_id] = data.get('data')
                    else:
                        self._cache_properties[cache_id] = None
                    if len(self._cache_properties) == 4:
                        self._cache_ready.set()
                    continue

                if cache_id == 8104:
                    commands = data.get("data")
                    if data.get("error") == "success" and isinstance(commands, list):
                        for command in commands:
                            if command.get("name") == "loadfile":
                                self._loadfile_has_index = any(
                                    arg.get("name") == "index" for arg in command.get("args", [])
                                )
                                break
                    self._loadfile_signature_ready.set()
                    continue

                if data.get("request_id") in (8001, 8002):
                    prop = "alang" if data["request_id"] == 8001 else "slang"
                    value = data.get("data", "")
                    self._default_languages[prop] = ",".join(str(code) for code in value) if isinstance(value, list) else str(value or "")
                    if len(self._default_languages) == 2:
                        self._language_defaults_ready.set()
                    continue

                probe = getattr(self, '_media_probe', -100)
                if data.get('request_id') == probe:
                    if data.get('error') == 'success' and data.get('data') == self.media_url:
                        self._awaiting_media = False
                        for offset, name in enumerate(('duration', 'time-pos'), 1):
                            self.send_command(['get_property', name], request_id=probe+offset)
                    continue
                if data.get('request_id') in (probe+1, probe+2) and not getattr(self, '_awaiting_media', False):
                    if data.get('error') == 'success':
                        val = data.get('data')
                        if data['request_id'] == probe + 1 and self._preview and isinstance(val, (int, float)) and val > 0:
                            self._preview.set_duration(float(val))
                        if self.on_progress:
                            self.on_progress('duration' if data['request_id'] == probe+1 else 'time-pos', val)
                    continue

                if "event" in data:
                    event_type = data["event"]
                    if event_type == 'file-loaded' and getattr(self, '_awaiting_media', False):
                        self.send_command(['get_property', 'path'], request_id=self._media_probe)
                    if getattr(self, '_awaiting_media', False) and (event_type == 'property-change' or
                            (event_type == 'end-file' and data.get('reason') not in ('error', 'quit'))):
                        continue
                    if event_type == 'client-message' and data.get('args') == ['cinema-segments-request']:
                        if self._segment_payload:
                            self.send_command(['script-message', 'cinema-segments', self._segment_payload])
                        self.send_command(['script-message', 'cinema-debug-mode', 'yes' if self._debug_mode else 'no'])
                        self.set_seek_step(self._seek_step)
                        continue
                    if self._tracks:
                        if event_type in ("start-file", "file-loaded", "end-file"):
                            self._tracks.event(event_type)
                        elif event_type == "property-change" and data.get("name") in ("track-list", "aid", "sid"):
                            self._tracks.event(data["name"], data.get("data"))
                    if event_type == "log-message":
                        level = data.get("level", "")
                        prefix = data.get("prefix", "")
                        text = data.get("text", "")
                        if level in ("error", "fatal") or (level == "warn" and prefix in ("ffmpeg", "hwdec", "vo/gpu")):
                            text_lower = text.lower()
                            if any(phrase in text_lower for phrase in (
                                "hardware decoding failed",
                                "failed to initialize a hardware decoder",
                                "could not create hw device",
                                "failed to create direct3d11 device",
                                "error opening hwdec",
                            )):
                                logger.warning("[MPV] Detected hardware decoding failure from %s: %s", prefix, text.strip())
                                if not self._hwdec_fallback_done and getattr(self, "_hwdec_mode", "auto-safe") != "no":
                                    self._trigger_hwdec_fallback()
                                    continue
                    if event_type == "shutdown":
                        shutdown_seen = True
                    if event_type in ("start-file", "end-file"):
                        self._preview_cache_state = {}
                        if event_type == "start-file":
                            self._osd_ready = False
                    if event_type == "property-change" and data.get("name") == "demuxer-cache-state":
                        state = data.get("data")
                        self._preview_cache_state = state if isinstance(state, dict) else {}
                        if self._preview:
                            self._preview.update_cache_state(self._preview_cache_state)
                    if event_type == "property-change" and data.get("name") == "duration":
                        dur = data.get("data")
                        if self._preview and isinstance(dur, (int, float)) and dur > 0:
                            self._preview.set_duration(float(dur))
                    if event_type == "client-message":
                        args = data.get("args", [])
                        if args and args[0] == "cinema-osd-ready":
                            if self._custom_osd and len(args) == 4:
                                self._osd_ready = True
                                logger.info("[MPV] Cinema OSD rendered at %sx%s with %s", *args[1:])
                            continue
                        if args and args[0] == "cinema-preview":
                            if self._preview:
                                if len(args) == 3:
                                    self._preview.request(args[1], args[2])
                                elif len(args) == 1:
                                    self._preview.cancel()
                            continue
                        if len(args) == 2 and args[0] == "cinema-action" and self.on_progress:
                            try:
                                command = json.loads(args[1])
                            except (TypeError, ValueError):
                                logger.warning("Invalid cinema OSD action")
                            else:
                                if isinstance(command, list) and command:
                                    try:
                                        self.on_progress("cinema-action", command)
                                    except Exception:
                                        logger.exception("Cinema OSD action callback failed")
                        continue
                    if event_type == "property-change" and "name" in data:
                        p_name = data["name"]
                        p_data = data.get("data")
                        self._properties[p_name] = p_data
                        if p_name == "aid" and p_data is not None:
                            self._record_audio_preference(p_data)
                        elif p_name == "sid" and p_data is not None:
                            self._record_subtitle_preference(p_data)
                        elif p_name == "track-list" and isinstance(p_data, list):
                            if self._pending_track_resolution:
                                self._apply_preserved_track_preferences(p_data)
                            else:
                                cur_aid = self._properties.get("aid")
                                if cur_aid is not None:
                                    self._record_audio_preference(cur_aid)
                                cur_sid = self._properties.get("sid")
                                if cur_sid is not None:
                                    self._record_subtitle_preference(cur_sid)
                    if event_type == "property-change" and data.get("name") == "file-format":
                        self.media_format = data.get("data")
                    if (
                        event_type == "property-change"
                        and data.get("name")
                        in (
                            "time-pos",
                            "duration",
                            "aid",
                            "sid",
                            "eof-reached",
                            "fullscreen",
                            "pause",
                            "volume",
                            "playback-time",
                            "track-list",
                            "chapter-list",
                            "sub-delay",
                            "audio-delay",
                            "mute",
                            "paused-for-cache",
                            "hwdec-current",
                            "video-format",
                            "decoder-frame-drop-count",
                            "frame-drop-count",
                        )
                        and self.on_progress
                    ):
                        try:
                            self.on_progress(data["name"], data.get("data"))
                        except Exception:
                            logger.exception(
                                "[MPV] Error in on_progress handler (%s=%s)",
                                data.get("name"),
                                data.get("data"),
                            )

                    elif event_type == "end-file":
                        if self._preview:
                            self._preview.cancel()
                        reason = data.get("reason")
                        if (
                            reason == "error"
                            and not self._hwdec_fallback_done
                            and getattr(self, "_hwdec_mode", "auto-safe") != "no"
                        ):
                            logger.warning(
                                "[MPV] File playback aborted with reason 'error' while hwdec was active; falling back to software decoding (hwdec=no)"
                            )
                            self._trigger_hwdec_fallback()
                            continue

                        terminal_event = reason in ("quit", "error")
                        if self.on_end:
                            try:
                                self.on_end(reason)
                            except Exception:
                                logger.exception("[MPV] Error in on_end handler")

        except (OSError, ValueError) as e:
            if self.is_running:
                logger.warning("[MPV] Reader loop IPC I/O error: %s", e)
        finally:
            logger.info("[MPV] Reader loop exiting.")
            if os.name != "nt" and f is not self.pipe:
                with suppress(OSError):
                    f.close()

            if self.on_progress:
                with suppress(Exception):
                    self.on_progress("flush", True)

            if not terminal_event and self.on_end and self.is_running and not self._stop_requested.is_set():
                reason = "quit" if shutdown_seen else "ipc_lost"
                if self.process and not shutdown_seen:
                    code = self.process.poll()
                    if code is None:
                        with suppress(subprocess.TimeoutExpired, OSError):
                            code = self.process.wait(timeout=0.2)
                    if code is not None:
                        reason = "quit" if code == 0 else "crash"
                        if code != 0:
                            self.last_error = f"MPV неожиданно завершился с кодом {code}"
                with suppress(Exception):
                    self.on_end(reason)

            # Корректно останавливаем контроллер, если вышли из цикла
            if self.is_running and not self._stop_requested.is_set():
                self.stop()

    def stop(self) -> Any:
        self._stop_internal()
        return _StopAwaitable(self)

    def _stop_internal(self) -> None:
        if self._tracks:
            self._tracks.event("end-file")
        self._stop_requested.set()
        pipe = self.pipe
        # Unblock a writer before waiting for the command lock it owns.
        if os.name == 'nt' and isinstance(pipe, WindowsPipe):
            pipe.cancel_pending()
        elif isinstance(pipe, socket.socket):
            with suppress(OSError):
                pipe.shutdown(socket.SHUT_RDWR)
        if self._preview:
            self._preview.close()
            self._preview = None
        with self._lock:
            if not self.is_running and not self.process:
                return
            self.is_running = False

        logger.info("[MPV] Stopping MPV Controller...")

        # 1. Закрываем IPC соединение
        if self.pipe:
            with suppress(OSError):
                self.pipe.close()
            self.pipe = None

        # 2. Завершаем процесс MPV
        proc = self.process
        owned_pid = self._owned_pid
        self.process = None
        self._owned_pid = None

        if proc:
            proc_pid = getattr(proc, "pid", None)
            if owned_pid is not None and proc_pid is not None and proc_pid != owned_pid:
                logger.warning(
                    "[MPV] Process PID mismatch (%s != %s); skipping termination to protect unowned process",
                    proc_pid,
                    owned_pid,
                )
            elif proc.poll() is None:
                with suppress(ProcessLookupError, OSError, subprocess.SubprocessError):
                    logger.info("[MPV] Gracefully stopping MPV process (PID %s)...", proc_pid)
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        logger.warning(
                            "[MPV] MPV process PID %s did not terminate within timeout; killing (SIGKILL)...",
                            proc_pid,
                        )
                        proc.kill()
                        with suppress(subprocess.TimeoutExpired):
                            proc.wait(timeout=2.0)

        # 3. Удаляем сокет-файл (Linux/macOS)
        if os.name != "nt" and self.pipe_name and os.path.exists(self.pipe_name):
            with suppress(OSError):
                os.remove(self.pipe_name)

        # 4. Закрываем log-файл
        if self.log_file:
            with suppress(OSError):
                self.log_file.close()
            self.log_file = None

        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)
        self.thread = None

        logger.info("[MPV] Controller stopped.")
