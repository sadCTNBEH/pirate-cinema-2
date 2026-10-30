"""Bundle FFmpeg tools with private libraries and isolated launchers."""
import argparse
import shutil
from pathlib import Path

from scripts.bundle_linux_mpv import bundle_mpv


def bundle_ffmpeg(output: Path) -> None:
    for name in ('ffmpeg', 'ffprobe'):
        binary = shutil.which(name)
        if not binary:
            raise FileNotFoundError(f'{name} is required to build the Linux bundle')
        bundle_mpv(Path(binary).resolve(), output, executable_name=name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('vendor/ffmpeg'))
    bundle_ffmpeg(parser.parse_args().output)
