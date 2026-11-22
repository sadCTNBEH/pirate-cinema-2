# Pirate Cinema — Project Documentation

## 1. Architecture Overview (v0.5.0)

Pirate Cinema is a cross-platform desktop media streaming application engineered for instant search, playback, and streaming of torrents, anime, and online video sources without requiring pre-downloads.

### Core Subsystems

- **Backend (`backend/`):** Built with FastAPI on Python 3.12+. Organized into domain services and repositories managing catalogs (Torznab/Jackett, Rutor, Shikimori, YummyAnime), torrent playback via TorrServer, MPV player control, watch history, metadata persistence, in-app updates, and system diagnostics.
- **Desktop Frontend (`frontend/`):** Single-page application built on React 19, TypeScript, and Tailwind CSS. Compiled with Vite 8 into the committed `static/` bundle.
  - Windows: Runs in a dedicated frameless desktop window using `pywebview` backed by the native Microsoft WebView2 runtime.
  - Linux: Opens a native desktop window powered by embedded Qt WebEngine (PyQt6), with an optional fallback to system Browser App Mode (`PIRATE_CINEMA_GUI=browser`).
- **Mobile Remote & Web Streaming (`/remote`):** Served directly by the local HTTP server. Enables remote control (playback toggle, timeline seek, audio/subtitle track selection, volume, next episode) and independent phone playback of torrent video files in local Wi-Fi networks.
  - Compatible formats (MP4 with H.264 video and AAC audio) stream directly.
  - Incompatible codecs (HEVC, 10-bit H.264, VP9, AV1, AC3, DTS) are transcoded on-the-fly into RAM-buffered HLS segments using FFmpeg without writing video chunks to disk.
  - Pairing is cryptographically anchored via a URL fragment capability (`#pair=...`) and validated with SHA-256 tokens stored with a 12-hour expiration window.
- **Embedded MPV Video Player:** Managed through bidirectional IPC (named pipes on Windows, Unix domain sockets on Linux). Features custom OSD overlays (`cinema.lua`), automatic episode continuation, chapter navigation, and intro/recap skip integration with configurable countdown.
- **Diagnostics & Privacy Enforcement (`backend/services/diagnostics.py`):** Collects hardware/OS metrics, TorrServer status, MPV state, codec support, and recent application logs. Automatically redacts authorization tokens, API keys, passwords, and user filesystem paths (`/Users/username/...` or `C:\Users\username\...` $\to$ `~/...`). Provides one-click export of sanitized diagnostic bundles in `.json` or `.zip` format.
- **In-App Updater (`backend/services/updater.py`):** Background update checks against GitHub Releases with semver comparison, atomic download, and safe restart/rollback mechanisms.

---

## 2. Environment & System Requirements

### Hardware & Platform Support

- **Windows:** Windows 10 (version 1809+) or Windows 11 (x86_64). Microsoft Edge WebView2 runtime is required (pre-installed by default on Windows 10/11).
- **Linux:** x86_64 architecture with `glibc >= 2.35` (e.g., Ubuntu 22.04+, Debian 12+, Fedora 38+, Arch Linux).
  - Compatible with both X11 and Wayland sessions (Wayland uses XWayland automatically when available).
  - **FUSE-agnostic:** The custom AppImage runtime detects whether `/dev/fuse` is operational. If FUSE is accessible, standard zero-overhead mounting is used; if FUSE is unavailable (Docker, WSL2, minimal distributions), it automatically falls back to isolated userland extraction into `/tmp` (permissions `0700`) without manual flags.

### Runtimes & Interpreters

- **Python:** `>= 3.12` (Python 3.12.7 recommended). Managed via `uv` (`pyproject.toml`).
- **Node.js:** `20.19+` (Node 20 LTS) or `22.12+` (Node 22 LTS) — only required when modifying or compiling the `frontend/` single-page application.

### Multimedia Binaries (Vendors)

- **TorrServer:** Embedded BitTorrent streaming engine. Release packages bundle TorrServer. For source builds, it is downloaded automatically on launch or via `python -m backend.infrastructure.downloader`.
- **MPV:** Embedded video player binary.
  - Windows: Downloaded automatically to `%LOCALAPPDATA%\Pirate Cinema\vendor\mpv\`.
  - Linux: AppImage and tarball include pre-compiled MPV with multimedia libraries.
- **FFmpeg & FFprobe:** Required for transcoding incompatible video formats into HLS streams for mobile remote playback.
  - Windows: Prepared in `%LOCALAPPDATA%\Pirate Cinema\vendor\ffmpeg\`.
  - Linux: Bundled in `_internal/vendor/ffmpeg/` inside AppImage and tarball builds.

---

## 3. Developer Guide: Local Setup and Launch

### 1. Repository Setup and Python Dependencies

The project uses [`uv`](https://github.com/astral-sh/uv) for fast and deterministic Python environment management.

```bash
# Clone the repository
git clone https://github.com/cyberboy1999/pirate-cinema.git
cd pirate-cinema-2

# Install and synchronize Python virtual environment with development dependencies
uv sync --frozen --group dev
```

### 2. Download and Verify Vendor Binaries

Prepare TorrServer, MPV, FFmpeg, and FFprobe:

```bash
# Windows & Linux:
uv run python -m backend.infrastructure.downloader

# Or on Linux (using helper script):
chmod +x run.sh
./run.sh
```

Downloaded binaries are verified with SHA-256 and stored in the user vendor directory:
- **Windows:** `%LOCALAPPDATA%\Pirate Cinema\vendor\`
- **Linux:** `~/.local/share/Pirate Cinema/vendor/`

### 3. Frontend Setup (Optional)

The repository includes a pre-built frontend in `static/`. If you are developing UI components:

```bash
cd frontend

# Install Node dependencies
npm ci

# Run Vite dev server with Hot Module Replacement (HMR) on http://localhost:3000
npm run dev

# Compile production bundle into ../static/
npm run build

cd ..
```

### 4. Running the Application

```bash
# Default launch (Native desktop window)
uv run run.py
# Or:
python run.py

# Launch in Browser App Mode (useful on headless or remote setups)
PIRATE_CINEMA_GUI=browser uv run run.py

# Custom network binding (allow remote access from other devices)
APP_HOST=0.0.0.0 APP_PORT=8000 uv run run.py

# Non-GUI smoke test (validates backend initialization and QR asset generation)
uv run run.py --smoke-test

# MPV player smoke test (verifies IPC controller and OSD script readiness)
uv run run.py --smoke-test-mpv
```

---

## 4. Testing & Quality Assurance Guide

### Backend Tests (Pytest, Ruff, Mypy)

Run the full Python test suite:

```bash
# Run all unit and integration tests
uv run pytest

# Run standard fast tests (excluding smoke and benchmarks)
uv run pytest tests/ -m "not integration and not smoke and not benchmark" -q

# Run diagnostics and security redaction tests
uv run pytest tests/test_diagnostics.py -v

# Run updater and rollback tests
uv run pytest tests/test_updater.py tests/test_update_helpers.py -v

# Run MPV controller and playback tests
uv run pytest tests/test_mpv_controller.py tests/test_playback_decomposition.py -v

# Run mobile remote and HLS transcoding tests
uv run pytest tests/test_mobile_hls.py tests/test_mobile_pairing.py -v

# Run performance benchmarks
uv run python tests/test_benchmarks.py
```

Code style and static typing checks:

```bash
# Check code style with Ruff
uv run ruff check .

# Check static typing with Mypy
uv run mypy backend/models backend/core backend/exceptions backend/repositories
```

### Frontend Tests (TypeScript, ESLint, Node Test Runner)

Run the frontend test suite:

```bash
cd frontend

# Type-check TypeScript without emitting output
npm run type-check

# Run ESLint across frontend components
npm run lint

# Run all frontend tests (Node.js native test runner via tsx)
npm test

# Run gamepad, spatial navigation, and input tests
npm run test:input

cd ..
```

### Packaging & Smoke Tests

```bash
# Test Linux media tools packaging on local video samples
python tests/smoke_linux_media.py ./vendor

# Test Linux AppImage launch without FUSE (/dev/fuse disabled)
xvfb-run python tests/smoke_no_fuse.py ./dist/Pirate_Cinema-x86_64.AppImage

# Test embedded MPV playback under Xvfb
xvfb-run python tests/smoke_embedded_mpv.py ./dist/Pirate_Cinema-x86_64.AppImage

# Test Windows bundle startup
python run.py --smoke-test
```

---

## 5. Release Checklist (Релизный чек-лист)

Перед формированием релиза и публикацией Git-тега выполните следующие шаги:

### Фаза 1: Контроль качества кода (Quality Gates)
- [ ] **Ruff:** Линтер не сообщает об ошибках (`uv run ruff check .`).
- [ ] **Mypy:** Статическая типизация ключевых модулей проходит без ошибок (`uv run mypy backend/models backend/core backend/exceptions backend/repositories`).
- [ ] **Pytest:** Все бэкенд-тесты проходят успешно (`uv run pytest -q`).
- [ ] **Frontend:** Проверка типов TypeScript успешна (`npm run type-check --prefix frontend`).
- [ ] **ESLint:** Фронтенд-код проходит проверки линтера (`npm run lint --prefix frontend`).
- [ ] **Frontend Tests:** Все 77+ тестов фронтенда завершаются без ошибок (`npm test --prefix frontend`).
- [ ] **Бенчмарки:** Производительность компонентов не деградировала по сравнению с базовой линией (`uv run python tests/test_benchmarks.py`).

### Фаза 2: Проверка вендорных бинарников и медиаинструментов
- [ ] **TorrServer:** Актуальная версия бинарника присутствует и запускается (`python -m backend.infrastructure.downloader`).
- [ ] **MPV:** Контроллер плеера корректно взаимодействует через IPC (`python run.py --smoke-test-mpv`).
- [ ] **FFmpeg / FFprobe:** Утилиты доступны для нарезки HLS-сегментов мобильного стриминга.
- [ ] **Lua OSD:** Скрипт `backend/infrastructure/mpv/cinema.lua` загружается без синтаксических ошибок.

### Фаза 3: Диагностика и безопасность (Privacy & Security)
- [ ] **Маскирование секретов:** Проверено вырезание API-токенов, паролей и заголовков `Authorization` из экспортируемых логов.
- [ ] **Обезличивание путей:** Личные пути пользователей (`/Users/username/...`, `C:\Users\username\...`) заменяются на `~/...`.
- [ ] **Экспорт диагностики:** Эндпоинты `/api/diagnostics/bundle?format=json` и `?format=zip` возвращают корректные очищенные архивы.

### Фаза 4: Синхронизация версий и тегирование
- [ ] **version.json:** Указана целевая версия релиза (например, `{"version": "0.5.0"}`).
- [ ] **frontend/package.json:** Поле `version` синхронизировано с `version.json`.
- [ ] **pyproject.toml:** Поле `version` в секции `[project]` соответствует версии релиза.
- [ ] **Коммит релиза:** Все изменения зафиксированы в Git (`git commit -m "chore(release): bump version to v0.5.0"`).
- [ ] **Создание тега:** Создан аннотированный Git-тег с префиксом `v` (`git tag -a v0.5.0 -m "Release v0.5.0"`).
- [ ] **Пуш тега:** Тег отправлен в репозиторий (`git push origin v0.5.0`).

### Фаза 5: Контроль CI/CD и сборки дистрибутивов
- [ ] **GitHub Actions (`build.yml`):**
  - [ ] `quality-gate-backend` успешно завершён.
  - [ ] `quality-gate-frontend` скомпилировал свежий бандл с версией из Git-тега.
  - [ ] `test-updater` подтвердил работоспособность обновления и отката на Windows и Linux.
  - [ ] `build-windows` собрал `pirate-cinema-portable.exe` и `pirate-cinema-installer.exe` с подстановкой версии.
  - [ ] `build-linux` собрал `Pirate_Cinema-x86_64.AppImage`, `pirate-cinema-linux.tar.gz` и архив медиабиблиотек.
  - [ ] `release` опубликовал релиз на GitHub с вычисленными контрольными суммами `SHA256SUMS`.

### Фаза 6: Пострелизная валидация (Sanity Testing)
- [ ] **Windows:** Проверена чистая установка через NSIS installer и запуск портативного `.exe`.
- [ ] **Linux (FUSE):** AppImage запускается штатно при наличии FUSE.
- [ ] **Linux (No-FUSE):** AppImage запускается автоматически при отсутствии `libfuse2` / `/dev/fuse`.
- [ ] **Пульт:** Подключение по QR-коду со смартфона и воспроизведение торрент-потока работает штатно.
- [ ] **Апдейтер:** Приложение успешно опрашивает `/api/updater/check` и определяет актуальную версию.
