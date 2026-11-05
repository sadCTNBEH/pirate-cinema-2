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
    logger.info(
        "Successfully created AppImage at %s (size: %.2f MB)",
        output_path,
        output_path.stat().st_size / (1024 * 1024),
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
