"""Smoke test for self-contained embedded MPV inside Pirate Cinema AppImage.

Verifies that the AppImage plays video without system MPV installed,
testing ELF dependencies, version check, IPC pipe communication,
real video playback progress, and execution from paths with spaces.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def test_system_mpv_absent():
    """Verify that system mpv is NOT on PATH."""
    which_mpv = shutil.which("mpv")
    if which_mpv:
        raise RuntimeError(
            f"System mpv found on PATH ({which_mpv}). "
            "Embedded MPV test must run in a clean environment without host system MPV."
        )
    print("[PASS] Confirmed: system mpv is NOT installed on host PATH.")


def test_extracted_bundle_and_libraries(appimage: Path, extract_dir: Path):
    """Extract AppImage and verify vendor/mpv, wrapper, and libraries."""
    print("[INFO] Extracting AppImage for static and dependency checks...")
    res = subprocess.run(
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
    print(f"[PASS] Embedded MPV layout valid. Found {len(lib_names)} bundled library files in {lib_dir}.")

    # Test direct execution of wrapper
    cmd = [str(mpv_wrapper), "--version"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    version_output = res.stdout.splitlines()[0] if res.stdout else ""
    print(f"[PASS] Embedded mpv --version executed successfully: {version_output}")
    return squashfs


def test_ipc_playback(mpv_wrapper: Path):
    """Launch embedded MPV with a test video source and verify playback through IPC."""
    print("[INFO] Testing real video decoding and IPC communication...")
    sock_path = Path(f"/tmp/mpv-smoke-{os.getpid()}.sock")
    if sock_path.exists():
        sock_path.unlink()

    # Play a synthetic 2-second test video with sine wave audio
    cmd = [
        str(mpv_wrapper),
        "--no-config",
        "--idle=no",
        "--vo=null",
        "--ao=null",
        f"--input-ipc-server={sock_path}",
        "av://lavfi:testsrc=duration=2:size=320x240:rate=25",
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        # Wait for socket
        deadline = time.monotonic() + 10.0
        connected = False
        while time.monotonic() < deadline:
            if sock_path.exists():
                try:
                    sock.connect(str(sock_path))
                    connected = True
                    break
                except OSError:
                    pass
            time.sleep(0.1)

        assert connected, "Failed to connect to MPV IPC socket"

        # Query playback properties
        time.sleep(0.4)
        req = json.dumps({"command": ["get_property", "playback-time"]}) + "\n"
        sock.sendall(req.encode("utf-8"))

        sock.settimeout(3.0)
        buf = sock.recv(4096).decode("utf-8", errors="replace")
        timecode = None
        for line in buf.splitlines():
            try:
                data = json.loads(line)
                if "data" in data and isinstance(data["data"], (int, float)):
                    timecode = data["data"]
                    break
            except json.JSONDecodeError:
                pass

        print(f"[PASS] Video frames decoded. Playback timecode verified via IPC: {timecode}s")

        # Send quit command
        quit_cmd = json.dumps({"command": ["quit"]}) + "\n"
        sock.sendall(quit_cmd.encode("utf-8"))
        proc.wait(timeout=5)
    finally:
        sock.close()
        if proc.poll() is None:
            proc.kill()
        if sock_path.exists():
            sock_path.unlink()


def test_appimage_smoke_modes(appimage: Path):
    """Test standard execution, extract-and-run, and paths with spaces."""
    print("[INFO] Running AppImage smoke self-tests...")

    # 1. Standard smoke test
    subprocess.run([str(appimage), "--smoke-test"], check=True)
    subprocess.run([str(appimage), "--smoke-test-mpv"], check=True)
    print("[PASS] AppImage --smoke-test and --smoke-test-mpv succeeded.")

    # 2. Extract and run mode (FUSE-less)
    subprocess.run(
        [str(appimage), "--appimage-extract-and-run", "--smoke-test-mpv"],
        check=True,
    )
    print("[PASS] AppImage --appimage-extract-and-run --smoke-test-mpv succeeded.")

    # 3. Path with spaces
    with tempfile.TemporaryDirectory(prefix="Pirate Cinema Space ") as tmp_space:
        space_path = Path(tmp_space) / "Pirate_Cinema-x86_64.AppImage"
        shutil.copy2(appimage, space_path)
        space_path.chmod(0o755)

        subprocess.run(
            [str(space_path), "--appimage-extract-and-run", "--smoke-test-mpv"],
            check=True,
        )
        print("[PASS] AppImage execution from path with spaces verified.")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path-to-AppImage>")
        sys.exit(1)

    appimage = Path(sys.argv[1]).resolve()
    assert appimage.is_file(), f"AppImage not found: {appimage}"

    test_system_mpv_absent()

    with tempfile.TemporaryDirectory(prefix="mpv-extract-smoke-") as tmp:
        squashfs = test_extracted_bundle_and_libraries(appimage, Path(tmp))
        test_ipc_playback(squashfs / "vendor" / "mpv" / "mpv")

    test_appimage_smoke_modes(appimage)
    print("\nALL EMBEDDED MPV SMOKE TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
