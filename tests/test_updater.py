"""Comprehensive tests for TASK-004: In-App Updater — GitHub Releases Auto-Updater."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api.deps import get_updater_service
from backend.api.schemas.updater import (
    UpdateActionResponse,
    UpdateCheckResponse,
    UpdateStatusResponse,
)
from backend.app import app
from backend.services.update_helper import (
    generate_linux_helper_script,
    generate_windows_helper_script,
)
from backend.services.updater import (
    UpdateInstallationError,
    UpdaterService,
    detect_installation_type,
    is_version_newer,
    read_installed_version,
)

# ─── 1. Version Comparison & Detection ───


def test_version_semantic_comparison():
    """Verify semantic version comparisons handle prefixes, minor/patch bumps, and equality."""
    assert is_version_newer("v0.1.2", "v0.1.1") is True
    assert is_version_newer("0.1.2", "v0.1.1") is True
    assert is_version_newer("v0.2.0", "v0.1.9") is True
    assert is_version_newer("v1.0.0", "v0.9.9") is True
    assert is_version_newer("v0.1.1", "v0.1.1") is False
    assert is_version_newer("v0.1.0", "v0.1.1") is False
    assert is_version_newer("v0.0.9", "v0.1.0") is False
    assert is_version_newer("", "v0.1.1") is False
    assert is_version_newer("invalid", "v0.1.1") is False


def test_read_installed_version(tmp_path: Path):
    """Verify read_installed_version reads from version.json correctly."""
    vfile = tmp_path / "version.json"
    vfile.write_text(json.dumps({"version": "v1.2.3"}), encoding="utf-8")

    with patch("backend.services.updater.BASE_DIR", tmp_path):
        ver = read_installed_version()
        assert ver == "v1.2.3"


def test_detect_installation_type_development():
    """When running without sys.frozen, detect development mode."""
    with patch.object(sys, "frozen", False, create=True):
        inst_type, asset_name, can_auto, reason = detect_installation_type()
        assert inst_type == "development"
        assert can_auto is False
        assert reason == "development_mode"
        if sys.platform == "win32":
            assert asset_name == "pirate-cinema-portable.exe"


def test_detect_installation_type_windows_portable():
    """When running frozen executable containing 'portable' on Windows."""
    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "platform", "win32"),
        patch.object(
            sys, "executable", "C:\\Programs\\Pirate Cinema\\pirate-cinema-portable.exe"
        ),
    ):
        inst_type, asset_name, can_auto, reason = detect_installation_type()
        assert inst_type == "windows_portable"
        assert asset_name == "pirate-cinema-portable.exe"
        assert can_auto is True
        assert reason is None


def test_detect_installation_type_windows_installer():
    """When running installed executable 'pirate-cinema.exe' on Windows."""
    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "platform", "win32"),
        patch.object(
            sys, "executable", "C:\\Users\\user\\AppData\\Local\\Programs\\Pirate Cinema\\pirate-cinema.exe"
        ),
    ):
        inst_type, asset_name, can_auto, reason = detect_installation_type()
        assert inst_type == "windows_installer"
        assert asset_name == "pirate-cinema-installer.exe"
        assert can_auto is True
        assert reason is None


def test_detect_installation_type_linux_portable():
    """When running portable on Linux."""
    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "platform", "linux"),
        patch.object(
            sys, "executable", "/home/user/Downloads/pirate-cinema-portable-linux"
        ),
        patch.dict(os.environ, {}, clear=True),
    ):
        inst_type, asset_name, can_auto, _reason = detect_installation_type()
        assert inst_type == "linux_portable"
        assert asset_name == "pirate-cinema-portable-linux"
        assert can_auto is True


def test_detect_installation_type_linux_appimage(tmp_path: Path):
    """When running from AppImage on Linux via APPIMAGE environment variable."""
    appimage = tmp_path / "Pirate_Cinema-x86_64.AppImage"
    appimage.write_text("mock appimage")
    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "platform", "linux"),
        patch.object(
            sys, "executable", "/tmp/.mount_Pirate123/pirate-cinema-linux"
        ),
        patch.dict(os.environ, {"APPIMAGE": str(appimage)}),
    ):
        inst_type, asset_name, can_auto, reason = detect_installation_type()
        assert inst_type == "linux_appimage"
        assert asset_name == "Pirate_Cinema-x86_64.AppImage"
        assert can_auto is True
        assert reason is None


def test_detect_installation_type_linux_appimage_readonly(tmp_path: Path):
    """When AppImage file or its folder is read-only, auto-update is rejected with reason."""
    appimage = tmp_path / "Pirate_Cinema-x86_64.AppImage"
    appimage.write_text("mock appimage")

    orig_access = os.access

    def mock_access(path, mode):
        if mode == os.W_OK:
            return False
        return orig_access(path, mode)

    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "platform", "linux"),
        patch.object(
            sys, "executable", "/tmp/.mount_Pirate123/pirate-cinema-linux"
        ),
        patch.dict(os.environ, {"APPIMAGE": str(appimage)}),
        patch("os.access", side_effect=mock_access),
    ):
        inst_type, asset_name, can_auto, reason = detect_installation_type()
        assert inst_type == "linux_appimage"
        assert asset_name == "Pirate_Cinema-x86_64.AppImage"
        assert can_auto is False
        assert reason == "read_only_filesystem"


# ─── 2. Release Checking & Checksum Extraction ───


@pytest.mark.asyncio
async def test_check_for_updates_available(tmp_path: Path):
    """Verify check_for_updates detects newer version and parses asset sha256."""
    mock_release = {
        "tag_name": "v0.1.2",
        "html_url": "https://github.com/sadCTNBEH/pirate-cinema-2/releases/tag/v0.1.2",
        "body": "Bug fixes and improvements",
        "published_at": "2026-10-22T00:00:00Z",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "pirate-cinema-portable.exe",
                "browser_download_url": "https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/v0.1.2/pirate-cinema-portable.exe",
                "size": 52428800,
                "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            }
        ],
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_release
    mock_resp.raise_for_status = MagicMock()

    service = UpdaterService(
        github_api_url="https://api.github.com/repos/sadCTNBEH/pirate-cinema-2/releases/latest",
        data_dir_provider=lambda: tmp_path,
        installed_version_provider=lambda: "v0.1.1",
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        with patch(
            "backend.services.updater.detect_installation_type",
            return_value=("windows_portable", "pirate-cinema-portable.exe", True, None),
        ):
            res = await service.check_for_updates()
            assert res.has_update is True
            assert res.version == "v0.1.2"
            assert res.can_auto_update is True
            assert res.asset_name == "pirate-cinema-portable.exe"
            assert res.size_bytes == 52428800
            assert (
                res.sha256
                == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )


@pytest.mark.asyncio
async def test_check_for_updates_extract_sha256_from_body(tmp_path: Path):
    """Verify SHA-256 fallback from release notes when asset.digest is absent."""
    body_text = (
        "Changes:\n"
        "- improved performance\n\n"
        "Checksums:\n"
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb  pirate-cinema-portable.exe\n"
    )
    mock_release = {
        "tag_name": "v0.1.2",
        "html_url": "https://github.com/sadCTNBEH/pirate-cinema-2/releases/tag/v0.1.2",
        "body": body_text,
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "pirate-cinema-portable.exe",
                "browser_download_url": "https://github.com/...",
                "size": 12345,
            }
        ],
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_release

    service = UpdaterService(
        github_api_url="https://api.github.com/test",
        data_dir_provider=lambda: tmp_path,
        installed_version_provider=lambda: "v0.1.1",
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        with patch(
            "backend.services.updater.detect_installation_type",
            return_value=("windows_portable", "pirate-cinema-portable.exe", True, None),
        ):
            res = await service.check_for_updates()
            assert res.has_update is True
            assert (
                res.sha256
                == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            )


@pytest.mark.asyncio
async def test_check_for_updates_rate_limited(tmp_path: Path):
    """Verify HTTP 403 (rate limited) returns graceful response without failing."""
    mock_resp = MagicMock()
    mock_resp.status_code = 403

    service = UpdaterService(
        github_api_url="https://api.github.com/test",
        data_dir_provider=lambda: tmp_path,
        installed_version_provider=lambda: "v0.1.1",
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await service.check_for_updates()
        assert res.has_update is False
        assert res.reason == "github_rate_limited"


@pytest.mark.asyncio
async def test_check_for_updates_skips_prereleases(tmp_path: Path):
    """Verify prereleases and drafts are ignored for stable auto-update."""
    mock_release = {
        "tag_name": "v0.2.0-beta.1",
        "draft": False,
        "prerelease": True,
        "assets": [],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_release

    service = UpdaterService(
        github_api_url="https://api.github.com/test",
        data_dir_provider=lambda: tmp_path,
        installed_version_provider=lambda: "v0.1.1",
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await service.check_for_updates()
        assert res.has_update is False
        assert res.reason == "prerelease_skipped"


# ─── 3. Streaming Download & Integrity Verification ───


@pytest.mark.asyncio
async def test_download_and_integrity_success(tmp_path: Path):
    """Verify streaming download calculates SHA-256 and marks ready upon match."""
    payload = b"FAKE_NEW_BINARY_CONTENT_PIRATE_CINEMA"
    calc_sha = hashlib.sha256(payload).hexdigest()

    service = UpdaterService(
        data_dir_provider=lambda: tmp_path,
        installed_version_provider=lambda: "v0.1.1",
    )

    # Set mock check response
    service._current_check = UpdateCheckResponse(
        current_version="v0.1.1",
        has_update=True,
        version="v0.1.2",
        download_url="https://github.com/test/download/pirate-cinema-portable.exe",
        asset_name="pirate-cinema-portable.exe",
        size_bytes=len(payload),
        can_auto_update=True,
        sha256=calc_sha,
    )

    async def mock_aiter(*args, **kwargs):
        yield payload

    stream_mock = MagicMock()
    stream_mock.headers = {"content-length": str(len(payload))}
    stream_mock.aiter_bytes = mock_aiter
    stream_mock.raise_for_status = MagicMock()

    class StreamContext:
        async def __aenter__(self):
            return stream_mock

        async def __aexit__(self, *args):
            pass

    with patch("httpx.AsyncClient.stream", return_value=StreamContext()):
        await service.start_download()
        # Wait for worker task to finish
        if service._active_download_task:
            await service._active_download_task

        status = service.get_status()
        assert status.state == "ready"
        assert status.downloaded_bytes == len(payload)
        assert status.progress_percent == 100.0
        assert status.error is None
        assert service._downloaded_file is not None
        assert service._downloaded_file.is_file()
        assert service._downloaded_file.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_integrity_mismatch_fails(tmp_path: Path):
    """Verify mismatched SHA-256 sets state to failed and discards partial file."""
    payload = b"CORRUPTED_FILE_DATA"
    wrong_sha = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"

    service = UpdaterService(
        data_dir_provider=lambda: tmp_path,
        installed_version_provider=lambda: "v0.1.1",
    )

    service._current_check = UpdateCheckResponse(
        current_version="v0.1.1",
        has_update=True,
        version="v0.1.2",
        download_url="https://github.com/test/download/pirate-cinema-portable.exe",
        asset_name="pirate-cinema-portable.exe",
        size_bytes=len(payload),
        can_auto_update=True,
        sha256=wrong_sha,
    )

    async def mock_aiter(*args, **kwargs):
        yield payload

    stream_mock = MagicMock()
    stream_mock.headers = {"content-length": str(len(payload))}
    stream_mock.aiter_bytes = mock_aiter
    stream_mock.raise_for_status = MagicMock()

    class StreamContext:
        async def __aenter__(self):
            return stream_mock

        async def __aexit__(self, *args):
            pass

    with patch("httpx.AsyncClient.stream", return_value=StreamContext()):
        await service.start_download()
        if service._active_download_task:
            await service._active_download_task

        status = service.get_status()
        assert status.state == "failed"
        assert "Integrity check failed" in (status.error or "")
        part_file = tmp_path / "updates" / "pirate-cinema-portable.exe.part"
        assert not part_file.exists()


@pytest.mark.asyncio
async def test_cancel_download(tmp_path: Path):
    """Verify cancelling download resets state to idle and removes partial file."""
    service = UpdaterService(
        data_dir_provider=lambda: tmp_path,
        installed_version_provider=lambda: "v0.1.1",
    )

    service._current_check = UpdateCheckResponse(
        current_version="v0.1.1",
        has_update=True,
        version="v0.1.2",
        download_url="https://github.com/test",
        asset_name="pirate-cinema-portable.exe",
        can_auto_update=True,
    )

    updates_dir = tmp_path / "updates"
    updates_dir.mkdir(parents=True)
    part_file = updates_dir / "pirate-cinema-portable.exe.part"
    part_file.write_bytes(b"partial content")

    await service.cancel_download()
    status = service.get_status()
    assert status.state == "idle"
    assert status.downloaded_bytes == 0
    assert not part_file.exists()


# ─── 4. Helper Script Generation & Rollback Logic ───


def test_windows_helper_script_generation(tmp_path: Path):
    """Verify generated Windows .cmd script contains tasklist check, replacement, and rollback."""
    script_path = tmp_path / "pirate_cinema_updater.ps1"
    target_exe = tmp_path / "pirate-cinema-portable.exe"
    new_file = tmp_path / "pirate-cinema-portable.exe.new"
    backup_file = tmp_path / "pirate-cinema-portable.exe.bak"
    log_file = tmp_path / "updater.log"

    generate_windows_helper_script(
        script_path=script_path,
        target_exe=target_exe,
        new_file=new_file,
        backup_file=backup_file,
        pid=12345,
        is_installer=False,
        log_file=log_file,
    )

    assert script_path.is_file()
    content = script_path.read_text(encoding="utf-8")
    assert "12345" in content
    assert "Get-Process -Id 12345" in content
    assert "WaitForExit(60000)" in content
    assert "Copy-Item -LiteralPath $download -Destination $staged" in content
    assert "Move-Item -LiteralPath $staged -Destination $target" in content
    assert "Copy-Item -LiteralPath $backup -Destination $target" in content
    assert "find /" not in content
    assert "PYINSTALLER_RESET_ENVIRONMENT" in content


def test_linux_helper_script_generation(tmp_path: Path):
    """Verify generated Linux bash script contains PID monitoring, replacement, and rollback."""
    script_path = tmp_path / "pirate_cinema_updater.sh"
    target_exe = tmp_path / "pirate-cinema-portable-linux"
    new_file = tmp_path / "pirate-cinema-portable-linux.new"
    backup_file = tmp_path / "pirate-cinema-portable-linux.bak"
    log_file = tmp_path / "updater.log"

    generate_linux_helper_script(
        script_path=script_path,
        target_exe=target_exe,
        new_file=new_file,
        backup_file=backup_file,
        pid=9999,
        is_archive=False,
        log_file=log_file,
    )

    assert script_path.is_file()
    content = script_path.read_text(encoding="utf-8")
    assert "9999" in content
    assert "kill -0 9999" in content
    assert "new_pid=$!" in content
    assert 'mv -- "$backup" "$destination"' in content


# ─── 5. Apply Update & Safety ───


@pytest.mark.asyncio
async def test_apply_update_creates_sqlite_backup_and_dry_run(tmp_path: Path):
    """Verify apply_update creates an automatic backup of pirate_cinema.sqlite3."""
    import sqlite3

    db_file = tmp_path / "history.sqlite3"
    with sqlite3.connect(db_file) as connection:
        connection.execute("PRAGMA user_version = 1")

    ready_file = tmp_path / "updates" / "pirate-cinema-portable.exe"
    ready_file.parent.mkdir(parents=True, exist_ok=True)
    ready_file.write_bytes(b"NEW_VERSION")

    service = UpdaterService(
        data_dir_provider=lambda: tmp_path,
        installed_version_provider=lambda: "v0.1.1",
    )
    service._state = "ready"
    service._downloaded_file = ready_file

    with patch(
        "backend.services.updater.detect_installation_type",
        return_value=("windows_portable", "pirate-cinema-portable.exe", True, None),
    ):
        res = await service.apply_update(dry_run=True)
        assert res.status == "applying"

        # Check DB backup exists
        db_bak = tmp_path / "history.sqlite3.update_bak"
        assert db_bak.is_file()
        with sqlite3.connect(db_bak) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_apply_update_not_ready_raises(tmp_path: Path):
    """Verify apply_update fails if state is not 'ready'."""
    service = UpdaterService(
        data_dir_provider=lambda: tmp_path,
        installed_version_provider=lambda: "v0.1.1",
    )
    service._state = "idle"

    with pytest.raises(UpdateInstallationError):
        await service.apply_update()


@pytest.mark.asyncio
async def test_updater_appimage_apply_update(tmp_path: Path):
    """Verify AppImage update uses the host AppImage path, not mounted sys.executable."""
    appimage_file = tmp_path / "Pirate_Cinema-x86_64.AppImage"
    appimage_file.write_text("current appimage")

    ready_file = tmp_path / "updates" / "Pirate_Cinema-x86_64.AppImage"
    ready_file.parent.mkdir(parents=True, exist_ok=True)
    ready_file.write_text("new appimage")

    service = UpdaterService(
        data_dir_provider=lambda: tmp_path,
        installed_version_provider=lambda: "v0.1.1",
    )
    service._state = "ready"
    service._downloaded_file = ready_file

    with (
        patch.object(sys, "platform", "linux"),
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "executable", "/tmp/.mount_XYZ/pirate-cinema-linux"),
        patch.dict(os.environ, {"APPIMAGE": str(appimage_file)}),
        patch("backend.services.updater.generate_linux_helper_script") as mock_helper,
    ):
        res = await service.apply_update(dry_run=True)
        assert res.status == "applying"
        mock_helper.assert_called_once()
        kwargs = mock_helper.call_args.kwargs
        assert kwargs["target_exe"] == appimage_file
        assert kwargs["is_archive"] is False


@pytest.mark.asyncio
async def test_updater_appimage_readonly_rejected(tmp_path: Path):
    """Verify apply_update rejects non-writable AppImage file or directory."""
    appimage_file = tmp_path / "Pirate_Cinema-x86_64.AppImage"
    appimage_file.write_text("current appimage")

    ready_file = tmp_path / "updates" / "Pirate_Cinema-x86_64.AppImage"
    ready_file.parent.mkdir(parents=True, exist_ok=True)
    ready_file.write_text("new appimage")

    service = UpdaterService(
        data_dir_provider=lambda: tmp_path,
        installed_version_provider=lambda: "v0.1.1",
    )
    service._state = "ready"
    service._downloaded_file = ready_file

    orig_access = os.access

    def mock_access(path, mode):
        if mode == os.W_OK:
            return False
        return orig_access(path, mode)

    # 1. Detection rejection
    with (
        patch.object(sys, "platform", "linux"),
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "executable", "/tmp/.mount_XYZ/pirate-cinema-linux"),
        patch.dict(os.environ, {"APPIMAGE": str(appimage_file)}),
        patch("os.access", side_effect=mock_access),
        pytest.raises(UpdateInstallationError, match="Automatic installation is not supported"),
    ):
        await service.apply_update(dry_run=False)

    # 2. Direct apply_update permission verification
    with (
        patch.object(sys, "platform", "linux"),
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "executable", "/tmp/.mount_XYZ/pirate-cinema-linux"),
        patch.dict(os.environ, {"APPIMAGE": str(appimage_file)}),
        patch(
            "backend.services.updater.detect_installation_type",
            return_value=("linux_appimage", "Pirate_Cinema-x86_64.AppImage", True, None),
        ),
        patch("os.access", side_effect=mock_access),
        pytest.raises(UpdateInstallationError, match="requires write permission"),
    ):
        await service.apply_update(dry_run=False)


# ─── 6. FastAPI Router Endpoints ───


def test_api_updater_status():
    """Verify GET /api/updater/status returns status schema."""
    client = TestClient(app)
    resp = client.get("/api/updater/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "state" in data
    assert "downloaded_bytes" in data
    assert "progress_percent" in data


def test_api_updater_check():
    """Verify GET /api/updater/check returns UpdateCheckResponse."""
    client = TestClient(app)
    mock_service = MagicMock()
    mock_service.check_for_updates = AsyncMock(
        return_value=UpdateCheckResponse(
            current_version="v0.1.1",
            has_update=False,
            version="v0.1.1",
            download_url="",
            release_url="",
            asset_name="",
            can_auto_update=False,
        )
    )

    app.dependency_overrides[get_updater_service] = lambda: mock_service
    try:
        resp = client.get("/api/updater/check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_version"] == "v0.1.1"
        assert data["has_update"] is False
    finally:
        app.dependency_overrides.pop(get_updater_service, None)


def test_api_updater_download_and_cancel():
    """Verify POST /api/updater/download and POST /api/updater/cancel."""
    client = TestClient(app)
    mock_service = MagicMock()
    mock_service.start_download = AsyncMock(
        return_value=UpdateStatusResponse(
            state="downloading",
            downloaded_bytes=100,
            total_bytes=1000,
            progress_percent=10.0,
            can_auto_update=True,
        )
    )
    mock_service.cancel_download = AsyncMock(
        return_value=UpdateStatusResponse(
            state="idle",
            downloaded_bytes=0,
            progress_percent=0.0,
            can_auto_update=True,
        )
    )

    app.dependency_overrides[get_updater_service] = lambda: mock_service
    try:
        resp_dl = client.post("/api/updater/download")
        assert resp_dl.status_code == 200
        assert resp_dl.json()["state"] == "downloading"

        resp_cancel = client.post("/api/updater/cancel")
        assert resp_cancel.status_code == 200
        assert resp_cancel.json()["state"] == "idle"
    finally:
        app.dependency_overrides.pop(get_updater_service, None)


def test_api_updater_apply_dry_run():
    """Verify POST /api/updater/apply accepts dry_run parameter."""
    client = TestClient(app)
    mock_service = MagicMock()
    mock_service.apply_update = AsyncMock(
        return_value=UpdateActionResponse(
            status="applying",
            message="Update helper launched successfully.",
        )
    )

    app.dependency_overrides[get_updater_service] = lambda: mock_service
    try:
        resp = client.post("/api/updater/apply", json={"dry_run": True})
        assert resp.status_code == 200
        assert resp.json()["status"] == "applying"
    finally:
        app.dependency_overrides.pop(get_updater_service, None)
