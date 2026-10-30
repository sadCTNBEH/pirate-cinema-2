# Pirate Cinema

## Architecture Overview (v0.4.5)

### Application

- **Backend (`backend/`):** FastAPI on Python 3.12+, with service and repository layers for catalogs, torrent selection, playback, diagnostics, updates, settings, and SQLite history.
- **Desktop frontend (`frontend/`):** React 19, TypeScript, and Tailwind CSS, built by Vite 8 into the committed `static/` directory. The Windows shell uses pywebview/WebView2; Linux uses an installed browser in app mode, with a configurable pywebview alternative.
- **Phone remote (`backend/services/remote_html.py`):** A separate HTML/JavaScript interface served at `/remote`. It controls the PC player, searches for torrents, and supports independent torrent playback on the phone.
- **Version:** Root `version.json` supplies the backend version and Vite's build-time version. The frontend also reads `/version.json` at runtime. Frontend package metadata follows the application release version.

### Playback

TorrServer supplies torrent streams. MPV is controlled through IPC and supports audio/subtitle tracks, chapters, verified intro/recap skipping, and episode continuation. Catalog-linked progress can follow the same episode across releases; ambiguous file matches require user selection.

Phone playback proxies compatible MP4/H.264/AAC streams directly. Other supported inputs are converted to fixed-duration HLS/H.264/AAC segments by FFmpeg. Segments stay in memory, with bounded buffering and a shared preparation semaphore. The mobile player exposes per-episode resume, previous/next episode navigation, and native video controls.

QR links carry a pairing capability in the URL fragment. Device credentials are retained in browser storage; the PC stores hashed credentials with their original 12-hour expiry so pairing survives restarts. Requests are limited to local-network peers and validate their origin and host. A video session belongs to its paired device and does not replace the PC player.

### Packaging

Windows releases include a portable executable and an installer. Linux releases include an AppImage and a tarball. Linux packages bundle MPV, FFmpeg, FFprobe, and private media libraries; display/audio system libraries and the browser come from the host. The custom AppImage runtime falls back to private temporary extraction when FUSE mounting is unavailable.

### Storage and validation

SQLite holds library metadata, collections, watch history, and per-file progress. Settings, downloaded vendor tools, pairing records, and logs live in the user's Pirate Cinema data directory. Playback and preparation resources are closed when sessions end or the application shuts down.

Python behavior is checked with pytest and Ruff. Browser scripts in `tests/` exercise the desktop/remote UI and real FFmpeg-to-HLS phone playback, including episode transitions and pairing recovery. GitHub Actions builds and smoke-tests release packages when a `v*` tag is pushed.
