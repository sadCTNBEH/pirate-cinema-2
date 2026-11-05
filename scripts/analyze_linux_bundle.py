#!/usr/bin/env python3
"""Measure an unpacked Linux bundle and its compressed release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


def component(path: Path) -> str:
    parts = path.parts
    name = path.name.lower()
    if "vendor" in parts[:-1]:
        tool = parts[parts.index("vendor") + 1]
        if tool in {"mpv", "ffmpeg", "torrserver"}:
            return tool
    if "webengine" in name or "qtwebengine_locales" in parts or name == "icudtl.dat":
        return "Qt WebEngine"
    if "PyQt6" in parts or name.startswith("libqt6"):
        return "PyQt6 and Qt"
    if name.startswith(("libpython", "base_library.zip")) or "lib-dynload" in parts:
        return "Python runtime"
    return "Other"


def elf_dependencies(path: Path) -> dict:
    output = subprocess.check_output(["readelf", "-dW", path], text=True)
    tags = defaultdict(list)
    for tag, value in re.findall(r"\((NEEDED|SONAME|RPATH|RUNPATH)\).*?\[([^\]]+)\]", output):
        tags[tag.lower()].append(value)
    return dict(tags)


def analyze(root: Path, artifacts: dict[str, Path], *, read_elf: bool = True) -> dict:
    if not root.is_dir():
        raise NotADirectoryError(root)
    directories = Counter({".": 0})
    components = Counter()
    apparent_components = Counter()
    files = []
    symlinks = {}
    suspicious = []
    by_hash = defaultdict(list)
    elf = {}
    by_soname = defaultdict(list)
    seen_inodes = {}
    root_path = root.resolve()

    for folder, subdirs, names in os.walk(root):
        subdirs.sort()
        directory = Path(folder)
        directories.setdefault(directory.relative_to(root).as_posix(), 0)
        for name in sorted(subdirs + names):
            path = directory / name
            relative = path.relative_to(root)
            key = relative.as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                target = path.readlink()
                symlinks[key] = str(target)
                if target.is_absolute() or not path.exists() or not path.resolve().is_relative_to(root_path):
                    suspicious.append(key)
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            with path.open("rb") as source:
                is_elf = source.read(4) == b"\x7fELF"
                source.seek(0)
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            identity = (info.st_dev, info.st_ino)
            group = component(relative)
            stored_bytes = 0 if identity in seen_inodes else info.st_size
            first_group = seen_inodes.setdefault(identity, group)
            apparent_components[group] += info.st_size
            if {first_group, group} == {"mpv", "ffmpeg"}:
                components[first_group] -= info.st_size
                components["Shared MPV and FFmpeg libraries"] += info.st_size
                seen_inodes[identity] = "Shared MPV and FFmpeg libraries"
            entry = {"path": key, "bytes": info.st_size, "stored_bytes": stored_bytes}
            files.append(entry)
            by_hash[digest].append(entry)
            for parent in relative.parents:
                directories[parent.as_posix()] += stored_bytes
            components[group] += stored_bytes
            if is_elf:
                tags = elf_dependencies(path) if read_elf else {}
                elf[key] = tags
                for soname in tags.get("soname", []):
                    by_soname[soname].append({"path": key, "sha256": digest})
            if (
                path.suffix.lower() in {".dll", ".exe", ".dylib", ".a", ".pdb", ".h", ".hpp", ".whl"}
                or {"__pycache__", "examples", "include", "tests", ".cache"} & set(relative.parts)
            ):
                suspicious.append(key)

    duplicates = [
        {
            "sha256": digest,
            "bytes_per_file": entries[0]["bytes"],
            "extra_stored_bytes": sum(e["stored_bytes"] for e in entries) - entries[0]["bytes"],
            "paths": [e["path"] for e in entries],
        }
        for digest, entries in by_hash.items()
        if len(entries) > 1
    ]
    duplicates.sort(key=lambda group: group["extra_stored_bytes"], reverse=True)
    return {
        "artifacts": {name: path.stat().st_size for name, path in artifacts.items()},
        "unpacked_bytes": directories["."],
        "unpacked_bytes_counting_hardlinks": sum(entry["bytes"] for entry in files),
        "duplicate_stored_bytes": sum(group["extra_stored_bytes"] for group in duplicates),
        "components": dict(components),
        "apparent_components": dict(apparent_components),
        "directories": dict(directories),
        "largest_files": sorted(files, key=lambda entry: entry["bytes"], reverse=True)[:50],
        "duplicates": duplicates,
        "symlinks": symlinks,
        "elf": elf,
        "soname_overlaps": {key: values for key, values in by_soname.items() if len(values) > 1},
        "suspicious_paths": suspicious,
    }


def summary(report: dict, baseline: dict | None, threshold: float) -> str:
    sizes = {
        **report["artifacts"],
        "Unpacked (unique inodes)": report["unpacked_bytes"],
        "Duplicate bytes": report["duplicate_stored_bytes"],
        **report["components"],
    }
    previous = {} if baseline is None else {
        **baseline["artifacts"],
        "Unpacked (unique inodes)": baseline["unpacked_bytes"],
        "Duplicate bytes": baseline["duplicate_stored_bytes"],
        **baseline["components"],
    }
    lines = ["| Item | Bytes | Baseline bytes | Change |", "| --- | ---: | ---: | ---: |"]
    warnings = []
    for name, size in sizes.items():
        before = previous.get(name)
        delta = size / before - 1 if before else None
        before_text = f"{before:,}" if before is not None else "—"
        delta_text = f"{delta:+.1%}" if delta is not None else "—"
        lines.append(f"| {name} | {size:,} | {before_text} | {delta_text} |")
        if delta is not None and delta > threshold and size - before >= 1_000_000:
            warnings.append(f"::warning::{name} grew by {delta:.1%} versus baseline")
    print("\n".join(warnings))
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Unpacked onedir or AppDir")
    parser.add_argument("--appimage", type=Path)
    parser.add_argument("--tar", type=Path)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, help="Previous JSON report for the same layout")
    parser.add_argument("--warning-growth", type=float, default=0.05)
    parser.add_argument("--skip-elf", action="store_true", help="Skip readelf on hosts without binutils")
    args = parser.parse_args()
    artifacts = {key: path for key, path in (("AppImage", args.appimage), ("tar.gz", args.tar)) if path}
    report = analyze(args.root, artifacts, read_elf=not args.skip_elf)
    args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    table = summary(report, baseline, args.warning_growth)
    print(table)
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(step_summary).open("a", encoding="utf-8") as output:
            output.write(f"### Linux size report for `{args.root.name}`\n\n{table}\n")


if __name__ == "__main__":
    main()