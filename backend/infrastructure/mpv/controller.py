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


class MPVController:
    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.pipe: Any = None
        self.pipe_name: str | None = None
        self.thread: threading.Thread | None = None

        self.on_progress: Callable[[str, Any], None] | None = None
        self.on_end: Callable[[str | None], None] | None = None

        self.is_running = False
        self.log_file: Any = None
        self._lock = threading.Lock()

    def launch(
            self,
            mpv_path: str | Path,
            url: str,
            title: str,
            start_time: int = 0,
            audio_track: int = 0,
    ) -> None:
        if self.is_running:
            self.stop()

        pipe_id = str(uuid.uuid4())
        if os.name == "nt":
            self.pipe_name = f"\\\\.\\pipe\\mpv-ipc-{pipe_id}"
        else:
            self.pipe_name = f"/tmp/mpv-ipc-{pipe_id}"

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
                if os.name == "nt":
                    connected_pipe = open(self.pipe_name, "r+b", buffering=0)  # noqa: SIM115
                else:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.connect(self.pipe_name)
                    connected_pipe = sock
                break
            except OSError:
                time.sleep(0.1)

        if not connected_pipe:
            self.stop()
            raise RuntimeError("Failed to connect to MPV IPC pipe")

        self.pipe = connected_pipe
        self.is_running = True

        # Начальные свойства и команда загрузки файла
        self.send_command(["set_property", "start", str(start_time)])
        self.send_command(["set_property", "force-media-title", title])
        if audio_track:
            self.send_command(["set_property", "aid", audio_track])

        self.send_command(["observe_property", 1, "time-pos"])
        self.send_command(["observe_property", 2, "duration"])
        self.send_command(["observe_property", 3, "aid"])
        self.send_command(["loadfile", url, "replace"])

        # Запуск фонового потока чтения событий
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()

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
                            and data.get("name") in ("time-pos", "duration", "aid")
                            and self.on_progress
                    ):
                        self.on_progress(data["name"], data.get("data"))

                    elif event_type == "end-file" and self.on_end:
                        self.on_end(data.get("reason"))

        except (OSError, ValueError) as e:
            if self.is_running:
                logger.warning("[MPV] Reader loop IPC I/O error: %s", e)
        finally:
            logger.info("[MPV] Reader loop exiting.")
            if os.name != "nt" and f is not self.pipe:
                with suppress(OSError):
                    f.close()

            if self.on_progress:
                self.on_progress("flush", True)

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
                    self.process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.process = None

        # 3. Удаляем сокет-файл (Linux/macOS)
        if (
                os.name != "nt"
                and self.pipe_name
                and os.path.exists(self.pipe_name)
        ):
            with suppress(OSError):
                os.remove(self.pipe_name)

        # 4. Закрываем log-файл
        if self.log_file:
            with suppress(OSError):
                self.log_file.close()
            self.log_file = None

        logger.info("[MPV] Controller stopped.")
