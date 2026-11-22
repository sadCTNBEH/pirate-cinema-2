import hashlib
import logging
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from backend.core.settings import get_data_dir
from backend.core.settings.config import config
from backend.infrastructure.instance_lock import instance_lock
from backend.infrastructure.process_env import system_process_env

logger = logging.getLogger(__name__)
LINUX_RELEASE_DOWNLOADS = "https://github.com/sadCTNBEH/pirate-cinema-2/releases/latest/download"
LINUX_VENDOR_PATH = Path("pirate-cinema-linux/_internal/vendor")
LINUX_MEDIA_ARCHIVES = ("pirate-cinema-linux-media-x86_64.tar.gz", "pirate-cinema-linux.tar.gz")

PINNED_CHECKSUMS = {
    "torrserver_win": "778bbc9bffb2e4d837a3a2c470fc2a4048d30f0a2004eb2553cd4a495b1bb2d6",
    "torrserver_linux": "0bbe73b2efc7391a59cd45adbb1bd6ed4b9571b7f62f04027a3e0ae41d23aa5d",
    "mpv_win": "4f431daae05d2c31c053f5d20750db70d43d7f38d2ed8fbde3b61f5ac8a0bd1f",
    "torrserver.exe": "778bbc9bffb2e4d837a3a2c470fc2a4048d30f0a2004eb2553cd4a495b1bb2d6",
    "torrserver": "0bbe73b2efc7391a59cd45adbb1bd6ed4b9571b7f62f04027a3e0ae41d23aa5d",
    "mpv.zip": "4f431daae05d2c31c053f5d20750db70d43d7f38d2ed8fbde3b61f5ac8a0bd1f",
}

VENDOR_MIRRORS = {
    "torrserver.exe": [
        config.TORRSERVER_WIN_URL,
        "https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/deps/TorrServer-windows-amd64.exe",
        "https://github.com/YouROK/TorrServer/releases/download/MatriX.145.2/TorrServer-windows-amd64.exe",
    ],
    "torrserver": [
        config.TORRSERVER_LINUX_URL,
        "https://github.com/YouROK/TorrServer/releases/download/MatriX.145.2/TorrServer-linux-amd64",
        "https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/deps/TorrServer-linux-amd64",
    ],
    "mpv.zip": [
        config.MPV_WIN_URL,
        "https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/deps/mpv-x86_64-20261004-git-413ff0b1cd.zip",
    ],
    "ffmpeg.zip": [
        config.FFMPEG_WIN_URL,
        "https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/deps/ffmpeg-release-essentials.zip",
        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    ],
}


def sha256_of_file(file_path: Path) -> str:
    """Calculate the lowercase SHA-256 hex digest of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def download_file(
    url: str,
    dest: Path,
    expected_sha256: str | None = None,
    mirrors: list[str] | None = None,
    timeout: int = 60,
    max_retries: int = 3,
) -> None:
    """Download a file with fallback mirrors, retries, and optional SHA-256 verification."""
    # Look up default checksum if not provided explicitly
    if expected_sha256 is None:
        expected_sha256 = PINNED_CHECKSUMS.get(dest.name)

    # Prepare candidate URLs (primary first, then unique mirrors)
    candidate_urls = [url]
    raw_mirrors = mirrors or VENDOR_MIRRORS.get(dest.name, [])
    for m in raw_mirrors:
        if m not in candidate_urls:
            candidate_urls.append(m)

    temp_dest = dest.with_suffix(dest.suffix + ".tmp")
    last_error: Exception | None = None

    for candidate_url in candidate_urls:
        for attempt in range(1, max_retries + 1):
            logger.info("Downloading %s to %s (attempt %d/%d)...", candidate_url, dest, attempt, max_retries)
            try:
                req = urllib.request.Request(
                    candidate_url,
                    headers={"User-Agent": "PirateCinema-Downloader/2.0"},
                )
                hasher = hashlib.sha256() if expected_sha256 else None
                with (
                    urllib.request.urlopen(req, timeout=timeout) as response,
                    open(temp_dest, "wb") as out_file,
                ):
                    while chunk := response.read(65536):
                        out_file.write(chunk)
                        if hasher:
                            hasher.update(chunk)

                if expected_sha256:
                    actual_sha256 = hasher.hexdigest().lower()
                    if actual_sha256 != expected_sha256.lower():
                        temp_dest.unlink(missing_ok=True)
                        msg = (
                            f"Checksum mismatch for {dest.name} from {candidate_url}: "
                            f"expected {expected_sha256.lower()}, got {actual_sha256}"
                        )
                        logger.warning("%s. Trying next mirror...", msg)
                        last_error = ValueError(msg)
                        break  # Break retry loop, try next mirror
                    logger.info("Verified SHA-256 for %s (%s)", dest.name, actual_sha256)

                temp_dest.replace(dest)
                return
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                temp_dest.unlink(missing_ok=True)
                logger.warning("Download failed for %s from %s (attempt %d): %s", dest.name, candidate_url, attempt, exc)
                last_error = exc

    temp_dest.unlink(missing_ok=True)
    logger.error("Failed to download and verify %s from all sources: %s", dest, candidate_urls)
    raise RuntimeError(f"Failed to download and verify binary from {candidate_urls}") from last_error


def _safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    """Безопасно извлекает zip-архив с защитой от Zip Slip."""
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        for member in zip_ref.infolist():
            member_path = (target_dir / member.filename).resolve()
            if not member_path.is_relative_to(target_dir.resolve()):
                raise RuntimeError(
                    f"Path traversal detected in zip archive: {member.filename}"
                )
        zip_ref.extractall(target_dir)


def ensure_torrserver_binary() -> Path:
    data_dir = get_data_dir()
    vendor_dir = data_dir / "vendor"
    vendor_dir.mkdir(parents=True, exist_ok=True)

    # TorrServer
    ts_dir = vendor_dir / "torrserver"
    ts_dir.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        ts_exe = ts_dir / "torrserver.exe"
        download_url = config.TORRSERVER_WIN_URL
        key = "torrserver.exe"
    else:
        ts_exe = ts_dir / "torrserver"
        download_url = config.TORRSERVER_LINUX_URL
        key = "torrserver"

    expected_sha256 = PINNED_CHECKSUMS.get(key)
    mirrors = VENDOR_MIRRORS.get(key, [])

    if ts_exe.exists() and expected_sha256:
        try:
            actual_sha256 = sha256_of_file(ts_exe)
            if actual_sha256 != expected_sha256.lower():
                logger.warning(
                    "Checksum mismatch on existing %s (%s != %s). Redownloading...",
                    ts_exe, actual_sha256, expected_sha256,
                )
                ts_exe.unlink()
        except OSError:
            pass

    if not ts_exe.exists():
        download_file(download_url, ts_exe, expected_sha256=expected_sha256, mirrors=mirrors)
        if sys.platform != "win32":
            try:
                os.chmod(ts_exe, 0o755)
            except OSError as e:
                logger.error(
                    "Failed to set executable permissions for %s: %s", ts_exe, e
                )

    return ts_exe


def ensure_ffmpeg_binaries() -> None:
    """Ensure ffmpeg and ffprobe are available, downloading if needed on Windows."""
    from backend.infrastructure.ffmpeg import find_binary

    if find_binary("ffmpeg") and find_binary("ffprobe"):
        return

    vendor_dir = get_data_dir() / "vendor"
    ffmpeg_dir = vendor_dir / "ffmpeg"
    ffmpeg_dir.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        ffmpeg_exe = ffmpeg_dir / "ffmpeg.exe"
        ffprobe_exe = ffmpeg_dir / "ffprobe.exe"
        if not (ffmpeg_exe.exists() and ffprobe_exe.exists()):
            zip_path = vendor_dir / "ffmpeg.zip"
            url = config.FFMPEG_WIN_URL
            try:
                download_file(url, zip_path)
                # Upstream archives put tools under a versioned bin/ directory.
                # Copy only the two CLI tools into the stable vendor location.
                with zipfile.ZipFile(zip_path) as archive:
                    for name in ('ffmpeg.exe', 'ffprobe.exe'):
                        member = next((m for m in archive.infolist() if Path(m.filename).name == name), None)
                        if member is None:
                            raise RuntimeError(f'{name} is missing from FFmpeg archive')
                        target = ffmpeg_dir / name
                        temporary = target.with_suffix('.exe.tmp')
                        with archive.open(member) as source, temporary.open('wb') as dest:
                            shutil.copyfileobj(source, dest)
                        temporary.replace(target)
            except (OSError, RuntimeError, zipfile.BadZipFile) as e:
                logger.warning("Could not auto-download FFmpeg binaries: %s", e)
            finally:
                if zip_path.exists():
                    try:
                        zip_path.unlink()
                    except OSError:
                        pass


def ensure_linux_media_tools() -> None:
    """Install missing Linux media tools from a checksummed Pirate Cinema release."""
    from backend.core.settings import find_mpv_binary
    from backend.infrastructure.ffmpeg import find_binary

    missing = {}
    if find_mpv_binary() is None:
        missing["mpv"] = ("mpv",)
    if not find_binary("ffmpeg") or not find_binary("ffprobe"):
        missing["ffmpeg"] = ("ffmpeg", "ffprobe")
    if not missing:
        return
    if platform.machine() != "x86_64":
        raise RuntimeError("Automatic Linux media tool downloads are available for x86_64")

    vendor_dir = get_data_dir() / "vendor"
    vendor_dir.mkdir(parents=True, exist_ok=True)
    with (
        instance_lock(vendor_dir / ".linux-media.lock"),
        tempfile.TemporaryDirectory(prefix=".linux-media-", dir=vendor_dir) as temporary,
    ):
        stage = Path(temporary)
        sums = stage / "SHA256SUMS"
        download_file(f"{LINUX_RELEASE_DOWNLOADS}/SHA256SUMS", sums)
        checksums = {}
        for line in sums.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) == 2:
                checksums[fields[1].lstrip("*")] = fields[0].lower()
        archive_name = next((name for name in LINUX_MEDIA_ARCHIVES if name in checksums), None)
        if archive_name is None:
            raise RuntimeError("Release checksums do not list a Linux media archive")

        archive_path = stage / archive_name
        download_file(f"{LINUX_RELEASE_DOWNLOADS}/{archive_name}", archive_path)
        with archive_path.open("rb") as archive_file:
            if hashlib.file_digest(archive_file, "sha256").hexdigest() != checksums[archive_name]:
                raise RuntimeError("Linux media archive checksum mismatch")

        extracted = stage / "extracted"
        with tarfile.open(archive_path, "r:gz") as archive:
            # The archive may hardlink byte-identical libraries across the two trees.
            # Extract both into staging, then publish only the tools that are missing.
            directories = [LINUX_VENDOR_PATH / tool for tool in ("mpv", "ffmpeg")]
            members = (item for item in archive if any(
                Path(item.name).is_relative_to(directory) for directory in directories
            ))
            archive.extractall(extracted, members=members, filter="data")

        for tool, commands in missing.items():
            source = extracted / LINUX_VENDOR_PATH / tool
            for command in commands:
                subprocess.run(
                    [str(source / command), "--version" if command == "mpv" else "-version"],
                    check=True, timeout=10, stdout=subprocess.DEVNULL, env=system_process_env(),
                )

        for tool in missing:
            target = vendor_dir / tool
            backup = stage / f"previous-{tool}"
            if target.exists() or target.is_symlink():
                target.rename(backup)
            try:
                (extracted / LINUX_VENDOR_PATH / tool).rename(target)
            except OSError:
                if backup.exists() or backup.is_symlink():
                    backup.rename(target)
                raise
            logger.info("Installed Linux media tools in %s", target)


def ensure_binaries() -> None:
    ensure_torrserver_binary()
    if sys.platform.startswith("linux"):
        ensure_linux_media_tools()
        return
    vendor_dir = get_data_dir() / "vendor"
    if sys.platform == "win32":
        mpv_dir = vendor_dir / "mpv"
        mpv_dir.mkdir(parents=True, exist_ok=True)
        mpv_exe = mpv_dir / "mpv.exe"

        if not mpv_exe.exists():
            zip_path = vendor_dir / "mpv.zip"
            mpv_url = config.MPV_WIN_URL
            expected_sha256 = PINNED_CHECKSUMS.get("mpv.zip")
            mirrors = VENDOR_MIRRORS.get("mpv.zip", [])
            try:
                download_file(mpv_url, zip_path, expected_sha256=expected_sha256, mirrors=mirrors)
                _safe_extract_zip(zip_path, mpv_dir)
            finally:
                if zip_path.exists():
                    try:
                        zip_path.unlink()
                    except OSError:
                        pass

    ensure_ffmpeg_binaries()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_binaries()
