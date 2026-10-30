"""Tests for AppImage packaging, AppDir layout, and appimagetool integration."""

from __future__ import annotations

import io
import os
import stat
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.build_appimage import (
    APPIMAGETOOL_SHA256,
    assemble_appdir,
    download_appimagetool,
)


def _create_mock_onedir(root: Path) -> Path:
    onedir = root / "pirate-cinema-linux"
    onedir.mkdir(parents=True, exist_ok=True)

    exe = onedir / "pirate-cinema-linux"
    exe.write_text("#!/bin/sh\necho pirate-cinema\n", encoding="utf-8")
    exe.chmod(0o755)

    internal = onedir / "_internal"
    internal.mkdir(parents=True, exist_ok=True)
    (internal / "libpython.so").write_bytes(b"\x7fELFfake")

    static_dir = internal / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")

    (internal / "version.json").write_text('{"version": "v0.4.2"}', encoding="utf-8")

    mpv_dir = internal / "backend" / "infrastructure" / "mpv"
    mpv_dir.mkdir(parents=True, exist_ok=True)
    (mpv_dir / "cinema.lua").write_text("-- cinema OSD\n", encoding="utf-8")

    ts_dir = internal / "vendor" / "torrserver"
    ts_dir.mkdir(parents=True, exist_ok=True)
    ts_bin = ts_dir / "torrserver"
    ts_bin.write_text("#!/bin/sh\necho torrserver\n", encoding="utf-8")
    ts_bin.chmod(0o755)

    return onedir


def test_assemble_appdir_structure_and_files(tmp_path: Path):
    onedir = _create_mock_onedir(tmp_path / "dist")
    icon = tmp_path / "icon.png"
    icon.write_bytes(b"\x89PNG\r\n\x1a\nfake-icon-data")

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "build").mkdir()
    (project_root / "build" / "icon.png").write_bytes(icon.read_bytes())

    appdir = tmp_path / "build" / "AppDir"
    assembled = assemble_appdir(
        onedir_path=onedir,
        appdir_path=appdir,
        icon_path=icon,
        project_root=project_root,
    )

    assert assembled == appdir
    assert appdir.is_dir()

    # 1. AppRun
    apprun = appdir / "AppRun"
    assert apprun.is_file()
    apprun_content = apprun.read_text(encoding="utf-8")
    assert apprun_content.startswith("#!/bin/sh")
    assert "APPDIR=" in apprun_content
    assert "APPIMAGE=" in apprun_content
    assert 'exec "${APPDIR}/pirate-cinema-linux" "$@"' in apprun_content
    if os.name != "nt":
        assert apprun.stat().st_mode & stat.S_IXUSR

    # 2. Desktop file
    desktop = appdir / "pirate-cinema.desktop"
    assert desktop.is_file()
    desktop_content = desktop.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in desktop_content
    assert "Type=Application" in desktop_content
    assert "Name=Pirate Cinema" in desktop_content
    assert "Exec=AppRun %U" in desktop_content
    assert "Icon=pirate-cinema" in desktop_content
    assert "Categories=AudioVideo;Video;Player;" in desktop_content

    usr_desktop = appdir / "usr" / "share" / "applications" / "pirate-cinema.desktop"
    assert usr_desktop.is_file()
    assert usr_desktop.read_text(encoding="utf-8") == desktop_content

    # 3. Icons
    root_icon = appdir / "pirate-cinema.png"
    assert root_icon.is_file()
    assert root_icon.read_bytes() == icon.read_bytes()

    dir_icon = appdir / ".DirIcon"
    assert dir_icon.exists()

    icon_512 = (
        appdir / "usr" / "share" / "icons" / "hicolor" / "512x512" / "apps" / "pirate-cinema.png"
    )
    assert icon_512.is_file()

    icon_256 = (
        appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "pirate-cinema.png"
    )
    assert icon_256.is_file()

    # 4. Resources
    assert (appdir / "static" / "index.html").is_file()
    assert (appdir / "version.json").is_file()
    assert (appdir / "cinema.lua").is_file()
    assert (appdir / "_internal" / "libpython.so").is_file()

    # 5. TorrServer
    ts_bin = appdir / "_internal" / "vendor" / "torrserver" / "torrserver"
    assert ts_bin.is_file()
    if os.name != "nt":
        assert ts_bin.stat().st_mode & stat.S_IXUSR


def test_assemble_appdir_in_path_with_spaces(tmp_path: Path):
    onedir = _create_mock_onedir(tmp_path / "dist with space")
    icon = tmp_path / "icon with space.png"
    icon.write_bytes(b"\x89PNG\r\n\x1a\nfake-icon-data")

    project_root = tmp_path / "project space"
    project_root.mkdir()

    appdir = tmp_path / "AppDir With Spaces"
    assembled = assemble_appdir(
        onedir_path=onedir,
        appdir_path=appdir,
        icon_path=icon,
        project_root=project_root,
    )

    assert assembled.is_dir()
    assert (assembled / "AppRun").is_file()
    assert (assembled / "pirate-cinema.desktop").is_file()


def test_download_appimagetool_verifies_checksum(tmp_path: Path):
    tools_dir = tmp_path / "tools"
    fake_content = b"fake-appimagetool-binary-payload"

    class MockResponse:
        def __init__(self, data: bytes):
            self.data = io.BytesIO(data)

        def read(self, amt=-1):
            return self.data.read(amt)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    # Corrupted content should raise ValueError
    with patch("urllib.request.urlopen", return_value=MockResponse(fake_content)):
        with pytest.raises(ValueError, match="appimagetool SHA-256 mismatch"):
            download_appimagetool(tools_dir)

    # Cached verified tool should be reused
    valid_tool = tools_dir / "appimagetool-x86_64.AppImage"
    valid_tool.write_bytes(b"already verified")
    with patch("scripts.build_appimage._sha256_file", return_value=APPIMAGETOOL_SHA256):
        res = download_appimagetool(tools_dir)
        assert res == valid_tool
