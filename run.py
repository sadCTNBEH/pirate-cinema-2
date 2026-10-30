import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

logger = logging.getLogger(__name__)


def configure_logging():
    handlers = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    try:
        base = os.environ.get("LOCALAPPDATA", str(Path.home())) if sys.platform == "win32" else os.environ.get(
            "XDG_DATA_HOME", str(Path.home() / ".local" / "share")
        )
        folder = Path(base) / "Pirate Cinema"
        folder.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(folder / "startup.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"))
    except OSError:
        logger.warning("Cannot create startup log", exc_info=True)
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main():
    if "--animego-worker" in sys.argv:
        from backend.services.online.animego_worker import run_worker
        return run_worker() or 0
    configure_logging()
    try:
        if "--smoke-test" in sys.argv or "--smoke-test-mpv" in sys.argv:
            import backend.main  # noqa: F401
            from backend.services.remote import generate_qr_svg

            if "<svg" not in generate_qr_svg("http://127.0.0.1:8000/remote"):
                raise RuntimeError("QR generation failed")
            if "--smoke-test-mpv" in sys.argv:
                from backend.core.settings import config, resolve_mpv_binary
                from backend.infrastructure.mpv.controller import MPVController

                config.MPV_ARGS = [
                    a for a in config.MPV_ARGS if a not in ("--fs", "--force-window=yes")
                ] + ["--vo=null", "--ao=null"]
                controller = MPVController()
                try:
                    controller.launch(resolve_mpv_binary(), "av://lavfi:sine=duration=0.1", "Playback self-test")
                finally:
                    controller.stop()
            return 0

        from backend.main import main as launch

        launch()
        return 0
    except Exception:
        logger.exception("Pirate Cinema startup failed; see the startup.log in the user data folder")
        return 1

if __name__ == "__main__":
    sys.exit(main())
