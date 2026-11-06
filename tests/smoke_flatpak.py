"""Smoke-test an installed bundle with an X11 display and a session D-Bus."""

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from smoke_linux_bundle import free_port

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=3) as response:
        return response.read()


def wait_for_ui(child, app_url):
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline and child.poll() is None:
        try:
            health = json.loads(request(app_url + "/api/settings/health"))
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.2)
            continue
        if health["error"]:
            raise RuntimeError(health["error"])
        window = subprocess.run(
            ["xwininfo", "-name", "Pirate Cinema"], capture_output=True, text=True, timeout=2,
        )
        if "Map State: IsViewable" in window.stdout:
            return
        time.sleep(0.2)
    raise RuntimeError("Flatpak failed to open the desktop UI and serve its local API")


def stop(app_id, child):
    subprocess.run(["flatpak", "kill", app_id], timeout=10, check=False)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)


def check_desktop_open(run, app_id, folder, ts_url):
    # A synthetic one-piece torrent provides metadata without requiring a tracker.
    info = b"d6:lengthi1e4:name9:smoke.mp412:piece lengthi16384e6:pieces20:" + b"x" * 20 + b"e"
    torrent = folder / "sample with spaces.torrent"
    torrent.write_bytes(b"d4:info" + info + b"e")
    torrent_hash = hashlib.sha1(info, usedforsecurity=False).hexdigest()
    desktop = Path(subprocess.check_output(
        ["flatpak", "info", "--user", "--show-location", app_id], text=True,
    ).strip()) / "export" / "share" / "applications" / f"{app_id}.desktop"
    exported = desktop.read_text()
    assert "x-scheme-handler/magnet;" in exported and "application/x-bittorrent;" in exported
    assert "--file-forwarding" in exported

    def check_torrent():
        status = json.loads(request(ts_url + "/torrents", {"action": "get", "hash": torrent_hash}))
        assert status["hash"].lower() == torrent_hash, status

    desktop_run = [*run[:2], "--file-forwarding", *run[2:], "@@u"]
    subprocess.run([*desktop_run, torrent.as_uri(), "@@"], check=True, timeout=45)
    check_torrent()
    subprocess.run(
        [*desktop_run, f"magnet:?xt=urn:btih:{torrent_hash}", "@@"], check=True, timeout=45,
    )
    check_torrent()
    print("PASS: exported MIME handlers, document portal file forwarding and magnet activation")


def main():
    app_id = sys.argv[1]
    subprocess.run(
        ["flatpak", "run", "--command=sh", app_id, "-ec", """
            test -x /app/share/pirate-cinema/vendor/torrserver/torrserver
            /app/bin/mpv --version
            /app/bin/mpv --hwdec=help
            /app/bin/ffmpeg -version
            /app/bin/ffprobe -version
            ldd /app/bin/mpv | grep -F "libavcodec.so" | grep -F /app/lib/pirate-cinema-media/
            cd /app/share/pirate-cinema
            PYTHONPATH=/app/lib/pirate-cinema-python python3 -c '
from backend.services.updater import detect_installation_type
assert detect_installation_type()[:3] == ("linux_flatpak", "Pirate_Cinema-x86_64.flatpak", False)
'
        """],
        check=True,
        timeout=15,
    )
    port, ts_port = free_port(), free_port()
    app_url, ts_url = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{ts_port}"
    run = [
        "flatpak", "run", "--env=APP_HOST=127.0.0.1", f"--env=APP_PORT={port}",
        f"--env=TORRSERVER_PORT={ts_port}", f"--env=TORRSERVER_DEFAULT_URL={ts_url}", app_id,
    ]
    with tempfile.TemporaryDirectory(prefix="pirate-flatpak-") as tmp:
        folder = Path(tmp)
        log = folder / "app.log"
        for restart in (False, True):
            with log.open("wb") as output:
                child = subprocess.Popen(run, stdout=output, stderr=subprocess.STDOUT)
            try:
                wait_for_ui(child, app_url)
                assert b"MatriX.145.2" in request(ts_url + "/echo")
                html = request(app_url)
                assets = re.findall(rb'(?:src|href)="(/assets/[^"]+)"', html)
                assert assets and all(request(app_url + asset.decode()) for asset in assets)
                settings_url = app_url + "/api/settings"
                if not restart:
                    request(settings_url, {"seek_step": 30})
                    check_desktop_open(run, app_id, folder, ts_url)
                assert json.loads(request(settings_url))["seek_step"] == 30
            except Exception:
                print(log.read_text(errors="replace"), file=sys.stderr)
                raise
            finally:
                stop(app_id, child)
        print("PASS: desktop launch, UI assets, TorrServer and settings persisted after restart")


if __name__ == "__main__":
    main()
