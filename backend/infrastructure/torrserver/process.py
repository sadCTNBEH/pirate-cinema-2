"""TorrServer process manager – mirrors torrserver_process.rs."""

import json
import logging
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib import error, request

from backend.core.settings import BASE_DIR, config, get_data_dir

logger = logging.getLogger(__name__)

_process: subprocess.Popen | None = None


def _probe(url: str = config.TORRSERVER_DEFAULT_URL) -> bool:
    try:
        request.urlopen(f"{url.rstrip('/')}/echo", timeout=4)
        return True
    except (error.URLError, error.HTTPError):
        return False


def bundled_executable() -> Path:
    binary_name = "torrserver.exe" if sys.platform == "win32" else "torrserver"

    # 1. Сначала проверяем директорию пользовательских данных (куда скачиваются вендорные бинарники)
    app_data_vendor = get_data_dir() / "vendor" / "torrserver" / binary_name
    if app_data_vendor.is_file():
        return app_data_vendor

    # 2. Фолбэк на исходную папку проекта (BASE_DIR)
    return BASE_DIR / "vendor" / "torrserver" / binary_name


def default_data_dir() -> Path:
    return get_data_dir() / "torrserver"


def connect_or_start(
    url: str = config.TORRSERVER_DEFAULT_URL,
    executable: Path | None = None,
    data_dir: Path | None = None,
) -> bool:
    """Returns True if TorrServer is ready. Raises on unrecoverable error."""
    global _process

    if _probe(url):
        return True

    if url.rstrip("/") != config.TORRSERVER_DEFAULT_URL.rstrip("/"):
        raise RuntimeError(
            f"Custom TorrServer endpoint not responding; auto-start only on {config.TORRSERVER_DEFAULT_URL}"
        )

    # Check port availability
    try:
        s = socket.socket()
        s.bind((config.APP_HOST, config.TORRSERVER_PORT))
        s.close()
    except OSError:
        raise RuntimeError(
            f"Port {config.TORRSERVER_PORT} is occupied but TorrServer isn't responding. Check existing services."
        )

    executable = executable or bundled_executable()
    if not executable.is_file():
        raise RuntimeError(f"TorrServer binary not found: {executable}")

    data_dir = data_dir or default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    kwargs: dict = {
        "cwd": str(data_dir),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x0800_0000  # CREATE_NO_WINDOW

    _process = subprocess.Popen([str(executable)], **kwargs)

    deadline = time.time() + config.TORRSERVER_START_TIMEOUT
    while time.time() < deadline:
        if _probe(url):
            try:
                _optimize_settings(url)
            except (error.URLError, error.HTTPError, json.JSONDecodeError) as e:
                logger.warning("Failed to optimize TorrServer: %s", e)
            return True
        if _process.poll() is not None:
            raise RuntimeError(
                f"TorrServer exited with code {_process.returncode}"
            )
        time.sleep(0.3)

    _process.kill()
    raise RuntimeError(
        f"TorrServer did not become ready in {config.TORRSERVER_START_TIMEOUT}s"
    )


def stop():
    global _process
    if _process and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.kill()
    _process = None


def _optimize_settings(url: str):
    req = request.Request(
        f"{url.rstrip('/')}/settings",
        data=json.dumps({"action": "get"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=config.TORRSERVER_HTTP_TIMEOUT) as res:
        settings = json.loads(res.read())

    changed = False
    if settings.get("ConnectionsLimit", 0) < config.TORRSERVER_CONNECTIONS_LIMIT:
        settings["ConnectionsLimit"] = config.TORRSERVER_CONNECTIONS_LIMIT
        changed = True
    if settings.get("DisableUTP") is True:
        settings["DisableUTP"] = False
        changed = True

    if changed:
        req_set = request.Request(
            f"{url.rstrip('/')}/settings",
            data=json.dumps({"action": "set", "sets": settings}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req_set, timeout=config.TORRSERVER_HTTP_TIMEOUT):
            pass
