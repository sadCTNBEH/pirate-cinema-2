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
            self._write_lock = threading.Lock()
            self._read_lock = threading.Lock()
            self._close_lock = threading.Lock()
            if not self._read_ov.hEvent or not self._write_ov.hEvent:
                self.close()
                raise OSError("Failed to create MPV IPC events")

        def write(self, data: bytes) -> None:
            with self._write_lock:
                if self._closed:
                    return
                written = wintypes.DWORD()
                self.k32.ResetEvent(self._write_ov.hEvent)
                ret = self.k32.WriteFile(
                    self.handle, data, len(data), ctypes.byref(written), ctypes.byref(self._write_ov)
                )
                if not ret:
                    err = ctypes.get_last_error()
                    if err == 997:  # ERROR_IO_PENDING
                        completed = self.k32.GetOverlappedResult(
                            self.handle, ctypes.byref(self._write_ov), ctypes.byref(written), True
                        )
                        if not completed and not self._closed:
                            raise ctypes.WinError(ctypes.get_last_error())
                    else:
                        raise OSError(f"WriteFile failed with error {err}")

        def flush(self) -> None:
            pass

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
                    break
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

    def _open_pipe(self, pipe_name: str) -> Any:
        if os.name == "nt":
            return WindowsPipe(pipe_name)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(pipe_name)
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

        pipe_id = str(uuid.uuid4())
        if os.name == "nt":
            self.pipe_name = f"\\\\.\\pipe\\mpv-ipc-{pipe_id}"
        else:
            self.pipe_name = f"/tmp/mpv-ipc-{pipe_id}"

        if wid is not None:
            base_args = [a for a in config.MPV_ARGS if a != "--fs"]
            base_args.extend(
                [
                    f"--wid={wid}",
                    "--osc=yes",
                    "--input-cursor=yes",
                    "--input-default-bindings=yes",
                    "--input-vo-keyboard=yes",
                    "--keepaspect=yes",
                    "--cursor-autohide=1500",
                    "--cursor-autohide-fs-only=no",
                    "--script-opts=osc-visibility=auto,osc-deadzonesize=0,osc-layout=bottombar,osc-boxalpha=80,osc-idlescreen=no,osc-windowcontrols=auto",
                ]
            )
            args = [str(mpv_path), *base_args, f"--input-ipc-server={self.pipe_name}"]
        else:
            args = [str(mpv_path), *config.MPV_ARGS, f"--input-ipc-server={self.pipe_name}"]

        if os.name == "nt":
            args.extend(config.MPV_WIN_EXTRA_ARGS)

        logger.info("[MPV] Launching with args: %s", args)
        try:
            log_path = get_data_dir() / "mpv_debug.log"
            self.log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
            self.process = subprocess.Popen(
                args,
                stdout=self.log_file,
                stderr=subprocess.STDOUT,
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

        while time.time() < deadline:
            try:
                connected_pipe = self._open_pipe(self.pipe_name)
                break
            except OSError:
                time.sleep(0.1)

        if not connected_pipe:
            self.stop()
            raise RuntimeError("Failed to connect to MPV IPC pipe")

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

        self.load_file(
            url=url,
            title=title,
            start_time=start_time,
            audio_track=audio_track,
            subtitle_track=subtitle_track,
        )

        # Запуск фонового потока чтения событий
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
        opts = ["pause=no", f"start={start_time}"]
        if audio_track:
            opts.append(f"aid={audio_track}")
        if subtitle_track:
            opts.append(f"sid={subtitle_track}")
        opts_str = ",".join(opts)

        self.send_command(["set_property", "start", "none"])
        self.send_command(["set_property", "force-media-title", title])
        if audio_track:
            self.send_command(["set_property", "aid", audio_track])
        if subtitle_track:
            self.send_command(["set_property", "sid", subtitle_track])
        self.send_command(["loadfile", url, "replace", -1, opts_str])
        self.send_command(["set_property", "pause", False])
        if self._wid is not None and os.name == "nt":
            self._enable_mpv_mouse(self._wid)

    def send_command(self, command: list[Any]) -> None:
        if not self.pipe or not self.is_running:
            return

        payload = (json.dumps({"command": command}) + "\n").encode("utf-8")
        try:
            with self._lock:
                if os.name == "nt":
                    self.pipe.write(payload)
                    self.pipe.flush()
                else:
                    self.pipe.sendall(payload)
        except OSError as e:
            logger.error("[MPV] Failed to send command %s: %s", command, e)

    def _reader_loop(self) -> None:
        logger.info("[MPV] Reader loop started.")
        f = self.pipe if os.name == "nt" else self.pipe.makefile("rb")
        end_file_called = False

        try:
            while self.is_running:
                line = f.readline()
                if not line:
                    break

                try:
                    data = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                if "event" in data:
                    event_type = data["event"]
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
                        end_file_called = True
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

            if not end_file_called and self.on_end and self.is_running:
                with suppress(Exception):
                    self.on_end("quit")

            # Корректно останавливаем контроллер, если вышли из цикла
            if self.is_running:
                self.stop()

    def stop(self) -> None:
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
            self.process = None

        # 3. Удаляем сокет-файл (Linux/macOS)
        if os.name != "nt" and self.pipe_name and os.path.exists(self.pipe_name):
            with suppress(OSError):
                os.remove(self.pipe_name)

        # 4. Закрываем log-файл
        if self.log_file:
            with suppress(OSError):
                self.log_file.close()
            self.log_file = None

        logger.info("[MPV] Controller stopped.")
