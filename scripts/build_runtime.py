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
        description="Build AppImage type2-runtime with automatic FUSE fallback"
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
        build_runtime(
            output_path=args.output.resolve(),
            work_dir=args.work_dir.resolve(),
            patch_file=args.patch.resolve() if args.patch.is_file() else None,
        )
        return 0
    except Exception as exc:
        logger.exception("Failed building runtime: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
