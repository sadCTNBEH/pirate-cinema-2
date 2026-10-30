"""Regression coverage for deployed tools and archived vendor layouts."""
import zipfile
from pathlib import Path
from unittest.mock import patch

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
