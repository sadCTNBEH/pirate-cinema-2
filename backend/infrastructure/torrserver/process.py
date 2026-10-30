"""TorrServer process manager – mirrors torrserver_process.rs."""

import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from backend.core.settings import BASE_DIR, config, get_data_dir
from backend.infrastructure.process_env import system_process_env

logger = logging.getLogger(__name__)

_process: subprocess.Popen | None = None
_last_error: str | None = None
_active_url: str | None = None
_lifecycle_lock = threading.RLock()
_managed_config: tuple[str, Path, Path] | None = None
_desired_running = False
_stop_requested = threading.Event()
_monitor_stop = threading.Event()
_monitor_thread: threading.Thread | None = None
_service_state = "stopped"
_health_failures = 0
_recovery_attempts = 0
_retry_at = 0.0
_last_failure: str | None = None
_version: str | None = None
_update_lock = threading.Lock()
_update_cache: tuple[float, dict] | None = None
_external_url: str | None = None
RECOVERY_DELAYS = (2.0, 5.0, 15.0)
MONITOR_INTERVAL = 5.0


def get_active_url() -> str | None:
    return _active_url


def is_running() -> bool:
    child = _process
    return child is not None and child.poll() is None


def get_pid() -> int | None:
    child = _process
    if child is not None and child.poll() is None:
        return child.pid
    return None


def get_last_error() -> str | None:
    child = _process
    if child is not None and child.poll() is not None:
        return _last_error or f"TorrServer exited unexpectedly with code {child.returncode}"
    return _last_error


def set_last_error(err: str | None) -> None:
    global _last_error
    _last_error = err


def _get_url(base_url: str | None = None) -> str:
    return (base_url or config.TORRSERVER_DEFAULT_URL).rstrip("/")


def _probe(url: str | None = None) -> bool:
    global _version
    target_url = _get_url(url)
    try:
        with httpx.Client(timeout=4.0, trust_env=False) as client:
            r = client.get(f"{target_url}/echo")
            if r.status_code == 200:
                _version = (r.text.strip()[:80] or None) if isinstance(r.text, str) else None
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
    global _desired_running, _recovery_attempts, _health_failures, _retry_at, _service_state
    with _lifecycle_lock:
        if _monitor_stop.is_set():
            raise RuntimeError("Приложение завершает работу; запуск TorrServer отменён")
        _stop_requested.clear()
        _desired_running = True
        _service_state = "recovering"
        _recovery_attempts = _health_failures = 0
        _retry_at = 0.0
        previous_process = _process
        try:
            result = _connect_or_start(url, executable, data_dir)
            _service_state = "running"
            return result
        except RuntimeError:
            _service_state = "error"
            # Retry only a child created by this call that actually exited.
            # Never replace an existing live server or reset its database.
            if _process is None or _process is previous_process or _process.poll() != 1:
                raise
            logger.warning("TorrServer exited during startup; retrying once without resetting data")
            result = _connect_or_start(url, executable, data_dir, append_log=True)
            _service_state = "running"
            return result


def _connect_or_start(
    url: str | None, executable: Path | None, data_dir: Path | None, append_log: bool = False,
) -> bool:
    """Returns True if TorrServer is ready. Raises on unrecoverable error."""
    global _process, _last_error, _active_url, _managed_config, _desired_running, _external_url

    target_url = _get_url(url)

    if _probe(target_url):
        if not is_running():
            _managed_config = None  # A reachable endpoint with no owned live child is external.
            _desired_running = False
            _external_url = target_url
        if is_running():
            _optimize_settings(target_url)
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
    _managed_config = (target_url, executable, data_dir)
    _external_url = None
    try:
        if _stop_requested.is_set():
            raise RuntimeError("TorrServer startup cancelled")
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _last_error = f"Cannot write TorrServer data folder: {data_dir}: {e}"
        raise RuntimeError(_last_error) from e

    log_path = data_dir / "startup.log"

    kwargs: dict = {
        "cwd": str(data_dir),
        "stdin": subprocess.DEVNULL,
        "stderr": subprocess.STDOUT,
        "env": system_process_env(),
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
        with log_path.open("ab" if append_log else "wb") as log_file:
            if _stop_requested.is_set():
                raise RuntimeError("TorrServer startup cancelled")
            if append_log:
                log_file.write(b"\n=== Retrying TorrServer startup (data preserved) ===\n")
                log_file.flush()
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
        if _stop_requested.is_set():
            _stop()
            raise RuntimeError("TorrServer startup cancelled")
        if _process.poll() is not None:
            err = _startup_failure(log_path, f"TorrServer exited unexpectedly with code {_process.returncode}")
            _last_error = err
            raise RuntimeError(err)
        if _probe(target_url):
            try:
                _optimize_settings(target_url)
            except (httpx.HTTPError, ValueError, RuntimeError) as e:
                _stop()
                _last_error = f'TorrServer RAM-only: {e}'
                raise RuntimeError(_last_error) from e
            _last_error = None
            return True

        _stop_requested.wait(0.3)

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
    global _desired_running, _service_state, _retry_at
    # Signal before waiting for the lifecycle lock so a startup/recovery can cancel.
    _desired_running = False
    _stop_requested.set()
    _retry_at = 0.0
    with _lifecycle_lock:
        _stop()
        _service_state = "stopped"


def start_monitor() -> None:
    global _monitor_thread
    with _lifecycle_lock:
        if _monitor_thread and _monitor_thread.is_alive():
            return
        _monitor_stop.clear()
        _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True, name="TorrServerHealth")
        _monitor_thread.start()


def shutdown_monitor() -> None:
    global _monitor_thread, _desired_running
    _desired_running = False
    _monitor_stop.set()
    _stop_requested.set()
    thread = _monitor_thread
    if thread and thread is not threading.current_thread():
        thread.join(timeout=config.TORRSERVER_START_TIMEOUT + 10)
    if not thread or not thread.is_alive():
        _monitor_thread = None
    else:
        logger.error("TorrServer health thread did not stop before shutdown timeout")


def _monitor_loop() -> None:
    while not _monitor_stop.wait(MONITOR_INTERVAL):
        try:
            _monitor_tick()
        except Exception:
            logger.exception("TorrServer health check failed")


def _monitor_tick(now: float | None = None) -> None:
    global _health_failures, _recovery_attempts, _retry_at, _service_state, _last_error, _last_failure
    if not _lifecycle_lock.acquire(blocking=False):
        return
    try:
        if not _desired_running or not _managed_config or _monitor_stop.is_set() or _stop_requested.is_set():
            return
        if _service_state == "error" and _recovery_attempts >= len(RECOVERY_DELAYS):
            return
        now = time.monotonic() if now is None else now
        if _retry_at:
            if now < _retry_at:
                return
            _retry_at = 0.0
            if _stop_requested.is_set() or not _desired_running:
                return
            _recovery_attempts += 1
            settings = _managed_config
            _stop()  # Only the Popen owned by this module; never kill by name/port.
            try:
                _connect_or_start(*settings, append_log=True)
                _service_state = "running"
                _health_failures = 0
                return
            except (RuntimeError, OSError) as error:
                _last_error = str(error)
                if _stop_requested.is_set() or not _desired_running:
                    _service_state = "stopped"
                    return
        elif is_running():
            if _probe(_managed_config[0]):
                _health_failures = 0
                _service_state = "running"
                return
            _health_failures += 1
            if _health_failures < 3:  # Slow/busy servers get several bounded probes.
                return
            _last_error = "TorrServer не ответил на три последовательные проверки"
        else:
            _last_error = get_last_error() or "TorrServer неожиданно завершился"
        _last_failure = _last_error
        if _recovery_attempts >= len(RECOVERY_DELAYS):
            _service_state = "error"
            _last_error = f"Автовосстановление TorrServer исчерпано ({_recovery_attempts} попытки). {_last_failure}"
            return
        _service_state = "recovering"
        _retry_at = now + RECOVERY_DELAYS[_recovery_attempts]
    finally:
        _lifecycle_lock.release()


def get_status() -> dict:
    settings = _managed_config
    return {
        "state": _service_state,
        "url": settings[0] if settings else _external_url,
        "managed": settings is not None,
        "desired_running": _desired_running,
        "path": str(settings[1]) if settings else None,
        "log_path": str(settings[2] / "startup.log") if settings else None,
        "version": _version,
        "recovery_attempts": _recovery_attempts,
        "last_error": (get_last_error() or _last_failure or '')[:500] or None,
    }


def restart(url: str) -> bool:
    with _lifecycle_lock:
        if _monitor_stop.is_set():
            raise RuntimeError("Приложение завершает работу")
        settings = _managed_config
        if settings and settings[0].rstrip('/') != url.rstrip('/'):
            raise RuntimeError("Настроен другой TorrServer; управляемая служба не будет перезапущена")
        if not settings:
            if _external_url == url.rstrip('/'):
                raise RuntimeError("Внешний TorrServer не управляется приложением")
            if _probe(url):
                raise RuntimeError("Внешний TorrServer не управляется приложением")
            return connect_or_start(url)
        if not is_running() and _probe(url):
            raise RuntimeError("Этот адрес уже обслуживает внешний TorrServer")
        _stop()
        return connect_or_start(*settings)


def read_log() -> str:
    settings = _managed_config
    if not settings:
        raise RuntimeError("У внешнего TorrServer нет локального управляемого журнала")
    path = settings[2] / "startup.log"
    try:
        with path.open('rb') as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 32768))
            return stream.read().decode('utf-8', errors='replace')
    except OSError as error:
        raise RuntimeError(f"Не удалось прочитать журнал TorrServer: {error}") from error


def check_update(installed: str | None = None) -> dict:
    """Read official release metadata only. Never download/replace an executable."""
    global _update_cache
    with _update_lock:
        now = time.monotonic()
        if _update_cache and now - _update_cache[0] < 900:
            release = dict(_update_cache[1])
        else:
            with httpx.Client(timeout=5.0, trust_env=False) as client:
                response = client.get('https://api.github.com/repos/YouROK/TorrServer/releases/latest',
                                      headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'Pirate-Cinema'})
                response.raise_for_status()
                data = response.json()
            tag, url = data.get('tag_name'), data.get('html_url')
            if not isinstance(tag, str) or len(tag) > 80 or not isinstance(url, str) or not url.startswith('https://github.com/YouROK/TorrServer/releases/'):
                raise RuntimeError("Некорректные сведения об официальном выпуске TorrServer")
            release = {'latest_version': tag, 'release_url': url}
            _update_cache = (now, release)
        import re

        current = installed or _version
        old = tuple(map(int, re.findall(r'\d+', current or '')))
        new = tuple(map(int, re.findall(r'\d+', release['latest_version'])))
        return {**release, 'installed_version': current, 'update_available': new > old if old and new else None,
                'install_supported': False}


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
    timeout = min(config.TORRSERVER_HTTP_TIMEOUT, 4.0)

    with httpx.Client(timeout=timeout, trust_env=False) as client:
        r = client.post(f"{target_url}/settings", json={"action": "get"})
        r.raise_for_status()
        settings = r.json()

        if not isinstance(settings, dict) or type(settings.get('UseDisk')) is not bool or 'CacheSize' not in settings:
            raise RuntimeError('API не позволяет подтвердить UseDisk/CacheSize')
        if settings['UseDisk'] or settings['CacheSize'] != 256 * 1024 * 1024:
            settings.update(UseDisk=False, CacheSize=256 * 1024 * 1024)
            # This API also restarts the torrent client; allow a bounded startup
            # reconfiguration without mistaking it for a failed RAM policy.
            res = client.post(f"{target_url}/settings", json={"action": "set", "sets": settings},
                              timeout=config.TORRSERVER_HTTP_TIMEOUT)
            res.raise_for_status()
        response = client.post(f"{target_url}/settings", json={"action": "get"})
        response.raise_for_status()
        from backend.infrastructure.torrserver.client import ram_cache_verified
        if not ram_cache_verified(response.json()):
            raise RuntimeError('сервер не подтвердил RAM-only кеш размером до 256 MiB')
