"""Validate the Qt WebEngine payload collected by PyInstaller on Linux."""

import os
import re
import subprocess
from pathlib import Path


def verify(internal: Path) -> None:
    internal = internal.resolve()
    qt = internal / "PyQt6/Qt6"
    helper = qt / "libexec/QtWebEngineProcess"
    plugin = qt / "plugins/platforms/libqxcb.so"
    resources = qt / "resources"
    required = [
        helper,
        plugin,
        resources / "qtwebengine_resources.pak",
        resources / "qtwebengine_resources_100p.pak",
        resources / "qtwebengine_resources_200p.pak",
        qt / "translations/qtwebengine_locales/en-US.pak",
    ]
    for file in required:
        if not file.is_file() or not file.stat().st_size:
            raise RuntimeError(f"Missing Qt WebEngine bundle file: {file}")

    engine = list(internal.rglob("libQt6WebEngineCore.so.6"))
    if len({path.resolve() for path in engine}) != 1:
        raise RuntimeError(f"Expected one Qt WebEngine ABI in the bundle, found {engine}")

    env = {**os.environ, "LD_LIBRARY_PATH": str(internal)}
    for binary in (helper, plugin, engine[0]):
        result = subprocess.run(
            ["ldd", str(binary)], env=env, check=True, capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if "not found" in line:
                raise RuntimeError(f"Unresolved dependency of {binary.name}: {line.strip()}")
            match = re.search(r"libQt6\S+\s+=>\s+(\S+)", line)
            if match and not Path(match[1]).resolve().is_relative_to(internal):
                raise RuntimeError(f"{binary.name} resolves Qt outside the bundle: {match[1]}")
    print("Verified bundled Qt WebEngine helper, resources, xcb and ELF dependencies")
