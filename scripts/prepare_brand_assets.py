"""Generate all brand assets from user uploaded image."""

import shutil
from pathlib import Path

from PIL import Image

SRC_PATH = Path(r"C:\Users\stark\.gemini\antigravity\brain\76db37b2-9a15-41c0-84df-580f0a350189\.user_uploaded\media_1791701254812_e78c9975.jpg")
ROOT_DIR = Path(__file__).resolve().parent.parent

BRAND_DIR = ROOT_DIR / "assets" / "brand"
BUILD_DIR = ROOT_DIR / "build"
FRONTEND_PUBLIC = ROOT_DIR / "frontend" / "public"
FRONTEND_ASSETS = ROOT_DIR / "frontend" / "src" / "assets"
STATIC_DIR = ROOT_DIR / "static"


def main():
    print("Loading source image from:", SRC_PATH)
    src = Image.open(SRC_PATH)
    print("Source image size:", src.size, "mode:", src.mode)

    # Ensure directories
    for d in [BRAND_DIR, BUILD_DIR, FRONTEND_PUBLIC, FRONTEND_ASSETS, STATIC_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    # Save copy of original
    shutil.copy2(SRC_PATH, BRAND_DIR / "original.jpg")

    # Generate 512x512 PNG
    img_512 = src.resize((512, 512), Image.Resampling.LANCZOS)
    img_512.save(BRAND_DIR / "logo.png", "PNG")
    img_512.save(BRAND_DIR / "icon.png", "PNG")

    # Generate 256x256 PNG
    img_256 = src.resize((256, 256), Image.Resampling.LANCZOS)
    img_256.save(BRAND_DIR / "icon-256.png", "PNG")

    # Generate 32x32 PNG
    img_32 = src.resize((32, 32), Image.Resampling.LANCZOS)
    img_32.save(BRAND_DIR / "favicon.png", "PNG")
    img_32.save(BRAND_DIR / "tray.png", "PNG")

    # Generate multi-size ICO
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    src.save(BRAND_DIR / "icon.ico", format="ICO", sizes=ico_sizes)

    # Generate tray & favicon ICO
    src.save(BRAND_DIR / "tray.ico", format="ICO", sizes=[(16, 16), (32, 32)])
    src.save(BRAND_DIR / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32)])

    # Distribute to build/
    shutil.copy2(BRAND_DIR / "icon.ico", BUILD_DIR / "icon.ico")
    shutil.copy2(BRAND_DIR / "icon.png", BUILD_DIR / "icon.png")
    shutil.copy2(BRAND_DIR / "logo.png", BUILD_DIR / "logo.png")

    # Distribute to frontend/public/
    shutil.copy2(BRAND_DIR / "logo.png", FRONTEND_PUBLIC / "logo.png")
    shutil.copy2(BRAND_DIR / "icon.png", FRONTEND_PUBLIC / "icon.png")
    shutil.copy2(BRAND_DIR / "favicon.png", FRONTEND_PUBLIC / "favicon.png")
    shutil.copy2(BRAND_DIR / "favicon.ico", FRONTEND_PUBLIC / "favicon.ico")
    shutil.copy2(BRAND_DIR / "tray.png", FRONTEND_PUBLIC / "tray.png")
    shutil.copy2(BRAND_DIR / "icon.ico", FRONTEND_PUBLIC / "icon.ico")

    # Distribute to frontend/src/assets/
    shutil.copy2(BRAND_DIR / "logo.png", FRONTEND_ASSETS / "logo.png")
    shutil.copy2(BRAND_DIR / "icon.png", FRONTEND_ASSETS / "icon.png")

    # Distribute to static/
    shutil.copy2(BRAND_DIR / "logo.png", STATIC_DIR / "logo.png")
    shutil.copy2(BRAND_DIR / "icon.png", STATIC_DIR / "icon.png")
    shutil.copy2(BRAND_DIR / "icon.ico", STATIC_DIR / "icon.ico")
    shutil.copy2(BRAND_DIR / "favicon.png", STATIC_DIR / "favicon.png")
    shutil.copy2(BRAND_DIR / "favicon.ico", STATIC_DIR / "favicon.ico")
    shutil.copy2(BRAND_DIR / "tray.png", STATIC_DIR / "tray.png")
    shutil.copy2(BRAND_DIR / "tray.ico", STATIC_DIR / "tray.ico")

    print("All brand assets generated and distributed successfully!")


if __name__ == "__main__":
    main()
