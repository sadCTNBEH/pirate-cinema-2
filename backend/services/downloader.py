import os
import sys
import urllib.request
import zipfile
import tarfile
from pathlib import Path
from backend.config import get_data_dir

def download_file(url, dest):
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    print(f"Downloading {url} to {dest}...")
    urllib.request.urlretrieve(url, dest, context=ctx)

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
            download_file("https://github.com/YouRoK/TorrServer/releases/download/Matrox.136/TorrServer-windows-amd64.exe", ts_exe)
    else:
        ts_exe = ts_dir / "torrserver"
        if not ts_exe.exists():
            download_file("https://github.com/YouRoK/TorrServer/releases/download/Matrox.136/TorrServer-linux-amd64", ts_exe)
            os.chmod(ts_exe, 0o755)
            
    # MPV (Windows only for now, Linux uses system mpv)
    if sys.platform == "win32":
        mpv_dir = vendor_dir / "mpv"
        mpv_dir.mkdir(parents=True, exist_ok=True)
        mpv_exe = mpv_dir / "mpv.exe"
        if not mpv_exe.exists():
            zip_path = vendor_dir / "mpv.zip"
            # Using shinchiro's latest MPV build
            download_file("https://sourceforge.net/projects/mpv-player-windows/files/64bit/mpv-x86_64-20240901-git-bb22b10.zip/download", zip_path)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(mpv_dir)
            os.remove(zip_path)
