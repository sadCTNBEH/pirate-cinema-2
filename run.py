import logging
import sys

logger = logging.getLogger(__name__)


def main():
    if "--smoke-test" in sys.argv:
        try:
            import backend.main  # noqa: F401
            from backend.services.remote import generate_qr_svg

            if "<svg" not in generate_qr_svg("http://127.0.0.1:8000/remote"):
                raise RuntimeError("QR generation failed")
        except Exception:
            logger.exception("Bundled startup self-test failed")
            return 1
        return 0

    from backend.main import main as launch

    launch()
    return 0

if __name__ == "__main__":
    sys.exit(main())
