# Pirate Cinema

## Architecture Overview (v0.2.1)

Pirate Cinema is built to be as simple, local, and robust as possible. It avoids complex build systems, heavy frontend frameworks, and cloud dependencies.

### Core Stack
1. **Python Backend (`backend/`)**:
   - Built on FastAPI.
   - Manages the lifecycle of the bundled `TorrServer` and `mpv` executables.
   - Proxies metadata searches to external APIs (like Cinemeta).
   - Serves the local database and torrent library to the frontend.
2. **Vanilla Frontend (`static/`)**:
   - Zero-build frontend using vanilla JavaScript and CSS (`app.js`, `style.css`).
   - Uses native DOM templates (`<template>`) for rendering views.
   - Styled using custom CSS variables (no Tailwind/Bootstrap).
3. **Desktop Window (`main.py`)**:
   - Uses `pywebview` (WebView2 on Windows) to create a native desktop window.
   - The FastAPI server runs in a daemon thread, while `pywebview` occupies the main thread.

### TorrServer Engine
TorrServer is bundled in `vendor/torrserver`. It acts as the backbone for downloading and seeding torrents sequentially to allow instant video playback. 
- Automatically configured by the Python backend on startup to use optimized settings (e.g., higher connection limits, UTP enabled) for faster DHT peer discovery.

### MPV Player
MPV is bundled in `vendor/mpv`. The Python backend orchestrates it via IPC or command-line arguments to play the streaming URL exposed by TorrServer.

### Storage
- All state, including history and settings, is stored locally in an SQLite database and the TorrServer internal database.
- Completely local-first. No accounts, no cloud sync.
