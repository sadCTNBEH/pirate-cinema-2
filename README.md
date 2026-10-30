# Pirate Cinema

*Читать на [Русском](#русская-версия) | Read in [English](#english-version)*

---

## Русская версия

Pirate Cinema — это десктопное приложение в киберпанк-стиле для мгновенного поиска и стриминга фильмов, сериалов и онлайн-видео без предварительного скачивания.

Это **Python-реворк** оригинального проекта на Rust от cyberboy1999: [https://github.com/cyberboy1999/pirate-cinema](https://github.com/cyberboy1999/pirate-cinema).

### Основные возможности

- **Встроенный плеер MPV:** Просмотр торрентов и онлайн-потоков прямо внутри приложения, автопереход к следующей серии, сохранение и продолжение с таймкода, переключение аудиодорожек и субтитров.
- **Веб-пульт для смартфона (Local Web Remote по QR-коду):** Управление воспроизведением (пауза/плей, шкала перемотки, кнопки ±10с, громкость, следующая серия, выбор дорожек озвучки и субтитров) со смартфона в локальной Wi-Fi сети без установки дополнительных приложений.
- **Плавающий мини-плеер («Картинка в картинке» / PiP):** Компактный режим воспроизведения поверх всех окон (TopMost) с элементами управления при наведении и мгновенным возвратом в исходный размер по двойному клику или кнопке.
- **Zero-Dependency запуск на Linux (Browser App Mode):** На Arch Linux, Ubuntu, Fedora, SteamOS и других дистрибутивах приложение работает **«из коробки» без установки `webkit2gtk-4.1`** через любой Chromium-браузер (`--app=http://...` без вкладок и адресной строки) или Firefox.
- **Онлайн-видео и стриминг:** Встроенная поддержка Rutube, прямых HLS-потоков, создание и редактирование плейлистов, отдельная история онлайн-просмотра.
- **Интеграция TorrServer:** Фоновый TorrServer автоматически обрабатывает P2P-стриминг, буферизацию и кэширование.
- **Бесшовное окно (Frameless UI):** Окно без системной серой рамки со стильными кнопками управления (свернуть, развернуть, закрыть) и drag-зоной перемещения.
- **Медиатека 2.0 с фильтрами:** Фильтрация по типу (фильмы/сериалы), статусу просмотра (просмотрено/в процессе/не просмотрено), жанрам, диапазону годов выпуска, сортировка и бесконечная плавная прокрутка.
- **Поиск и агрегация:** Поддержка Jackett (Torznab) и Rutor с фильтрами по качеству, озвучке, сезонам и языкам.
- **Диагностика системы:** Раздел мониторинга статуса TorrServer, версии MPV, целостности базы данных и свободного места на диске.
- **Встроенные обновления (In-App Updater):** Автоматическая проверка свежих версий через GitHub Releases с информационным баннером и безопасным перезапуском.
- **Избранное, «Позже» и История:** Постоянные списки для контента, выборочное удаление эпизодов и синхронизация между разделами.
- **Резервные копии и системный трей:** Экспорт/импорт настроек в ZIP, сворачивание в системный трей при закрытии.

### Требования
- **Windows:** Windows 10/11 (WebView2 встроен по умолчанию).
- **Linux:** x86_64, glibc 2.35+ (например, Ubuntu 22.04+).
  - Для воспроизведения требуется системный `mpv` (`sudo apt install mpv` / `sudo dnf install mpv` / `sudo pacman -S mpv`).
  - WebKitGTK не требуется — используется Browser App Mode на базе установленного браузера (Chromium, Chrome, Brave, Edge, Firefox).
  - Для монтирования AppImage требуется поддержка FUSE (`libfuse2` в Ubuntu 22.04+) либо запуск с флагом `--appimage-extract-and-run`.
- **Python:** 3.12+ (при запуске из исходников).
- **Node.js:** 18+ (только для пересборки фронтенда).

### Автоматическая загрузка компонентов
При первом запуске приложение **автоматически скачивает** необходимые бинарные файлы (`TorrServer` и `mpv` под Windows) в каталог пользователя:
- Windows: `%LOCALAPPDATA%\Pirate Cinema\vendor\`
- Linux: `~/.local/share/Pirate Cinema/vendor/` (на Linux используется системный `mpv`).

### Запуск на Linux (AppImage)

Скачайте `Pirate_Cinema-x86_64.AppImage`, выдайте права на исполнение и запустите:

```bash
chmod +x Pirate_Cinema-x86_64.AppImage
./Pirate_Cinema-x86_64.AppImage
```

> **Ограничения FUSE:** Если в системе отсутствует FUSE (например, в Docker-контейнере, минимальной среде или WSL2), запустите AppImage с автоматической распаковкой:
> ```bash
> ./Pirate_Cinema-x86_64.AppImage --appimage-extract-and-run
> ```
> Либо установите поддержку FUSE 2: `sudo apt install libfuse2` (Ubuntu/Debian).

> **Системный MPV:** Pirate Cinema использует внешний системный MPV для аппаратного ускорения и стабильного воспроизведения видео. Убедитесь, что `mpv` установлен в системе:
> ```bash
> # Ubuntu / Debian / Linux Mint:
> sudo apt install mpv
> 
> # Fedora / RHEL:
> sudo dnf install mpv
> 
> # Arch Linux / Manjaro:
> sudo pacman -S mpv
> ```

#### Запуск Linux-архива (.tar.gz)
Для обновления существующих директорий и работы без AppImage:
```bash
tar -xzf pirate-cinema-linux.tar.gz
cd pirate-cinema-linux
chmod +x pirate-cinema-linux
./pirate-cinema-linux
```
Папка `_internal` должна оставаться рядом с исполняемым файлом. Журнал запуска: `~/.local/share/Pirate Cinema/startup.log` (или `$XDG_DATA_HOME/Pirate Cinema/startup.log`). Ошибки загрузчика до старта Python видны только при запуске из терминала.

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
**v0.4.2**

---

## English Version

Pirate Cinema is a cyberpunk-themed desktop streaming application that allows you to instantly search and stream movies, TV shows, and online video streams without downloading them first.

This is a **Python rework** of the original project written in Rust by cyberboy1999: [https://github.com/cyberboy1999/pirate-cinema](https://github.com/cyberboy1999/pirate-cinema).

### Features

- **Embedded MPV Player:** Stream torrents and online media directly inside the app, resume playback from saved timecode, switch audio/subtitle tracks, and auto-advance episodes.
- **Local Web Remote via QR Code:** Control playback (play/pause, seekbar, ±10s skip, volume, next episode, audio and subtitle tracks) from a smartphone on the local Wi-Fi network without installing apps.
- **Picture-in-Picture (PiP) Mini-Player:** Compact TopMost floating playback mode with hover controls and instant double-click restore.
- **Zero-Dependency Linux Support (Browser App Mode):** Runs out of the box on Arch Linux, Ubuntu, Fedora, SteamOS, and other distros **without needing `webkit2gtk-4.1`** by launching a dedicated standalone Chromium window (`--app=http://...`) or Firefox.
- **Online Video Streaming:** Native support for Rutube, direct HLS streams, playlist management, and dedicated online watch history.
- **TorrServer Integration:** Embedded background TorrServer manages torrent caching, peer discovery, and P2P streaming.
- **Frameless Cyberpunk UI:** Seamless frameless window with custom controls (minimize, maximize/restore, close) and integrated title bar drag region.
- **Library 2.0 with Advanced Filters:** Filter by type (Movies/Series), watch status (Watched/In Progress/Unwatched), genre, year range; sort and scroll with infinite pagination.
- **Search & Aggregation:** Search through Jackett (Torznab) and Rutor with filters for quality, voiceover, season, and audio language.
- **System Diagnostics:** Dedicated diagnostics panel monitoring TorrServer status, MPV version, database integrity, and disk space.
- **In-App Updater:** Automated background update checks via GitHub Releases with notification banner and safe atomic restart.
- **Favorites, Watch Later & History:** Persistent lists for titles and saved searches, idempotent episode deletion, and auto-sync between views.
- **Backups & System Tray:** Export/import application settings as ZIP archives; minimize to system tray on close with restore actions.

### Requirements
- **Windows:** Windows 10/11 (WebView2 included by default).
- **Linux:** x86_64, glibc 2.35+ (for example, Ubuntu 22.04+).
  - Playback requires system `mpv` (`sudo apt install mpv` / `sudo dnf install mpv` / `sudo pacman -S mpv`).
  - WebKitGTK is not required — Browser App Mode runs via an installed Chromium browser or Firefox.
  - AppImage mounting requires FUSE support (`libfuse2` on Ubuntu 22.04+) or launching with `--appimage-extract-and-run`.
- **Python:** 3.12+ (when running from source).
- **Node.js:** 18+ (only if rebuilding frontend).

### Automatic Binaries Download
Upon first launch, Pirate Cinema automatically downloads required vendor binaries (`TorrServer` and Windows `mpv`) into the user data directory:
- Windows: `%LOCALAPPDATA%\Pirate Cinema\vendor\`
- Linux: `~/.local/share/Pirate Cinema/vendor/` (Linux uses system `mpv`).

### Linux Launch (AppImage)

Download `Pirate_Cinema-x86_64.AppImage`, make it executable, and launch:

```bash
chmod +x Pirate_Cinema-x86_64.AppImage
./Pirate_Cinema-x86_64.AppImage
```

> **FUSE Note:** If FUSE is not available on your system (such as inside a container, minimal environment, or WSL2), launch the AppImage using extract-and-run:
> ```bash
> ./Pirate_Cinema-x86_64.AppImage --appimage-extract-and-run
> ```
> Or install FUSE 2 support: `sudo apt install libfuse2` (Ubuntu/Debian).

> **System MPV Requirement:** Video playback requires system `mpv`:
> ```bash
> # Ubuntu / Debian / Linux Mint:
> sudo apt install mpv
> 
> # Fedora / RHEL:
> sudo dnf install mpv
> 
> # Arch Linux / Manjaro:
> sudo pacman -S mpv
> ```

#### Running from Linux Tarball (.tar.gz)
For legacy installations or manual folder extraction:
```bash
tar -xzf pirate-cinema-linux.tar.gz
cd pirate-cinema-linux
chmod +x pirate-cinema-linux
./pirate-cinema-linux
```
Keep the `_internal` directory alongside the binary. Startup log is written to `~/.local/share/Pirate Cinema/startup.log` (or `$XDG_DATA_HOME/Pirate Cinema/startup.log`).

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
**v0.4.2**
