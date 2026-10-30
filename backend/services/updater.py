"""In-App Updater Service for GitHub Releases."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import httpx

try:
    from packaging.version import InvalidVersion, Version
    from packaging.version import parse as parse_version
except ImportError:
    Version = None  # type: ignore
    InvalidVersion = ValueError  # type: ignore

    def parse_version(v: str) -> tuple[int, ...]:  # type: ignore
        parts = []
        for p in re.findall(r"\d+", v.lstrip("vV")):
            parts.append(int(p))
        return tuple(parts)

from backend import __version__
from backend.api.schemas.updater import (
    UpdateActionResponse,
    UpdateCheckResponse,
    UpdateStatusResponse,
)
from backend.core.settings import BASE_DIR, config, get_data_dir
from backend.services.update_helper import (
    generate_linux_helper_script,
    generate_windows_helper_script,
    launch_detached_helper,
    prepare_linux_bundle,
)

logger = logging.getLogger(__name__)


class UpdateError(RuntimeError):
    """Base exception for updater failures."""


class UpdateDownloadError(UpdateError):
    """Exception raised when downloading the release asset fails."""


class UpdateVerificationError(UpdateError):
    """Exception raised when integrity check fails."""


class UpdateInstallationError(UpdateError):
    """Exception raised when preparing or applying the update fails."""


def read_installed_version() -> str:
    """Read the current application version from local version.json."""
    candidates = [
        BASE_DIR / "version.json",
        Path(__file__).resolve().parent.parent.parent / "version.json",
        Path.cwd() / "version.json",
    ]
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.insert(0, Path(sys._MEIPASS) / "version.json")

    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                ver = data.get("version")
                if ver:
                    return str(ver).strip()
            except (OSError, json.JSONDecodeError) as e:
                logger.debug("Failed reading version from %s: %s", path, e)

    return str(__version__).strip() or "v0.1.1"


def is_version_newer(latest: str, current: str) -> bool:
    """Compare two version strings semantically, returning True if latest > current."""
    latest_clean = latest.lstrip("vV").strip()
    current_clean = current.lstrip("vV").strip()
    if not latest_clean or not current_clean:
        return False

    try:
        if Version is not None:
            return parse_version(latest_clean) > parse_version(current_clean)
        # Fallback numeric comparison
        def num_tuple(s: str) -> tuple[int, ...]:
            digits = re.findall(r"\d+", s)
            return tuple(int(d) for d in digits) if digits else (0,)

        return num_tuple(latest_clean) > num_tuple(current_clean)
    except (InvalidVersion, ValueError, TypeError) as err:
        logger.debug("Failed comparing versions %s and %s: %s", latest, current, err)
        return False


def get_appimage_path() -> Path | None:
    """Return path to host AppImage if running inside an AppImage environment."""
    appimage_env = os.environ.get("APPIMAGE")
    if appimage_env and appimage_env.strip():
        return Path(appimage_env.strip()).resolve()
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        if exe.name.lower().endswith(".appimage") or exe.suffix.lower() == ".appimage":
            return exe
    return None


def detect_installation_type() -> tuple[str, str | None, bool, str | None]:
    """Determine how the current application is running.

    Returns:
        (installation_type, expected_asset_name, can_auto_update, reason)
    """
    if not getattr(sys, "frozen", False):
        # Running directly from source (python -m run)
        asset_name = (
            "pirate-cinema-portable.exe"
            if sys.platform == "win32"
            else "Pirate_Cinema-x86_64.AppImage"
        )
        return (
            "development",
            asset_name,
            False,
            "development_mode",
        )

    exe_str = str(sys.executable).replace("\\", "/")
    exe_name = exe_str.split("/")[-1].lower()

    if sys.platform == "win32":
        if "portable" in exe_name:
            return ("windows_portable", "pirate-cinema-portable.exe", True, None)
        if exe_name == "pirate-cinema.exe":
            return ("windows_installer", "pirate-cinema-installer.exe", True, None)
        return ("windows_portable", "pirate-cinema-portable.exe", True, None)

    if sys.platform.startswith("linux"):
        appimage_path = get_appimage_path()
        if appimage_path is not None:
            can_write = True
            try:
                parent_dir = appimage_path.parent
                if parent_dir.exists() and not os.access(parent_dir, os.W_OK) or appimage_path.exists() and not os.access(appimage_path, os.W_OK):
                    can_write = False
            except OSError:
                can_write = False

            if not can_write:
                return (
                    "linux_appimage",
                    "Pirate_Cinema-x86_64.AppImage",
                    False,
                    "read_only_filesystem",
                )
            return (
                "linux_appimage",
                "Pirate_Cinema-x86_64.AppImage",
                True,
                None,
            )

        if "portable" in exe_name:
            return (
                "linux_portable",
                "pirate-cinema-portable-linux",
                True,
                None,
            )
        return ("linux_directory", "pirate-cinema-linux.tar.gz", True, None)

    return ("unsupported", None, False, "unsupported_platform")


class UpdaterService:
    """Manages release checks, asynchronous streaming downloads, SHA256 integrity,

    and atomic process replacement with automatic rollback.
    """

    def __init__(
        self,
        github_api_url: str | None = None,
        data_dir_provider: Callable[[], Path] | None = None,
        installed_version_provider: Callable[[], str] | None = None,
    ) -> None:
        self._github_url = github_api_url or config.GITHUB_API_URL
        self._get_data_dir = data_dir_provider or get_data_dir
        self._get_version = installed_version_provider or read_installed_version

        # Updater state
        self._state: str = "idle"
        self._current_check: UpdateCheckResponse | None = None
        self._downloaded_bytes: int = 0
        self._total_bytes: int | None = None
        self._progress_percent: float = 0.0
        self._error: str | None = None
        self._downloaded_file: Path | None = None
        self._active_download_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._exit_task: asyncio.Task[None] | None = None

    @property
    def state(self) -> str:
        return self._state

    def get_status(self) -> UpdateStatusResponse:
        """Return the current updater status snapshot."""
        target_version = self._current_check.version if self._current_check else None
        can_auto = (
            self._current_check.can_auto_update if self._current_check else False
        )
        asset_name = self._current_check.asset_name if self._current_check else None

        return UpdateStatusResponse(
            state=self._state,
            version=target_version,
            downloaded_bytes=self._downloaded_bytes,
            total_bytes=self._total_bytes,
            progress_percent=self._progress_percent,
            error=self._error,
            can_auto_update=can_auto,
            asset_name=asset_name,
        )

    async def check_for_updates(self) -> UpdateCheckResponse:
        """Query GitHub Releases API for newer stable releases."""
        async with self._lock:
            current_ver = self._get_version()
            _inst_type, asset_name, can_auto, reason = detect_installation_type()

            try:
                headers = {
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "Pirate-Cinema-Updater",
                }
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                    resp = await client.get(self._github_url, headers=headers)

                if resp.status_code == 403:
                    return UpdateCheckResponse(
                        current_version=current_ver,
                        has_update=False,
                        version="",
                        release_notes="",
                        download_url="",
                        release_url="",
                        asset_name=asset_name or "",
                        can_auto_update=False,
                        reason="github_rate_limited",
                    )
                if resp.status_code == 404:
                    return UpdateCheckResponse(
                        current_version=current_ver,
                        has_update=False,
                        version="",
                        release_notes="",
                        download_url="",
                        release_url="",
                        asset_name=asset_name or "",
                        can_auto_update=False,
                        reason="releases_not_found",
                    )

                resp.raise_for_status()
                data = resp.json()
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.HTTPStatusError,
                httpx.NetworkError,
                httpx.RequestError,
                json.JSONDecodeError,
            ) as req_err:
                logger.warning("Failed querying GitHub Releases: %s", req_err)
                return UpdateCheckResponse(
                    current_version=current_ver,
                    has_update=False,
                    version="",
                    release_notes="",
                    download_url="",
                    release_url="",
                    asset_name=asset_name or "",
                    can_auto_update=False,
                    reason=f"network_error: {req_err}",
                )

            # Skip draft or prerelease
            if data.get("draft") or data.get("prerelease"):
                return UpdateCheckResponse(
                    current_version=current_ver,
                    has_update=False,
                    version=data.get("tag_name", ""),
                    release_notes="",
                    download_url="",
                    release_url=data.get("html_url", ""),
                    asset_name=asset_name or "",
                    can_auto_update=False,
                    reason="prerelease_skipped",
                )

            tag_name = data.get("tag_name", "")
            has_update = is_version_newer(tag_name, current_ver)
            release_url = data.get("html_url", "")
            release_notes = data.get("body", "") or ""
            published_at = data.get("published_at")

            # Match binary asset
            matched_asset: dict[str, Any] | None = None
            assets = data.get("assets", [])
            if asset_name:
                for a in assets:
                    if a.get("name") == asset_name:
                        matched_asset = a
                        break

            if has_update and not matched_asset:
                can_auto = False
                reason = "asset_not_found"

            download_url = (
                matched_asset.get("browser_download_url", "") if matched_asset else ""
            )
            size_bytes = (
                matched_asset.get("size") if matched_asset else None
            )

            # Extract SHA-256 checksum
            sha256 = self._extract_sha256(matched_asset, assets, release_notes)
            if has_update and can_auto and not sha256:
                can_auto = False
                reason = "missing_checksum"

            result = UpdateCheckResponse(
                current_version=current_ver,
                has_update=has_update,
                version=tag_name,
                release_notes=release_notes,
                download_url=download_url,
                release_url=release_url,
                asset_name=asset_name or "",
                size_bytes=size_bytes,
                can_auto_update=can_auto,
                reason=reason,
                published_at=published_at,
                sha256=sha256,
            )

            self._current_check = result
            if has_update and self._state in ("idle", "checking"):
                self._state = "available"

            return result

    def _extract_sha256(
        self,
        asset: dict[str, Any] | None,
        all_assets: list[dict[str, Any]],
        release_notes: str,
    ) -> str | None:
        """Extract expected SHA-256 from asset digest, checksum files, or release notes."""
        if not asset:
            return None

        # 1. Direct asset digest (e.g. "sha256:ed81cacb...")
        digest = asset.get("digest")
        if digest and isinstance(digest, str) and digest.lower().startswith("sha256:"):
            return digest.split(":", 1)[1].strip().lower()

        # 2. Search in release notes for "<asset_name>: <hash>" or "<hash> <asset_name>"
        name = asset.get("name", "")
        if name and release_notes:
            escaped_name = re.escape(name)
            # Pattern 1: hash name
            match1 = re.search(
                rf"([a-fA-F0-9]{{64}})\s+[^\n]*{escaped_name}", release_notes
            )
            if match1:
                return match1.group(1).lower()
            # Pattern 2: name: hash
            match2 = re.search(
                rf"{escaped_name}[^\n]*[:\s]+([a-fA-F0-9]{{64}})", release_notes
            )
            if match2:
                return match2.group(1).lower()

        return None

    async def start_download(self) -> UpdateStatusResponse:
        """Start downloading the verified update asset in the background."""
        async with self._lock:
            if not self._current_check or not self._current_check.has_update:
                raise UpdateError("No update available to download.")

            if not self._current_check.can_auto_update or not self._current_check.download_url:
                raise UpdateError(
                    f"Auto-update is not supported: {self._current_check.reason or 'unsupported'}"
                )

            if self._state == "downloading" and self._active_download_task and not self._active_download_task.done():
                return self.get_status()

            if self._state == "ready" and self._downloaded_file and self._downloaded_file.is_file():
                return self.get_status()

            self._state = "downloading"
            self._downloaded_bytes = 0
            self._total_bytes = self._current_check.size_bytes
            self._progress_percent = 0.0
            self._error = None

            self._active_download_task = asyncio.create_task(self._download_worker())
            return self.get_status()

    async def _download_worker(self) -> None:
        """Streaming download worker with incremental SHA-256 calculation."""
        assert self._current_check is not None
        asset_url = self._current_check.download_url
        asset_name = self._current_check.asset_name
        expected_sha = self._current_check.sha256

        updates_dir = self._get_data_dir() / "updates"
        try:
            updates_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._state = "failed"
            self._error = f"Failed creating updates folder: {e}"
            return

        part_file = updates_dir / f"{asset_name}.part"
        final_file = updates_dir / asset_name

        try:
            hasher = hashlib.sha256()
            timeout = httpx.Timeout(connect=15.0, read=30.0, write=30.0, pool=30.0)

            async with (
                httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client,
                client.stream("GET", asset_url) as resp,
            ):
                resp.raise_for_status()

                # Resolve total bytes from headers if not known
                content_length = resp.headers.get("content-length")
                if content_length and content_length.isdigit():
                    self._total_bytes = int(content_length)

                async with await anyio.open_file(part_file, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        await f.write(chunk)
                        hasher.update(chunk)
                        self._downloaded_bytes += len(chunk)
                        if self._total_bytes:
                            self._progress_percent = round(
                                (self._downloaded_bytes / self._total_bytes) * 100, 1
                            )

            # Verify integrity
            self._state = "verifying"
            calc_sha = hasher.hexdigest().lower()
            if expected_sha and calc_sha != expected_sha.lower():
                try:
                    part_file.unlink(missing_ok=True)
                except OSError:
                    pass
                self._state = "failed"
                self._error = (
                    f"Integrity check failed: expected SHA-256 {expected_sha}, got {calc_sha}"
                )
                return

            # Rename .part to target
            if final_file.exists():
                try:
                    final_file.unlink()
                except OSError:
                    pass
            part_file.rename(final_file)

            self._downloaded_file = final_file
            self._progress_percent = 100.0
            self._state = "ready"
            self._error = None
            logger.info("Update asset verified and ready: %s", final_file)

        except (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.HTTPStatusError,
            httpx.NetworkError,
            httpx.RequestError,
            OSError,
        ) as err:
            logger.warning("Download failed for %s: %s", asset_name, err)
            try:
                part_file.unlink(missing_ok=True)
            except OSError:
                pass
            self._state = "failed"
            self._error = f"Download failed: {err}"

    async def cancel_download(self) -> UpdateStatusResponse:
        """Cancel ongoing download and clean up partial artifacts."""
        async with self._lock:
            if self._active_download_task and not self._active_download_task.done():
                self._active_download_task.cancel()
                try:
                    await self._active_download_task
                except (asyncio.CancelledError, RuntimeError):
                    pass

            if self._current_check:
                part_file = (
                    self._get_data_dir()
                    / "updates"
                    / f"{self._current_check.asset_name}.part"
                )
                try:
                    part_file.unlink(missing_ok=True)
                except OSError:
                    pass

            self._state = "idle"
            self._downloaded_bytes = 0
            self._progress_percent = 0.0
            self._error = None
            return self.get_status()

    async def apply_update(self, dry_run: bool = False) -> UpdateActionResponse:
        """Launch the detached external update helper and initiate clean application restart."""
        async with self._lock:
            if self._state != "ready" or not self._downloaded_file or not self._downloaded_file.is_file():
                raise UpdateInstallationError(
                    "Cannot apply update: no verified update file is ready for installation."
                )

            inst_type, _, can_auto, _ = detect_installation_type()
            if not can_auto and not dry_run:
                raise UpdateInstallationError(
                    "Automatic installation is not supported for this environment."
                )

            if inst_type == "linux_appimage":
                target_exe = get_appimage_path() or Path(sys.executable).resolve()
            else:
                target_exe = Path(sys.executable).resolve()
            new_file = self._downloaded_file.resolve()
            backup_file = target_exe.with_suffix(target_exe.suffix + ".bak")
            destination_parent = target_exe.parent.parent if inst_type in ("windows_installer", "linux_directory") else target_exe.parent
            if not dry_run and (not os.access(destination_parent, os.W_OK) or (target_exe.exists() and not os.access(target_exe, os.W_OK))):
                raise UpdateInstallationError(
                    f"Update requires write permission to {target_exe}. Install the update manually or use a user-writable installation folder."
                )

            updates_dir = self._get_data_dir() / "updates"
            updates_dir.mkdir(parents=True, exist_ok=True)
            log_file = updates_dir / "updater.log"

            pid = os.getpid()
            is_installer = inst_type == "windows_installer"

            # SQLite's backup API includes committed WAL data in the snapshot.
            try:
                db_path = self._get_data_dir() / "history.sqlite3"
                if db_path.is_file():
                    db_bak = db_path.with_suffix(".sqlite3.update_bak")
                    await anyio.to_thread.run_sync(self._backup_database, db_path, db_bak)
            except (OSError, sqlite3.Error) as db_bak_err:
                raise UpdateInstallationError(f"Cannot back up application database: {db_bak_err}") from db_bak_err

            if inst_type == "linux_directory":
                try:
                    new_file = await anyio.to_thread.run_sync(
                        prepare_linux_bundle, new_file, updates_dir, target_exe.name
                    )
                except (OSError, ValueError, tarfile.TarError) as error:
                    raise UpdateInstallationError(f"Invalid Linux update bundle: {error}") from error

            # 2. Generate platform helper script
            if sys.platform == "win32":
                script_path = updates_dir / "pirate_cinema_updater.ps1"
                generate_windows_helper_script(
                    script_path=script_path,
                    target_exe=target_exe,
                    new_file=new_file,
                    backup_file=backup_file,
                    pid=pid,
                    is_installer=is_installer,
                    log_file=log_file,
                )
            else:
                script_path = updates_dir / "pirate_cinema_updater.sh"
                generate_linux_helper_script(
                    script_path=script_path,
                    target_exe=target_exe,
                    new_file=new_file,
                    backup_file=backup_file,
                    pid=pid,
                    is_archive=(inst_type == "linux_directory"),
                    log_file=log_file,
                )

            # 3. Launch helper process detached
            if not dry_run:
                try:
                    launch_detached_helper(script_path)
                except OSError as launch_err:
                    self._state = "failed"
                    self._error = f"Failed launching updater helper: {launch_err}"
                    raise UpdateInstallationError(str(launch_err)) from launch_err

                # 4. Schedule graceful exit after short delay to allow HTTP response to return
                self._exit_task = asyncio.create_task(self._delayed_exit())

            self._state = "applying"

            return UpdateActionResponse(
                status="applying",
                message="Update helper launched successfully. Application is restarting.",
            )

    @staticmethod
    def _backup_database(source: Path, destination: Path) -> None:
        with sqlite3.connect(source) as original, sqlite3.connect(destination) as backup:
            original.backup(backup)

    async def _delayed_exit(self) -> None:
        """Gracefully close background services and exit main application."""
        await asyncio.sleep(0.6)
        try:
            from backend.api.deps import get_playback_service
            from backend.infrastructure.torrserver import process as torrserver_process

            try:
                await asyncio.wait_for(get_playback_service().stop_all(), timeout=5)
            except (OSError, RuntimeError, TimeoutError) as error:
                logger.warning("Error stopping playback for update: %s", error)
            await asyncio.wait_for(
                anyio.to_thread.run_sync(torrserver_process.stop), timeout=7
            )
        except (OSError, RuntimeError, TimeoutError) as error:
            logger.warning("Error shutting down for update: %s", error)
        finally:
            # An updater exit must bypass the user's minimize-to-tray close action.
            os._exit(0)
