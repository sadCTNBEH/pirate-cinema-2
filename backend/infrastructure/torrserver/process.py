"""TorrServer process manager – mirrors torrserver_process.rs."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib import error, request

from backend.core.config import BASE_DIR

DEFAULT_URL = "http://127.0.0.1:8090"

_process: subprocess.Popen | None = None


def _probe(url: str = DEFAULT_URL) -> bool:
    try:
        request.urlopen(f"{url.rstrip('/')}/echo", timeout=4)
        return True
    except (error.URLError, error.HTTPError):
        return False


def bundled_executable() -> Path:
    here = BASE_DIR
    if sys.platform == "win32":
        return here / "vendor" / "torrserver" / "torrserver.exe"
    return here / "vendor" / "torrserver" / "torrserver"


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", Path.home())
    else:
        base = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    return Path(base) / "Pirate Cinema" / "torrserver"


def connect_or_start(url: str = DEFAULT_URL, executable: Path | None = None, data_dir: Path | None = None) -> bool:
    """Returns True if TorrServer is ready. Raises on unrecoverable error."""
    global _process

    if _probe(url):
        return True

    if url.rstrip('/') != DEFAULT_URL.rstrip('/'):
        raise RuntimeError("Custom TorrServer endpoint not responding; auto-start only on 127.0.0.1:8090")

    # Check port available
    try:
        s = socket.socket()
        s.bind(("127.0.0.1", 8090))
        s.close()
    except OSError:
        raise RuntimeError("Port 8090 is occupied but TorrServer isn't responding. Check existing services.")

    executable = executable or bundled_executable()
    if not executable.is_file():
        raise RuntimeError(f"TorrServer binary not found: {executable}")

    data_dir = data_dir or default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    kwargs: dict = {
        "cwd": str(data_dir),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x0800_0000  # CREATE_NO_WINDOW

    _process = subprocess.Popen([str(executable)], **kwargs)

    deadline = time.time() + 30
    while time.time() < deadline:
        if _probe(url):
            try:
                _optimize_settings(url)
            except (error.URLError, error.HTTPError, json.JSONDecodeError) as e:
                print(f"[WARN] Failed to optimize TorrServer: {e}")
            return True
        if _process.poll() is not None:
            raise RuntimeError(f"TorrServer exited with code {_process.returncode}")
        time.sleep(0.3)

    _process.kill()
    raise RuntimeError("TorrServer did not become ready in 30s")


def stop():
    global _process
    if _process and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.kill()
    _process = None


def _optimize_settings(url: str):
    req = request.Request(f"{url.rstrip('/')}/settings", data=json.dumps({"action": "get"}).encode(), headers={'Content-Type': 'application/json'})
    with request.urlopen(req, timeout=5) as res:
        settings = json.loads(res.read())
        
    changed = False
    if settings.get("ConnectionsLimit") < 200:
        settings["ConnectionsLimit"] = 400
        changed = True
    if settings.get("DisableUTP") is True:
        settings["DisableUTP"] = False
        changed = True
        
    if changed:
        req_set = request.Request(f"{url.rstrip('/')}/settings", data=json.dumps({"action": "set", "sets": settings}).encode(), headers={'Content-Type': 'application/json'})
        with request.urlopen(req_set, timeout=5):
            pass
