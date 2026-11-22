#!/usr/bin/env python3
"""Bundle Linux x86_64 MPV with FFmpeg and media dependencies for Pirate Cinema.

Collects ELF dependencies of MPV while excluding core glibc, host display
servers (X11/Wayland), audio daemons (ALSA/Pulse/PipeWire), and GPU drivers
(OpenGL/Vulkan/DRM) to ensure hardware acceleration and display compatibility
on host Linux systems.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("bundle_linux_mpv")

# Standard AppImage exclusion rules for system-provided host libraries
EXCLUDED_EXACT = {
    "ld-linux.so.2",
    "ld-linux-x86-64.so.2",
    "libc.so.6",
    "libdl.so.2",
    "libm.so.6",
    "libmvec.so.1",
    "libpthread.so.0",
    "librt.so.1",
    "libresolv.so.2",
    "libutil.so.1",
    "libnsl.so.1",
    "libanl.so.1",
    "libstdc++.so.6",
    "libgcc_s.so.1",
    "libz.so.1",
    "libexpat.so.1",
    "libuuid.so.1",
    "libasound.so.2",
    "libjack.so.0",
    "libdbus-1.so.3",
    "libsystemd.so.0",
    "libudev.so.1",
}

EXCLUDED_PREFIXES = (
    "ld-linux",
    "libc.",
    "libm.",
    "libdl.",
    "libpthread.",
    "librt.",
    "libresolv.",
    "libnss_",
    "libstdc++",
    "libgcc_s",
    # GPU & Graphics drivers (must come from host for HW acceleration)
    "libGL.",
    "libGLX.",
    "libEGL.",
    "libGLdispatch.",
    "libOpenGL.",
    "libGLESv2.",
    "libglapi.",
    "libdrm.",
    "libgbm.",
    "libvulkan.",
    # X11 core libraries
    "libX11.",
    "libX11-xcb.",
    "libxcb.",
    "libxcb-",
    "libXext.",
    "libXfixes.",
    "libXrender.",
    "libXdamage.",
    "libXcomposite.",
    "libXinerama.",
    "libXrandr.",
    "libXi.",
    "libXcursor.",
    "libXv.",
    "libXss.",
    "libxkbcommon.",
    "libxkbcommon-x11.",
    # Wayland core libraries
    "libwayland-client.",
    "libwayland-cursor.",
    "libwayland-egl.",
    "libwayland-server.",
    # Audio server libraries
    "libpulse.",
    "libpulse-simple.",
    "libpulsecommon-",
    "libpipewire-",
    "libasound.",
    # Tkinter / Tcl / Tk (unused GUI libraries)
    "libtk.",
    "libtk8.",
    "libtcl.",
    "libtcl8.",
    # Test libraries
    "libgtest.",
    "libgmock.",
    "libcmocka.",
    "libcheck.",
    "libcppunit.",
)

WRAPPER_SCRIPT = """#!/bin/sh
# Isolated launcher for bundled MPV player.
# Keeps private LD_LIBRARY_PATH strictly scoped to MPV and its child processes.
set -e
HERE="$(dirname "$(readlink -f "$0")")"
export LD_LIBRARY_PATH="${HERE}/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "${HERE}/mpv.bin" "$@"
"""

LICENSE_TEXT = """# Open Source Licenses for Bundled MPV and Dependencies

This installation of Pirate Cinema bundles a standalone build of MPV and
associated media libraries (including FFmpeg) to provide out-of-the-box video
playback on Linux systems without requiring system package installation.

## MPV Player
- **License:** GNU General Public License v2.0 or later (GPL-2.0+) / LGPLv2.1+
- **Website:** https://mpv.io
- **Source Code:** https://github.com/mpv-player/mpv

## FFmpeg Libraries
- **Libraries:** libavcodec, libavformat, libavutil, libswscale, libswresample, libavfilter
- **License:** GNU Lesser General Public License v2.1 or later (LGPL-2.1+) / GPL-2.0+
- **Website:** https://ffmpeg.org
- **Source Code:** https://git.ffmpeg.org/ffmpeg.git

## Supporting Libraries
- **libass** (Subtitles): ISC License
- **Lua** (Scripting runtime for cinema.lua): MIT License
- **libuchardet** (Charset detection): Mozilla Public License 1.1 / GPL / LGPL
- **libplacebo** (GPU image processing): LGPL-2.1+
- **libbluray**: LGPL-2.1+
- **Audio & Video Codecs** (libdav1d, libvpx, libx264, libx265, libopus, libvorbis, libtheora, etc.):
  Respective BSD / LGPL / GPL open source licenses.

Full license texts are available in the upstream repositories and in Linux system
documentation under `/usr/share/doc/<package>/copyright`.
"""


def is_library_excluded(name: str) -> bool:
    """Return True if the library should NOT be bundled into the AppImage."""
    clean_name = name.strip().lower()
    if clean_name in EXCLUDED_EXACT:
        return True
    return any(clean_name.startswith(p.lower()) for p in EXCLUDED_PREFIXES)


def parse_ldd_output(ldd_text: str) -> dict[str, Path]:
    """Parse ldd output into a dictionary of {soname: resolved_file_path}."""
    deps: dict[str, Path] = {}
    for line in ldd_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Case 1: libname.so.1 => /path/to/libname.so.1 (0x00007f...)
        match1 = re.match(r"^([^\s]+)\s*=>\s*([^\s]+)\s*\(0x[0-9a-fA-F]+\)$", line)
        if match1:
            soname = Path(match1.group(1)).name
            raw_path = match1.group(2)
            p = Path(raw_path)
            if p.is_file() and not is_library_excluded(soname):
                deps[soname] = p.resolve()
            continue

        # Case 2: /lib64/ld-linux-x86-64.so.2 (0x00007f...)
        match2 = re.match(r"^([^\s]+)\s*\(0x[0-9a-fA-F]+\)$", line)
        if match2:
            p = Path(match2.group(1))
            soname = p.name
            if p.is_file() and not is_library_excluded(soname):
                deps[soname] = p.resolve()

    return deps


def get_binary_dependencies(binary_path: Path) -> dict[str, Path]:
    """Run ldd on an ELF binary and return non-excluded dependencies."""
    if not binary_path.is_file():
        raise FileNotFoundError(f"Binary not found: {binary_path}")

    try:
        res = subprocess.run(
            ["ldd", str(binary_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        return parse_ldd_output(res.stdout)
    except (subprocess.CalledProcessError, OSError) as err:
        logger.warning("Failed running ldd on %s: %s", binary_path, err)
        return {}


def collect_transitive_dependencies(entry_binary: Path) -> dict[str, Path]:
    """Recursively discover all transitive non-excluded libraries."""
    logger.info("Resolving dependencies for %s...", entry_binary)
    collected: dict[str, Path] = {}
    visited_files: set[Path] = {entry_binary.resolve()}
    queue: list[Path] = [entry_binary]

    while queue:
        current = queue.pop(0)
        direct = get_binary_dependencies(current)
        for soname, target_file in direct.items():
            if target_file not in visited_files:
                visited_files.add(target_file)
                collected[soname] = target_file
                queue.append(target_file)
            else:
                if soname not in collected:
                    collected[soname] = target_file

    logger.info("Found %d non-system libraries to bundle.", len(collected))
    return collected


def get_directory_size(path: Path) -> int:
    """Calculate total stored size of regular files in a directory, avoiding double-counting hardlinks."""
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    seen_inodes: set[tuple[int, int]] = set()
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            try:
                st = item.stat()
                identity = (st.st_dev, st.st_ino)
                if identity not in seen_inodes:
                    seen_inodes.add(identity)
                    total += st.st_size
            except OSError:
                continue
    return total


def strip_debug_symbols(file_path: Path) -> int:
    """Strip debug and unneeded symbols from an ELF binary or shared library.

    Returns the number of bytes saved.
    """
    if not file_path.is_file() or file_path.is_symlink():
        return 0
    try:
        with open(file_path, "rb") as f:
            if f.read(4) != b"\x7fELF":
                return 0
    except OSError:
        return 0

    strip_bin = shutil.which("strip")
    if not strip_bin:
        return 0

    initial_size = file_path.stat().st_size
    flag = "--strip-unneeded" if ".so" in file_path.name else "--strip-all"
    try:
        subprocess.run(
            [strip_bin, flag, str(file_path)],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        # Fallback to --strip-debug if --strip-all/--strip-unneeded failed
        try:
            subprocess.run(
                [strip_bin, "--strip-debug", str(file_path)],
                capture_output=True,
                check=True,
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            logger.debug("strip failed on %s: %s", file_path, exc)
            return 0

    final_size = file_path.stat().st_size
    saved = max(0, initial_size - final_size)
    if saved > 0:
        logger.debug("Stripped %s: saved %d bytes", file_path.name, saved)
    return saved


def remove_unused_bundle_files(directory: Path) -> tuple[int, int]:
    """Filter out debug symbols (*.pdb, *.debug), unused tkinter/test libraries, and doc files.

    Returns (removed_count, bytes_saved).
    """
    removed_count = 0
    saved_bytes = 0

    protected_names = {
        "license.md",
        "mpv_ffmpeg_licenses.md",
        "cinema.lua",
        "mpv",
        "mpv.bin",
        "ffmpeg",
        "ffmpeg.bin",
        "ffprobe",
        "ffprobe.bin",
        "torrserver",
    }

    for item in list(directory.rglob("*")):
        if not item.is_file() or item.is_symlink():
            continue

        name_lower = item.name.lower()
        if name_lower in protected_names or name_lower.startswith("libav") or name_lower.startswith("libssl"):
            continue

        parts_lower = [p.lower() for p in item.parts]

        is_debug = any(name_lower.endswith(ext) for ext in (".pdb", ".debug", ".dsym"))
        is_unused_gui = any(x in name_lower for x in ("tkinter", "_tkinter", "libtk", "libtcl"))
        is_test = any(p in ("test", "tests") for p in parts_lower) or any(
            name_lower.startswith(p) for p in ("libgtest", "libgmock", "libcmocka", "libcheck")
        )
        is_doc = any(p in ("doc", "docs", "man") for p in parts_lower) and name_lower.endswith(
            (".html", ".htm", ".txt", ".chm", ".1", ".3", ".5", ".man")
        )

        if is_debug or is_unused_gui or is_test or is_doc:
            try:
                size = item.stat().st_size
                item.unlink()
                removed_count += 1
                saved_bytes += size
                logger.debug("Removed unused file: %s (%d bytes)", item, size)
            except OSError as err:
                logger.warning("Failed removing unused file %s: %s", item, err)

    return removed_count, saved_bytes


def deduplicate_directory_binaries(directory: Path) -> tuple[int, int]:
    """Identify duplicate ELF binaries by SHA-256 hash and replace them with hardlinks/symlinks.

    Returns (dedup_count, bytes_saved).
    """
    if not directory.is_dir():
        return 0, 0

    by_hash: dict[str, Path] = {}
    dedup_count = 0
    saved_bytes = 0

    for item in sorted(directory.iterdir()):
        if not item.is_file() or item.is_symlink():
            continue
        try:
            with open(item, "rb") as f:
                header = f.read(4)
                if header != b"\x7fELF":
                    continue
                f.seek(0)
                file_hash = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            continue

        if file_hash in by_hash:
            original = by_hash[file_hash]
            try:
                orig_stat = original.stat()
                item_stat = item.stat()
                if (orig_stat.st_dev, orig_stat.st_ino) == (item_stat.st_dev, item_stat.st_ino):
                    continue
                size = item_stat.st_size
                item.unlink()
                try:
                    os.link(original, item)
                except OSError:
                    item.symlink_to(original.name)
                dedup_count += 1
                saved_bytes += size
                logger.debug("Deduplicated %s -> %s (%d bytes saved)", item.name, original.name, size)
            except OSError as err:
                logger.warning("Failed deduplicating %s: %s", item, err)
        else:
            by_hash[file_hash] = item

    return dedup_count, saved_bytes


def bundle_mpv(
    source_mpv: Path,
    output_dir: Path,
    docs_dir: Path | None = None,
    executable_name: str = 'mpv',
) -> Path:
    """Bundle MPV binary, dependencies, wrapper, and licenses into output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    lib_dir = output_dir / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)

    # 1. Discover all non-excluded libraries
    deps = collect_transitive_dependencies(source_mpv)

    # 2. Copy libraries into output_dir/lib
    copied_files: set[Path] = set()
    for soname, real_path in deps.items():
        dest_file = lib_dir / real_path.name
        if not dest_file.exists():
            shutil.copy2(real_path, dest_file)
            dest_file.chmod(dest_file.stat().st_mode | stat.S_IRUSR | stat.S_IWUSR)
        copied_files.add(dest_file)

        # Create soname symlink if different from real filename
        if soname != real_path.name:
            symlink_dest = lib_dir / soname
            if symlink_dest.exists() or symlink_dest.is_symlink():
                symlink_dest.unlink()
            symlink_dest.symlink_to(real_path.name)

    # 3. Copy MPV executable as mpv.bin
    mpv_bin = output_dir / f"{executable_name}.bin"
    shutil.copy2(source_mpv, mpv_bin)
    mpv_bin.chmod(0o755)

    # 4. Patch RPATH if patchelf is available
    patchelf = shutil.which("patchelf")
    if patchelf:
        logger.info("Patching RPATH with patchelf...")
        try:
            # mpv.bin looks into $ORIGIN/lib and $ORIGIN
            subprocess.run(
                [patchelf, "--set-rpath", "$ORIGIN/lib:$ORIGIN", str(mpv_bin)],
                check=True,
            )
            # Bundled libraries look into $ORIGIN (their own directory)
            for lib_file in copied_files:
                try:
                    subprocess.run(
                        [patchelf, "--set-rpath", "$ORIGIN", str(lib_file)],
                        check=True,
                    )
                except subprocess.CalledProcessError as e:
                    logger.debug("Failed setting RPATH on %s: %s", lib_file, e)
        except (subprocess.CalledProcessError, OSError) as err:
            logger.warning("patchelf execution encountered warnings: %s", err)
    else:
        logger.warning("patchelf not found; relying on wrapper LD_LIBRARY_PATH.")

    # 5. Create wrapper script
    wrapper = output_dir / executable_name
    wrapper.write_text(WRAPPER_SCRIPT.replace('mpv.bin', f'{executable_name}.bin'), encoding="utf-8", newline="\n")
    wrapper.chmod(0o755)

    # 6. Write license notices
    license_file = output_dir / "LICENSE.md"
    license_file.write_text(LICENSE_TEXT, encoding="utf-8")

    if docs_dir:
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "MPV_FFMPEG_LICENSES.md").write_text(
            LICENSE_TEXT, encoding="utf-8"
        )

    # 7. Optimization and cleanup: strip symbols, remove unused files, deduplicate binaries
    initial_size = get_directory_size(output_dir)
    logger.info("Optimizing bundled %s (stripping symbols, removing unused files, deduplicating)...", executable_name)
    strip_debug_symbols(mpv_bin)
    for lib_file in copied_files:
        strip_debug_symbols(lib_file)
    removed_unused, unused_saved = remove_unused_bundle_files(output_dir)
    dedup_count, dedup_saved = deduplicate_directory_binaries(lib_dir)

    final_size = get_directory_size(output_dir)
    saved_bytes = max(0, initial_size - final_size)
    saved_pct = (saved_bytes / initial_size * 100.0) if initial_size > 0 else 0.0
    logger.info(
        "Bundled %s size before cleanup: %d bytes (%.2f MB), after cleanup: %d bytes (%.2f MB), saved: %d bytes (%.2f MB, %.1f%%) [removed %d unused files, deduplicated %d libraries]",
        executable_name,
        initial_size,
        initial_size / (1024 * 1024),
        final_size,
        final_size / (1024 * 1024),
        saved_bytes,
        saved_bytes / (1024 * 1024),
        saved_pct,
        removed_unused,
        dedup_count,
    )

    # 8. Verification if on Linux
    if sys.platform.startswith("linux"):
        try:
            res = subprocess.run(
                [str(wrapper), "--version" if executable_name == 'mpv' else '-version'],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            version_line = res.stdout.splitlines()[0] if res.stdout else "unknown"
            logger.info("Verified bundled %s: %s", executable_name, version_line)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Bundled %s self-check warning: %s", executable_name, exc)

    logger.info("Successfully bundled %s at %s", executable_name, output_dir)
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bundle Linux x86_64 MPV and dependencies"
    )
    parser.add_argument(
        "--mpv-path",
        type=Path,
        default=Path("/usr/bin/mpv"),
        help="Path to host mpv executable (default: /usr/bin/mpv or which mpv)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("vendor/mpv"),
        help="Target output directory (default: vendor/mpv)",
    )
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=Path("docs/licenses"),
        help="Documentation directory for license file",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    mpv_bin = args.mpv_path
    if not mpv_bin.is_file():
        which_bin = shutil.which("mpv")
        if which_bin:
            mpv_bin = Path(which_bin)

    if not mpv_bin.is_file():
        logger.error("Could not find mpv executable at %s", mpv_bin)
        return 1

    try:
        bundle_mpv(
            source_mpv=mpv_bin.resolve(),
            output_dir=args.output.resolve(),
            docs_dir=args.docs_dir.resolve() if args.docs_dir else None,
        )
        return 0
    except Exception:
        logger.exception("Failed bundling MPV")
        return 1


if __name__ == "__main__":
    sys.exit(main())
