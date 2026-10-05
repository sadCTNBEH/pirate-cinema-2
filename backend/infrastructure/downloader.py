import logging
import os
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from backend.core.settings import get_data_dir
from backend.core.settings.config import config

logger = logging.getLogger(__name__)


def download_file(url: str, dest: Path) -> None:
    logger.info("Downloading %s to %s...", url, dest)
    temp_dest = dest.with_suffix(dest.suffix + ".tmp")

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response, open(
            temp_dest, "wb"
        ) as out_file:
            shutil.copyfileobj(response, out_file)
        temp_dest.replace(dest)
    except (urllib.error.URLError, OSError) as e:
        if temp_dest.exists():
            try:
                temp_dest.unlink()
            except OSError:
                pass
        logger.error("Failed to download %s: %s", url, e)
        raise RuntimeError(f"Failed to download binary from {url}") from e


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


def ensure_binaries() -> None:
    data_dir = get_data_dir()
    vendor_dir = data_dir / "vendor"
    vendor_dir.mkdir(parents=True, exist_ok=True)

    # TorrServer
    ts_dir = vendor_dir / "torrserver"
    ts_dir.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        ts_exe = ts_dir / "torrserver.exe"
        download_url = config.TORRSERVER_WIN_URL
    else:
        ts_exe = ts_dir / "torrserver"
        download_url = config.TORRSERVER_LINUX_URL

    if not ts_exe.exists():
        download_file(download_url, ts_exe)
        if sys.platform != "win32":
            try:
                os.chmod(ts_exe, 0o755)
            except OSError as e:
                logger.error("Failed to set executable permissions for %s: %s", ts_exe, e)

    # MPV (Windows only for now, Linux uses system mpv)
    if sys.platform == "win32":
        mpv_dir = vendor_dir / "mpv"
        mpv_dir.mkdir(parents=True, exist_ok=True)
        mpv_exe = mpv_dir / "mpv.exe"

        if not mpv_exe.exists():
            zip_path = vendor_dir / "mpv.zip"
            mpv_url = config.MPV_WIN_URL
            try:
                download_file(mpv_url, zip_path)
                _safe_extract_zip(zip_path, mpv_dir)
            finally:
                if zip_path.exists():
                    try:
                        zip_path.unlink()
                    except OSError:
                        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_binaries()
