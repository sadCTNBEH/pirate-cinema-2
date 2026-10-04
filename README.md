# Pirate Cinema

Pirate Cinema is a minimalist desktop streaming application that allows you to instantly search and stream movies and TV shows from torrents without downloading them first. It provides a native Windows desktop experience powered by Python, FastAPI, and `pywebview`.

## Features
- **Instant Streaming:** Stream torrents instantly via the built-in MPV player.
- **TorrServer Integration:** Uses a bundled TorrServer instance to handle torrent protocols in the background.
- **Search & Catalog:** Search TMDB via Cinemeta and automatically fetch corresponding torrents.
- **Library:** Keep track of your continued watching and saved torrents.
- **Native Desktop App:** Runs as a lightweight native window using WebView2 (via `pywebview`).
- **No Build Steps:** Vanilla JS and CSS frontend—no React, no bundlers, no node_modules.

## Requirements
- Windows 10/11
- Python 3.12+
- WebView2 Runtime (Included in Windows 11 by default)

## Installation & Binaries
Pirate Cinema requires `TorrServer.exe` and `mpv.exe` to function. 
When you start the application, it will attempt to download `TorrServer` automatically. 

**Manual setup if auto-download fails:**
1. **TorrServer**: Download `TorrServer-windows-amd64.exe` from [YouRoK/TorrServer](https://github.com/YouRoK/TorrServer/releases) and place it in the `vendor/torrserver/` folder and rename it to `TorrServer.exe`.
2. **MPV**: Download MPV for Windows from [sourceforge](https://sourceforge.net/projects/mpv-player-windows/files/) and extract it into the `mpv/` folder at the root of the project so that `mpv/mpv.exe` exists.

## Getting Started
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the application (this will also check for missing binaries):
   ```bash
   run.bat
   ```

## Architecture
- **Backend:** FastAPI (Python) handles the API routes and manages background processes (TorrServer).
- **Frontend:** Pure HTML/JS/CSS, rendered via PyWebView.
- **Player:** MPV handles video playback.

## Version
**0.2.1**

## Note on v0.2.1
This project was recently rewritten in Python (v0.2.x) from its legacy Rust implementation (v0.5.x). As a result, it is currently a streamlined, minimalist release.
Features such as system tray integration, OS-level magnet handler registration, diagnostics, backup/restore, external player configurations, and multi-language support (i18n) from the legacy version have been intentionally omitted to keep the architecture clean and maintainable. Language support is currently Russian-only.
