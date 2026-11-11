"""Select codec-enabled system PyQt6 on Linux without mixing Qt installations."""

from __future__ import annotations

import importlib.util
import os
import re
import runpy
import sys
from pathlib import Path
from types import ModuleType


CODEC_FEATURE = re.compile(
    r"^\s*#\s*define\s+QT_FEATURE_webengine_proprietary_codecs\s+1\s*$",
    re.MULTILINE,
)


def _system_pyqt_candidates() -> list[Path]:
    """Find system PyQt packages, excluding this project's virtualenv."""
    candidates: list[Path] = []
    venv = Path(sys.prefix).resolve()
    project = Path(__file__).resolve().parents[1]

    for entry in sys.path:
        if not entry:
            continue
        base = Path(entry).resolve()
        if base == venv or venv in base.parents or base == project or project in base.parents:
            continue
        package = base / "PyQt6"
        if (
            (package / "QtCore.abi3.so").is_file()
            and (package / "QtWebEngineWidgets.abi3.so").is_file()
            and not (package / "Qt6").exists()
        ):
            if package not in candidates:
                candidates.append(package)

    # Some distributions do not expose their system site-packages to a venv's
    # sys.path. Search only standard system Python locations for the same ABI.
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    standard_locations = [
        root / version / suffix / "PyQt6"
        for root in (Path("/usr/lib"), Path("/usr/local/lib"))
        for suffix in ("site-packages", "dist-packages")
    ]
    standard_locations.extend((
        Path("/usr/lib/python3/dist-packages/PyQt6"),
        Path("/usr/local/lib/python3/dist-packages/PyQt6"),
    ))
    for package in standard_locations:
        if (
            (package / "QtCore.abi3.so").is_file()
            and (package / "QtWebEngineWidgets.abi3.so").is_file()
            and not (package / "Qt6").exists()
        ):
            if package not in candidates:
                candidates.append(package)
    return candidates


def _codec_feature_file(package: Path) -> Path | None:
    # System packages normally install this generated header alongside Qt.
    # Deriving the prefix from the binding path also supports package roots
    # with a multiarch library directory.
    if len(package.parents) <= 3:
        return None
    prefix = package.parents[3]
    include_dirs = (
        "include/qt6",
        "include/x86_64-linux-gnu/qt6",
        "include/aarch64-linux-gnu/qt6",
    )
    for include_dir in include_dirs:
        module_dir = prefix / include_dir / "QtWebEngineCore"
        for header in module_dir.rglob("qtwebenginecore-config*.h"):
            if CODEC_FEATURE.search(header.read_text(encoding="utf-8", errors="replace")):
                return header
    return None


def _load_pyqt(package: Path, *, wheel: bool = False) -> None:
    init_file = package / "__init__.py"
    if init_file.is_file():
        spec = importlib.util.spec_from_file_location(
            "PyQt6", init_file, submodule_search_locations=[str(package)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load PyQt6 package at {package}")
        module = importlib.util.module_from_spec(spec)
        sys.modules["PyQt6"] = module
        spec.loader.exec_module(module)
    else:
        module = ModuleType("PyQt6")
        sys.modules["PyQt6"] = module
    # PyQt6 wheels use a namespace package. Keep this runtime's package tree
    # closed so a missing system submodule can never be filled by a wheel.
    module.__path__ = [str(package)]

    # Import before the app so Qt resolves every binding from one package tree.
    from PyQt6 import QtCore  # noqa: PLC0415
    from PyQt6 import QtWebEngineCore, QtWebEngineWidgets  # noqa: PLC0415

    built = tuple(map(int, QtCore.QT_VERSION_STR.split(".")))
    linked = tuple(map(int, QtCore.qVersion().split(".")))
    if linked[:2] != built[:2] or linked < built:
        raise RuntimeError(
            f"PyQt6 was built for Qt {QtCore.QT_VERSION_STR}, "
            f"but the loader found Qt {QtCore.qVersion()}"
        )
    for loaded in (QtCore, QtWebEngineCore, QtWebEngineWidgets):
        path = Path(loaded.__file__).resolve()
        if package.resolve() not in path.parents:
            raise RuntimeError(f"Mixed Qt bindings detected: {loaded.__name__} loaded from {path}")

    venv = Path(sys.prefix).resolve()
    for mapping in Path("/proc/self/maps").read_text(errors="replace").splitlines():
        _, _, path = mapping.partition("/")
        if "libQt6" not in path:
            continue
        library = Path("/" + path)
        mixed = not library.is_relative_to(package) if wheel else library.is_relative_to(venv)
        if mixed:
            raise RuntimeError(f"Mixed Qt libraries detected: {library}")


def _remove_venv_qt_paths() -> bool:
    """Prevent stale wheel paths from shadowing the selected system Qt."""
    venv = Path(sys.prefix).resolve()
    variables = ("LD_LIBRARY_PATH", *QT_PATHS)
    loader_path_changed = False
    for name in variables:
        original = os.environ.get(name, "")
        values = original.split(os.pathsep)
        filtered = []
        for value in values:
            if not value:
                continue
            path = Path(value).resolve()
            if not path.is_relative_to(venv):
                filtered.append(value)
        cleaned = os.pathsep.join(filtered)
        if name == "LD_LIBRARY_PATH" and original != cleaned:
            loader_path_changed = True
        if cleaned:
            os.environ[name] = cleaned
        else:
            os.environ.pop(name, None)
    return loader_path_changed


QT_PATHS = (
    "QT_PLUGIN_PATH",
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    "QTWEBENGINEPROCESS_PATH",
    "QTWEBENGINE_RESOURCES_PATH",
    "QTWEBENGINE_LOCALES_PATH",
    "QML_IMPORT_PATH",
    "QML2_IMPORT_PATH",
)


def _restart() -> None:
    os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])


def _activate_wheel() -> None:
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    package = Path(sys.prefix) / "lib" / version / "site-packages/PyQt6"
    if not (package / "Qt6/lib/libQt6WebEngineCore.so.6").is_file():
        raise RuntimeError("Install the fallback in .venv with `python -m pip install 'pywebview[qt6]'`.")
    for name in QT_PATHS:
        os.environ.pop(name, None)
    _load_pyqt(package.resolve(), wheel=True)


def main() -> int:
    runtime = os.environ.get("PIRATE_CINEMA_QT_RUNTIME", "auto").strip().lower()
    if runtime not in {"auto", "system", "wheel"}:
        print("PIRATE_CINEMA_QT_RUNTIME must be auto, system, or wheel", file=sys.stderr)
        return 2

    os.environ["QT_API"] = "pyqt6"
    os.environ["PIRATE_CINEMA_QT_RUNTIME_SELECTED"] = "wheel"
    if runtime != "wheel":
        candidates = _system_pyqt_candidates()
        enabled = next(
            (candidate for candidate in candidates if _codec_feature_file(candidate)),
            None,
        )
        if enabled:
            try:
                if _remove_venv_qt_paths():
                    # The ELF loader reads LD_LIBRARY_PATH when Python starts.
                    _restart()
                _load_pyqt(enabled)
            except Exception as error:
                print(f"Cannot start with codec-enabled system Qt: {error}", file=sys.stderr)
                if runtime == "auto":
                    print("Retrying with the isolated Qt wheel. H.264/AAC may be unavailable.", file=sys.stderr)
                    os.environ["PIRATE_CINEMA_QT_RUNTIME"] = "wheel"
                    _restart()
                return 1
            os.environ["PIRATE_CINEMA_QT_RUNTIME_SELECTED"] = "system"
            print(f"Using codec-enabled system Qt WebEngine from {enabled}", flush=True)
        elif runtime == "system":
            print(
                "Codec-enabled system PyQt6/Qt WebEngine was not found. On Arch/CachyOS install it with "
                "`sudo pacman -S --needed qt6-webengine python-pyqt6-webengine python-pyqt6`; headers must "
                "report QT_FEATURE_webengine_proprietary_codecs=1.",
                file=sys.stderr,
            )
            return 1
        else:
            print(
                "WARNING: no codec-enabled system Qt WebEngine found; using the isolated .venv Qt runtime. "
                "Anime H.264/AAC playback may be unsupported.",
                flush=True,
            )

    if os.environ["PIRATE_CINEMA_QT_RUNTIME_SELECTED"] == "wheel":
        try:
            _activate_wheel()
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            print(f"Cannot start with the isolated Qt wheel: {error}", file=sys.stderr)
            return 1

    project = Path(__file__).resolve().parents[1]
    if str(project) not in sys.path:
        sys.path.insert(0, str(project))
    runpy.run_path(str(project / "run.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
