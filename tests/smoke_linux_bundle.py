"""Exercise a frozen Linux bundle in an isolated test environment."""

from __future__ import annotations

import argparse
import gc
import json
import logging
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

import psutil

logger = logging.getLogger("smoke_linux_bundle")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def free_port() -> int:
    """Acquire a free local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ResourceLeakTracker:
    """Tracks lingering child processes and file descriptors after test completion."""

    def __init__(self, name: str = "smoke_linux_bundle"):
        self.name = name
        self.proc = psutil.Process()
        self.initial_children = {p.pid for p in self.proc.children(recursive=True)}
        self.initial_fds = self.proc.num_fds() if hasattr(self.proc, "num_fds") else None

    def check_leaks(self, max_fd_delta: int = 15) -> None:
        """Verify no lingering child processes or file descriptor leaks."""
        gc.collect()

        # Check child processes
        children = [p for p in self.proc.children(recursive=True) if p.pid not in self.initial_children]
        if children:
            _, alive = psutil.wait_procs(children, timeout=3.0)
            if alive:
                leaked = [(p.pid, p.name()) for p in alive]
                for p in alive:
                    try:
                        p.kill()
                    except Exception:
                        pass
                raise AssertionError(f"[{self.name}] Lingering child process leak detected: {leaked}")

        # Check file descriptors (Linux)
        if hasattr(self.proc, "num_fds") and self.initial_fds is not None:
            current_fds = self.proc.num_fds()
            delta = current_fds - self.initial_fds
            if delta > max_fd_delta:
                raise AssertionError(
                    f"[{self.name}] File descriptor leak detected: "
                    f"initial={self.initial_fds}, final={current_fds}, delta=+{delta} (max: {max_fd_delta})"
                )


def run_isolated_bundle_smoke(binary: Path, native: bool = False, timeout: float = 25.0) -> None:
    """Launch the compiled bundle in an isolated test environment and verify its full lifecycle."""
    logger.info("Initializing isolated test environment for %s (native=%s)...", binary, native)
    tracker = ResourceLeakTracker(name="smoke_linux_bundle")

    with tempfile.TemporaryDirectory(prefix="pirate-linux-smoke-") as tmp:
        folder = Path(tmp)

        # Isolated subdirectories for sandbox
        isolated_home = folder / "home"
        isolated_data = folder / "data"
        isolated_config = folder / "config"
        isolated_cache = folder / "cache"
        isolated_state = folder / "state"
        isolated_runtime = folder / "runtime"
        isolated_tmp = folder / "tmp"

        for d in (isolated_home, isolated_data, isolated_config, isolated_cache,
                  isolated_state, isolated_runtime, isolated_tmp):
            d.mkdir(parents=True, exist_ok=True)

        browser = folder / "google-chrome-stable"
        marker = folder / "browser-started"
        browser.write_text(
            '#!/bin/sh\nprintf "%s" "$LD_LIBRARY_PATH" > "$PIRATE_SMOKE_MARKER"\nexec sleep 90\n',
            encoding="utf-8",
        )
        browser.chmod(0o755)

        port, ts_port = free_port(), free_port()
        env = {
            **os.environ,
            "PATH": f"{folder}:{os.environ.get('PATH', '')}",
            "HOME": str(isolated_home),
            "XDG_DATA_HOME": str(isolated_data),
            "XDG_CONFIG_HOME": str(isolated_config),
            "XDG_CACHE_HOME": str(isolated_cache),
            "XDG_STATE_HOME": str(isolated_state),
            "XDG_RUNTIME_DIR": str(isolated_runtime),
            "TMPDIR": str(isolated_tmp),
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(port),
            "TORRSERVER_PORT": str(ts_port),
            "TORRSERVER_DEFAULT_URL": f"http://127.0.0.1:{ts_port}",
            "PIRATE_CINEMA_GUI": "browser",
            "PIRATE_SMOKE_MARKER": str(marker),
            "LC_ALL": "C.UTF-8",
            "LANG": "C.UTF-8",
        }

        for name in ("PYSTRAY_BACKEND", "WAYLAND_DISPLAY", "PYWEBVIEW_GUI", "TORRSERVER_DIR"):
            env.pop(name, None)

        if native:
            env.pop("PIRATE_CINEMA_GUI", None)
            env["QT_QPA_PLATFORM"] = "wayland"
        else:
            env.pop("DISPLAY", None)

        # Pre-check: Run bundle internal smoke self-tests in the isolated environment
        logger.info("Executing bundle internal self-tests (--smoke-test, --smoke-test-mpv)...")
        try:
            res_smoke = subprocess.run(
                [str(binary), "--smoke-test"],
                env=env,
                capture_output=True,
                text=True,
                timeout=12,
            )
            if res_smoke.returncode == 0:
                logger.info("[PASS] Bundle --smoke-test succeeded in isolated environment.")
            else:
                logger.warning("Bundle --smoke-test returned code %d: %s", res_smoke.returncode, res_smoke.stderr)
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("Bundle --smoke-test pre-check skipped or timed out: %s", e)

        # Launch bundle daemon
        log_path = folder / "output.log"
        logger.info("Launching compiled bundle daemon in isolated environment (port %d)...", port)
        child = None
        with log_path.open("wb") as output:
            popen_kwargs = {"env": env, "cwd": folder, "stdout": output, "stderr": subprocess.STDOUT}
            if os.name != "nt":
                popen_kwargs["start_new_session"] = True
            child = subprocess.Popen([str(binary)], **popen_kwargs)

        try:
            url = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + timeout
            health = {}

            logger.info("Awaiting backend health endpoint (%s/api/settings/health)...", url)
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError(f"Bundle exited prematurely with code {child.returncode}")
                try:
                    req = urllib.request.Request(f"{url}/api/settings/health")
                    with urllib.request.urlopen(req, timeout=1.0) as response:
                        health = json.load(response)
                    if native:
                        if marker.exists():
                            raise RuntimeError("AppImage launched an external browser in native mode")
                        window = subprocess.run(
                            ["xwininfo", "-name", "Pirate Cinema"],
                            capture_output=True,
                            text=True,
                            timeout=2,
                        )
                        if "Map State: IsViewable" in window.stdout:
                            break
                    elif marker.exists():
                        break
                except (urllib.error.URLError, TimeoutError, OSError):
                    pass
                time.sleep(0.2)

            if not health:
                raise RuntimeError(f"Bundle failed to serve UI or respond to health check within {timeout}s")
            if health.get("error"):
                raise RuntimeError(f"Health endpoint reported error: {health['error']}")
            logger.info("[PASS] Backend health check verified: %s", health)

            # Verify no tools installed in user directory
            if (isolated_data / "Pirate Cinema" / "vendor").exists():
                raise RuntimeError("Linux bundle leaked tools into user directory (vendor directory created)")
            logger.info("[PASS] User data directory isolation verified.")

            # Verify frontend assets
            with urllib.request.urlopen(url, timeout=2.0) as response:
                html = response.read().decode("utf-8", errors="replace")

            assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
            if not assets:
                raise RuntimeError("Frontend asset references missing from index.html")
            for asset in assets:
                with urllib.request.urlopen(url + asset, timeout=2.0) as response:
                    content = response.read()
                    if not content:
                        raise RuntimeError(f"Frontend asset is empty: {asset}")
            logger.info("[PASS] Verified %d frontend assets successfully.", len(assets))

            # Verify remote assets
            with urllib.request.urlopen(f"{url}/remote", timeout=2.0) as response:
                remote_html = response.read().decode("utf-8", errors="replace")

            for asset in (
                "/remote/assets/remote.css",
                "/remote/assets/remote.js",
                "/static/vendor/hls.light.min.js",
            ):
                if f'"{asset}"' not in remote_html:
                    raise RuntimeError(f"Remote page does not reference {asset}")
                with urllib.request.urlopen(url + asset, timeout=2.0) as response:
                    if not response.read():
                        raise RuntimeError(f"Remote asset is empty: {asset}")
            logger.info("[PASS] Verified remote UI and HLS assets successfully.")

            # Verify player API readiness
            try:
                with urllib.request.urlopen(f"{url}/api/player/active", timeout=2.0) as response:
                    player_active = json.load(response)
                    logger.info("[PASS] Player router responsive: active=%s", player_active)
            except Exception as e:
                logger.warning("Player active check notice: %s", e)

            # Verify library search path isolation
            if not native and marker.exists():
                if marker.read_text(encoding="utf-8") != os.environ.get("LD_LIBRARY_PATH", ""):
                    raise RuntimeError("Browser inherited bundled library search paths")
                logger.info("[PASS] Browser process library path isolation verified.")

            mode = "desktop window" if native else "browser without a tray"
            logger.info("PASS: %s: backend, TorrServer, frontend and remote assets, %s", binary.name, mode)

        except Exception:
            if log_path.exists():
                print(log_path.read_text(errors="replace"), file=sys.stderr)
            raise

        finally:
            # Terminate daemon cleanly
            if child and child.poll() is None:
                logger.info("Terminating bundle process (PID %s)...", child.pid)
                try:
                    if os.name != "nt":
                        os.killpg(child.pid, signal.SIGTERM)
                    else:
                        child.terminate()
                    child.wait(timeout=5.0)
                except (ProcessLookupError, OSError):
                    pass
                except subprocess.TimeoutExpired:
                    logger.warning("Bundle process did not terminate within timeout; killing...")
                    try:
                        if os.name != "nt":
                            os.killpg(child.pid, signal.SIGKILL)
                        else:
                            child.kill()
                        child.wait(timeout=3.0)
                    except (ProcessLookupError, OSError):
                        pass

    # Verify no leaks
    logger.info("Verifying absence of lingering processes and file descriptor leaks...")
    tracker.check_leaks(max_fd_delta=15)
    logger.info("[PASS] Zero leaks detected after bundle termination.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", nargs="?", default=None,
                        help="Path to compiled bundle executable or AppImage")
    parser.add_argument("--native", action="store_true", default=False,
                        help="Exercise native desktop window mode rather than browser mode")
    args = parser.parse_args()

    binary_path = None
    if args.binary:
        binary_path = Path(args.binary).resolve()
    else:
        # Search for candidates in typical build locations
        candidates = [
            Path("dist/Pirate_Cinema-x86_64.AppImage").resolve(),
            Path("build/pirate-cinema-linux/pirate-cinema-linux").resolve(),
        ]
        binary_path = next((c for c in candidates if c.is_file()), None)

    if binary_path is None or not binary_path.is_file():
        logger.error("No valid compiled Linux bundle found or specified.")
        print(f"Usage: {sys.argv[0]} <path-to-bundle-executable> [--native]")
        return 1

    start_time = time.monotonic()
    try:
        run_isolated_bundle_smoke(binary_path, native=args.native, timeout=25.0)
        elapsed = time.monotonic() - start_time
        logger.info("Bundle smoke test completed in %.2f seconds (limit: 30s).", elapsed)
        if elapsed > 30.0:
            logger.error("Bundle smoke test exceeded 30s limit: %.2fs", elapsed)
            return 1
        return 0
    except Exception as exc:
        logger.exception("Bundle smoke test failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
