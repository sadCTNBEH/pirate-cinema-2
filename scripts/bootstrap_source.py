"""Install project requirements into the launcher's virtual environment."""
import hashlib
import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    if sys.prefix == sys.base_prefix or sys.version_info < (3, 12):
        raise SystemExit("Pirate Cinema requires Python 3.12 or newer in a virtual environment.")

    requirements = root / "requirements.txt"
    signature = hashlib.sha256(requirements.read_bytes()).hexdigest()
    stamp = Path(sys.prefix) / ".pirate-cinema-requirements"
    if not stamp.is_file() or stamp.read_text(encoding="ascii").strip() != signature:
        subprocess.run(
            [sys.executable, "-m", "pip", "--disable-pip-version-check", "install", "-r", str(requirements)],
            check=True,
        )
        stamp.write_text(signature + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
