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

export PATH="${APPDIR}:${PATH}"

exec "${APPDIR}/pirate-cinema-linux" "$@"
"""


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def _set_executable(path: Path) -> None:
    try:
        current = path.stat().st_mode
        path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as err:
        logger.debug("Failed setting executable permission on %s: %s", path, err)


def assemble_appdir(
    onedir_path: Path,
    appdir_path: Path,
    icon_path: Path,
    project_root: Path,
) -> Path:
    """Construct a compliant AppDir layout from PyInstaller onedir output."""
    if not onedir_path.is_dir():
        raise FileNotFoundError(
            f"PyInstaller onedir distribution not found at: {onedir_path}"
        )
    if not icon_path.is_file():
        raise FileNotFoundError(f"Application icon not found at: {icon_path}")

    logger.info("Assembling AppDir at %s...", appdir_path)
    if appdir_path.exists():
        shutil.rmtree(appdir_path)
    appdir_path.mkdir(parents=True, exist_ok=True)

    # 1. Copy all contents of PyInstaller onedir (binary, _internal, etc.)
    for item in onedir_path.iterdir():
        dest = appdir_path / item.name
        if item.is_dir():
            shutil.copytree(item, dest, symlinks=True)
        else:
            shutil.copy2(item, dest)

    # 2. Ensure AppRun script
    apprun_path = appdir_path / "AppRun"
    apprun_path.write_text(APPRUN_SCRIPT, encoding="utf-8", newline="\n")
    _set_executable(apprun_path)

    # 3. Create .desktop file
    desktop_path = appdir_path / "pirate-cinema.desktop"
    desktop_path.write_text(DESKTOP_ENTRY, encoding="utf-8", newline="\n")

    usr_apps = appdir_path / "usr" / "share" / "applications"
    usr_apps.mkdir(parents=True, exist_ok=True)
    shutil.copy2(desktop_path, usr_apps / "pirate-cinema.desktop")

    # 4. Install icons
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

    # 5. Ensure root-level resource references exist (static, version.json, cinema.lua)
    # PyInstaller puts them in _internal or alongside the executable.
    internal_dir = appdir_path / "_internal"

    # static
    static_root = appdir_path / "static"
    if not static_root.exists():
        if internal_dir.is_dir() and (internal_dir / "static").is_dir():
            shutil.copytree(internal_dir / "static", static_root, symlinks=True)
        elif (project_root / "static").is_dir():
            shutil.copytree(project_root / "static", static_root, symlinks=True)

    # version.json
    version_root = appdir_path / "version.json"
    if not version_root.exists():
        if internal_dir.is_dir() and (internal_dir / "version.json").is_file():
            shutil.copy2(internal_dir / "version.json", version_root)
        elif (project_root / "version.json").is_file():
            shutil.copy2(project_root / "version.json", version_root)

    # cinema.lua
    cinema_lua_root = appdir_path / "cinema.lua"
    if not cinema_lua_root.exists():
        src_lua = (
            project_root / "backend" / "infrastructure" / "mpv" / "cinema.lua"
        )
        internal_lua = (
            internal_dir / "backend" / "infrastructure" / "mpv" / "cinema.lua"
        )
        if internal_lua.is_file():
            shutil.copy2(internal_lua, cinema_lua_root)
        elif src_lua.is_file():
            shutil.copy2(src_lua, cinema_lua_root)

    # 6. Ensure embedded MPV player is present and executable
    vendor_mpv_root = appdir_path / "vendor" / "mpv"
    internal_mpv = internal_dir / "vendor" / "mpv"
    project_mpv = project_root / "vendor" / "mpv"

    if not vendor_mpv_root.is_dir():
        if internal_mpv.is_dir():
            shutil.copytree(internal_mpv, vendor_mpv_root, symlinks=True)
        elif project_mpv.is_dir():
            shutil.copytree(project_mpv, vendor_mpv_root, symlinks=True)
        elif sys.platform.startswith("linux") and (Path("/usr/bin/mpv").is_file() or shutil.which("mpv")):
            try:
                from scripts.bundle_linux_mpv import bundle_mpv
                host_mpv = Path("/usr/bin/mpv") if Path("/usr/bin/mpv").is_file() else Path(shutil.which("mpv"))
                bundle_mpv(host_mpv, vendor_mpv_root, docs_dir=project_root / "licenses")
            except Exception as e:
                logger.warning("Could not auto-bundle host MPV: %s", e)

    if vendor_mpv_root.is_dir() and not internal_mpv.exists():
        internal_mpv.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(vendor_mpv_root, internal_mpv, symlinks=True)

    # 7. Ensure executable permissions for binaries
    main_bin = appdir_path / "pirate-cinema-linux"
    if main_bin.is_file():
        _set_executable(main_bin)

    for ts_path in [
        appdir_path / "vendor" / "torrserver" / "torrserver",
        internal_dir / "vendor" / "torrserver" / "torrserver",
    ]:
        if ts_path.is_file():
            _set_executable(ts_path)

    for mpv_exe in [
        vendor_mpv_root / "mpv",
        vendor_mpv_root / "mpv.bin",
        internal_mpv / "mpv",
        internal_mpv / "mpv.bin",
    ]:
        if mpv_exe.is_file():
            _set_executable(mpv_exe)

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
    ]

    if runtime_file and runtime_file.is_file():
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
        default=Path("build/runtime/runtime-x86_64"),
        help="Path to custom type2-runtime with automatic FUSE fallback (default: build/runtime/runtime-x86_64)",
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
            project_root=project_root,
        )

        if args.appdir_only:
            logger.info("AppDir assembly finished (--appdir-only specified).")
            return 0

        runtime_path = args.runtime_file.resolve() if args.runtime_file and args.runtime_file.is_file() else None
        build_appimage(
            appdir_path=appdir,
            output_path=args.output.resolve(),
            tools_dir=args.tools_dir.resolve(),
            runtime_file=runtime_path,
        )
        return 0
    except Exception as exc:
        logger.exception("AppImage packaging failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
