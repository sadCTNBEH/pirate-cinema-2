import os
import shutil
import sys
import urllib.request
import zipfile

from backend.core.config import get_data_dir


def download_file(url, dest):
    print(f"Downloading {url} to {dest}...")
    
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response, open(dest, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)

def ensure_binaries():
    data_dir = get_data_dir()
    vendor_dir = data_dir / "vendor"
    vendor_dir.mkdir(parents=True, exist_ok=True)
    
    # TorrServer
    ts_dir = vendor_dir / "torrserver"
    ts_dir.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        ts_exe = ts_dir / "torrserver.exe"
        if not ts_exe.exists():
            download_file("https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/deps/TorrServer-windows-amd64.exe", ts_exe)
    else:
        ts_exe = ts_dir / "torrserver"
        if not ts_exe.exists():
            download_file("https://github.com/YouROK/TorrServer/releases/download/MatriX.145.2/TorrServer-linux-amd64", ts_exe)
            os.chmod(ts_exe, 0o755)
            
    # MPV (Windows only for now, Linux uses system mpv)
    if sys.platform == "win32":
        mpv_dir = vendor_dir / "mpv"
        mpv_dir.mkdir(parents=True, exist_ok=True)
        mpv_exe = mpv_dir / "mpv.exe"
        if not mpv_exe.exists():
            zip_path = vendor_dir / "mpv.zip"
            # Using shinchiro's latest MPV build
            download_file("https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/deps/mpv-x86_64-20261004-git-413ff0b1cd.zip", zip_path)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(mpv_dir)
            os.remove(zip_path)
if __name__ == "__main__": ensure_binaries()
