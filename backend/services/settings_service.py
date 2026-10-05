import os
import tempfile
import zipfile
from pathlib import Path

from backend.config import get_data_dir


def create_backup_zip() -> Path:
    data_dir = get_data_dir()
    fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    
    with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Save specific files
        for file_name in ["history.sqlite3", "preferences.json"]:
            p = data_dir / file_name
            if p.exists():
                zf.write(p, file_name)
        
        # Save posters directory
        posters_dir = data_dir / "posters"
        if posters_dir.exists():
            for root, _, files in os.walk(posters_dir):
                for f in files:
                    file_path = Path(root) / f
                    arcname = file_path.relative_to(data_dir)
                    zf.write(file_path, arcname)
                    
    return Path(tmp_path)

def restore_backup_zip(zip_path: Path):
    data_dir = get_data_dir()
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Basic safety check against zip slip
        for member in zf.namelist():
            if ".." in member or member.startswith(("/", "\\")):
                raise ValueError(f"Invalid zip payload: {member}")
        
        zf.extractall(data_dir)
