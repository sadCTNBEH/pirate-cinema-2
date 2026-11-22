#!/usr/bin/env python3
"""Build custom AppImage type 2 runtime with automatic FUSE fallback from pinned source."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("build_runtime")

# Pinned commit of official AppImage/type2-runtime ensuring bit-identical reproducible builds
TYPE2_RUNTIME_REPO = "https://github.com/AppImage/type2-runtime.git"
TYPE2_RUNTIME_COMMIT = "fedfad51acc2860b2916a1eef32ba4a500ff31ef"


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def verify_runtime_magic(runtime_file: Path) -> bool:
    """Verify that file is an ELF executable and has AppImage type 2 magic (AI\\x02 at offset 8)."""
    if not runtime_file.is_file() or runtime_file.stat().st_size < 10000:
        return False
    with open(runtime_file, "rb") as f:
        magic = f.read(16)
    is_elf = magic.startswith(b"\x7fELF")
    has_appimage_magic = magic[8:11] == b"AI\x02"
    return is_elf and has_appimage_magic


def stamp_appimage_magic(runtime_file: Path) -> None:
    """Stamp 'AI\\x02' AppImage type 2 magic bytes at offset 8 if not already present."""
    with open(runtime_file, "r+b") as f:
        f.seek(0)
        hdr = f.read(16)
        if not hdr.startswith(b"\x7fELF"):
            raise ValueError(f"{runtime_file} is not a valid ELF file")
        f.seek(8)
        f.write(b"AI\x02")


def get_directory_size(path: Path) -> int:
    """Calculate total stored size of regular files in a directory, avoiding double-counting hardlinks."""
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    seen_inodes: set[tuple[int, int]] = set()
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            try:
                st = item.stat()
                identity = (st.st_dev, st.st_ino)
                if identity not in seen_inodes:
                    seen_inodes.add(identity)
                    total += st.st_size
            except OSError:
                continue
    return total


def strip_binary(file_path: Path) -> int:
    """Strip debug and unneeded symbols from an executable or library.

    Returns the number of bytes saved.
    """
    if not file_path.is_file() or file_path.is_symlink():
        return 0
    try:
        with open(file_path, "rb") as f:
            magic = f.read(4)
            if magic != b"\x7fELF" and not file_path.name.lower().endswith((".dll", ".pyd", ".exe", ".so")):
                return 0
    except OSError:
        return 0

    strip_bin = shutil.which("strip")
    if not strip_bin:
        return 0

    initial_size = file_path.stat().st_size
    flag = "--strip-unneeded" if (".so" in file_path.name or ".pyd" in file_path.name) else "--strip-all"
    try:
        subprocess.run(
            [strip_bin, flag, str(file_path)],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        try:
            subprocess.run(
                [strip_bin, "--strip-debug", str(file_path)],
                capture_output=True,
                check=True,
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            logger.debug("strip failed on %s: %s", file_path, exc)
            return 0

    final_size = file_path.stat().st_size
    saved = max(0, initial_size - final_size)
    return saved


def filter_unused_runtime_libraries(runtime_dir: Path) -> tuple[int, int]:
    """Filter out debug symbols (*.pdb), unused libraries (test, tkinter, idlelib), and doc files.

    Preserves necessary libraries for MPV, FFmpeg, TorrServer, and SSL.
    Returns (removed_count, bytes_saved).
    """
    if not runtime_dir.is_dir():
        return 0, 0

    removed_count = 0
    saved_bytes = 0

    protected_exact = {
        "cinema.lua",
        "version.json",
        "apprun",
        "pirate-cinema-linux",
        "pirate-cinema.desktop",
        "pirate-cinema.png",
        "mpv",
        "mpv.bin",
        "mpv.exe",
        "ffmpeg",
        "ffmpeg.bin",
        "ffmpeg.exe",
        "ffprobe",
        "ffprobe.bin",
        "ffprobe.exe",
        "torrserver",
        "torrserver.exe",
    }

    # Directories to completely remove if found
    unwanted_dir_names = {
        "test",
        "tests",
        "unittest",
        "idlelib",
        "tcl8.6",
        "tk8.6",
        "tcl",
        "tk",
        "tkinter",
        "turtledemo",
    }

    # 1. Remove unwanted directories
    for root, dirs, _ in os.walk(runtime_dir, topdown=False):
        for d in dirs:
            dir_lower = d.lower()
            if dir_lower in unwanted_dir_names:
                dir_path = Path(root) / d
                # Ensure directory doesn't contain protected assets
                has_protected = any(
                    item.name.lower() in protected_exact or "ssl" in item.name.lower() or "mpv" in item.name.lower()
                    for item in dir_path.rglob("*")
                )
                if not has_protected:
                    dir_size = get_directory_size(dir_path)
                    try:
                        shutil.rmtree(dir_path)
                        removed_count += 1
                        saved_bytes += dir_size
                        logger.debug("Removed unused runtime directory: %s (%d bytes)", dir_path, dir_size)
                    except OSError as err:
                        logger.warning("Failed removing directory %s: %s", dir_path, err)

    # 2. Remove unwanted standalone files
    for item in list(runtime_dir.rglob("*")):
        if not item.is_file() or item.is_symlink():
            continue

        name_lower = item.name.lower()
        if (
            name_lower in protected_exact
            or "ssl" in name_lower
            or "crypto" in name_lower
            or "hashlib" in name_lower
            or "libav" in name_lower
            or "certifi" in name_lower
            or "static" in [p.lower() for p in item.parts]
        ):
            continue

        parts_lower = [p.lower() for p in item.parts]

        is_debug = any(name_lower.endswith(ext) for ext in (".pdb", ".debug", ".dsym"))
        is_unused_gui = any(x in name_lower for x in ("_tkinter", "libtcl", "libtk", "tcl86", "tk86")) or name_lower == "turtle.py"
        is_test_file = any(p in ("test", "tests") for p in parts_lower) or any(
            name_lower.startswith(p) for p in ("libgtest", "libgmock", "libcmocka", "libcheck")
        )
        is_doc = any(p in ("doc", "docs", "man") for p in parts_lower) and name_lower.endswith(
            (".html", ".htm", ".txt", ".chm", ".1", ".3", ".5", ".man")
        )

        if is_debug or is_unused_gui or is_test_file or is_doc:
            try:
                size = item.stat().st_size
                item.unlink()
                removed_count += 1
                saved_bytes += size
                logger.debug("Removed unused runtime file: %s (%d bytes)", item, size)
            except OSError as err:
                logger.warning("Failed removing file %s: %s", item, err)

    return removed_count, saved_bytes


def deduplicate_binaries(directory: Path) -> tuple[int, int]:
    """Find identical binaries by SHA-256 hash and replace duplicates with hardlinks.

    Returns (dedup_count, bytes_saved).
    """
    if not directory.is_dir():
        return 0, 0

    by_hash: dict[str, Path] = {}
    dedup_count = 0
    saved_bytes = 0

    for item in sorted(directory.rglob("*")):
        if not item.is_file() or item.is_symlink():
            continue
        # Only inspect binary extensions or ELF files
        name_lower = item.name.lower()
        is_bin_candidate = name_lower.endswith((".so", ".pyd", ".dll", ".exe", ".bin")) or (
            "." not in item.name and item.stat().st_size > 1000
        )
        if not is_bin_candidate:
            continue

        try:
            with open(item, "rb") as f:
                header = f.read(4)
                if header != b"\x7fELF" and not name_lower.endswith((".dll", ".pyd", ".exe", ".so")):
                    continue
                f.seek(0)
                file_hash = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            continue

        if file_hash in by_hash:
            original = by_hash[file_hash]
            try:
                orig_stat = original.stat()
                item_stat = item.stat()
                if (orig_stat.st_dev, orig_stat.st_ino) == (item_stat.st_dev, item_stat.st_ino):
                    continue
                size = item_stat.st_size
                item.unlink()
                try:
                    os.link(original, item)
                except OSError:
                    try:
                        rel = os.path.relpath(original, item.parent)
                        item.symlink_to(rel)
                    except OSError:
                        # Restore file if linking failed
                        shutil.copy2(original, item)
                        continue
                dedup_count += 1
                saved_bytes += size
                logger.debug("Deduplicated %s -> %s (%d bytes saved)", item.name, original.name, size)
            except OSError as err:
                logger.warning("Failed deduplicating binary %s: %s", item, err)
        else:
            by_hash[file_hash] = item

    return dedup_count, saved_bytes


def strip_debug_symbols_in_dir(directory: Path) -> tuple[int, int]:
    """Recursively strip debug symbols from ELF and shared library files.

    Returns (stripped_count, bytes_saved).
    """
    if not directory.is_dir() or not shutil.which("strip"):
        return 0, 0

    stripped_count = 0
    saved_bytes = 0

    for item in list(directory.rglob("*")):
        if not item.is_file() or item.is_symlink():
            continue
        saved = strip_binary(item)
        if saved > 0:
            stripped_count += 1
            saved_bytes += saved

    return stripped_count, saved_bytes


def optimize_runtime(runtime_dir: Path) -> dict[str, Any]:
    """Filter debug symbols, unused libraries (test, tkinter, doc), and duplicate binaries.

    Logs package size before and after cleanup.
    Returns detailed summary dictionary.
    """
    initial_size = get_directory_size(runtime_dir)
    logger.info("Optimizing runtime at %s (initial size: %d bytes / %.2f MB)...", runtime_dir, initial_size, initial_size / (1024 * 1024))

    removed_unused, unused_saved = filter_unused_runtime_libraries(runtime_dir)
    stripped_count, strip_saved = strip_debug_symbols_in_dir(runtime_dir)
    dedup_count, dedup_saved = deduplicate_binaries(runtime_dir)

    final_size = get_directory_size(runtime_dir)
    saved_bytes = max(0, initial_size - final_size)
    saved_pct = (saved_bytes / initial_size * 100.0) if initial_size > 0 else 0.0

    logger.info(
        "Runtime payload size before cleanup: %d bytes (%.2f MB), after cleanup: %d bytes (%.2f MB), saved: %d bytes (%.2f MB, %.1f%%) [removed %d unused, stripped %d binaries, deduplicated %d files]",
        initial_size,
        initial_size / (1024 * 1024),
        final_size,
        final_size / (1024 * 1024),
        saved_bytes,
        saved_bytes / (1024 * 1024),
        saved_pct,
        removed_unused,
        stripped_count,
        dedup_count,
    )

    return {
        "initial_size": initial_size,
        "final_size": final_size,
        "saved_bytes": saved_bytes,
        "saved_pct": saved_pct,
        "removed_unused": removed_unused,
        "stripped_count": stripped_count,
        "dedup_count": dedup_count,
    }


def build_runtime_in_docker(source_dir: Path, out_dir: Path) -> Path:
    """Build the runtime in a reproducible Alpine container using official Docker setup."""
    logger.info("Building runtime using Docker container...")
    docker_bin = shutil.which("docker")
    if not docker_bin:
        raise RuntimeError("docker is required to build type2-runtime from source")

    # Build container image from Dockerfile
    docker_dir = source_dir / "scripts" / "docker"
    image_tag = "pirate-cinema-type2-runtime:build"
    build_cmd = [
        docker_bin,
        "build",
        "-t",
        image_tag,
        "-f",
        str(docker_dir / "Dockerfile"),
        str(source_dir),
    ]
    logger.info("Executing: %s", " ".join(build_cmd))
    subprocess.run(build_cmd, check=True)

    # Run build inside container
    uid = os.getuid() if hasattr(os, "getuid") else 1000
    gid = os.getgid() if hasattr(os, "getgid") else 1000
    out_dir.mkdir(parents=True, exist_ok=True)

    run_cmd = [
        docker_bin,
        "run",
        "--rm",
        "-u",
        f"{uid}:{gid}",
        "-e",
        "ARCH=x86_64",
        "-v",
        f"{source_dir.resolve()}:/ws",
        "-w",
        "/ws",
        image_tag,
        "bash",
        "scripts/build-runtime.sh",
    ]
    logger.info("Executing: %s", " ".join(run_cmd))
    subprocess.run(run_cmd, check=True)

    produced_runtime = source_dir / "out" / "runtime-x86_64"
    if not produced_runtime.is_file():
        raise FileNotFoundError(f"Expected runtime binary not found at {produced_runtime}")

    return produced_runtime


def prepare_source_and_patch(
    work_dir: Path,
    patch_file: Path | None = None,
) -> Path:
    """Clone pinned type2-runtime repository and apply automatic FUSE fallback patch."""
    src_repo_dir = work_dir / "type2-runtime-src"
    if src_repo_dir.exists():
        shutil.rmtree(src_repo_dir)

    work_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Cloning type2-runtime from %s (pinned commit %s)...", TYPE2_RUNTIME_REPO, TYPE2_RUNTIME_COMMIT)
    subprocess.run(
        ["git", "clone", TYPE2_RUNTIME_REPO, str(src_repo_dir)],
        check=True,
    )
    subprocess.run(
        ["git", "checkout", TYPE2_RUNTIME_COMMIT],
        cwd=str(src_repo_dir),
        check=True,
    )

    runtime_c = src_repo_dir / "src" / "runtime" / "runtime.c"
    assert runtime_c.is_file(), f"runtime.c missing in cloned repo: {runtime_c}"

    # Apply patch
    if patch_file and patch_file.is_file():
        logger.info("Applying patch from %s...", patch_file)
        try:
            subprocess.run(
                ["git", "apply", str(patch_file.resolve())],
                cwd=str(src_repo_dir),
                check=True,
            )
            logger.info("Git apply succeeded.")
        except subprocess.CalledProcessError:
            logger.warning("git apply failed, falling back to python script patcher...")
            from scripts.patch_runtime import patch_runtime_source
            patch_runtime_source(runtime_c)
    else:
        from scripts.patch_runtime import patch_runtime_source
        patch_runtime_source(runtime_c)

    return src_repo_dir


def build_runtime(
    output_path: Path,
    work_dir: Path,
    patch_file: Path | None = None,
) -> Path:
    """Build and stamp the custom runtime."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Prepare and patch source
    src_dir = prepare_source_and_patch(work_dir, patch_file)

    # 2. Build via Docker
    built_file = build_runtime_in_docker(src_dir, work_dir / "out")

    # 3. Copy to destination
    shutil.copy2(built_file, output_path)

    # Strip debug symbols from the compiled runtime binary
    size_before = output_path.stat().st_size
    strip_binary(output_path)
    size_after = output_path.stat().st_size
    saved = max(0, size_before - size_after)
    logger.info(
        "Runtime binary size before stripping: %d bytes (%.2f KB), after stripping: %d bytes (%.2f KB), saved: %d bytes (%.2f KB)",
        size_before,
        size_before / 1024,
        size_after,
        size_after / 1024,
        saved,
        saved / 1024,
    )

    # 4. Stamp AppImage magic if needed
    stamp_appimage_magic(output_path)
    output_path.chmod(output_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # 5. Verify
    if not verify_runtime_magic(output_path):
        raise ValueError(f"Output file {output_path} failed AppImage runtime validation")

    logger.info(
        "Successfully built AppImage runtime at %s (SHA-256: %s, size: %d bytes)",
        output_path,
        sha256_file(output_path),
        output_path.stat().st_size,
    )
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build AppImage type2-runtime with automatic FUSE fallback or optimize bundle runtime"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/runtime/runtime-x86_64"),
        help="Path for built runtime binary (default: build/runtime/runtime-x86_64)",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("build/runtime-work"),
        help="Temporary directory for cloning and compilation",
    )
    parser.add_argument(
        "--patch",
        type=Path,
        default=Path("patches/runtime-fuse-fallback.patch"),
        help="Path to unified diff patch (default: patches/runtime-fuse-fallback.patch)",
    )
    parser.add_argument(
        "--optimize-dir",
        type=Path,
        help="Path to runtime or bundle directory to optimize (filter test/tkinter/doc, strip debug symbols, deduplicate binaries)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        if args.optimize_dir:
            optimize_runtime(args.optimize_dir.resolve())
            return 0

        build_runtime(
            output_path=args.output.resolve(),
            work_dir=args.work_dir.resolve(),
            patch_file=args.patch.resolve() if args.patch.is_file() else None,
        )
        return 0
    except Exception:
        logger.exception("Failed building runtime")
        return 1


if __name__ == "__main__":
    sys.exit(main())
