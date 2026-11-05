"""Regression coverage for deployed tools and archived vendor layouts."""
import hashlib
import os
import shutil
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.core import settings
from backend.infrastructure import downloader, ffmpeg


def test_appdir_tools_precede_system_path(tmp_path, monkeypatch):
    bundled = tmp_path / 'vendor/ffmpeg/ffprobe'
    bundled.parent.mkdir(parents=True)
    bundled.write_text('#!/bin/sh\n')
    monkeypatch.setenv('APPDIR', str(tmp_path))
    monkeypatch.setattr(ffmpeg.sys, 'platform', 'linux')
    with patch.object(ffmpeg.shutil, 'which', return_value='/system/ffprobe'):
        assert ffmpeg.get_ffprobe() == bundled


def test_windows_archive_with_versioned_bin_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader.sys, 'platform', 'win32')
    monkeypatch.setattr(downloader, 'get_data_dir', lambda: tmp_path)
    def download(url, destination):
        with zipfile.ZipFile(destination, 'w') as archive:
            for name in ('ffmpeg.exe', 'ffprobe.exe'):
                archive.writestr('ffmpeg-release-essentials/bin/' + name, b'executable')
    with patch.object(ffmpeg, 'find_binary', return_value=None), patch.object(downloader, 'download_file', side_effect=download):
        downloader.ensure_ffmpeg_binaries()
    for name in ('ffmpeg.exe', 'ffprobe.exe'):
        assert (tmp_path / 'vendor/ffmpeg' / name).read_bytes() == b'executable'


@pytest.mark.skipif(downloader.sys.platform != "linux", reason="Linux media tools")
@pytest.mark.parametrize("mpv_already_present", [False, True])
def test_linux_release_installs_missing_tools_after_checksum_verification(tmp_path, monkeypatch, mpv_already_present):
    vendor = tmp_path / "vendor"
    release = tmp_path / "release"
    archive_name = downloader.LINUX_MEDIA_ARCHIVES[0]
    for tool, commands in {"mpv": ["mpv"], "ffmpeg": ["ffmpeg", "ffprobe"]}.items():
        for command in commands:
            path = release / downloader.LINUX_VENDOR_PATH / tool / command
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
    release_vendor = release / downloader.LINUX_VENDOR_PATH
    mpv_lib = release_vendor / "mpv/lib/libshared.so"
    ffmpeg_lib = release_vendor / "ffmpeg/lib/libshared.so"
    mpv_lib.parent.mkdir()
    ffmpeg_lib.parent.mkdir()
    mpv_lib.write_bytes(b"shared library")
    os.link(mpv_lib, ffmpeg_lib)
    archive_path = release / archive_name
    with tarfile.open(archive_path, "w:gz") as archive:
        for tool in ("mpv", "ffmpeg"):
            directory = downloader.LINUX_VENDOR_PATH / tool
            archive.add(release / directory, arcname=str(directory))
    if mpv_already_present:
        installed = vendor / "mpv/mpv"
        installed.parent.mkdir(parents=True)
        installed.write_text("existing MPV")

    monkeypatch.setattr(downloader, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(downloader.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(settings, "find_mpv_binary", lambda: (vendor / "mpv/mpv") if (vendor / "mpv/mpv").exists() else None)
    monkeypatch.setattr(ffmpeg, "find_binary", lambda name: (vendor / "ffmpeg" / name) if (vendor / "ffmpeg" / name).exists() else None)
    sums = release / "SHA256SUMS"
    sums.write_text(f"{'0' * 64}  {archive_name}\n", encoding="utf-8")
    with patch.object(downloader, "download_file", side_effect=lambda url, dest: shutil.copyfile(release / url.rsplit("/", 1)[1], dest)) as download:
        with pytest.raises(RuntimeError, match="checksum mismatch"):
            downloader.ensure_linux_media_tools()
        assert not (vendor / "ffmpeg").exists()
        sums.write_text(f"{hashlib.sha256(archive_path.read_bytes()).hexdigest()}  {archive_name}\n", encoding="utf-8")
        downloader.ensure_linux_media_tools()
        assert (vendor / "mpv/mpv").is_file()
        assert (vendor / "ffmpeg/ffprobe").is_file()
        assert (vendor / "ffmpeg/lib/libshared.so").read_bytes() == b"shared library"
        if mpv_already_present:
            assert (vendor / "mpv/mpv").read_text() == "existing MPV"
        downloader.ensure_linux_media_tools()
        assert download.call_count == 4


def test_hls_requires_exact_boundaries_even_for_h264_mkv():
    data = {'format': {'format_name': 'matroska', 'duration': '120'}, 'streams': [
        {'codec_type': 'video', 'codec_name': 'h264', 'pix_fmt': 'yuv420p'},
    ]}
    assert ffmpeg.analyze_compatibility(data)['mode'] == 'transcode'
    cmd = ffmpeg.build_hls_command(Path('ffmpeg'), 'source.mkv', 42, 7, 6, 'sink_%d.ts', 'sink.m3u8')
    assert cmd[cmd.index('-force_key_frames') + 1] == 'expr:gte(t,n_forced*6)'
    assert cmd[cmd.index('-map', cmd.index('-map') + 1) + 1] == '0:a:0?'
    assert cmd[cmd.index('-t') + 1] == '42'


def test_video_duration_does_not_add_an_audio_padding_segment():
    data = {'format': {'duration': '54.016'}, 'streams': [
        {'codec_type': 'video', 'codec_name': 'h264', 'start_time': '0.005',
         'tags': {'DURATION': '00:00:54.005000000'}},
    ]}
    assert ffmpeg.analyze_compatibility(data)['duration'] == 54
