"""Tests for AppImage packaging, AppDir layout, and embedded MPV bundling."""

from __future__ import annotations

import io
import os
import stat
import sys
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.core.settings import user
from scripts.build_appimage import (
    APPIMAGETOOL_SHA256,
    assemble_appdir,
    build_appimage,
    download_appimagetool,
)
from scripts.build_runtime import (
    stamp_appimage_magic,
    verify_runtime_magic,
)
from scripts.bundle_linux_mpv import (
    bundle_mpv,
    is_library_excluded,
    parse_ldd_output,
)
from scripts.patch_runtime import patch_runtime_source


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

    (internal / "version.json").write_text('{"version": "v0.4.3"}', encoding="utf-8")

    mpv_dir = internal / "backend" / "infrastructure" / "mpv"
    mpv_dir.mkdir(parents=True, exist_ok=True)
    (mpv_dir / "cinema.lua").write_text("-- cinema OSD\n", encoding="utf-8")

    ts_dir = internal / "vendor" / "torrserver"
    ts_dir.mkdir(parents=True, exist_ok=True)
    ts_bin = ts_dir / "torrserver"
    ts_bin.write_text("#!/bin/sh\necho torrserver\n", encoding="utf-8")
    ts_bin.chmod(0o755)

    # Embedded MPV in vendor/mpv
    vendor_mpv = internal / "vendor" / "mpv"
    vendor_mpv.mkdir(parents=True, exist_ok=True)
    wrapper = vendor_mpv / "mpv"
    wrapper.write_text("#!/bin/sh\nexec ./mpv.bin \"$@\"\n", encoding="utf-8")
    wrapper.chmod(0o755)
    mpv_bin = vendor_mpv / "mpv.bin"
    mpv_bin.write_bytes(b"\x7fELFfake-mpv")
    mpv_bin.chmod(0o755)
    lib_dir = vendor_mpv / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "libavcodec.so.58").write_bytes(b"\x7fELFfake-avcodec")

    ffmpeg_dir = internal / 'vendor' / 'ffmpeg'
    ffmpeg_dir.mkdir(parents=True)
    for name in ('ffmpeg', 'ffprobe'):
        (ffmpeg_dir / name).write_text(f'#!/bin/sh\nexec "$(dirname "$0")/{name}.bin" "$@"\n')
        (ffmpeg_dir / f'{name}.bin').write_bytes(b'\x7fELFfake-tool')
    (ffmpeg_dir / 'lib').mkdir()
    (ffmpeg_dir / 'lib' / 'libavformat.so.58').write_bytes(b'\x7fELFfake-lib')

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

    # 6. Embedded MPV
    root_mpv = appdir / "vendor" / "mpv" / "mpv"
    root_mpv_bin = appdir / "vendor" / "mpv" / "mpv.bin"
    internal_mpv = appdir / "_internal" / "vendor" / "mpv" / "mpv"
    assert root_mpv.is_file()
    assert root_mpv_bin.is_file()
    assert internal_mpv.is_file()
    assert (appdir / "vendor" / "mpv" / "lib" / "libavcodec.so.58").is_file()
    if os.name != "nt":
        assert root_mpv.stat().st_mode & stat.S_IXUSR
        assert root_mpv_bin.stat().st_mode & stat.S_IXUSR
    for location in (appdir, appdir / '_internal'):
        for name in ('ffmpeg', 'ffprobe', 'ffmpeg.bin', 'ffprobe.bin'):
            tool = location / 'vendor' / 'ffmpeg' / name
            assert tool.is_file()
            if os.name != 'nt':
                assert tool.stat().st_mode & stat.S_IXUSR
        assert (location / 'vendor/ffmpeg/lib/libavformat.so.58').is_file()


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
    assert (assembled / "vendor" / "mpv" / "mpv").is_file()


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


def test_library_exclusion_rules():
    """Verify that host-provided libraries are excluded and media libraries are bundled."""
    # Excluded (host-provided)
    assert is_library_excluded("libc.so.6") is True
    assert is_library_excluded("libm.so.6") is True
    assert is_library_excluded("ld-linux-x86-64.so.2") is True
    assert is_library_excluded("libGL.so.1") is True
    assert is_library_excluded("libEGL.so.1") is True
    assert is_library_excluded("libdrm.so.2") is True
    assert is_library_excluded("libvulkan.so.1") is True
    assert is_library_excluded("libX11.so.6") is True
    assert is_library_excluded("libxcb.so.1") is True
    assert is_library_excluded("libwayland-client.so.0") is True
    assert is_library_excluded("libasound.so.2") is True
    assert is_library_excluded("libpulse.so.0") is True
    assert is_library_excluded("libstdc++.so.6") is True

    # Included (bundled media/FFmpeg/subtitle/scripting libraries)
    assert is_library_excluded("libavcodec.so.58") is False
    assert is_library_excluded("libavformat.so.58") is False
    assert is_library_excluded("libavutil.so.56") is False
    assert is_library_excluded("libswscale.so.5") is False
    assert is_library_excluded("libswresample.so.3") is False
    assert is_library_excluded("libass.so.9") is False
    assert is_library_excluded("liblua5.2.so.0") is False
    assert is_library_excluded("libplacebo.so.192") is False
    assert is_library_excluded("libdav1d.so.5") is False
    assert is_library_excluded("libx264.so.163") is False


def test_parse_ldd_output(tmp_path: Path):
    """Verify that ldd output parser correctly extracts and filters libraries."""
    fake_libav = tmp_path / "libavcodec.so.58"
    fake_libav.write_bytes(b"\x7fELF")
    fake_libc = tmp_path / "libc.so.6"
    fake_libc.write_bytes(b"\x7fELF")

    raw_ldd = f"""
        linux-vdso.so.1 (0x00007ffc5c7d2000)
        libavcodec.so.58 => {fake_libav} (0x00007f35b4400000)
        libc.so.6 => {fake_libc} (0x00007f35b4000000)
        /lib64/ld-linux-x86-64.so.2 (0x00007f35b5000000)
    """
    deps = parse_ldd_output(raw_ldd)
    assert "libavcodec.so.58" in deps
    assert deps["libavcodec.so.58"] == fake_libav.resolve()
    assert "libc.so.6" not in deps
    assert "ld-linux-x86-64.so.2" not in deps


def test_find_mpv_binary_embedded_priority(tmp_path: Path):
    """Verify that find_mpv_binary prioritizes custom player_path, then embedded MPV, then fallback."""
    custom_player = tmp_path / "my_custom_mpv"
    custom_player.write_text("#!/bin/sh\n")
    custom_player.chmod(0o755)

    embedded_mpv = tmp_path / "appdir" / "vendor" / "mpv" / "mpv"
    embedded_mpv.parent.mkdir(parents=True, exist_ok=True)
    embedded_mpv.write_text("#!/bin/sh\n")
    embedded_mpv.chmod(0o755)

    # 1. User custom player_path has highest priority
    with patch.dict(os.environ, {"APPIMAGE": "1", "APPDIR": str(tmp_path / "appdir")}):
        found = user.find_mpv_binary({"player_path": str(custom_player)})
        assert found == custom_player.resolve()

    # 2. Embedded MPV inside APPDIR is default when no player_path set
    with (
        patch.dict(os.environ, {"APPDIR": str(tmp_path / "appdir")}),
        patch.object(sys, "platform", "linux"),
    ):
        found = user.find_mpv_binary({})
        assert found == embedded_mpv.resolve()

    # 3. Fallback to system MPV when embedded not found
    fallback_sys_mpv = tmp_path / "system_mpv"
    fallback_sys_mpv.write_text("#!/bin/sh\n")
    fallback_sys_mpv.chmod(0o755)

    orig_is_file = Path.is_file

    def mock_is_file(self):
        try:
            if self.resolve() == fallback_sys_mpv.resolve():
                return orig_is_file(self)
        except OSError:
            pass
        if self.name.lower().startswith("mpv"):
            return False
        return orig_is_file(self)

    with (
        patch.dict(os.environ, {"APPDIR": "", "APPIMAGE": ""}),
        patch.object(user, "BASE_DIR", tmp_path / "empty_base"),
        patch.object(user, "get_data_dir", lambda: tmp_path / "empty_data"),
        patch.object(sys, "platform", "linux"),
        patch("shutil.which", return_value=str(fallback_sys_mpv)),
        patch.object(Path, "is_file", mock_is_file),
    ):
        found = user.find_mpv_binary({})
        assert found is not None
        assert found.resolve() == fallback_sys_mpv.resolve()


def test_build_appimage_invokes_custom_runtime(tmp_path: Path):
    """Verify build_appimage passes --runtime-file to appimagetool when provided."""
    appdir = tmp_path / "AppDir"
    appdir.mkdir(parents=True)
    out_file = tmp_path / "dist" / "output.AppImage"
    tools_dir = tmp_path / "tools"
    custom_runtime = tmp_path / "custom_runtime"
    custom_runtime.write_bytes(b"\x7fELF" + b"\x00" * 4 + b"AI\x02" + b"\x00" * 20000)

    mock_tool = tools_dir / "appimagetool-x86_64.AppImage"
    mock_tool.parent.mkdir(parents=True, exist_ok=True)
    mock_tool.write_text("#!/bin/sh\n")

    executed_cmds = []

    def mock_subprocess_run(cmd, **kwargs):
        executed_cmds.append(cmd)
        # Create expected output file with size > 1MB
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"\x00" * 1_500_000)
        res = MagicMock()
        res.returncode = 0
        return res

    with (
        patch("scripts.build_appimage.download_appimagetool", return_value=mock_tool),
        patch("subprocess.run", side_effect=mock_subprocess_run),
    ):
        build_appimage(
            appdir_path=appdir,
            output_path=out_file,
            tools_dir=tools_dir,
            runtime_file=custom_runtime,
        )

    assert len(executed_cmds) == 1
    cmd = executed_cmds[0]
    assert "--runtime-file" in cmd
    runtime_idx = cmd.index("--runtime-file")
    assert cmd[runtime_idx + 1] == str(custom_runtime)


def test_runtime_magic_stamping_and_verification(tmp_path: Path):
    """Verify stamping AI\\x02 magic bytes at offset 8 and checking validity."""
    fake_elf = tmp_path / "fake_runtime"
    # Valid ELF header without AppImage magic
    fake_elf.write_bytes(b"\x7fELF" + b"\x00" * 20000)
    assert verify_runtime_magic(fake_elf) is False

    stamp_appimage_magic(fake_elf)
    assert verify_runtime_magic(fake_elf) is True

    # Check bytes directly
    raw = fake_elf.read_bytes()
    assert raw[:4] == b"\x7fELF"
    assert raw[8:11] == b"AI\x02"


def test_patch_runtime_source(tmp_path: Path):
    """Verify patch_runtime_source applies automatic fallback code to runtime.c."""
    runtime_c = tmp_path / "runtime.c"
    sample_runtime = """
void set_portable_home_and_config(char* basepath) {
    /* portable config */
}

int main(int argc, char* argv[]) {
    if (pid == 0) {
        if (0 != fusefs_main(5, child_argv, fuse_mounted)) {
            char* title;
            char* body;
            title = "Cannot mount AppImage, please check your FUSE setup.";
            body = "You might still be able to extract the contents of this AppImage \\n"
                   "if you run it with the --appimage-extract option. \\n"
                   "See https://github.com/AppImage/AppImageKit/wiki/FUSE \\n"
                   "for more information";
            printf("\\n%s\\n", title);
            printf("%s\\n", body);
        };
    } else {
        /* Pause until mounted */
        read(keepalive_pipe[0], &c, 1);

        /* Fuse process has now daemonized, reap our child */
        waitpid(pid, NULL, 0);

        dir_fd = open(mount_dir, O_RDONLY);
    }
    return 0;
}
"""
    runtime_c.write_text(sample_runtime, encoding="utf-8")
    assert patch_runtime_source(runtime_c) is True

    modified = runtime_c.read_text(encoding="utf-8")
    assert "execute_extracted_fallback" in modified
    assert "pirate_cinema_extracted_" in modified
    assert "FUSE mount failed! Clean up empty mount_dir and fallback" in modified

