# -*- mode: python ; coding: utf-8 -*-
# Media is staged after COLLECT so PyInstaller never analyzes or rewrites its ELF tree.

import subprocess
from pathlib import Path

from PyQt6 import QtWebEngineCore
from PyInstaller.utils.hooks import get_package_paths
from PyInstaller.utils.hooks.qt import pyqt6_library_info

from scripts.linux_qt_launcher import _codec_feature_file
from scripts.verify_bundled_webengine import verify

root = Path(SPECPATH).resolve().parent
datas = [
    (str(root / "static"), "static"),
    (str(root / "version.json"), "."),
    (str(root / "THIRD_PARTY_NOTICES"), "."),
    (str(root / "licenses"), "licenses"),
    (str(root / "backend/infrastructure/mpv/cinema.lua"), "backend/infrastructure/mpv"),
    (str(root / "backend/infrastructure/mpv/osd-font"), "backend/infrastructure/mpv/osd-font"),
    (str(root / "backend/services/remote_assets"), "backend/services/remote_assets"),
]
_, bindings = get_package_paths("PyQt6")
if (Path(bindings) / "Qt6").exists():
    raise SystemExit("Use distro PyQt6 and Qt WebEngine for the Linux bundle, without Qt wheels.")
if _codec_feature_file(Path(bindings)) is None:
    raise SystemExit("Qt WebEngine must be built with proprietary codecs; install its private development headers.")
qt_libraries = Path(pyqt6_library_info.location["LibrariesPath"])
if not (qt_libraries / "libQt6WebEngineCore.so.6").is_file():
    raise SystemExit(f"No Qt WebEngine libraries under {qt_libraries}")
print(f"Collecting Qt WebEngine from {QtWebEngineCore.__file__} and {qt_libraries}")


a = Analysis(
    [str(root / "run.py")],
    datas=datas,
    hiddenimports=["PyQt6.QtWebEngineWidgets", "backend.infrastructure.mpv.qt_surface"],
    excludes=[
        "PyQt5", "PySide2", "PySide6",
        # The Python app uses QWidget/QWebEngineView, with no QML engine or imports.
        # Analysis still follows the native DT_NEEDED QtQuick/QtQml dependencies.
        "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtQuickWidgets",
    ],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="pirate-cinema-linux", console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="pirate-cinema-linux")
# The frozen runtime hook points Qt at the PyQt6/Qt6 tree created by the
# PyInstaller Qt hooks. Verify the deployable layout before packing it.
verify(Path(DISTPATH) / "pirate-cinema-linux/_internal")
# The interpreter's libpython can ship with DWARF sections. Leave runtime symbols,
# the bootloader, Qt, and prebuilt vendor ELF files as collected.
for library in (Path(DISTPATH) / "pirate-cinema-linux/_internal").glob("libpython*.so*"):
    if not library.is_symlink():
        subprocess.run(["strip", "--strip-debug", library], check=True)
