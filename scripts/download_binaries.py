import sys
import zipfile
from pathlib import Path
from urllib import error, request


def main():
    root = Path(__file__).parent.parent
    vendor = root / "vendor"
    vendor.mkdir(exist_ok=True)
    
    mpv_dir = root / "mpv"
    mpv_dir.mkdir(exist_ok=True)

    torr_dir = vendor / "torrserver"
    torr_dir.mkdir(exist_ok=True)
    
    torr_exe = torr_dir / "torrserver.exe" if sys.platform == "win32" else torr_dir / "torrserver"
    mpv_exe = mpv_dir / "mpv.exe" if sys.platform == "win32" else mpv_dir / "mpv"

    # Download TorrServer (Windows only for now in this script)
    if not torr_exe.exists() and sys.platform == "win32":
        print("Downloading TorrServer for Windows...")
        ts_url = "https://github.com/YouRoK/TorrServer/releases/latest/download/TorrServer-windows-amd64.exe"
        try:
            request.urlretrieve(ts_url, torr_exe)
            print("TorrServer downloaded.")
        except (error.URLError, OSError) as e:
            print(f"Failed to download TorrServer: {e}")

    # Download MPV (Windows minimal build)
    if not mpv_exe.exists() and sys.platform == "win32":
        print("Downloading MPV for Windows...")
        import json
        import subprocess
        try:
            # 1. Get latest shinchiro 7z URL
            req = request.Request('https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest')
            data = json.loads(request.urlopen(req).read())
            mpv_url = next(a['browser_download_url'] for a in data['assets'] if 'mpv-x86_64-v3' in a['name'] and a['name'].endswith('.7z'))
            
            # 2. Download 7zr.exe (standalone 7-zip command line tool)
            sz_exe = root / "7zr.exe"
            request.urlretrieve('https://www.7-zip.org/a/7zr.exe', sz_exe)
            
            # 3. Download MPV .7z archive
            mpv_7z = root / "mpv.7z"
            print(f"Downloading MPV from {mpv_url} ...")
            request.urlretrieve(mpv_url, mpv_7z)
            
            # 4. Extract
            print("Extracting MPV...")
            subprocess.run([str(sz_exe), 'x', str(mpv_7z), f'-o{mpv_dir}', '-y'], check=True, stdout=subprocess.DEVNULL)
            
            # 5. Cleanup
            sz_exe.unlink(missing_ok=True)
            mpv_7z.unlink(missing_ok=True)
            print("MPV downloaded and extracted.")
        except (error.URLError, zipfile.BadZipFile, OSError) as e:
            print(f"Failed to download or extract MPV: {e}")
            print("Please download it manually from https://sourceforge.net/projects/mpv-player-windows/files/ and extract to the 'mpv' folder.")


if __name__ == "__main__":
    main()
