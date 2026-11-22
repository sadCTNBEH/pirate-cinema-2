"""Report the highest glibc symbol version required by an extracted Linux bundle."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

GLIBC_SYMBOL = re.compile(r"GLIBC_(\d+(?:\.\d+)+)")


def _version_key(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def maximum_glibc(roots: list[Path]) -> tuple[str | None, Path | None]:
    """Return the highest GLIBC symbol version and a binary requiring it."""
    required: set[str] = set()
    binaries: list[tuple[str, Path]] = []
    paths = (path for root in roots for path in ([root] if root.is_file() else root.rglob("*")))
    for path in paths:
        if not path.is_file():
            continue
        try:
            with path.open("rb") as stream:
                if stream.read(4) != b"\x7fELF":
                    continue
        except OSError:
            continue
        result = subprocess.run(
            ["readelf", "--version-info", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        versions = set(GLIBC_SYMBOL.findall(result.stdout))
        required.update(versions)
        binaries.extend((version, path) for version in versions)
    if not required:
        return None, None
    highest = max(required, key=_version_key)
    return highest, next(path for version, path in binaries if version == highest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "bundle_paths",
        type=Path,
        nargs="+",
        help="extracted AppDir/PyInstaller _internal directory and optional outer AppImage ELF",
    )
    args = parser.parse_args()
    highest, binary = maximum_glibc(args.bundle_paths)
    if highest is None:
        parser.error(f"No ELF files or GLIBC symbol requirements found under {args.bundle_paths}")
    print(f"Maximum required GLIBC symbol version: {highest}")
    print(f"Requiring binary: {binary}")
    print("Ubuntu 22.04 provides glibc 2.35; compatibility requires maximum <= 2.35.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
