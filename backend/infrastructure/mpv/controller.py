import json
import logging
import os
import socket
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from backend.core.settings import config, get_data_dir
from backend.core.settings.user import save_track_preferences
from backend.infrastructure.mpv.preview import (
    EXCERPT_BYTES,
    PreviewSession,
    StreamPreviewSession,
    buffered_range,
)
from backend.infrastructure.mpv.tracks import TrackSelection
from backend.infrastructure.process_env import system_process_env

logger = logging.getLogger("mpv")
logger.setLevel(logging.DEBUG)
PROGRESSCALLBACK = Callable[[str, Any], None]
ENDCALLBACK = Callable[[str | None], None]


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


class MPVController:
    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.pipe: Any = None
        self.pipe_name: str | None = None
        self.thread: threading.Thread | None = None

        self.on_progress: PROGRESSCALLBACK | None = None
        self.on_end: ENDCALLBACK | None = None

        self.is_running = False
        self.log_file: Any = None
        self._lock = threading.Lock()
        self._wid: int | None = None
        self._stop_requested = threading.Event()
        self.last_error: str | None = None
        self._preview: PreviewSession | None = None
        self._preview_cache_state: dict = {}
        self._preview_export_slow = False
        self._preview_buffering = False
        self._preview_request_id = 100000
        self._preview_exports: dict[int, tuple[threading.Event, list[bool], Path]] = {}
        self._tracks: TrackSelection | None = None
        self._default_languages = {}
        self._managed_languages = set()
        self._language_defaults_ready = threading.Event()

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

    def launch(
        self,
        mpv_path: str | Path,
        url: str,
        title: str,
        start_time: int = 0,
        audio_track: int = 0,
        subtitle_track: int = 0,
        wid: int | None = None,
    ) -> None:
        if self.is_running:
            self.stop()
        self._stop_requested.clear()
        self.last_error = None
        self._wid = wid

        pipe_id = str(uuid.uuid4())
        if os.name == "nt":
            self.pipe_name = f"\\\\.\\pipe\\mpv-ipc-{pipe_id}"
        else:
            self.pipe_name = f"/tmp/mpv-ipc-{pipe_id}"

        if wid is not None:
            script = Path(__file__).with_name("cinema.lua")
            custom_osd = script.is_file() and os.environ.get("CINEMA_MPV_OSC") != "legacy"
            base_args = [a for a in config.MPV_ARGS if a != "--fs"]
            base_args.extend(
                [
                    f"--wid={wid}",
                    "--osc=no" if custom_osd else "--osc=yes",
                    "--input-cursor=yes",
                    "--input-default-bindings=yes",
                    "--input-vo-keyboard=no",
                    "--input-builtin-dragging=no",
                    "--window-dragging=no",
                    "--keepaspect=yes",
                    "--cursor-autohide=no" if custom_osd else "--cursor-autohide=1500",
                    "--cursor-autohide-fs-only=no",
                    "--script-opts=osc-visibility=auto,osc-deadzonesize=0,osc-layout=bottombar,osc-boxalpha=80,osc-idlescreen=no,osc-windowcontrols=auto",
                ]
            )
            if custom_osd:
                base_args.append(f"--script={script}")
                base_args.append("--msg-level=cinema=warn")
                base_args.append("--input-doubleclick-time=0")
            args = [str(mpv_path), *base_args, f"--input-ipc-server={self.pipe_name}"]
        else:
            args = [str(mpv_path), *config.MPV_ARGS, f"--input-ipc-server={self.pipe_name}"]

        if os.name == "nt":
            windows_args = list(config.MPV_WIN_EXTRA_ARGS)
            if wid is not None:
                # OpenGL's embedded fullscreen path can lose the native cursor.
                # Use the verified Windows renderer without changing decoding options.
                windows_args = [arg for arg in windows_args
                                if not arg.startswith(("--gpu-api=", "--gpu-context="))]
                windows_args.extend(["--gpu-api=d3d11", "--gpu-context=d3d11"])
            args.extend(windows_args)

        logger.info("[MPV] Launching with args: %s", args)
        try:
            log_path = get_data_dir() / "mpv_debug.log"
            self.log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
            self.process = subprocess.Popen(
                args,
                stdout=self.log_file,
                stderr=subprocess.STDOUT,
                env=system_process_env(),
            )
            logger.info("[MPV] Process started with PID %s", self.process.pid)
        except OSError:
            if self.log_file:
                self.log_file.close()
                self.log_file = None
            logger.exception("[MPV] Failed to start process")
            raise

        # Подключение к IPC пайпу
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
            self.log_file.flush()
            try:
                with log_path.open("rb") as stream:
                    stream.seek(0, os.SEEK_END)
                    stream.seek(max(0, stream.tell() - 2048))
                    details = stream.read().decode("utf-8", errors="replace").strip()
            except OSError as e:
                details = str(e)
            self.stop()
            raise RuntimeError(f"Failed to connect to MPV IPC. Log: {log_path}\n{details}")

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
        self.load_file(url=url, title=title, start_time=start_time,
                       audio_track=audio_track, subtitle_track=subtitle_track)
        if not self._tracks:
            self.thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.thread.start()

        self._wid = wid
        if wid is not None and os.name == "nt":
            self._enable_mpv_mouse(wid)

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
        self.media_url = url
        self.media_format = None
        if self._preview:
            self._preview.close()
            self._preview = None
        if self.is_embedded:
            self.send_command(["script-message", "cinema-preview-reset"])
            self._preview_cache_state = {}
            self._preview_export_slow = False
            self._preview_buffering = False
            try:
                def publish(request_id, path):
                    self.send_command(["script-message", "cinema-preview-result", request_id, path])
                self._preview = PreviewSession(url, publish)
                if self._preview.source is None and url.startswith(("http://", "https://")):
                    self._preview = StreamPreviewSession(url, publish, self._export_preview, lambda: self._preview_cache_state)
                self.send_command(["script-message", "cinema-preview-mode",
                                   "stream" if isinstance(self._preview, StreamPreviewSession) else "local"])
            except (OSError, ValueError):
                pass
        opts = ["pause=no", f"start={start_time}"]
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

        self.send_command(["loadfile", url, "replace", -1, opts_str])
        self.send_command(["set_property", "pause", False])
        if self._wid is not None and os.name == "nt":
            self._enable_mpv_mouse(self._wid)

    def _export_preview(self, path: Path, position: float, cancelled) -> bool:
        region = buffered_range(self._preview_cache_state, position)
        if (not region or self._preview_buffering or self._preview_export_slow
                or not self.is_running or self._preview_exports or cancelled()):
            return False
        # Export one keyframe region only. A finite end never records future packets.
        end = min(position + 0.25, region[1] - 0.01)
        self._preview_request_id += 1
        request_id = self._preview_request_id
        ready, result = threading.Event(), []
        self._preview_exports[request_id] = (ready, result, path)
        started = time.monotonic()
        try:
            self.send_command(["dump-cache", position, end, str(path)], request_id=request_id)
            while not ready.wait(0.02):
                too_large = path.is_file() and path.stat().st_size > EXCERPT_BYTES
                if (cancelled() or self._stop_requested.is_set() or too_large
                        or time.monotonic() - started > 2):
                    if too_large or time.monotonic() - started > 2:
                        self._preview_export_slow = True
                    if self.is_running and not self._stop_requested.is_set():
                        self.send_command(["dump-cache", "no", "no", ""])
                    return False
            # Discontinue expensive exports for this film rather than repeatedly
            # contending with playback on an unusually long/high-bitrate GOP.
            if time.monotonic() - started > 1:
                self._preview_export_slow = True
            return result == [True] and not cancelled()
        finally:
            if ready.is_set():
                self._preview_exports.pop(request_id, None)
            else:
                # Remove a late file only after MPV has finished writing it.
                result.append(False)

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
            logger.error("[MPV] Failed to send command %s: %s", command, e)
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

                if data.get("request_id") in (8001, 8002):
                    prop = "alang" if data["request_id"] == 8001 else "slang"
                    value = data.get("data", "")
                    self._default_languages[prop] = ",".join(str(code) for code in value) if isinstance(value, list) else str(value or "")
                    if len(self._default_languages) == 2:
                        self._language_defaults_ready.set()
                    continue

                capture = self._preview_exports.get(data.get("request_id"))
                if capture:
                    ready, result, path = capture
                    if result:
                        with suppress(OSError):
                            path.unlink(missing_ok=True)
                        self._preview_exports.pop(data["request_id"], None)
                    else:
                        result.append(data.get("error") == "success")
                        ready.set()

                if "event" in data:
                    event_type = data["event"]
                    if self._tracks:
                        if event_type in ("start-file", "file-loaded", "end-file"):
                            self._tracks.event(event_type)
                        elif event_type == "property-change" and data.get("name") in ("track-list", "aid", "sid"):
                            self._tracks.event(data["name"], data.get("data"))
                    if event_type == "shutdown":
                        shutdown_seen = True
                    if event_type in ("start-file", "end-file"):
                        self._preview_cache_state = {}
                    if event_type == "property-change":
                        if data.get("name") == "demuxer-cache-state":
                            state = data.get("data")
                            self._preview_cache_state = state if isinstance(state, dict) else {}
                        elif data.get("name") == "paused-for-cache":
                            self._preview_buffering = bool(data.get("data"))
                    if event_type == "client-message":
                        args = data.get("args", [])
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
                            "mute",
                            "paused-for-cache",
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

                    elif event_type == "end-file" and self.on_end:
                        if self._preview:
                            self._preview.cancel()
                        terminal_event = data.get("reason") in ("quit", "error")
                        try:
                            self.on_end(data.get("reason"))
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

    def stop(self) -> None:
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
        if self.process:
            with suppress(OSError):
                self.process.terminate()
                try:
                    self.process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            self.process = None

        for ready, result, path in list(self._preview_exports.values()):
            result.append(False)
            ready.set()
            with suppress(OSError):
                path.unlink(missing_ok=True)
        self._preview_exports.clear()

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
