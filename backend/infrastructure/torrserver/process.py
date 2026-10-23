"""TorrServer process manager – mirrors torrserver_process.rs."""

import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from backend.core.settings import BASE_DIR, config, get_data_dir

logger = logging.getLogger(__name__)

_process: subprocess.Popen | None = None
_last_error: str | None = None
_active_url: str | None = None
_lifecycle_lock = threading.RLock()


def get_active_url() -> str | None:
    return _active_url


def is_running() -> bool:
    return _process is not None and _process.poll() is None


def get_pid() -> int | None:
    if _process is not None and _process.poll() is None:
        return _process.pid
    return None


def get_last_error() -> str | None:
    if _process is not None and _process.poll() is not None:
        return _last_error or f"TorrServer exited unexpectedly with code {_process.returncode}"
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
    with _lifecycle_lock:
        return _connect_or_start(url, executable, data_dir)


def _connect_or_start(
    url: str | None, executable: Path | None, data_dir: Path | None,
) -> bool:
    """Returns True if TorrServer is ready. Raises on unrecoverable error."""
    global _process, _last_error, _active_url

    target_url = _get_url(url)

    if _probe(target_url):
        _last_error = None
        return True

    parsed = urlsplit(target_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        err = f"Custom TorrServer endpoint not responding: {target_url}; auto-start is only supported on local HTTP endpoints"
        _last_error = err
        raise RuntimeError(err)

    if is_running():
        err = f"Managed TorrServer is already running at {_active_url}, but is not responding. A second process will not be started."
        _last_error = err
        raise RuntimeError(err)

    host = "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    # Check the address TorrServer will actually bind, independently of the app's host.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
    except OSError:
        err = f"Port {port} is occupied but TorrServer isn't responding. Check existing services."
        _last_error = err
        raise RuntimeError(err)

    if executable is None:
        executable = bundled_executable()
        if not executable.is_file():
            from backend.infrastructure.downloader import ensure_torrserver_binary

            executable = ensure_torrserver_binary()
    executable = executable.resolve()
    if not executable.is_file():
        err = f"TorrServer binary not found: {executable}"
        _last_error = err
        raise RuntimeError(err)

    data_dir = (data_dir or default_data_dir()).resolve()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=data_dir):
            pass
    except OSError as e:
        _last_error = f"Cannot write TorrServer data folder: {data_dir}: {e}"
        raise RuntimeError(_last_error) from e

    log_path = data_dir / "startup.log"

    kwargs: dict = {
        "cwd": str(data_dir),
        "stdin": subprocess.DEVNULL,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    if sys.platform != "win32":
        try:
            if not os.access(executable, os.X_OK):
                os.chmod(executable, 0o755)
        except OSError as e:
            logger.debug("Failed to set executable permissions for %s: %s", executable, e)

    try:
        with log_path.open("wb") as log_file:
            _active_url = target_url
            _process = subprocess.Popen(
                [str(executable), "--port", str(port), "--ip", host, "--path", str(data_dir)],
                stdout=log_file,
                **kwargs,
            )
    except OSError as e:
        _last_error = f"Cannot start TorrServer ({executable}); data folder: {data_dir}: {e}"
        raise RuntimeError(_last_error) from e

    deadline = time.monotonic() + config.TORRSERVER_START_TIMEOUT
    while time.monotonic() < deadline:
        if _process.poll() is not None:
            err = _startup_failure(log_path, f"TorrServer exited unexpectedly with code {_process.returncode}")
            _last_error = err
            raise RuntimeError(err)
        if _probe(target_url):
            try:
                _optimize_settings(target_url)
            except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to optimize TorrServer settings: %s", e)
            _last_error = None
            return True

        time.sleep(0.3)

    _process.kill()
    _process.wait()
    err = _startup_failure(log_path, f"TorrServer did not become ready in {config.TORRSERVER_START_TIMEOUT}s")
    _last_error = err
    raise RuntimeError(err)


def _startup_failure(log_path: Path, message: str) -> str:
    try:
        with log_path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 4096))
            details = stream.read().decode("utf-8", errors="replace").strip()
    except OSError as e:
        details = f"Cannot read startup log: {e}"
    error = f"{message}\nLog: {log_path}"
    if details:
        error += f"\n{details}"
    logger.error("%s", error)
    return error


def stop() -> None:
    with _lifecycle_lock:
        _stop()


def _stop() -> None:
    global _process, _last_error, _active_url
    if _process and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            _process.kill()
            _process.wait(timeout=5.0)
    _process = None
    _last_error = None
    _active_url = None


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
