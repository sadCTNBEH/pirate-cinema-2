"""Diagnostics Service for system health checks and monitoring."""

from __future__ import annotations

import asyncio
import collections
import datetime
import inspect
import logging
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import anyio
import httpx

from backend import __version__
from backend.core.settings import config, find_mpv_binary, get_data_dir
from backend.core.settings.user import get_torrserver_url
from backend.infrastructure.torrserver import process as torrserver_process
from backend.repositories.db import Database

logger = logging.getLogger(__name__)


class ErrorBuffer:
    """Thread-safe ring buffer storing up to maxlen recent diagnostic errors in memory."""

    def __init__(self, maxlen: int = 50) -> None:
        self._buffer: collections.deque[dict[str, Any]] = collections.deque(
            maxlen=maxlen
        )
        self._lock = threading.Lock()

    def record(
        self,
        component: str,
        error_type: str,
        message: str,
        timestamp: datetime.datetime | None = None,
    ) -> None:
        safe_msg = self._sanitize(message)
        item = {
            "timestamp": timestamp or datetime.datetime.now(datetime.timezone.utc),
            "component": str(component or "unknown"),
            "error_type": str(error_type or "Error"),
            "message": safe_msg,
        }
        with self._lock:
            self._buffer.append(item)

    def get_errors(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()

    @staticmethod
    def _sanitize(message: str) -> str:
        if not message:
            return ""
        msg = str(message)
        # Redact sensitive patterns: API tokens, keys, passwords, bearer tokens
        msg = re.sub(
            r"(token|api[_-]?key|password|secret|auth)=([^\s&]+)",
            r"\1=***",
            msg,
            flags=re.IGNORECASE,
        )
        msg = re.sub(r"(Bearer\s+)[^\s]+", r"\1***", msg, flags=re.IGNORECASE)
        # Truncate overly long error messages to prevent memory explosion
        if len(msg) > 500:
            msg = msg[:497] + "..."
        return msg


# Global ring buffer for capturing diagnostic errors across application lifecycle
default_error_buffer = ErrorBuffer(maxlen=50)

# Global cache for relatively static MPV metadata
_mpv_cache_lock = threading.Lock()
_cached_mpv_path: str | None = None
_cached_mpv_version: str | None = None
_cached_mpv_checked: bool = False


def clear_mpv_cache() -> None:
    """Clear cached MPV binary path and version (used for testing)."""
    global _cached_mpv_path, _cached_mpv_version, _cached_mpv_checked
    with _mpv_cache_lock:
        _cached_mpv_path = None
        _cached_mpv_version = None
        _cached_mpv_checked = False


def record_diagnostic_error(component: str, error_type: str, message: str) -> None:
    """Helper to record an error to the global diagnostic error ring buffer."""
    default_error_buffer.record(component, error_type, message)


class DiagnosticsService:
    def __init__(
        self,
        db: Database,
        error_buffer: ErrorBuffer | None = None,
        torrserver_url_provider: Callable[[], str] | None = None,
        torrserver_client: Any = None,
        playback_status_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._db = db
        self._error_buffer = (
            error_buffer if error_buffer is not None else default_error_buffer
        )
        self._get_ts_url = torrserver_url_provider or get_torrserver_url
        self._torrserver_client = torrserver_client
        self._playback_status = playback_status_provider

        # Cache for relatively static MPV metadata
        self._cached_mpv_path: str | None = None
        self._cached_mpv_version: str | None = None
        self._cached_mpv_checked: bool = False
        self._mpv_lock = asyncio.Lock()

    @property
    def error_buffer(self) -> ErrorBuffer:
        return self._error_buffer

    def record_error(self, component: str, error_type: str, message: str) -> None:
        self._error_buffer.record(component, error_type, message)

    async def get_diagnostics(self) -> dict[str, Any]:
        """Collect and return full application diagnostics."""
        start_time = time.perf_counter()
        checked_at = datetime.datetime.now(datetime.timezone.utc)

        # Run independent checks concurrently to optimize latency
        ts_task = self._check_torrserver()
        mpv_task = self._check_mpv()
        disk_task = self._check_disk()
        db_task = self._check_db()

        ts_info, mpv_info, disk_info, db_info = await asyncio.gather(
            ts_task, mpv_task, disk_task, db_task
        )

        last_errors = self._error_buffer.get_errors()

        # Determine overall status
        status = "healthy"
        if not db_info.get("ok"):
            status = "unhealthy"
        elif not ts_info.get("running") or not mpv_info.get("available") or mpv_info.get("state") == "error":
            status = "degraded"

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        version_str = str(__version__).lstrip("v")

        return {
            "version": version_str,
            "status": status,
            "checked_at": checked_at,
            "response_time_ms": elapsed_ms,
            "torrserver": ts_info,
            "mpv": mpv_info,
            "disk": disk_info,
            "db": db_info,
            "last_errors": last_errors,
        }

    async def _check_torrserver(self) -> dict[str, Any]:
        info = await self._probe_torrserver()
        status = torrserver_process.get_status()
        matches = status.get('url') and status['url'].rstrip('/') == self._get_ts_url().rstrip('/')
        managed = bool(status['managed'] and matches)
        target = urlparse(self._get_ts_url())
        can_restart = managed or (not info['running'] and not matches and target.scheme == 'http' and target.hostname in ('127.0.0.1', 'localhost'))
        state = status['state'] if managed and (status['state'] in ('recovering', 'error') or not status['desired_running']) else 'running' if info['running'] else 'error' if info.get('last_error') else 'stopped'
        return {**info, 'running': info['running'] and state == 'running', 'state': state, 'managed': managed, 'can_restart': can_restart,
                'path': status['path'] if managed else None, 'log_path': status['log_path'] if managed else None,
                'version': info.get('version') or (status['version'] if matches else None),
                'recovery_attempts': status['recovery_attempts'] if managed else 0,
                'last_error': (status['last_error'] or info.get('last_error')) if managed else info.get('last_error')}

    async def restart_torrserver(self) -> dict[str, Any]:
        if self._playback_status and self._playback_status().get('state') in ('running', 'starting'):
            raise RuntimeError('Сначала остановите воспроизведение: перезапуск прервёт поток')
        await anyio.to_thread.run_sync(torrserver_process.restart, self._get_ts_url())
        return await self._check_torrserver()

    async def check_torrserver_update(self) -> dict[str, Any]:
        status = await self._check_torrserver()
        return await anyio.to_thread.run_sync(torrserver_process.check_update, status.get('version'))

    async def _probe_torrserver(self) -> dict[str, Any]:
        """Gather TorrServer process, port, and health diagnostics."""
        ts_url = config.TORRSERVER_DEFAULT_URL
        try:
            ts_url = self._get_ts_url()
        except (KeyError, ValueError, TypeError) as e:
            logger.debug("Failed to resolve TorrServer URL: %s", e)

        managed_url = torrserver_process.get_active_url()
        managed_matches = not managed_url or managed_url.rstrip("/") == ts_url.rstrip("/")

        parsed_port: int | None = config.TORRSERVER_PORT
        try:
            p = urlparse(ts_url).port
            if p is not None:
                parsed_port = p
        except (ValueError, AttributeError):
            parsed_port = config.TORRSERVER_PORT

        # 1. Check if process is managed by the application
        if managed_matches and torrserver_process.is_running():
            return {
                "running": True,
                "port": parsed_port,
                "pid": torrserver_process.get_pid(),
                "last_error": torrserver_process.get_last_error(),
            }

        # 2. Check if a managed process exited with an error code
        proc_err = torrserver_process.get_last_error() if managed_matches else None
        if proc_err and "exited" in proc_err:
            return {
                "running": False,
                "port": parsed_port,
                "pid": None,
                "last_error": proc_err,
            }

        # 3. Probe endpoint with a short non-blocking timeout (supports external TorrServer)
        is_alive = False
        target_probe = ts_url.rstrip("/") + "/echo"
        if hasattr(self._torrserver_client, "get"):
            http_client = self._torrserver_client
        elif hasattr(self._torrserver_client, "get_client") and callable(
            self._torrserver_client.get_client
        ):
            http_client = self._torrserver_client.get_client()
        else:
            from backend.infrastructure.torrserver.client import (
                get_client as default_get_client,
            )

            http_client = default_get_client()

        try:
            req = http_client.get(target_probe, timeout=0.4)
            res = await req if inspect.isawaitable(req) else req
            if getattr(res, "status_code", None) == 200:
                is_alive = True
        except (httpx.HTTPError, OSError, RuntimeError) as probe_err:
            logger.debug("TorrServer echo probe failed: %s", probe_err)

        if is_alive:
            return {
                "running": True,
                "port": parsed_port,
                "pid": None,
                "last_error": None,
                "version": res.text.strip()[:80] if isinstance(getattr(res, 'text', None), str) else None,
            }

        return {
            "running": False,
            "port": parsed_port,
            "pid": None,
            "last_error": proc_err or "TorrServer is not running",
        }

    async def _check_mpv(self) -> dict[str, Any]:
        info = await self._probe_mpv()
        status = self._playback_status() if self._playback_status else {'state': 'stopped', 'last_error': None, 'can_resume': False}
        return {**info, **status}

    async def _probe_mpv(self) -> dict[str, Any]:
        """Gather MPV binary availability, path, and version."""
        global _cached_mpv_path, _cached_mpv_version, _cached_mpv_checked

        with _mpv_cache_lock:
            # If already cached and valid, return cached results
            if _cached_mpv_checked:
                available = bool(
                    _cached_mpv_path and Path(_cached_mpv_path).is_file()
                )
                return {
                    "available": available,
                    "path": _cached_mpv_path if available else None,
                    "version": _cached_mpv_version if available else None,
                }

        # Locate binary outside of lock
        mpv_path_obj: Path | None = None
        try:
            mpv_path_obj = find_mpv_binary()
        except (OSError, ValueError) as err:
            logger.debug("Error while resolving MPV binary path: %s", err)

        if not mpv_path_obj or not mpv_path_obj.is_file():
            with _mpv_cache_lock:
                _cached_mpv_path = None
                _cached_mpv_version = None
                _cached_mpv_checked = True
            return {
                "available": False,
                "path": None,
                "version": None,
            }

        resolved_path_str = str(mpv_path_obj.resolve())

        # Probe version using limited timeout
        version_str: str | None = None
        try:
            creation_flags = (
                subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            proc = await anyio.to_thread.run_sync(
                lambda: subprocess.run(
                    [resolved_path_str, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                    check=False,
                    creationflags=creation_flags,
                )
            )
            if proc.returncode == 0 and proc.stdout:
                match = re.search(r"mpv\s+v?([0-9a-zA-Z\.\-]+)", proc.stdout)
                if match:
                    version_str = match.group(1)
                else:
                    first_line = proc.stdout.strip().splitlines()[0]
                    version_str = first_line[:30]
        except (
            subprocess.TimeoutExpired,
            subprocess.SubprocessError,
            OSError,
            FileNotFoundError,
            PermissionError,
        ) as v_err:
            logger.debug("Failed to extract MPV version: %s", v_err)

        with _mpv_cache_lock:
            _cached_mpv_path = resolved_path_str
            _cached_mpv_version = version_str
            _cached_mpv_checked = True

        return {
            "available": True,
            "path": resolved_path_str,
            "version": version_str,
        }

    async def _check_disk(self) -> dict[str, Any]:
        """Gather data directory and disk usage statistics."""
        data_dir = get_data_dir()
        data_dir_str = str(data_dir.resolve())

        try:
            target_path = data_dir if data_dir.exists() else data_dir.parent
            usage = await anyio.to_thread.run_sync(shutil.disk_usage, target_path)
            used_mb = round(usage.used / (1024 * 1024), 2)
            free_mb = round(usage.free / (1024 * 1024), 2)
            return {
                "data_dir": data_dir_str,
                "used_mb": used_mb,
                "free_mb": free_mb,
            }
        except (OSError, FileNotFoundError, PermissionError, ValueError) as e:
            logger.debug("Failed to get disk usage for %s: %s", data_dir_str, e)
            return {
                "data_dir": data_dir_str,
                "used_mb": None,
                "free_mb": None,
            }

    async def _check_db(self) -> dict[str, Any]:
        """Verify SQLite responsiveness and calculate database storage size."""
        db_path = self._db.db_path
        if isinstance(db_path, str):
            db_path = Path(db_path)

        def _inspect_db_sync() -> tuple[bool, float | None]:
            # 1. Size calculation: main db + wal + shm (calculated before opening connection)
            total_bytes: int = 0
            size_mb: float | None = None
            try:
                if db_path.is_file():
                    total_bytes += db_path.stat().st_size

                    wal_path = db_path.with_name(db_path.name + "-wal")
                    if wal_path.is_file():
                        total_bytes += wal_path.stat().st_size

                    shm_path = db_path.with_name(db_path.name + "-shm")
                    if shm_path.is_file():
                        total_bytes += shm_path.stat().st_size
                    size_mb = round(total_bytes / (1024 * 1024), 2)
            except (OSError, PermissionError) as stat_err:
                logger.debug("Failed to stat database file: %s", stat_err)

            # 2. Health check: SELECT 1
            is_ok = False
            try:
                with self._db.get_connection() as conn:
                    row = conn.execute("SELECT 1;").fetchone()
                    if row and row[0] == 1:
                        is_ok = True
            except (sqlite3.OperationalError, sqlite3.DatabaseError, OSError) as err:
                logger.debug("Database health check failed: %s", err)
                is_ok = False

            return is_ok, size_mb

        try:
            ok, size_mb = await anyio.to_thread.run_sync(_inspect_db_sync)
            return {"ok": ok, "size_mb": size_mb}
        except (OSError, RuntimeError) as run_err:
            logger.debug("Thread execution failed during db check: %s", run_err)
            return {"ok": False, "size_mb": None}
