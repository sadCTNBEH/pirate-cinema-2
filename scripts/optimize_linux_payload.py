"""Trim the Linux payload after PyInstaller has collected runtime dependencies."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

# The product supports Russian and English. Keep Chromium's default en-US
# fallback and en-GB as well as ru. Qt's native .qm catalogs are independent.
WEBENGINE_LOCALES = {"en-US.pak", "en-GB.pak", "ru.pak"}


def trim_webengine_locales(internal: Path) -> int:
    locales = internal / "PyQt6/Qt6/translations/qtwebengine_locales"
    if not all((locales / name).is_file() for name in WEBENGINE_LOCALES):
        raise RuntimeError(f"Required Qt WebEngine locales missing in {locales}")
    saved = 0
    for path in sorted(locales.glob("*.pak")):
        if path.name not in WEBENGINE_LOCALES:
            saved += path.lstat().st_size
            path.unlink()
    return saved


def elf_abi(path: Path) -> bytes:
    """Capture dynamic symbols, version requirements, DT_NEEDED and loader paths."""
    output = subprocess.check_output(
        ["readelf", "--wide", "--dyn-syms", "--version-info", "--dynamic", path],
        env={**os.environ, "LC_ALL": "C"},
    )
    # Section indices and file offsets can change when removing non-loadable
    # sections. Keep symbol/version records and the dynamic entries themselves.
    output = re.sub(rb"^Dynamic section at offset 0x[0-9a-f]+ ", b"Dynamic section ", output, flags=re.M)
    return re.sub(rb"^ Addr: .*  Offset: .*  Link: \d+ ", b" ", output, flags=re.M)


def strip_elf(path: Path, flag: str) -> int:
    if path.is_symlink() or not path.is_file():
        return 0
    before = path.stat()
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        stripped = Path(directory) / path.name
        subprocess.run(["strip", flag, "-o", stripped, path], check=True)
        saved = before.st_size - stripped.stat().st_size
        if saved <= 0:
            return 0
        if elf_abi(path) != elf_abi(stripped):
            raise RuntimeError(f"Stripping changed the dynamic ELF ABI of {path}")
        stripped.chmod(stat.S_IMODE(before.st_mode))
        stripped.replace(path)
    return saved


def strip_wheel_elfs(internal: Path) -> int:
    # Python bindings export their entry points through .dynsym. The Qt
    # framework and the prebuilt media executables are outside this selection.
    saved = sum(strip_elf(path, "--strip-unneeded") for path in (internal / "PyQt6").glob("*.so"))
    for name in ("libicui18n", "libicuuc"):
        for path in (internal / "PyQt6/Qt6/lib").glob(f"{name}.so.*"):
            saved += strip_elf(path, "--strip-unneeded")
    for pattern in ("PIL/*.so", "pillow.libs/*.so*"):
        for path in internal.glob(pattern):
            saved += strip_elf(path, "--strip-debug")
    return saved


def share_static_assets(internal: Path) -> int:
    """Keep both static URLs and store matching, immutable images once."""
    static = internal / "static"
    saved = 0
    for first, second in (("icon.png", "logo.png"), ("favicon.png", "tray.png")):
        source, target = static / first, static / second
        if source.is_symlink() or target.is_symlink() or not (source.is_file() and target.is_file()):
            continue
        src, dst = source.stat(), target.stat()
        if (src.st_mode, src.st_size) != (dst.st_mode, dst.st_size) or source.samefile(target):
            continue
        with source.open("rb") as left, target.open("rb") as right:
            if hashlib.file_digest(left, "sha256").digest() != hashlib.file_digest(right, "sha256").digest():
                continue
        with tempfile.TemporaryDirectory(dir=static) as directory:
            link = Path(directory) / target.name
            os.link(source, link)
            link.replace(target)
        saved += dst.st_size
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onedir", type=Path, default=Path("dist/pirate-cinema-linux"))
    args = parser.parse_args()
    internal = args.onedir / "_internal"
    print(f"Qt WebEngine locales: {trim_webengine_locales(internal):,} bytes removed")
    print(f"Wheel ELF symbols: {strip_wheel_elfs(internal):,} bytes removed")
    print(f"Static image hardlinks: {share_static_assets(internal):,} bytes shared")


if __name__ == "__main__":
    main()