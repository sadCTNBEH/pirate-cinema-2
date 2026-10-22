"""Tests for TASK-003: Diagnostics & Health Endpoint."""

from __future__ import annotations

import concurrent.futures
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.api.deps import get_database, get_diagnostics_service
from backend.api.schemas.diagnostics import DiagnosticsResponse
from backend.app import app
from backend.repositories.db import Database
from backend.services.diagnostics import (
    DiagnosticsService,
    ErrorBuffer,
    clear_mpv_cache,
    default_error_buffer,
)


def test_error_buffer_basic_and_ring_overflow():
    """Verify error ring buffer records entries and maintains maxlen=50 bound."""
    buf = ErrorBuffer(maxlen=50)
    assert buf.get_errors() == []

    # Record 10 errors
    for i in range(10):
        buf.record("test", "TestError", f"Error message {i}")
    errors = buf.get_errors()
    assert len(errors) == 10
    assert errors[0]["message"] == "Error message 0"
    assert errors[-1]["message"] == "Error message 9"

    # Add 50 more errors (total 60 added -> oldest 10 evicted)
    for i in range(10, 60):
        buf.record("test", "TestError", f"Error message {i}")
    errors = buf.get_errors()
    assert len(errors) == 50
    # Oldest retained is 10, newest is 59
    assert errors[0]["message"] == "Error message 10"
    assert errors[-1]["message"] == "Error message 59"


def test_error_buffer_sanitization():
    """Verify sensitive tokens, passwords, and long messages are sanitized."""
    buf = ErrorBuffer(maxlen=10)

    buf.record(
        "api",
        "AuthError",
        "Failed request with token=secret12345&api_key=my_secret_key and password=superpass",
    )
    buf.record("http", "ClientError", "Header Authorization: Bearer eyJhbGciOi...123")
    long_msg = "X" * 600
    buf.record("system", "Overflow", long_msg)

    errors = buf.get_errors()
    assert "token=***" in errors[0]["message"]
    assert "api_key=***" in errors[0]["message"]
    assert "password=***" in errors[0]["message"]
    assert "secret12345" not in errors[0]["message"]

    assert "Bearer ***" in errors[1]["message"]
    assert "eyJhbGciOi" not in errors[1]["message"]

    # Long message truncated
    assert len(errors[2]["message"]) <= 500
    assert errors[2]["message"].endswith("...")


def test_error_buffer_thread_safety():
    """Verify error buffer works safely under concurrent multi-threaded writes."""
    buf = ErrorBuffer(maxlen=50)

    def worker(worker_id: int):
        for j in range(20):
            buf.record(f"worker_{worker_id}", "WorkerError", f"Message {j}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(8)]
        for f in futures:
            f.result()

    errors = buf.get_errors()
    assert len(errors) == 50
    assert all("worker_" in e["component"] for e in errors)


@pytest.mark.anyio
async def test_torrserver_diagnostics_running_managed():
    """Verify TorrServer reports running=True with PID and port when managed process is active."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        with patch(
            "backend.infrastructure.torrserver.process.is_running", return_value=True
        ), patch(
            "backend.infrastructure.torrserver.process.get_pid", return_value=9876
        ), patch(
            "backend.infrastructure.torrserver.process.get_last_error",
            return_value=None,
        ):
            svc = DiagnosticsService(
                db=db,
                torrserver_url_provider=lambda: "http://127.0.0.1:8090",
            )
            res = await svc._check_torrserver()
            assert res["running"] is True
            assert res["port"] == 8090
            assert res["pid"] == 9876
            assert res["last_error"] is None


@pytest.mark.anyio
async def test_torrserver_diagnostics_exited_with_error():
    """Verify TorrServer reports running=False with returncode message when process crashed."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        with patch(
            "backend.infrastructure.torrserver.process.is_running", return_value=False
        ), patch(
            "backend.infrastructure.torrserver.process.get_last_error",
            return_value="TorrServer exited unexpectedly with code 1",
        ):
            svc = DiagnosticsService(
                db=db,
                torrserver_url_provider=lambda: "http://127.0.0.1:8090",
            )
            res = await svc._check_torrserver()
            assert res["running"] is False
            assert res["port"] == 8090
            assert res["pid"] is None
            assert "exited unexpectedly with code 1" in res["last_error"]


@pytest.mark.anyio
async def test_torrserver_diagnostics_external_probed():
    """Verify external TorrServer (not started by app) is detected via HTTP probe."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        mock_http = MagicMock()
        mock_http.get = AsyncMock(return_value=MagicMock(status_code=200))

        with patch(
            "backend.infrastructure.torrserver.process.is_running", return_value=False
        ), patch(
            "backend.infrastructure.torrserver.process.get_last_error",
            return_value=None,
        ):
            svc = DiagnosticsService(
                db=db,
                torrserver_url_provider=lambda: "http://192.168.1.50:9000",
                torrserver_client=mock_http,
            )
            res = await svc._check_torrserver()
            assert res["running"] is True
            assert res["port"] == 9000
            assert res["pid"] is None
            assert res["last_error"] is None


@pytest.mark.anyio
async def test_torrserver_diagnostics_not_running():
    """Verify TorrServer reports running=False when process is absent and probe fails."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        mock_http = MagicMock()
        mock_http.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with patch(
            "backend.infrastructure.torrserver.process.is_running", return_value=False
        ), patch(
            "backend.infrastructure.torrserver.process.get_last_error",
            return_value=None,
        ):
            svc = DiagnosticsService(
                db=db,
                torrserver_url_provider=lambda: "http://127.0.0.1:8090",
                torrserver_client=mock_http,
            )
            res = await svc._check_torrserver()
            assert res["running"] is False
            assert res["port"] == 8090
            assert res["pid"] is None
            assert "not running" in res["last_error"].lower()


@pytest.mark.anyio
async def test_mpv_diagnostics_available_and_cached():
    """Verify MPV availability, version parsing, and caching."""
    clear_mpv_cache()

    with tempfile.TemporaryDirectory() as tmp_dir:
        fake_mpv = Path(tmp_dir) / "mpv.exe"
        fake_mpv.write_text("binary")

        mock_subproc = MagicMock(
            returncode=0,
            stdout="mpv v0.39.0 Copyright © 2000-2024 mpv/MPlayer/mplayer2 projects\n",
        )

        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        with patch(
            "backend.services.diagnostics.find_mpv_binary", return_value=fake_mpv
        ), patch("subprocess.run", return_value=mock_subproc) as run_spy:
            svc = DiagnosticsService(db=db)
            res1 = await svc._check_mpv()
            assert res1["available"] is True
            assert res1["path"] == str(fake_mpv.resolve())
            assert res1["version"] == "0.39.0"
            assert run_spy.call_count == 1

            # Second call must use cache and NOT invoke subprocess.run again
            res2 = await svc._check_mpv()
            assert res2["available"] is True
            assert res2["version"] == "0.39.0"
            assert run_spy.call_count == 1


@pytest.mark.anyio
async def test_mpv_diagnostics_missing():
    """Verify MPV reports available=False when binary is not found."""
    clear_mpv_cache()

    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        with patch(
            "backend.services.diagnostics.find_mpv_binary", return_value=None
        ):
            svc = DiagnosticsService(db=db)
            res = await svc._check_mpv()
            assert res["available"] is False
            assert res["path"] is None
            assert res["version"] is None


@pytest.mark.anyio
async def test_mpv_diagnostics_version_timeout():
    """Verify subprocess timeout during version query does not crash diagnostic service."""
    clear_mpv_cache()

    with tempfile.TemporaryDirectory() as tmp_dir:
        fake_mpv = Path(tmp_dir) / "mpv.exe"
        fake_mpv.write_text("binary")

        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        with patch(
            "backend.services.diagnostics.find_mpv_binary", return_value=fake_mpv
        ), patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["mpv"], timeout=2.0),
        ):
            svc = DiagnosticsService(db=db)
            res = await svc._check_mpv()
            assert res["available"] is True
            assert res["path"] == str(fake_mpv.resolve())
            assert res["version"] is None


@pytest.mark.anyio
async def test_disk_diagnostics_valid_and_missing_dir():
    """Verify disk diagnostics retrieves used and free space correctly."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        svc = DiagnosticsService(db=db)
        res = await svc._check_disk()
        assert res["data_dir"] is not None
        assert isinstance(res["used_mb"], (int, float))
        assert isinstance(res["free_mb"], (int, float))
        assert res["used_mb"] >= 0
        assert res["free_mb"] >= 0

        # Simulate inaccessible disk
        with patch("shutil.disk_usage", side_effect=OSError("Drive unmounted")):
            res_err = await svc._check_disk()
            assert res_err["used_mb"] is None
            assert res_err["free_mb"] is None


@pytest.mark.anyio
async def test_database_diagnostics_healthy_and_wal():
    """Verify database health probe and size computation (including WAL/SHM)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.sqlite3"
        db = Database(db_path=db_path)
        db.init_db()

        # Write dummy data to create positive size
        with db.get_connection() as conn:
            conn.execute("CREATE TABLE dummy (id INTEGER, data TEXT)")
            conn.execute("INSERT INTO dummy VALUES (1, 'hello world')")

        # Create dummy WAL and SHM files
        wal_file = Path(tmp_dir) / "test.sqlite3-wal"
        wal_file.write_bytes(b"x" * 1024 * 1024)  # 1 MB
        shm_file = Path(tmp_dir) / "test.sqlite3-shm"
        shm_file.write_bytes(b"y" * 512 * 1024)  # 0.5 MB

        svc = DiagnosticsService(db=db)
        res = await svc._check_db()
        assert res["ok"] is True
        assert res["size_mb"] is not None
        assert res["size_mb"] >= 1.5  # Includes WAL + SHM

        # Test broken DB check returning ok=False
        import sqlite3
        with patch.object(
            db, "get_connection", side_effect=sqlite3.OperationalError("database is locked")
        ):
            res_broken = await svc._check_db()
            assert res_broken["ok"] is False
            assert res_broken["size_mb"] is not None


@pytest.mark.anyio
async def test_diagnostics_endpoint_full_response_and_schema():
    """Verify GET /api/diagnostics returns 200 with schema-validated JSON."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.sqlite3"
        db = Database(db_path=db_path)
        db.init_db()

        mock_http = MagicMock()
        mock_http.get = AsyncMock(return_value=MagicMock(status_code=200))

        svc = DiagnosticsService(
            db=db,
            error_buffer=default_error_buffer,
            torrserver_url_provider=lambda: "http://127.0.0.1:8090",
            torrserver_client=mock_http,
        )

        app.dependency_overrides[get_database] = lambda: db
        app.dependency_overrides[get_diagnostics_service] = lambda: svc

        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                res = await client.get("/api/diagnostics")
                assert res.status_code == 200

                payload = res.json()
                # Validate against Pydantic schema
                parsed = DiagnosticsResponse.model_validate(payload)
                assert parsed.version is not None
                assert parsed.status in ("healthy", "degraded", "unhealthy")
                assert parsed.response_time_ms >= 0
                assert isinstance(parsed.torrserver.running, bool)
                assert isinstance(parsed.mpv.available, bool)
                assert parsed.db.ok is True
                assert isinstance(parsed.last_errors, list)
        finally:
            app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_diagnostics_endpoint_graceful_degradation():
    """Verify that when TorrServer is stopped and MPV is missing, API returns 200 with degraded status."""
    clear_mpv_cache()

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.sqlite3"
        db = Database(db_path=db_path)
        db.init_db()

        mock_http = MagicMock()
        mock_http.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        svc = DiagnosticsService(
            db=db,
            torrserver_url_provider=lambda: "http://127.0.0.1:8090",
            torrserver_client=mock_http,
        )

        app.dependency_overrides[get_database] = lambda: db
        app.dependency_overrides[get_diagnostics_service] = lambda: svc

        with patch(
            "backend.infrastructure.torrserver.process.is_running",
            return_value=False,
        ), patch(
            "backend.infrastructure.torrserver.process.get_last_error",
            return_value="TorrServer not running",
        ), patch(
            "backend.services.diagnostics.find_mpv_binary", return_value=None
        ):

            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    res = await client.get("/api/diagnostics")
                    assert res.status_code == 200

                    data = res.json()
                    assert data["status"] == "degraded"
                    assert data["torrserver"]["running"] is False
                    assert data["mpv"]["available"] is False
                    assert data["db"]["ok"] is True
            finally:
                app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_diagnostics_endpoint_performance():
    """Verify GET /api/diagnostics completes faster than 500 ms."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.sqlite3"
        db = Database(db_path=db_path)
        db.init_db()

        mock_http = MagicMock()
        mock_http.get = AsyncMock(return_value=MagicMock(status_code=200))

        svc = DiagnosticsService(
            db=db,
            torrserver_url_provider=lambda: "http://127.0.0.1:8090",
            torrserver_client=mock_http,
        )

        app.dependency_overrides[get_database] = lambda: db
        app.dependency_overrides[get_diagnostics_service] = lambda: svc

        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Warmup call
                await client.get("/api/diagnostics")

                # Timed call
                t0 = time.perf_counter()
                res = await client.get("/api/diagnostics")
                elapsed_ms = (time.perf_counter() - t0) * 1000

                assert res.status_code == 200
                assert elapsed_ms < 500
                assert res.json()["response_time_ms"] < 500
        finally:
            app.dependency_overrides.clear()
