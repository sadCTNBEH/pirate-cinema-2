"""Install prebuilt Linux media tools after PyInstaller's ELF analysis."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import tempfile
from pathlib import Path

REQUIRED_TOOLS = {
    "mpv": ("mpv", "mpv.bin"),
    "ffmpeg": ("ffmpeg", "ffmpeg.bin", "ffprobe", "ffprobe.bin"),
    "torrserver": ("torrserver",),
}


def validate_vendor(vendor: Path) -> None:
    for tool, names in REQUIRED_TOOLS.items():
        for name in names:
            path = vendor / tool / name
            if not path.is_file():
                raise RuntimeError(f"Linux package requires the bundled {path}")


def share_media_libraries(vendor: Path) -> tuple[int, int]:
    """Replace identical ELF files with hardlinks while preserving both lookup paths."""
    mpv = vendor / "mpv" / "lib"
    ffmpeg = vendor / "ffmpeg" / "lib"
    shared = saved = 0
    for target in sorted(ffmpeg.glob("*")):
        source = mpv / target.name
        if source.is_symlink() or target.is_symlink() or not (source.is_file() and target.is_file()):
            continue
        src, dst = source.stat(), target.stat()
        if (src.st_size, stat.S_IMODE(src.st_mode)) != (dst.st_size, stat.S_IMODE(dst.st_mode)):
            continue
        if source.samefile(target):
            continue
        with source.open("rb") as left, target.open("rb") as right:
            if left.read(4) != b"\x7fELF" or right.read(4) != b"\x7fELF":
                continue
            left.seek(0)
            right.seek(0)
            if hashlib.file_digest(left, "sha256").digest() != hashlib.file_digest(right, "sha256").digest():
                continue
        with tempfile.TemporaryDirectory(dir=ffmpeg) as tmp:
            link = Path(tmp) / target.name
            os.link(source, link)
            link.replace(target)
        shared += 1
        saved += dst.st_size
    return shared, saved


def install_vendor(source: Path, onedir: Path) -> None:
    """Stage only the Linux vendor directories needed at runtime."""
    validate_vendor(source)
    internal = onedir / "_internal"
    if not internal.is_dir():
        raise NotADirectoryError(internal)
    destination = internal / "vendor"
    with tempfile.TemporaryDirectory(dir=internal) as tmp:
        staged = Path(tmp) / "vendor"
        for tool in REQUIRED_TOOLS:
            shutil.copytree(source / tool, staged / tool, symlinks=True)
        for path in staged.rglob("*"):
            if path.is_symlink() and (
                path.readlink().is_absolute() or not path.resolve(strict=True).is_relative_to(staged)
            ):
                raise ValueError(f"Vendor symlink points outside the package: {path}")
        count, saved = share_media_libraries(staged)
        staged.rename(destination)
    print(f"Shared {count} identical media libraries ({saved:,} bytes saved before compression)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, default=Path("vendor"))
    parser.add_argument("--onedir", type=Path, default=Path("dist/pirate-cinema-linux"))
    args = parser.parse_args()
    install_vendor(args.vendor, args.onedir)