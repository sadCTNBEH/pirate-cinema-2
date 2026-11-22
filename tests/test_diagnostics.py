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
async def test_torrserver_diagnostics_ignores_error_from_another_endpoint(monkeypatch):
    monkeypatch.setattr("backend.infrastructure.torrserver.process.get_active_url",
                        lambda: "http://127.0.0.1:18765")
    monkeypatch.setattr("backend.infrastructure.torrserver.process.get_last_error",
                        lambda: "TorrServer exited unexpectedly with code 1")
    mock_http = MagicMock()
    mock_http.get = AsyncMock(return_value=MagicMock(status_code=200))
    svc = DiagnosticsService(
        db=MagicMock(), torrserver_url_provider=lambda: "http://127.0.0.1:8091",
        torrserver_client=mock_http,
    )
    result = await svc._check_torrserver()
    assert result["port"] == 8091
    assert result["running"] is True
    assert result["last_error"] is None
    mock_http.get.assert_awaited_once_with("http://127.0.0.1:8091/echo", timeout=0.4)


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


@pytest.mark.anyio
async def test_diagnostics_service_collects_playback_metrics():
    """Verify DiagnosticsService collects basic playback metrics (codec, dropped_frames, hwdec_active)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        # 1. Stopped / default state
        svc_stopped = DiagnosticsService(db=db)
        mpv_stopped = await svc_stopped._check_mpv()
        assert mpv_stopped["codec"] is None
        assert mpv_stopped["dropped_frames"] == 0
        assert mpv_stopped["hwdec_active"] is False

        # 2. Running state with metrics provided by status provider
        svc_running = DiagnosticsService(
            db=db,
            playback_status_provider=lambda: {
                "state": "running",
                "codec": "hevc",
                "dropped_frames": 18,
                "hwdec_active": True,
            },
        )
        mpv_running = await svc_running._check_mpv()
        assert mpv_running["codec"] == "hevc"
        assert mpv_running["dropped_frames"] == 18
        assert mpv_running["hwdec_active"] is True

        # 3. Dynamic resolution from active controller object
        class FakeController:
            is_running = True
            def get_playback_metrics(self):
                return {"codec": "av1", "dropped_frames": 4, "hwdec_active": True}

        class FakePlaybackService:
            controllers = {"main": FakeController()}
            def get_health(self):
                return {"state": "running"}

        fake_ps = FakePlaybackService()
        svc_dynamic = DiagnosticsService(
            db=db,
            playback_status_provider=lambda: fake_ps.get_health(),
        )
        mpv_dynamic = await svc_dynamic._check_mpv()
        assert mpv_dynamic["codec"] == "av1"
        assert mpv_dynamic["dropped_frames"] == 4
        assert mpv_dynamic["hwdec_active"] is True


def test_sensitive_data_redaction():
    """Verify redaction of tokens, API keys, passwords, and personal paths."""
    from backend.services.diagnostics import sanitize_personal_paths, sanitize_sensitive_data

    # 1. Personal paths
    assert sanitize_personal_paths("/Users/alex/Documents/secret.mkv") == "~/Documents/secret.mkv"
    assert sanitize_personal_paths("/home/bob/.config/app/settings.json") == "~/.config/app/settings.json"
    assert sanitize_personal_paths(r"C:\Users\Charlie\AppData\Local\log.txt") == r"~\AppData\Local\log.txt"
    assert sanitize_personal_paths("C:/Users/Dave/Desktop/movie.mp4") == "~/Desktop/movie.mp4"

    # 2. Query tokens and API keys
    assert "token=***" in sanitize_sensitive_data("https://tracker.org/announce?token=supersecret123&peer_id=1")
    assert "supersecret123" not in sanitize_sensitive_data("token=supersecret123")
    assert "api_key=***" in sanitize_sensitive_data("GET /torznab?api_key=jackett_key_999")
    assert "jackett_key_999" not in sanitize_sensitive_data("GET /torznab?api_key=jackett_key_999")
    assert "password=***" in sanitize_sensitive_data("connect with password=mypassword")

    # 3. Bearer & JWT tokens
    jwt_msg = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThis"
    sanitized_jwt = sanitize_sensitive_data(jwt_msg)
    assert "Bearer ***" in sanitized_jwt
    assert "doNotLeakThis" not in sanitized_jwt

    # 4. Basic Auth in URLs
    url_msg = "TorrServer at http://admin:verysecret@127.0.0.1:8090/status"
    assert "http://admin:***@127.0.0.1:8090/status" in sanitize_sensitive_data(url_msg)

    # 5. Combined log line with paths and keys
    combined = "Error in /Users/dev/project/run.py: failed auth token=secret_tok_123 path=C:\\Users\\admin\\app.db"
    clean_combined = sanitize_sensitive_data(combined)
    assert "/Users/dev" not in clean_combined
    assert "C:\\Users\\admin" not in clean_combined
    assert "secret_tok_123" not in clean_combined
    assert "~/project/run.py" in clean_combined
    assert "token=***" in clean_combined


def test_recent_logs_redaction_and_limit():
    """Verify get_recent_logs returns at most 200 lines and redacts secrets."""
    from backend.services.diagnostics import get_recent_logs

    with tempfile.TemporaryDirectory() as tmp_dir:
        fake_log = Path(tmp_dir) / "startup.log"
        # Write 250 log lines containing secrets and personal paths
        with fake_log.open("w", encoding="utf-8") as f:
            for i in range(250):
                f.write(
                    f"2026-11-22 10:00:{i%60:02d} INFO /Users/developer/app.py: Request {i} with token=secret_{i} and api_key=key_{i}\n"
                )

        with patch("backend.services.diagnostics.get_data_dir", return_value=Path(tmp_dir)):
            logs = get_recent_logs(max_lines=200)

            assert len(logs) == 200
            # Check oldest line is 50, latest is 249
            assert "Request 50" in logs[0]
            assert "Request 249" in logs[-1]

            # Verify complete absence of raw secrets and raw user paths
            for line in logs:
                assert "/Users/developer" not in line
                assert "~/app.py" in line
                assert "token=***" in line
                assert "api_key=***" in line
                assert "secret_" not in line
                assert "key_" not in line


@pytest.mark.anyio
async def test_diagnostics_bundle_content_and_structure():
    """Verify DiagnosticsService.get_diagnostic_bundle() gathers required system info and codecs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        svc = DiagnosticsService(
            db=db,
            playback_status_provider=lambda: {
                "state": "running",
                "codec": "hevc",
                "dropped_frames": 2,
                "hwdec_active": True,
            },
        )

        bundle = await svc.get_diagnostic_bundle()

        # 1. System info
        assert "system" in bundle
        assert "os" in bundle["system"]
        assert "os_version" in bundle["system"]
        assert "architecture" in bundle["system"]
        assert "python_version" in bundle["system"]

        # 2. App info
        assert "app" in bundle
        assert bundle["app"]["name"] == "Pirate Cinema"
        assert bundle["app"]["version"] is not None

        # 3. Statuses
        assert "torrserver" in bundle
        assert "mpv" in bundle
        assert bundle["mpv"]["state"] == "running"

        # 4. Codecs
        assert "codecs" in bundle
        assert bundle["codecs"]["active"] == "hevc"
        assert "h264" in bundle["codecs"]["supported"]
        assert "hevc" in bundle["codecs"]["supported"]
        assert "av1" in bundle["codecs"]["supported"]

        # 5. Logs and errors
        assert "logs" in bundle
        assert isinstance(bundle["logs"], list)
        assert len(bundle["logs"]) <= 200
        assert "recent_errors" in bundle


@pytest.mark.anyio
async def test_diagnostics_bundle_export_endpoints():
    """Verify GET /api/diagnostics/bundle and /export for JSON and ZIP formats."""
    import io
    import json
    import zipfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        svc = DiagnosticsService(db=db)
        app.dependency_overrides[get_database] = lambda: db
        app.dependency_overrides[get_diagnostics_service] = lambda: svc

        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                # 1. Export as JSON (default)
                res_json = await client.get("/api/diagnostics/bundle")
                assert res_json.status_code == 200
                assert res_json.headers["content-type"].startswith("application/json")
                assert 'attachment; filename="pirate_cinema_diagnostics_' in res_json.headers["content-disposition"]
                assert res_json.headers["content-disposition"].endswith('.json"')

                payload = res_json.json()
                assert "system" in payload
                assert "app" in payload
                assert "torrserver" in payload
                assert "mpv" in payload
                assert "codecs" in payload
                assert "logs" in payload

                # 2. Export as ZIP
                res_zip = await client.get("/api/diagnostics/bundle?format=zip")
                assert res_zip.status_code == 200
                assert res_zip.headers["content-type"] == "application/zip"
                assert res_zip.headers["content-disposition"].endswith('.zip"')

                # Inspect ZIP contents
                zf = zipfile.ZipFile(io.BytesIO(res_zip.content))
                namelist = zf.namelist()
                assert "diagnostics.json" in namelist
                assert "logs.txt" in namelist
                assert "summary.txt" in namelist

                # Validate diagnostics.json inside ZIP
                inner_json = json.loads(zf.read("diagnostics.json").decode("utf-8"))
                assert inner_json["app"]["name"] == "Pirate Cinema"

                # 3. Test alias /export
                res_alias = await client.get("/api/diagnostics/export?format=json")
                assert res_alias.status_code == 200
                assert res_alias.json()["app"]["name"] == "Pirate Cinema"

                # 4. Invalid format validation
                res_invalid = await client.get("/api/diagnostics/bundle?format=tar")
                assert res_invalid.status_code == 422
        finally:
            app.dependency_overrides.clear()

