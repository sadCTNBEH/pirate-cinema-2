"""Smoke test for self-contained embedded MPV.

Verifies that embedded MPV plays video without system MPV installed,
testing dependencies, version check, IPC pipe/socket communication,
the complete playback lifecycle:
  Launch -> MPV Init -> Media Load -> Seek -> Pause -> Stop -> Shutdown,
absence of process and file descriptor leaks,
and execution from paths with spaces.
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

logger = logging.getLogger("smoke_embedded_mpv")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class ResourceLeakTracker:
    """Tracks child processes, open file descriptors, and handles to detect leaks."""

    def __init__(self, name: str = "smoke_embedded_mpv"):
        self.name = name
        self.proc = psutil.Process()
        self.initial_children = {p.pid for p in self.proc.children(recursive=True)}
        self.initial_fds = self.proc.num_fds() if hasattr(self.proc, "num_fds") else None
        self.initial_handles = self.proc.num_handles() if hasattr(self.proc, "num_handles") else None
        try:
            self.initial_files = {f.path for f in self.proc.open_files()}
        except Exception:
            self.initial_files = set()

    def check_leaks(self, max_fd_delta: int = 10, max_handle_delta: int = 40) -> None:
        """Verify no lingering child processes, leaked fds, or leaked file handles."""
        gc.collect()

        # 1. Child processes leak check
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

        # 2. File descriptors leak check (Linux / macOS)
        if hasattr(self.proc, "num_fds") and self.initial_fds is not None:
            current_fds = self.proc.num_fds()
            delta_fds = current_fds - self.initial_fds
            if delta_fds > max_fd_delta:
                raise AssertionError(
                    f"[{self.name}] File descriptor leak detected: "
                    f"initial={self.initial_fds}, final={current_fds}, delta=+{delta_fds} (max: {max_fd_delta})"
                )

        # 3. Handle leak check (Windows)
        if hasattr(self.proc, "num_handles") and self.initial_handles is not None:
            current_handles = self.proc.num_handles()
            delta_handles = current_handles - self.initial_handles
            if delta_handles > max_handle_delta:
                raise AssertionError(
                    f"[{self.name}] Windows handle leak detected: "
                    f"initial={self.initial_handles}, final={current_handles}, delta=+{delta_handles} (max: {max_handle_delta})"
                )


def test_system_mpv_absent():
    """Verify that system mpv is NOT on PATH in clean Linux bundle test environment."""
    if sys.platform.startswith("linux"):
        which_mpv = shutil.which("mpv")
        if which_mpv:
            raise RuntimeError(
                f"System mpv found on PATH ({which_mpv}). "
                "Embedded MPV test must run in a clean environment without host system MPV."
            )
        logger.info("[PASS] Confirmed: system mpv is NOT installed on host PATH.")


def test_extracted_bundle_and_libraries(appimage: Path, extract_dir: Path) -> tuple[Path, Path | None]:
    """Extract AppImage and verify vendor/mpv, wrapper, and libraries."""
    logger.info("Extracting AppImage for static and dependency checks...")
    subprocess.run(
        [str(appimage), "--appimage-extract"],
        cwd=extract_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    squashfs = extract_dir / "squashfs-root"
    assert squashfs.is_dir(), "squashfs-root missing after extraction"

    mpv_wrapper = squashfs / "vendor" / "mpv" / "mpv"
    mpv_bin = squashfs / "vendor" / "mpv" / "mpv.bin"
    lib_dir = squashfs / "vendor" / "mpv" / "lib"

    assert mpv_wrapper.is_file(), f"Embedded MPV wrapper missing: {mpv_wrapper}"
    assert mpv_bin.is_file(), f"Embedded MPV binary missing: {mpv_bin}"
    assert lib_dir.is_dir(), f"Embedded MPV library folder missing: {lib_dir}"
    assert os.access(mpv_wrapper, os.X_OK), "MPV wrapper not executable"
    assert os.access(mpv_bin, os.X_OK), "MPV binary not executable"

    # Verify essential media libraries are present
    lib_names = [f.name for f in lib_dir.iterdir()]
    assert any("libavcodec" in name for name in lib_names), "libavcodec missing from bundled libraries"
    assert any("libavformat" in name for name in lib_names), "libavformat missing from bundled libraries"
    assert any("libavutil" in name for name in lib_names), "libavutil missing from bundled libraries"
    logger.info("[PASS] Embedded MPV layout valid. Found %d bundled library files in %s.", len(lib_names), lib_dir)

    # Verify custom cinema.lua OSD is bundled inside AppDir
    lua_candidates = [
        squashfs / "cinema.lua",
        squashfs / "_internal" / "backend" / "infrastructure" / "mpv" / "cinema.lua",
        squashfs / "backend" / "infrastructure" / "mpv" / "cinema.lua",
    ]
    cinema_lua = next((p for p in lua_candidates if p.is_file()), None)
    assert cinema_lua is not None, f"Custom cinema.lua OSD script missing from bundle: checked {lua_candidates}"
    logger.info("[PASS] Custom cinema.lua found in bundle: %s", cinema_lua.relative_to(squashfs))

    # Test direct execution of wrapper
    cmd = [str(mpv_wrapper), "--version"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    version_output = res.stdout.splitlines()[0] if res.stdout else ""
    logger.info("[PASS] Embedded mpv --version executed successfully: %s", version_output)
    return squashfs, cinema_lua


def test_ipc_playback(
    mpv_binary: Path,
    cinema_lua: Path | None = None,
    test_video: str | None = None,
) -> None:
    """Verify the full playback lifecycle via IPC:
    Launch -> MPV Init -> Media Load -> Seek -> Pause -> Stop -> Shutdown,
    and assert zero process or file descriptor leaks.
    """
    logger.info("Step 1: Launching MPV (%s) with IPC server...", mpv_binary)
    tracker = ResourceLeakTracker(name="smoke_embedded_mpv_ipc")

    ipc_sock: socket.socket | None = None
    ipc_file = None
    sock_path: Path | None = None
    pipe_name: str | None = None

    if os.name == "nt":
        pipe_name = rf"\\.\pipe\mpv-smoke-{os.getpid()}-{time.time_ns()}"
        ipc_endpoint = pipe_name
    else:
        sock_path = Path(f"/tmp/mpv-smoke-{os.getpid()}-{time.time_ns()}.sock")
        if sock_path.exists():
            sock_path.unlink()
        ipc_endpoint = str(sock_path)

    cmd = [
        str(mpv_binary),
        "--no-config",
        "--idle=yes",
        "--vo=null",
        "--ao=null",
        f"--input-ipc-server={ipc_endpoint}",
    ]
    if cinema_lua and cinema_lua.is_file():
        cmd.extend([
            "--osc=no",
            f"--script={cinema_lua}",
            "--msg-level=all=no,cplayer=info,lua=warn,cinema=warn",
        ])

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # Step 2: Initialize connection to MPV IPC
        logger.info("Step 2: Connecting to MPV IPC (%s)...", ipc_endpoint)
        deadline = time.monotonic() + 8.0
        connected = False

        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"MPV process exited prematurely with code {proc.returncode}")
            if os.name == "nt":
                try:
                    ipc_file = open(pipe_name, "r+b", buffering=0)
                    connected = True
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                if sock_path and sock_path.exists():
                    try:
                        ipc_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        ipc_sock.connect(str(sock_path))
                        ipc_file = ipc_sock.makefile("rwb", buffering=0)
                        connected = True
                        break
                    except OSError:
                        if ipc_sock:
                            ipc_sock.close()
                            ipc_sock = None
                        time.sleep(0.1)
                else:
                    time.sleep(0.1)

        assert connected and ipc_file is not None, "Failed to connect to MPV IPC server within deadline"
        logger.info("Step 2 PASS: Connected to MPV IPC server.")

        def send_command(command: list[any], timeout: float = 3.0) -> dict:
            payload = (json.dumps({"command": command}) + "\n").encode("utf-8")
            ipc_file.write(payload)
            start = time.monotonic()
            while time.monotonic() - start < timeout:
                line = ipc_file.readline()
                if not line:
                    time.sleep(0.05)
                    continue
                try:
                    data = json.loads(line.decode("utf-8", errors="replace"))
                    if "error" in data:
                        return data
                except json.JSONDecodeError:
                    continue
            return {"error": "timeout"}

        # Verify MPV responsiveness
        ver_resp = send_command(["get_property", "mpv-version"])
        assert ver_resp.get("error") == "success", f"MPV version probe failed: {ver_resp}"
        logger.info("Step 2 PASS: MPV responsive (version: %s).", ver_resp.get("data", "ok"))

        # Step 3: Media Load
        media = test_video or "av://lavfi:testsrc=duration=5:size=320x240:rate=25"
        logger.info("Step 3: Loading test media (%s)...", media)
        load_resp = send_command(["loadfile", media, "replace"])
        assert load_resp.get("error") == "success", f"Loadfile command failed: {load_resp}"
        send_command(["set_property", "pause", False])

        # Wait for media duration and active playback timecode
        timecode = None
        media_deadline = time.monotonic() + 10.0
        while time.monotonic() < media_deadline:
            pos_resp = send_command(["get_property", "playback-time"])
            if pos_resp.get("error") == "success" and isinstance(pos_resp.get("data"), (int, float)):
                if pos_resp["data"] > 0:
                    timecode = pos_resp["data"]
                    break
            time.sleep(0.1)

        assert timecode is not None, "Failed to verify playback timecode after loading test media"
        logger.info("Step 3 PASS: Test media loaded and decoding frames (playback-time: %.2fs).", timecode)

        # Step 4: Seek
        logger.info("Step 4: Executing seek to 2.0s...")
        seek_resp = send_command(["seek", 2.0, "absolute+exact"])
        assert seek_resp.get("error") == "success", f"Seek command failed: {seek_resp}"
        time.sleep(0.2)
        seek_pos = send_command(["get_property", "playback-time"])
        cur_pos = seek_pos.get("data")
        assert cur_pos is not None and cur_pos >= 1.5, f"Seek was not reflected via IPC: {seek_pos}"
        logger.info("Step 4 PASS: Seek verified at %.2fs.", cur_pos)

        # Step 5: Pause
        logger.info("Step 5: Pausing playback...")
        pause_resp = send_command(["set_property", "pause", True])
        assert pause_resp.get("error") == "success", f"Pause command failed: {pause_resp}"
        check_pause = send_command(["get_property", "pause"])
        assert check_pause.get("data") is True, f"Pause property is not true: {check_pause}"
        logger.info("Step 5 PASS: Playback pause verified.")

        # Step 6: Stop
        logger.info("Step 6: Stopping playback...")
        stop_resp = send_command(["stop"])
        assert stop_resp.get("error") == "success", f"Stop command failed: {stop_resp}"
        logger.info("Step 6 PASS: Playback stopped.")

        # Step 7: Shutdown
        logger.info("Step 7: Quitting MPV and verifying clean exit...")
        send_command(["quit"])
        proc.wait(timeout=5)
        assert proc.returncode == 0, f"MPV exited with non-zero code {proc.returncode}"
        logger.info("Step 7 PASS: MPV exited cleanly with code 0.")

    finally:
        if ipc_file:
            try:
                ipc_file.close()
            except Exception:
                pass
        if ipc_sock:
            try:
                ipc_sock.close()
            except Exception:
                pass
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)
        if sock_path and sock_path.exists():
            try:
                sock_path.unlink()
            except Exception:
                pass

    # Verify no leaks
    logger.info("Verifying absence of process and file descriptor/handle leaks...")
    tracker.check_leaks(max_fd_delta=10, max_handle_delta=40)
    logger.info("[PASS] Full embedded MPV lifecycle verified without leaks!")


def test_appimage_smoke_modes(appimage: Path) -> None:
    """Test standard execution, extract-and-run, and paths with spaces."""
    logger.info("Running AppImage smoke self-tests...")

    # 1. Standard smoke test
    subprocess.run([str(appimage), "--smoke-test"], check=True, timeout=15)
    subprocess.run([str(appimage), "--smoke-test-mpv"], check=True, timeout=15)
    logger.info("[PASS] AppImage --smoke-test and --smoke-test-mpv succeeded.")

    # 2. Extract and run mode (FUSE-less)
    subprocess.run(
        [str(appimage), "--appimage-extract-and-run", "--smoke-test-mpv"],
        check=True,
        timeout=15,
    )
    logger.info("[PASS] AppImage --appimage-extract-and-run --smoke-test-mpv succeeded.")

    # 3. Path with spaces
    with tempfile.TemporaryDirectory(prefix="Pirate Cinema Space ", ignore_cleanup_errors=True) as tmp_space:
        space_path = Path(tmp_space) / "Pirate_Cinema-x86_64.AppImage"
        shutil.copy2(appimage, space_path)
        space_path.chmod(0o755)

        subprocess.run(
            [str(space_path), "--appimage-extract-and-run", "--smoke-test-mpv"],
            check=True,
            timeout=15,
        )
        logger.info("[PASS] AppImage execution from path with spaces verified.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=None,
                        help="Path to AppImage or MPV executable")
    parser.add_argument("--mpv", dest="mpv_path", default=None,
                        help="Explicit path to MPV executable to test directly")
    parser.add_argument("--video", dest="video_path", default=None,
                        help="Path to mock video file")
    args = parser.parse_args()

    start_time = time.monotonic()
    try:
        target_path = Path(args.target).resolve() if args.target else None
        mpv_path = Path(args.mpv_path).resolve() if args.mpv_path else None

        # Check if target is an AppImage
        is_appimage = (target_path and target_path.is_file() and
                       (target_path.suffix.lower() == ".appimage" or "appimage" in target_path.name.lower()))

        if is_appimage:
            logger.info("Running full AppImage test suite on %s...", target_path)
            test_system_mpv_absent()
            with tempfile.TemporaryDirectory(prefix="mpv-extract-smoke-", ignore_cleanup_errors=True) as tmp:
                squashfs, cinema_lua = test_extracted_bundle_and_libraries(target_path, Path(tmp))
                test_ipc_playback(
                    squashfs / "vendor" / "mpv" / "mpv",
                    cinema_lua=cinema_lua,
                    test_video=args.video_path,
                )
            test_appimage_smoke_modes(target_path)
        else:
            # Standalone MPV binary smoke test
            binary = mpv_path or target_path
            if binary is None or not binary.is_file():
                # Attempt to find local embedded mpv
                candidates = [
                    Path("mpv/mpv.exe").resolve(),
                    Path("vendor/mpv/mpv").resolve(),
                    Path("dist/Pirate_Cinema-x86_64.AppImage").resolve(),
                ]
                binary = next((c for c in candidates if c.is_file()), None)

            if binary is None:
                logger.error("No AppImage or MPV binary specified or found.")
                print(f"Usage: {sys.argv[0]} <path-to-AppImage | path-to-mpv-binary>")
                return 1

            if binary.suffix.lower() == ".appimage":
                return main_with_appimage(binary, args.video_path)

            logger.info("Running standalone IPC playback lifecycle smoke on %s...", binary)
            cinema_lua = Path("backend/infrastructure/mpv/cinema.lua").resolve()
            test_ipc_playback(
                binary,
                cinema_lua=cinema_lua if cinema_lua.is_file() else None,
                test_video=args.video_path,
            )

        elapsed = time.monotonic() - start_time
        logger.info("\nALL EMBEDDED MPV SMOKE TESTS PASSED SUCCESSFULLY in %.2f seconds (limit: 30s)!", elapsed)
        if elapsed > 30.0:
            logger.error("Test exceeded 30s limit: %.2fs", elapsed)
            return 1
        return 0

    except Exception as exc:
        logger.exception("Embedded MPV smoke test failed: %s", exc)
        return 1


def main_with_appimage(appimage: Path, video_path: str | None) -> int:
    test_system_mpv_absent()
    with tempfile.TemporaryDirectory(prefix="mpv-extract-smoke-", ignore_cleanup_errors=True) as tmp:
        squashfs, cinema_lua = test_extracted_bundle_and_libraries(appimage, Path(tmp))
        test_ipc_playback(
            squashfs / "vendor" / "mpv" / "mpv",
            cinema_lua=cinema_lua,
            test_video=video_path,
        )
    test_appimage_smoke_modes(appimage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
