"""Handle Flatpak desktop activation through the app's existing HTTP APIs."""

import logging
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

import run
from backend.core.settings import config, get_torrserver_url
from backend.infrastructure.torrserver.client import magnet_info_hash

logger = logging.getLogger(__name__)
MAX_TORRENT_SIZE = 16 * 1024 * 1024


def open_target(client: httpx.Client, app_url: str, target: str) -> None:
    uri = urlsplit(target)
    if uri.scheme == "magnet" and magnet_info_hash(target):
        response = client.post(f"{app_url}/api/player/add_magnet", json={"magnet": target})
    else:
        if uri.scheme not in ("", "file") or uri.netloc not in ("", "localhost"):
            raise ValueError("Expected a magnet link or a local .torrent file")
        path = Path(unquote(uri.path) if uri.scheme == "file" else target)
        if path.suffix.lower() != ".torrent" or not path.is_file():
            raise ValueError("Expected a .torrent file shared through the document portal")
        with path.open("rb") as source:
            torrent = source.read(MAX_TORRENT_SIZE + 1)
        if len(torrent) > MAX_TORRENT_SIZE:
            raise ValueError(".torrent file exceeds 16 MiB")
        response = client.post(
            f"{get_torrserver_url().rstrip('/')}/torrent/upload",
            files={"file": (path.name, torrent, "application/x-bittorrent")},
            data={"save": "1"},
        )
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict) or not result.get("hash"):
        raise ValueError("TorrServer rejected the torrent")


def deliver_target(target: str) -> None:
    app_url = f"http://127.0.0.1:{config.APP_PORT}"
    deadline = time.monotonic() + config.TORRSERVER_START_TIMEOUT + 15
    with httpx.Client(trust_env=False, timeout=config.TORRSERVER_HTTP_TIMEOUT) as client:
        while time.monotonic() < deadline:
            try:
                health = client.get(f"{app_url}/api/settings/health", timeout=1)
                health.raise_for_status()
            except httpx.RequestError:
                time.sleep(0.25)
                continue
            if health.json() != {"error": None}:
                raise RuntimeError("Pirate Cinema reports a TorrServer startup error")
            open_target(client, app_url, target)
            return
    raise TimeoutError("Pirate Cinema did not open its localhost API")


def main() -> int:
    config.MPV_ARGS = [*config.MPV_ARGS, f"--hwdec={os.getenv('PIRATE_CINEMA_HWDEC', 'auto')}"]
    if len(sys.argv) == 1 or sys.argv[1].startswith("--"):
        return run.main()

    failed = threading.Event()

    def deliver() -> None:
        try:
            deliver_target(sys.argv[1])
        except (OSError, ValueError, RuntimeError, httpx.HTTPError) as error:
            # Error messages from HTTP clients may contain private tracker URLs.
            logger.error("Desktop activation failed (%s)", type(error).__name__)
            failed.set()

    worker = threading.Thread(target=deliver, daemon=True)
    worker.start()
    status = run.main()
    worker.join()
    return status or int(failed.is_set())


if __name__ == "__main__":
    sys.exit(main())
