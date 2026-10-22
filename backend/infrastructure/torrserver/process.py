"""TorrServer process manager – mirrors torrserver_process.rs."""

import json
import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from backend.core.settings import BASE_DIR, config, get_data_dir

logger = logging.getLogger(__name__)

_process: subprocess.Popen | None = None
_last_error: str | None = None


def is_running() -> bool:
    return _process is not None and _process.poll() is None


def get_pid() -> int | None:
    if _process is not None and _process.poll() is None:
        return _process.pid
    return None


def get_last_error() -> str | None:
    if _process is not None and _process.poll() is not None:
        return f"TorrServer exited unexpectedly with code {_process.returncode}"
    return _last_error


def set_last_error(err: str | None) -> None:
    global _last_error
    _last_error = err


def _get_url(base_url: str | None = None) -> str:
    return (base_url or config.TORRSERVER_DEFAULT_URL).rstrip("/")


def _probe(url: str | None = None) -> bool:
    target_url = _get_url(url)
    try:
        with httpx.Client(timeout=4.0) as client:
            r = client.get(f"{target_url}/echo")
            return r.status_code == 200
    except httpx.HTTPError:
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
    url: str | None = None,
    executable: Path | None = None,
    data_dir: Path | None = None,
) -> bool:
    """Returns True if TorrServer is ready. Raises on unrecoverable error."""
    global _process, _last_error

    target_url = _get_url(url)

    if _probe(target_url):
        _last_error = None
        return True

    if target_url != config.TORRSERVER_DEFAULT_URL.rstrip("/"):
        err = f"Custom TorrServer endpoint not responding; auto-start only on {config.TORRSERVER_DEFAULT_URL}"
        _last_error = err
        raise RuntimeError(err)

    # Check port availability
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((config.APP_HOST, config.TORRSERVER_PORT))
    except OSError:
        err = f"Port {config.TORRSERVER_PORT} is occupied but TorrServer isn't responding. Check existing services."
        _last_error = err
        raise RuntimeError(err)

    executable = executable or bundled_executable()
    if not executable.is_file():
        err = f"TorrServer binary not found: {executable}"
        _last_error = err
        raise RuntimeError(err)

    data_dir = data_dir or default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    kwargs: dict = {
        "cwd": str(data_dir),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    if sys.platform != "win32":
        try:
            if not os.access(executable, os.X_OK):
                os.chmod(executable, 0o755)
        except OSError as e:
            logger.debug("Failed to set executable permissions for %s: %s", executable, e)

    _process = subprocess.Popen([str(executable)], **kwargs)

    deadline = time.time() + config.TORRSERVER_START_TIMEOUT
    while time.time() < deadline:
        if _probe(target_url):
            try:
                _optimize_settings(target_url)
            except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to optimize TorrServer settings: %s", e)
            _last_error = None
            return True

        if _process.poll() is not None:
            err = f"TorrServer exited unexpectedly with code {_process.returncode}"
            _last_error = err
            raise RuntimeError(err)
        time.sleep(0.3)

    _process.kill()
    err = f"TorrServer did not become ready in {config.TORRSERVER_START_TIMEOUT}s"
    _last_error = err
    raise RuntimeError(err)


def stop() -> None:
    global _process, _last_error
    if _process and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            _process.kill()
    _process = None
    _last_error = None


def _optimize_settings(url: str) -> None:
    target_url = _get_url(url)
    timeout = config.TORRSERVER_HTTP_TIMEOUT

    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{target_url}/settings", json={"action": "get"})
        r.raise_for_status()
        settings = r.json()

        if not isinstance(settings, dict):
            return

        changed = False
        if settings.get("ConnectionsLimit", 0) < config.TORRSERVER_CONNECTIONS_LIMIT:
            settings["ConnectionsLimit"] = config.TORRSERVER_CONNECTIONS_LIMIT
            changed = True
        if settings.get("DisableUTP") is True:
            settings["DisableUTP"] = False
            changed = True
        if not settings.get("EnableRutorSearch"):
            settings["EnableRutorSearch"] = True
            changed = True

        if changed:
            res = client.post(
                f"{target_url}/settings",
                json={"action": "set", "sets": settings},
            )
            res.raise_for_status()
