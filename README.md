# Pirate Cinema

*Читать на [Русском](#русская-версия) | Read in [English](#english-version)*

---

## Русская версия

Pirate Cinema — это десктопное приложение в киберпанк-стиле для мгновенного поиска и стриминга фильмов, сериалов и онлайн-видео без предварительного скачивания.

Это **Python-реворк** оригинального проекта на Rust от cyberboy1999: [https://github.com/cyberboy1999/pirate-cinema](https://github.com/cyberboy1999/pirate-cinema).

### Основные возможности

- **Встроенный плеер MPV:** Просмотр торрентов и онлайн-потоков прямо внутри приложения, автопереход к следующей серии, сохранение и продолжение с таймкода, переключение аудиодорожек и субтитров.
- **Zero-Dependency запуск на Linux (Browser App Mode):** На Arch Linux, Ubuntu, Fedora, SteamOS и других дистрибутивах приложение работает **«из коробки» без установки `webkit2gtk-4.1`** через любой Chromium-браузер (`--app=http://...` без вкладок и адресной строки) или Firefox.
- **Онлайн-видео и стриминг:** Встроенная поддержка Rutube, прямых HLS-потоков, создание и редактирование плейлистов, отдельная история онлайн-просмотра.
- **Интеграция TorrServer:** Фоновый TorrServer автоматически обрабатывает P2P-стриминг, буферизацию и кэширование.
- **Бесшовное окно (Frameless UI):** Окно без системной серой рамки со стильными кнопками управления (свернуть, развернуть, закрыть) и drag-зоной перемещения.
- **Медиатека 2.0 с фильтрами:** Фильтрация по типу (фильмы/сериалы), статусу просмотра (просмотрено/в процессе/не просмотрено), жанрам, диапазону годов выпуска, сортировка и бесконечная плавная прокрутка.
- **Поиск и агрегация:** Поддержка Jackett (Torznab) и Rutor с фильтрами по качеству, озвучке, сезонам и языкам.
- **Диагностика системы:** Раздел мониторинга статуса TorrServer, версии MPV, целостности базы данных и свободного места на диске.
- **Встроенные обновления (In-App Updater):** Автоматическая проверка свежих версий через GitHub Releases с информационным баннером.
- **Избранное, «Позже» и История:** Постоянные списки для контента, выборочное удаление эпизодов и синхронизация между разделами.
- **Резервные копии и системный трей:** Экспорт/импорт настроек в ZIP, сворачивание в системный трей при закрытии.

### Требования
- **Windows:** Windows 10/11 (WebView2 встроен по умолчанию).
- **Linux:** Любой современный дистрибутив (Arch Linux, Ubuntu, Debian, Fedora, openSUSE, SteamOS и др.). Дополнительные пакеты WebKit не требуются — достаточно установленного браузера (Chromium, Chrome, Brave, Edge, Firefox).
- **Python:** 3.12+ (при запуске из исходников).
- **Node.js:** 18+ (только для пересборки фронтенда).

### Автоматическая загрузка компонентов
При первом запуске приложение **автоматически скачивает** необходимые бинарные файлы (`TorrServer` и `mpv` под Windows) в каталог пользователя:
- Windows: `%LOCALAPPDATA%\Pirate Cinema\vendor\`
- Linux: `~/.local/share/Pirate Cinema/vendor/` (на Linux используется системный `mpv`).

### Переменные окружения (опционально)
- `PIRATE_CINEMA_GUI=browser` — принудительно запускать приложение в Browser App Mode.
- `PIRATE_CINEMA_GUI=webview` — использовать нативный движок PyWebView (WebKitGTK/WebView2).
- `APP_HOST` / `APP_PORT` — хост и порт локального веб-сервера (по умолчанию: `127.0.0.1:8000`).

### Запуск из исходников
1. Установите Python-зависимости:
   ```bash
   pip install -r requirements.txt
   ```
2. Сборка фронтенда (опционально, готовая сборка уже находится в `static/`):
   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   ```
3. Запустите приложение:
   ```bash
   python -m run
   ```

### Архитектура
- **Бэкенд:** FastAPI (Python 3.12) обрабатывает REST/IPC запросы, управляет процессами (TorrServer, MPV), парсингом каталогов и SQLite-базой данных.
- **Оконная оболочка:** `pywebview` в frameless-режиме (Windows) / Browser App Mode (Linux & универсальный fallback).
- **Фронтенд:** React 19, TypeScript, Tailwind CSS, сборка через Vite в директорию `static/`.
- **Плеер:** MPV с управлением через двусторонний сокет/пайп IPC и автопереходом по сериям.

### Версия
**v0.2.0**

---

## English Version

Pirate Cinema is a cyberpunk-themed desktop streaming application that allows you to instantly search and stream movies, TV shows, and online video streams without downloading them first.

This is a **Python rework** of the original project written in Rust by cyberboy1999: [https://github.com/cyberboy1999/pirate-cinema](https://github.com/cyberboy1999/pirate-cinema).

### Features

- **Embedded MPV Player:** Stream torrents and online media directly inside the app, resume playback from saved timecode, switch audio/subtitle tracks, and auto-advance episodes.
- **Zero-Dependency Linux Support (Browser App Mode):** Runs out of the box on Arch Linux, Ubuntu, Fedora, SteamOS, and other distros **without needing `webkit2gtk-4.1`** by launching a dedicated standalone Chromium window (`--app=http://...`) or Firefox.
- **Online Video Streaming:** Native support for Rutube, direct HLS streams, playlist management, and dedicated online watch history.
- **TorrServer Integration:** Embedded background TorrServer manages torrent caching, peer discovery, and P2P streaming.
- **Frameless Cyberpunk UI:** Seamless frameless window with custom controls (minimize, maximize/restore, close) and integrated title bar drag region.
- **Library 2.0 with Advanced Filters:** Filter by type (Movies/Series), watch status (Watched/In Progress/Unwatched), genre, year range; sort and scroll with infinite pagination.
- **Search & Aggregation:** Search through Jackett (Torznab) and Rutor with filters for quality, voiceover, season, and audio language.
- **System Diagnostics:** Dedicated diagnostics panel monitoring TorrServer status, MPV version, database integrity, and disk space.
- **In-App Updater:** Automated background update checks via GitHub Releases with notification banner.
- **Favorites, Watch Later & History:** Persistent lists for titles and saved searches, idempotent episode deletion, and auto-sync between views.
- **Backups & System Tray:** Export/import application settings as ZIP archives; minimize to system tray on close with restore actions.

### Requirements
- **Windows:** Windows 10/11 (WebView2 included by default).
- **Linux:** Any modern Linux distribution (Arch Linux, Ubuntu, Debian, Fedora, openSUSE, SteamOS, etc.). No extra WebKit packages required — runs using any installed browser (Chromium, Chrome, Brave, Edge, Firefox).
- **Python:** 3.12+ (when running from source).
- **Node.js:** 18+ (only if rebuilding frontend).

### Automatic Binaries Download
Upon first launch, Pirate Cinema automatically downloads required vendor binaries (`TorrServer` and Windows `mpv`) into the user data directory:
- Windows: `%LOCALAPPDATA%\Pirate Cinema\vendor\`
- Linux: `~/.local/share/Pirate Cinema/vendor/` (Linux uses system `mpv`).

### Environment Variables (Optional)
- `PIRATE_CINEMA_GUI=browser` — Force Browser App Mode.
- `PIRATE_CINEMA_GUI=webview` — Force native PyWebView shell (WebKitGTK/WebView2).
- `APP_HOST` / `APP_PORT` — Local server host and port (default: `127.0.0.1:8000`).

### Getting Started
1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Build the frontend (optional, pre-built assets are included in `static/`):
   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   ```
3. Start the application:
   ```bash
   python -m run
   ```

### Architecture
- **Backend:** FastAPI (Python 3.12) managing REST/IPC APIs, background processes (TorrServer, MPV), metadata pipelines, and SQLite database.
- **Desktop Shell:** `pywebview` frameless mode (Windows) / Browser App Mode (Linux & universal fallback).
- **Frontend:** React 19, TypeScript, Tailwind CSS, built with Vite into `static/`.
- **Player:** MPV with IPC socket/pipe control and automatic playback resume.

### Version
**v0.2.1**
