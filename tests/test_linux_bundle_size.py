"""Tests for Linux media staging and size analysis."""

import os
import tarfile

from scripts.analyze_linux_bundle import analyze, summary
from scripts.stage_linux_vendor import REQUIRED_TOOLS, install_vendor


def test_vendor_staging_shares_only_identical_media_elfs(tmp_path):
    source = tmp_path / "vendor"
    for tool, names in REQUIRED_TOOLS.items():
        (source / tool).mkdir(parents=True)
        for name in names:
            (source / tool / name).touch()
    (source / "download.tmp").touch()
    mpv = source / "mpv/lib"
    ffmpeg = source / "ffmpeg/lib"
    for directory in (mpv, ffmpeg):
        directory.mkdir()
        (directory / "libsame.so.1.2").write_bytes(b"\x7fELF identical")
        (directory / "libtext.so").write_bytes(b"not ELF")
    (mpv / "libdifferent.so.1").write_bytes(b"\x7fELF x")
    (ffmpeg / "libdifferent.so.1").write_bytes(b"\x7fELF y")
    onedir = tmp_path / "onedir"
    (onedir / "_internal").mkdir(parents=True)

    install_vendor(source, onedir)
    staged = onedir / "_internal/vendor"
    assert not (staged / "download.tmp").exists()
    shared = "libsame.so.1.2"
    assert (staged / "mpv/lib" / shared).samefile(staged / "ffmpeg/lib" / shared)
    assert not (mpv / shared).samefile(staged / "mpv/lib" / shared)
    for name in ("libdifferent.so.1", "libtext.so"):
        assert not (staged / "mpv/lib" / name).samefile(staged / "ffmpeg/lib" / name)

    archive = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(staged, arcname="vendor")
    unpacked = tmp_path / "unpacked"
    with tarfile.open(archive, "r:gz") as tar:
        assert any(member.islnk() for member in tar)
        tar.extractall(unpacked, filter="data")
    assert (unpacked / "vendor/mpv/lib" / shared).samefile(unpacked / "vendor/ffmpeg/lib" / shared)


def test_size_report_separates_hardlinks_from_stored_duplicates(tmp_path, capsys):
    data = b"\x7fELF" + b"x" * 1_000_000
    root = tmp_path / "bundle"
    root.mkdir()
    one = root / "first.so"
    one.write_bytes(data)
    os.link(one, root / "hardlink.so")
    before = analyze(root, {}, read_elf=False)
    (root / "physical-copy.so").write_bytes(data)
    after = analyze(root, {}, read_elf=False)

    assert after["unpacked_bytes"] == 2 * len(data)
    assert after["unpacked_bytes_counting_hardlinks"] == 3 * len(data)
    assert after["duplicate_stored_bytes"] == len(data)
    assert len(after["elf"]) == 3
    assert "+100.0%" in summary(after, before, 0.05)
    assert "::warning::Unpacked" in capsys.readouterr().out