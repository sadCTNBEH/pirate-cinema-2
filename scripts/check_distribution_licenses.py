"""Check required public-distribution license and notice files without granting rights."""

from __future__ import annotations

import os
from pathlib import Path

REQUIRED_FILES = (
    Path("LICENSE"),
    Path("THIRD_PARTY_NOTICES"),
    Path("licenses/LINUX_DISTRIBUTION.md"),
    Path("licenses/MPV_FFMPEG_LICENSES.md"),
    Path("licenses/hls.js-LICENSE"),
)
REQUIRED_PACKAGING_REFERENCES = {
    Path("scripts/pirate-cinema-linux.spec"): 'root / "LICENSE"',
    Path("scripts/flatpak/io.github.sadctnbeh.PirateCinema.yml"): "../../LICENSE",
    Path("build/installer.nsi"): "MUI_PAGE_LICENSE",
    Path(".github/workflows/build.yml"): '--add-data "LICENSE;licenses"',
}


def main() -> int:
    missing = [str(path) for path in REQUIRED_FILES if not path.is_file() or path.stat().st_size == 0]
    packaging_missing = []
    for path, marker in REQUIRED_PACKAGING_REFERENCES.items():
        if not path.is_file() or marker not in path.read_text(encoding="utf-8"):
            packaging_missing.append(f"{path} (expected packaging reference: {marker})")
    complete = not missing and not packaging_missing
    print("Public distribution license files: " + ("present" if complete else "incomplete"))
    for path in missing:
        print(f"Missing or empty: {path}")
    for item in packaging_missing:
        print(f"Missing package license configuration: {item}")
    print("This formal file/configuration result is not legal approval or evidence of copyright, commercial, or patent rights.")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"complete={'true' if complete else 'false'}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write("## Distribution license file check\n\n")
            stream.write("Status: **complete**\n" if complete else "Status: **incomplete; binary publication remains disabled**\n")
            if missing:
                stream.write("\nMissing files:\n" + "\n".join(f"- `{path}`" for path in missing) + "\n")
            if packaging_missing:
                stream.write("\nMissing package configuration:\n" + "\n".join(f"- `{item}`" for item in packaging_missing) + "\n")
            stream.write("\nThis formal check is not a legal, source-compliance, commercial-license, or patent-rights determination.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
