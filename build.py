import os
import subprocess
import shutil

def main():
    print("Building Pirate Cinema...")
    
    # Ensure run.py exists
    if not os.path.exists("run.py"):
        with open("run.py", "w", encoding="utf-8") as f:
            f.write("from backend.main import run_app\n\nif __name__ == '__main__':\n    run_app()\n")

    # Build one-file portable
    subprocess.run([
        "pyinstaller", "--name", "pirate-cinema-portable", "--onefile", "--windowed", 
        "--icon", "build/icon.ico", "--add-data", "static;static", "--add-data", "vendor;vendor", 
        "run.py"
    ], check=True)

    # Build one-dir for installer
    subprocess.run([
        "pyinstaller", "--name", "pirate-cinema", "--onedir", "--windowed", 
        "--icon", "build/icon.ico", "--add-data", "static;static", "--add-data", "vendor;vendor", 
        "run.py"
    ], check=True)

    print("Build complete!")

if __name__ == "__main__":
    main()
