"""Exercise a frozen Linux bundle in browser mode or its default desktop mode."""

import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    binary = Path(sys.argv[1]).resolve()
    native = sys.argv[2:] == ["--native"]
    with tempfile.TemporaryDirectory(prefix="pirate-linux-smoke-") as tmp:
        folder = Path(tmp)
        browser = folder / "google-chrome-stable"
        marker = folder / "browser-started"
        browser.write_text('#!/bin/sh\nprintf "%s" "$LD_LIBRARY_PATH" > "$PIRATE_SMOKE_MARKER"\nexec sleep 90\n')
        browser.chmod(0o755)
        port, ts_port = free_port(), free_port()
        env = {**os.environ, "PATH": f"{folder}:{os.environ['PATH']}",
               "XDG_DATA_HOME": str(folder / "data"), "APP_HOST": "127.0.0.1",
               "APP_PORT": str(port), "TORRSERVER_PORT": str(ts_port),
               "TORRSERVER_DEFAULT_URL": f"http://127.0.0.1:{ts_port}",
               "PIRATE_CINEMA_GUI": "browser", "PIRATE_SMOKE_MARKER": str(marker)}
        for name in ("PYSTRAY_BACKEND", "WAYLAND_DISPLAY", "PYWEBVIEW_GUI"):
            env.pop(name, None)
        if native:
            env.pop("PIRATE_CINEMA_GUI")
            env["QT_QPA_PLATFORM"] = "wayland"
        else:
            env.pop("DISPLAY", None)
        with (folder / "output.log").open("wb") as output:
            child = subprocess.Popen([str(binary)], env=env, cwd=folder, stdout=output,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        try:
            url = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 60
            while True:
                if child.poll() is not None:
                    raise RuntimeError("Bundle exited before opening UI")
                try:
                    with urllib.request.urlopen(url + "/api/settings/health", timeout=1) as response:
                        health = json.load(response)
                    if native:
                        if marker.exists():
                            raise RuntimeError("AppImage launched an external browser")
                        window = subprocess.run(
                            ["xwininfo", "-name", "Pirate Cinema"],
                            capture_output=True, text=True, timeout=2,
                        )
                        if "Map State: IsViewable" in window.stdout:
                            break
                    elif marker.exists():
                        break
                except (urllib.error.URLError, TimeoutError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Bundle failed to serve UI or open a window within 60 seconds")
                time.sleep(0.2)
            if health.get("error"):
                raise RuntimeError(health["error"])
            if (folder / "data" / "Pirate Cinema" / "vendor").exists():
                raise RuntimeError("Linux bundle installed tools in the user directory")
            with urllib.request.urlopen(url, timeout=2) as response:
                html = response.read().decode()
            assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
            if not assets:
                raise RuntimeError("Frontend asset references missing")
            for asset in assets:
                with urllib.request.urlopen(url + asset, timeout=2) as response:
                    if not response.read():
                        raise RuntimeError(f"Frontend asset is empty: {asset}")
            with urllib.request.urlopen(url + "/remote", timeout=2) as response:
                remote = response.read().decode()
            for asset in ("/remote/assets/remote.css", "/remote/assets/remote.js",
                          "/static/vendor/hls.light.min.js"):
                if f'"{asset}"' not in remote:
                    raise RuntimeError(f"Remote page does not reference {asset}")
                with urllib.request.urlopen(url + asset, timeout=2) as response:
                    if not response.read():
                        raise RuntimeError(f"Remote asset is empty: {asset}")
            if not native and marker.read_text() != os.environ.get("LD_LIBRARY_PATH", ""):
                raise RuntimeError("Browser inherited bundled library search paths")
            mode = "desktop window" if native else "browser without a tray"
            print(f"PASS: {binary.name}: backend, TorrServer, frontend and remote assets, {mode}")
        except Exception:
            print((folder / "output.log").read_text(errors="replace"), file=sys.stderr)
            raise
        finally:
            try:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=10)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)


if __name__ == "__main__":
    main()
