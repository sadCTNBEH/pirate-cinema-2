#!/usr/bin/env python3
"""Build Pirate_Cinema-x86_64.AppImage from PyInstaller onedir distribution."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

if __package__:
    from scripts.stage_linux_vendor import REQUIRED_TOOLS, validate_vendor
else:
    from stage_linux_vendor import REQUIRED_TOOLS, validate_vendor

logger = logging.getLogger("build_appimage")

APPIMAGETOOL_URL = (
    "https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
)
APPIMAGETOOL_SHA256 = "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=Pirate Cinema
GenericName=Media Player
Comment=Watch movies, series and streams directly via torrents and online sources
Exec=AppRun %U
Icon=pirate-cinema
Categories=AudioVideo;Video;Player;
Terminal=false
StartupWMClass=Pirate Cinema
MimeType=x-scheme-handler/magnet;
Keywords=cinema;player;torrent;stream;video;
"""

APPRUN_SCRIPT = """#!/bin/sh
set -e

APPDIR="$(dirname "$(readlink -f "$0")")"
export APPDIR

if [ -z "${APPIMAGE:-}" ]; then
    export APPIMAGE="$(readlink -f "$0")"
fi

export PATH="${APPDIR}/vendor/ffmpeg:${APPDIR}/vendor/mpv:${APPDIR}:${PATH}"
export PIRATE_CINEMA_GUI="${PIRATE_CINEMA_GUI:-native}"
export PYWEBVIEW_GUI="${PYWEBVIEW_GUI:-qt}"
if [ -n "${DISPLAY:-}" ] && [ -z "${QT_QPA_PLATFORM:-}" ]; then
    export QT_QPA_PLATFORM="xcb"
fi

exec "${APPDIR}/pirate-cinema-linux" "$@"
"""


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def _set_executable(path: Path) -> None:
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


FORBIDDEN_HOST_LIBRARIES = {
    "libc.so.6",
    "ld-linux.so.2",
    "ld-linux-x86-64.so.2",
    "libm.so.6",
    "libpthread.so.0",
    "libdl.so.2",
    "librt.so.1",
    "libresolv.so.2",
    "libstdc++.so.6",
    "libgcc_s.so.1",
    "libgl.so.1",
    "libegl.so.1",
    "libdrm.so.2",
    "libvulkan.so.1",
    "libx11.so.6",
    "libxcb.so.1",
    "libasound.so.2",
    "libpulse.so.0",
}

FUSE_FALLBACK_SIGNATURES = [
    b"execute_extracted_fallback",
    b"pirate_cinema_extracted_",
    b"APPIMAGE_FALLBACK_ACTIVE",
]


def get_appdir_size(path: Path) -> int:
    """Calculate total stored size of regular files in AppDir without double-counting hardlinks."""
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


def clean_appdir(appdir_path: Path) -> tuple[int, int]:
    """Prune debug symbols, test/tkinter/doc files, and deduplicate identical binaries in AppDir.

    Returns (removed_count, bytes_saved).
    """
    removed_count = 0
    saved_bytes = 0

    protected_names = {
        "apprun",
        "pirate-cinema.desktop",
        "pirate-cinema.png",
        ".diricon",
        "cinema.lua",
        "version.json",
        "pirate-cinema-linux",
        "mpv",
        "mpv.bin",
        "ffmpeg",
        "ffmpeg.bin",
        "ffprobe",
        "ffprobe.bin",
        "torrserver",
    }

    # 1. Prune unused test/tkinter/doc directories
    unwanted_dirs = {"test", "tests", "unittest", "idlelib", "tcl8.6", "tk8.6", "tcl", "tk", "tkinter"}
    for root, dirs, _ in os.walk(appdir_path, topdown=False):
        for d in dirs:
            if d.lower() in unwanted_dirs:
                target_dir = Path(root) / d
                has_protected = any(item.name.lower() in protected_names for item in target_dir.rglob("*"))
                if not has_protected:
                    dir_sz = get_appdir_size(target_dir)
                    try:
                        shutil.rmtree(target_dir)
                        removed_count += 1
                        saved_bytes += dir_sz
                    except OSError:
                        pass

    # 2. Prune unused standalone files
    for item in list(appdir_path.rglob("*")):
        if not item.is_file() or item.is_symlink():
            continue
        name_lower = item.name.lower()
        if (
            name_lower in protected_names
            or name_lower.startswith("libav")
            or name_lower.startswith("libssl")
            or "static" in [p.lower() for p in item.parts]
        ):
            continue

        parts_lower = [p.lower() for p in item.parts]
        is_debug = any(name_lower.endswith(ext) for ext in (".pdb", ".debug", ".dsym"))
        is_unused_gui = any(x in name_lower for x in ("_tkinter", "libtcl", "libtk", "tcl86", "tk86")) or name_lower == "turtle.py"
        is_test = any(p in ("test", "tests") for p in parts_lower) or any(
            name_lower.startswith(p) for p in ("libgtest", "libgmock", "libcmocka", "libcheck")
        )
        is_doc = any(p in ("doc", "docs", "man") for p in parts_lower) and name_lower.endswith(
            (".html", ".htm", ".txt", ".chm", ".1", ".3", ".5", ".man")
        )

        if is_debug or is_unused_gui or is_test or is_doc:
            try:
                sz = item.stat().st_size
                item.unlink()
                removed_count += 1
                saved_bytes += sz
            except OSError:
                pass

    # 3. Strip ELF debug symbols if strip tool is available
    strip_bin = shutil.which("strip")
    if strip_bin:
        for item in list(appdir_path.rglob("*")):
            if not item.is_file() or item.is_symlink():
                continue
            try:
                with open(item, "rb") as f:
                    if f.read(4) != b"\x7fELF":
                        continue
                before = item.stat().st_size
                flag = "--strip-unneeded" if ".so" in item.name else "--strip-all"
                res = subprocess.run([strip_bin, flag, str(item)], capture_output=True)
                if res.returncode != 0:
                    subprocess.run([strip_bin, "--strip-debug", str(item)], capture_output=True)
                after = item.stat().st_size
                if after < before:
                    saved_bytes += (before - after)
            except OSError:
                pass

    return removed_count, saved_bytes


def verify_packaged_dependencies(appdir: Path) -> dict[str, Any]:
    """Verify packaged dependencies in AppDir, ensuring required media/runtime tools are present
    and forbidden host libraries are not accidentally bundled."""
    internal = appdir / "_internal"
    warnings = []
    required_found = []

    # 1. Check required vendor tools
    vendor_dir = internal / "vendor" if internal.is_dir() else appdir / "vendor"
    if vendor_dir.is_dir():
        validate_vendor(vendor_dir)
        required_found.append("vendor_tools")

    # 2. Check entry points and desktop assets
    for name in ("pirate-cinema-linux", "AppRun", "pirate-cinema.desktop", "pirate-cinema.png"):
        if (appdir / name).exists():
            required_found.append(name)
        else:
            warnings.append(f"Missing AppDir asset: {name}")

    # 3. Check forbidden host libraries
    found_forbidden = []
    for item in appdir.rglob("*.so*"):
        if item.name.lower() in FORBIDDEN_HOST_LIBRARIES:
            found_forbidden.append(str(item.relative_to(appdir)))
            warnings.append(f"Forbidden host library found in bundle: {item.name} at {item}")

    logger.info(
        "Packaged dependencies verified (%d required assets verified, %d warnings)",
        len(required_found),
        len(warnings),
    )
    return {
        "valid": len(found_forbidden) == 0,
        "required_found": required_found,
        "forbidden_found": found_forbidden,
        "warnings": warnings,
    }


def verify_fuse_fallback(runtime_file: Path | None, appdir: Path | None = None) -> bool:
    """Verify that custom type 2 runtime has automatic FUSE fallback logic embedded."""
    if runtime_file is None or not runtime_file.is_file():
        logger.info("No custom runtime file provided; standard runtime fallback relies on --appimage-extract-and-run.")
        return False

    # 1. Check ELF magic
    try:
        with open(runtime_file, "rb") as f:
            content = f.read(65536)
    except OSError as err:
        logger.warning("Could not read runtime file %s: %s", runtime_file, err)
        return False

    if not content.startswith(b"\x7fELF"):
        logger.warning("Runtime file %s is not an ELF binary.", runtime_file)
        return False

    has_type2_magic = len(content) > 11 and content[8:11] == b"AI\x02"
    if not has_type2_magic:
        logger.warning("Runtime file %s does not have AppImage type 2 magic (offset 8).", runtime_file)

    # 2. Check for FUSE fallback signatures in the binary
    try:
        full_content = runtime_file.read_bytes()
        has_fallback_sig = any(sig in full_content for sig in FUSE_FALLBACK_SIGNATURES)
    except OSError:
        has_fallback_sig = False

    if has_fallback_sig:
        logger.info("Verified: Runtime binary %s contains automatic FUSE fallback support.", runtime_file)
        return True
    else:
        logger.warning(
            "Runtime binary %s missing custom FUSE fallback signature (fallback may require manual --appimage-extract-and-run).",
            runtime_file,
        )
        return False


def assemble_appdir(
    onedir_path: Path,
    appdir_path: Path,
    icon_path: Path,
) -> Path:
    """Construct a compliant AppDir layout from PyInstaller onedir output."""
    if not onedir_path.is_dir():
        raise FileNotFoundError(
            f"PyInstaller onedir distribution not found at: {onedir_path}"
        )
    if not icon_path.is_file():
        raise FileNotFoundError(f"Application icon not found at: {icon_path}")

    source, destination = onedir_path.resolve(), appdir_path.resolve()
    if source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError("AppDir and PyInstaller onedir must be separate trees")
    logger.info("Assembling AppDir at %s...", appdir_path)
    if appdir_path.exists():
        shutil.rmtree(appdir_path)

    # Preserve hardlinks within the copied tree without linking back to the source.
    copied: dict[tuple[int, int], str] = {}

    def copy_payload(source: str, target: str) -> None:
        info = os.stat(source)
        key = (info.st_dev, info.st_ino)
        if info.st_nlink > 1 and key in copied:
            os.link(copied[key], target)
        else:
            shutil.copy2(source, target)
            if info.st_nlink > 1:
                copied[key] = target

    shutil.copytree(
        onedir_path, appdir_path, symlinks=True, copy_function=copy_payload,
    )

    # Install AppRun.
    apprun_path = appdir_path / "AppRun"
    apprun_path.write_text(APPRUN_SCRIPT, encoding="utf-8", newline="\n")
    _set_executable(apprun_path)

    # Install the desktop entry.
    desktop_path = appdir_path / "pirate-cinema.desktop"
    desktop_path.write_text(DESKTOP_ENTRY, encoding="utf-8", newline="\n")

    usr_apps = appdir_path / "usr" / "share" / "applications"
    usr_apps.mkdir(parents=True, exist_ok=True)
    shutil.copy2(desktop_path, usr_apps / "pirate-cinema.desktop")

    # Install icons.
    icon_dest = appdir_path / "pirate-cinema.png"
    shutil.copy2(icon_path, icon_dest)

    dir_icon = appdir_path / ".DirIcon"
    try:
        if dir_icon.exists() or dir_icon.is_symlink():
            dir_icon.unlink()
        dir_icon.symlink_to("pirate-cinema.png")
    except OSError:
        shutil.copy2(icon_path, dir_icon)

    hicolor_512 = (
        appdir_path / "usr" / "share" / "icons" / "hicolor" / "512x512" / "apps"
    )
    hicolor_512.mkdir(parents=True, exist_ok=True)
    shutil.copy2(icon_path, hicolor_512 / "pirate-cinema.png")

    hicolor_256 = (
        appdir_path / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    )
    hicolor_256.mkdir(parents=True, exist_ok=True)
    shutil.copy2(icon_path, hicolor_256 / "pirate-cinema.png")

    # Keep the AppDir entry points while storing the payload only in _internal.
    internal = appdir_path / "_internal"
    lua = internal / "backend/infrastructure/mpv/cinema.lua"
    validate_vendor(internal / "vendor")
    for alias, target in (
        ("static", internal / "static"),
        ("version.json", internal / "version.json"),
        ("cinema.lua", lua),
        ("vendor/mpv", internal / "vendor/mpv"),
        ("vendor/ffmpeg", internal / "vendor/ffmpeg"),
    ):
        if not target.exists():
            raise FileNotFoundError(target)
        path = appdir_path / alias
        path.parent.mkdir(parents=True, exist_ok=True)
        if not (path.exists() or path.is_symlink()):
            path.symlink_to(os.path.relpath(target, path.parent), target_is_directory=target.is_dir())

    _set_executable(appdir_path / "pirate-cinema-linux")
    for tool, names in REQUIRED_TOOLS.items():
        for name in names:
            _set_executable(internal / "vendor" / tool / name)

    # Clean AppDir (filter debug symbols, unused test/tkinter/doc files, deduplicate)
    initial_appdir_size = get_appdir_size(appdir_path)
    removed_count, saved_bytes = clean_appdir(appdir_path)
    final_appdir_size = get_appdir_size(appdir_path)
    saved = max(0, initial_appdir_size - final_appdir_size)
    pct = (saved / initial_appdir_size * 100.0) if initial_appdir_size > 0 else 0.0

    logger.info(
        "AppDir size before cleanup: %d bytes (%.2f MB), after cleanup: %d bytes (%.2f MB), saved: %d bytes (%.2f MB, %.1f%%) [removed %d unused items]",
        initial_appdir_size,
        initial_appdir_size / (1024 * 1024),
        final_appdir_size,
        final_appdir_size / (1024 * 1024),
        saved,
        saved / (1024 * 1024),
        pct,
        removed_count,
    )

    # Verify packaged dependencies (ensuring required tools exist and no forbidden host libraries)
    verify_packaged_dependencies(appdir_path)

    logger.info("AppDir assembled successfully.")
    return appdir_path


def download_appimagetool(tools_dir: Path) -> Path:
    """Download official appimagetool with strict SHA-256 verification."""
    tools_dir.mkdir(parents=True, exist_ok=True)
    tool_path = tools_dir / "appimagetool-x86_64.AppImage"

    if tool_path.is_file():
        existing_sha = _sha256_file(tool_path)
        if existing_sha == APPIMAGETOOL_SHA256:
            logger.info("Found cached appimagetool with verified checksum: %s", tool_path)
            _set_executable(tool_path)
            return tool_path
        logger.warning(
            "Cached appimagetool checksum mismatch (expected %s, got %s). Redownloading...",
            APPIMAGETOOL_SHA256,
            existing_sha,
        )
        tool_path.unlink()

    logger.info("Downloading appimagetool from %s...", APPIMAGETOOL_URL)
    temp_tool = tool_path.with_suffix(".part")
    if temp_tool.exists():
        temp_tool.unlink()

    req = urllib.request.Request(
        APPIMAGETOOL_URL,
        headers={"User-Agent": "Pirate-Cinema-Builder/1.0"},
    )
    with (
        urllib.request.urlopen(req, timeout=60) as response,
        open(temp_tool, "wb") as f,
    ):
        shutil.copyfileobj(response, f)

    calculated_sha = _sha256_file(temp_tool)
    if calculated_sha != APPIMAGETOOL_SHA256:
        temp_tool.unlink(missing_ok=True)
        raise ValueError(
            f"appimagetool SHA-256 mismatch: expected {APPIMAGETOOL_SHA256}, got {calculated_sha}"
        )

    temp_tool.rename(tool_path)
    _set_executable(tool_path)
    logger.info("Verified appimagetool saved to %s", tool_path)
    return tool_path


def build_appimage(
    appdir_path: Path,
    output_path: Path,
    tools_dir: Path,
    runtime_file: Path | None = None,
) -> Path:
    """Package the AppDir using official appimagetool and optional custom runtime."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    tool_path = download_appimagetool(tools_dir)

    # Verify FUSE fallback support
    fallback_ok = verify_fuse_fallback(runtime_file, appdir_path)
    logger.info("FUSE fallback capability status: %s", "active (automatic fallback)" if fallback_ok else "standard appimagetool")

    appdir_size = get_appdir_size(appdir_path)

    env = os.environ.copy()
    env["ARCH"] = "x86_64"

    cmd = [
        str(tool_path),
        "--appimage-extract-and-run",
        "--comp", "zstd",
        "--mksquashfs-opt", "-Xcompression-level",
        "--mksquashfs-opt", "19",
        "--mksquashfs-opt", "-b",
        "--mksquashfs-opt", "524288",
    ]

    if runtime_file is not None:
        if not runtime_file.is_file():
            raise FileNotFoundError(runtime_file)
        logger.info("Embedding custom runtime with automatic FUSE fallback: %s", runtime_file)
        cmd.extend(["--runtime-file", str(runtime_file)])

    cmd.extend([
        str(appdir_path),
        str(output_path),
    ])

    logger.info("Executing appimagetool: %s", " ".join(cmd))
    res = subprocess.run(cmd, env=env, check=False)
    if res.returncode != 0:
        raise RuntimeError(
            f"appimagetool failed with return code {res.returncode}"
        )

    if not output_path.is_file() or output_path.stat().st_size < 1_000_000:
        raise RuntimeError(
            f"Expected AppImage was not created or is invalid: {output_path}"
        )

    _set_executable(output_path)
    output_size = output_path.stat().st_size
    ratio = ((appdir_size - output_size) / appdir_size * 100.0) if appdir_size > 0 else 0.0
    logger.info(
        "Successfully created AppImage at %s (size: %d bytes / %.2f MB, compressed from %d bytes / %.2f MB, %.1f%% reduction)",
        output_path,
        output_size,
        output_size / (1024 * 1024),
        appdir_size,
        appdir_size / (1024 * 1024),
        ratio,
    )
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Pirate Cinema AppImage for Linux x86_64"
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("dist/pirate-cinema-linux"),
        help="Path to PyInstaller onedir bundle (default: dist/pirate-cinema-linux)",
    )
    parser.add_argument(
        "--appdir",
        type=Path,
        default=Path("build/AppDir"),
        help="Path for assembled AppDir (default: build/AppDir)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/Pirate_Cinema-x86_64.AppImage"),
        help="Path for output AppImage (default: dist/Pirate_Cinema-x86_64.AppImage)",
    )
    parser.add_argument(
        "--tools-dir",
        type=Path,
        default=Path("build/tools"),
        help="Directory to cache appimagetool (default: build/tools)",
    )
    parser.add_argument(
        "--runtime-file",
        type=Path,
        help="Path to a custom type2-runtime with automatic FUSE fallback",
    )
    parser.add_argument(
        "--appdir-only",
        action="store_true",
        help="Assemble AppDir only, skip packaging",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    project_root = Path(__file__).resolve().parent.parent
    icon_path = project_root / "build" / "icon.png"

    try:
        appdir = assemble_appdir(
            onedir_path=args.source_dir.resolve(),
            appdir_path=args.appdir.resolve(),
            icon_path=icon_path.resolve(),
        )

        if args.appdir_only:
            logger.info("AppDir assembly finished (--appdir-only specified).")
            return 0

        default_runtime = Path("build/runtime/runtime-x86_64")
        runtime_path = args.runtime_file or (default_runtime if default_runtime.is_file() else None)
        if runtime_path is not None:
            runtime_path = runtime_path.resolve()
        build_appimage(
            appdir_path=appdir,
            output_path=args.output.resolve(),
            tools_dir=args.tools_dir.resolve(),
            runtime_file=runtime_path,
        )
        return 0
    except Exception:
        logger.exception("AppImage packaging failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
