"""Exercise all bundled media tools with a real H.264/AAC file."""

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def smoke_media(vendor: Path) -> None:
    for name in ("mpv", "ffmpeg", "ffprobe"):
        if shutil.which(name):
            raise RuntimeError(f"System {name} is still on PATH")

    vendor = vendor.resolve(strict=True)
    mpv = vendor / "mpv/mpv"
    ffmpeg = vendor / "ffmpeg/ffmpeg"
    ffprobe = vendor / "ffmpeg/ffprobe"
    for tool, flag in ((mpv, "--version"), (ffmpeg, "-version"), (ffprobe, "-version")):
        subprocess.run([tool, flag], check=True, timeout=15, stdout=subprocess.DEVNULL)

    with tempfile.TemporaryDirectory(prefix="Pirate Cinema media ") as tmp:
        video = Path(tmp) / "H264 and AAC.mp4"
        subprocess.run(
            [
                ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=25:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-c:v", "libx264", "-threads", "1", "-c:a", "aac", "-shortest", video,
            ],
            cwd=tmp, check=True, timeout=30,
        )
        probe = subprocess.check_output(
            [ffprobe, "-v", "error", "-show_entries", "stream=codec_name", "-of", "json", video],
            cwd=tmp, text=True, timeout=15,
        )
        codecs = {stream["codec_name"] for stream in json.loads(probe)["streams"]}
        if codecs != {"h264", "aac"}:
            raise RuntimeError(f"Unexpected test media codecs: {codecs}")

        # The image output records decoded video frames independently of the display server.
        frames = Path(tmp) / "decoded"
        frames.mkdir()
        result = subprocess.run(
            [
                mpv, "--no-config", "--no-audio", "--vo=image", "--vo-image-format=png",
                f"--vo-image-outdir={frames}", "--frames=5", "--hwdec=no", video,
            ],
            cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            check=True, timeout=30,
        )
        images = list(frames.glob("*.png"))
        if len(images) != 5 or any(not image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for image in images):
            raise RuntimeError(f"MPV did not decode five frames:\n{result.stdout}")
    print("PASS: bundled FFmpeg encoded H.264/AAC, FFprobe identified both streams, MPV decoded five frames")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vendor", type=Path, help="The extracted bundle's _internal/vendor")
    smoke_media(parser.parse_args().vendor)