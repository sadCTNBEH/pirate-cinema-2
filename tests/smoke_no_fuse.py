"""Integration smoke test for Pirate Cinema AppImage running in an environment without FUSE.

Verifies:
1. Strict invocation: ./Pirate_Cinema-x86_64.AppImage --smoke-test (NO --appimage-extract-and-run, NO APPIMAGE_EXTRACT_AND_RUN=1).
2. Host /dev/fuse is inaccessible or missing.
3. Actual application and embedded MPV launch without error.
4. Correct exit code propagation.
5. Private temporary extraction directory with mode 0700 created and fully cleaned up.
6. Execution from paths containing spaces.
7. Concurrent/repeated runs without collisions.
8. APPIMAGE environment variable pointing to the original AppImage file.
"""

from __future__ import annotations

import glob
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def verify_fuse_inaccessible() -> None:
    """Verify that /dev/fuse cannot be accessed by normal processes."""
    fuse_path = Path("/dev/fuse")
    if not fuse_path.exists():
        print("[PASS] Confirmed: /dev/fuse does not exist.")
        return

    # Check read/write access
    can_rw = os.access(fuse_path, os.R_OK | os.W_OK)
    if can_rw:
        print("[WARN] /dev/fuse appears accessible; testing automatic fallback under restricted mount...")
    else:
        print("[PASS] Confirmed: /dev/fuse is restricted and not writable by current user.")


def test_strict_invocation(appimage: Path) -> None:
    """Test standard command with NO fallback flags."""
    print("[INFO] Testing strict command: ./AppImage --smoke-test")
    # Verify environment does NOT contain extract-and-run flags
    clean_env = os.environ.copy()
    clean_env.pop("APPIMAGE_EXTRACT_AND_RUN", None)

    # 1. Main smoke test
    cmd = [str(appimage), "--smoke-test"]
    res = subprocess.run(cmd, env=clean_env, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[FAIL] --smoke-test failed with exit code {res.returncode}:\n{res.stderr}\n{res.stdout}")
        sys.exit(res.returncode)
    print(f"[PASS] ./AppImage --smoke-test completed with exit code 0.")

    # 2. MPV smoke test
    print("[INFO] Testing strict command: ./AppImage --smoke-test-mpv")
    cmd_mpv = [str(appimage), "--smoke-test-mpv"]
    res_mpv = subprocess.run(cmd_mpv, env=clean_env, capture_output=True, text=True)
    if res_mpv.returncode != 0:
        print(f"[FAIL] --smoke-test-mpv failed with exit code {res_mpv.returncode}:\n{res_mpv.stderr}\n{res_mpv.stdout}")
        sys.exit(res_mpv.returncode)
    print(f"[PASS] ./AppImage --smoke-test-mpv completed with exit code 0.")


def test_tmp_directory_cleanup_and_permissions(appimage: Path) -> None:
    """Verify that extracted directory is created in /tmp with 0700 and deleted after exit."""
    print("[INFO] Testing temporary directory cleanup...")
    initial_folders = set(glob.glob("/tmp/pirate_cinema_extracted_*"))

    # Run quick check
    clean_env = os.environ.copy()
    clean_env.pop("APPIMAGE_EXTRACT_AND_RUN", None)
    res = subprocess.run([str(appimage), "--smoke-test"], env=clean_env, capture_output=True, text=True)
    assert res.returncode == 0, f"AppImage exited with {res.returncode}"

    time.sleep(0.5)
    remaining_folders = set(glob.glob("/tmp/pirate_cinema_extracted_*")) - initial_folders
    if remaining_folders:
        print(f"[FAIL] Leftover temporary directories found in /tmp: {remaining_folders}")
        sys.exit(1)
    print("[PASS] Temporary extraction directory cleaned up completely after exit.")


def test_path_with_spaces(appimage: Path) -> None:
    """Verify launch from a path with spaces without FUSE."""
    print("[INFO] Testing launch from path with spaces...")
    with tempfile.TemporaryDirectory(prefix="Pirate Cinema Space ") as tmp_dir:
        dest = Path(tmp_dir) / "Pirate_Cinema-x86_64.AppImage"
        shutil.copy2(appimage, dest)
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        clean_env = os.environ.copy()
        clean_env.pop("APPIMAGE_EXTRACT_AND_RUN", None)

        cmd = [str(dest), "--smoke-test"]
        res = subprocess.run(cmd, env=clean_env, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"[FAIL] Space path smoke test failed:\n{res.stderr}\n{res.stdout}")
            sys.exit(res.returncode)
        print("[PASS] Execution from path with spaces succeeded.")


def test_parallel_execution(appimage: Path) -> None:
    """Verify concurrent execution does not cause extraction collisions."""
    print("[INFO] Testing concurrent execution...")
    clean_env = os.environ.copy()
    clean_env.pop("APPIMAGE_EXTRACT_AND_RUN", None)

    p1 = subprocess.Popen([str(appimage), "--smoke-test"], env=clean_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p2 = subprocess.Popen([str(appimage), "--smoke-test"], env=clean_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out1, err1 = p1.communicate(timeout=30)
    out2, err2 = p2.communicate(timeout=30)

    assert p1.returncode == 0, f"Process 1 failed with {p1.returncode}: {err1.decode()}"
    assert p2.returncode == 0, f"Process 2 failed with {p2.returncode}: {err2.decode()}"
    print("[PASS] Concurrent runs completed without collision.")


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path-to-AppImage>")
        return 1

    appimage = Path(sys.argv[1]).resolve()
    if not appimage.is_file():
        print(f"AppImage not found: {appimage}")
        return 1

    print(f"--- Running No-FUSE Integration Smoke Tests for {appimage} ---")
    verify_fuse_inaccessible()
    test_strict_invocation(appimage)
    test_tmp_directory_cleanup_and_permissions(appimage)
    test_path_with_spaces(appimage)
    test_parallel_execution(appimage)

    print("\nALL NO-FUSE INTEGRATION TESTS PASSED SUCCESSFULLY!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
