"""Exercise the Linux payload trim without touching a real installation."""

import ctypes
import shutil
import subprocess
import sys

import pytest

from scripts.optimize_linux_payload import (
    WEBENGINE_LOCALES,
    elf_abi,
    share_static_assets,
    strip_elf,
    trim_webengine_locales,
)


def test_webengine_locale_trim_retains_fallback_and_other_qt_resources(tmp_path):
    qt = tmp_path / "PyQt6/Qt6"
    locales = qt / "translations/qtwebengine_locales"
    locales.mkdir(parents=True)
    (qt / "resources").mkdir()
    chromium = qt / "resources/qtwebengine_resources.pak"
    chromium.write_bytes(b"required Chromium resource")
    qt_catalog = locales.parent / "qtbase_de.qm"
    qt_catalog.touch()
    for name in WEBENGINE_LOCALES:
        (locales / name).touch()
    (locales / "de.pak").write_bytes(b"unshipped locale")

    assert trim_webengine_locales(tmp_path) == len(b"unshipped locale")
    assert {p.name for p in locales.iterdir()} == WEBENGINE_LOCALES
    assert chromium.is_file() and qt_catalog.is_file()
    assert trim_webengine_locales(tmp_path) == 0


def test_webengine_locale_trim_fails_before_removing_files_if_required_locale_missing(tmp_path):
    locales = tmp_path / "PyQt6/Qt6/translations/qtwebengine_locales"
    locales.mkdir(parents=True)
    unrelated = locales / "de.pak"
    unrelated.touch()
    with pytest.raises(RuntimeError, match="Required Qt WebEngine locales missing"):
        trim_webengine_locales(tmp_path)
    assert unrelated.exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux package filesystem")
def test_static_hardlinks_require_identical_contents(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    for name in ("icon.png", "logo.png", "tray.png"):
        (static / name).write_bytes(b"same icon")
    (static / "favicon.png").write_bytes(b"distinct")
    assert share_static_assets(tmp_path) == len(b"same icon")
    assert (static / "icon.png").samefile(static / "logo.png")
    assert not (static / "favicon.png").samefile(static / "tray.png")
    assert share_static_assets(tmp_path) == 0


@pytest.mark.skipif(
    sys.platform != "linux" or not all(shutil.which(tool) for tool in ("cc", "strip", "readelf")),
    reason="GNU ELF build tools",
)
def test_strip_preserves_dynamic_abi_and_loadability(tmp_path):
    src = tmp_path / "fixture.c"
    src.write_text("int fixture(void) { return 42; }\n")
    library = tmp_path / "fixture.so"
    subprocess.run(["cc", "-shared", "-fPIC", "-g", "-o", library, src], check=True)
    abi = elf_abi(library)
    assert strip_elf(library, "--strip-unneeded") > 0
    assert elf_abi(library) == abi
    assert ctypes.CDLL(str(library)).fixture() == 42