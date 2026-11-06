# -*- mode: python ; coding: utf-8 -*-
# Media is staged after COLLECT so PyInstaller never analyzes or rewrites its ELF tree.

import subprocess
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH).resolve().parent
datas = [
    (str(root / "static"), "static"),
    (str(root / "version.json"), "."),
    (str(root / "licenses"), "licenses"),
    (str(root / "backend/infrastructure/mpv/cinema.lua"), "backend/infrastructure/mpv"),
    (str(root / "backend/infrastructure/mpv/osd-font"), "backend/infrastructure/mpv/osd-font"),
    (str(root / "backend/services/remote_assets"), "backend/services/remote_assets"),
]
for package in ("PyQt6", "PyQt6-Qt6", "PyQt6-WebEngine", "PyQt6-WebEngine-Qt6", "PyQt6-sip"):
    datas.extend(copy_metadata(package))

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
# The setup-python libpython ships with DWARF sections. Leave runtime symbols,
# the bootloader, Qt, and prebuilt vendor ELF files as collected.
for library in (Path(DISTPATH) / "pirate-cinema-linux/_internal").glob("libpython*.so*"):
    if not library.is_symlink():
        subprocess.run(["strip", "--strip-debug", library], check=True)
