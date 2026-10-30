# Pirate Cinema

*Читать на [Русском](#русская-версия) | Read in [English](#english-version)*

---

## Русская версия

Pirate Cinema — это десктопное приложение для мгновенного поиска и стриминга фильмов, сериалов и онлайн-видео без предварительного скачивания.

Это **Python-реворк** оригинального проекта на Rust от cyberboy1999: [https://github.com/cyberboy1999/pirate-cinema](https://github.com/cyberboy1999/pirate-cinema).

### Основные возможности

- **Встроенный плеер MPV:** Просмотр торрентов и онлайн-потоков прямо внутри приложения, автопереход к следующей серии, сохранение и продолжение с таймкода, переключение аудиодорожек и субтитров.
- **Веб-пульт для смартфона (Local Web Remote по QR-коду):** Управление воспроизведением (пауза/плей, шкала перемотки, кнопки ±10с, громкость, следующая серия, выбор дорожек озвучки и субтитров) со смартфона в локальной Wi-Fi сети без установки дополнительных приложений.
- **Просмотр торрентов на телефоне:** Запуск текущего видео с ПК или выбранного файла из поиска в браузере телефона. Совместимые MP4/H.264/AAC передаются напрямую; остальные форматы подготавливаются на ПК в HLS/H.264/AAC через FFmpeg. Есть продолжение с позиции ПК или сохранённого прогресса выбранной серии, кнопки предыдущей и следующей серии, название текущего файла и штатный полный экран браузерного плеера.
- **Продолжение сериалов:** Прогресс привязан к конкретной серии. Для связанного с каталогом контента поддерживается продолжение той же серии из другой раздачи и предложение следующей серии по подтверждённым метаданным; неоднозначные файлы выбирает пользователь.
- **Главы и пропуск заставок:** Навигация по главам MPV и пропуск подтверждённых заставок и повторов. Автопропуск включается в настройках, показывает отменяемый отсчёт 8 секунд; титры пропускаются вручную.
- **Каталоги аниме:** Shikimori и YummyAnime, настройки ключей YummyAnime, онлайн-провайдер AnimeGo с выбором серии и озвучки.
- **Плавающий мини-плеер («Картинка в картинке» / PiP):** Компактный режим воспроизведения поверх всех окон (TopMost) с элементами управления при наведении и мгновенным возвратом в исходный размер по двойному клику или кнопке.
- **Linux без WebKitGTK (Browser App Mode):** На Arch Linux, Ubuntu, Fedora, SteamOS и других дистрибутивах приложение работает **«из коробки» без установки `webkit2gtk-4.1`** через любой Chromium-браузер (`--app=http://...` без вкладок и адресной строки) или Firefox.
- **Онлайн-видео и стриминг:** Встроенная поддержка Rutube, прямых HLS-потоков, создание и редактирование плейлистов, отдельная история онлайн-просмотра.
- **Интеграция TorrServer:** Фоновый TorrServer автоматически обрабатывает P2P-стриминг, буферизацию и кэширование.
- **Бесшовное окно (Frameless UI):** Окно без системной серой рамки с кнопками управления (свернуть, развернуть, закрыть) и drag-зоной перемещения.
- **Медиатека 2.0 с фильтрами:** Фильтрация по типу (фильмы/сериалы), статусу просмотра (просмотрено/в процессе/не просмотрено), жанрам, диапазону годов выпуска, сортировка и бесконечная плавная прокрутка.
- **Поиск и агрегация:** Поддержка Jackett (Torznab) и Rutor с фильтрами по качеству, озвучке, сезонам и языкам.
- **Диагностика системы:** Раздел мониторинга статуса TorrServer, версии MPV, целостности базы данных и свободного места на диске.
- **Встроенные обновления (In-App Updater):** Автоматическая проверка свежих версий через GitHub Releases с информационным баннером и безопасным перезапуском.
- **Избранное, «Позже» и История:** Постоянные списки для контента, выборочное удаление эпизодов и синхронизация между разделами.
- **Резервные копии и системный трей:** Экспорт/импорт настроек в ZIP, сворачивание в системный трей при закрытии.

### Требования
- **Windows:** Windows 10/11 (WebView2 встроен по умолчанию).
- **Linux:** x86_64, glibc 2.35+ (например, Ubuntu 22.04+).
  - **Встроенные медиакомпоненты:** MPV, утилиты `ffmpeg` / `ffprobe` и их мультимедийные библиотеки входят в AppImage и Linux-архив. Устанавливать системные `mpv` и `ffmpeg` для этих сборок не требуется.
  - **Автоматический запуск с FUSE и без него:** При наличии FUSE используется быстрое стандартное монтирование. При отсутствии или недоступности FUSE AppImage запускается автоматически через приватное изолированное извлечение без `sudo`, `libfuse2` или дополнительных флагов.
  - Системный `mpv` поддерживается как автоматический резервный вариант (fallback) или при запуске из исходного кода (`sudo apt install mpv` / `sudo dnf install mpv` / `sudo pacman -S mpv`).
  - WebKitGTK не требуется — используется Browser App Mode на базе установленного браузера (Chromium, Chrome, Brave, Edge, Firefox).
- **Python:** 3.12+ (при запуске из исходников).
- **Node.js:** 20 (от 20.19) или 22.12+ — только для пересборки фронтенда на Vite 8.

### Автоматическая загрузка компонентов
При первом запуске недостающий `TorrServer` и плеер `mpv` под Windows загружаются автоматически. Команда `python -m backend.infrastructure.downloader` явно подготавливает компоненты, включая недостающие `ffmpeg` / `ffprobe` под Windows. Загруженные файлы хранятся в каталоге пользователя:
- Windows: `%LOCALAPPDATA%\Pirate Cinema\vendor\`
- Linux: `~/.local/share/Pirate Cinema/vendor/` (в AppImage и Linux-архиве MPV и FFmpeg уже встроены).

### Запуск на Linux (AppImage)

Инструкция одинакова для любых Linux-систем — как с установленным FUSE, так и без него (Docker, WSL2, минимальные дистрибутивы, Ubuntu 24.04/22.04 без `libfuse2`):

```bash
chmod +x Pirate_Cinema-x86_64.AppImage
./Pirate_Cinema-x86_64.AppImage
```

> **Автоматический запуск без FUSE:**
> - Если FUSE доступен в системе, используется стандартное мгновенное монтирование образа.
> - Если FUSE отсутствует или доступ к нему ограничен, AppImage автоматически переключается в безопасный fallback-режим: распаковывает компоненты в приватную временную директорию (`/tmp`, права 0700) и сразу запускает приложение. При отсутствии FUSE первый и последующие запуски могут происходить чуть медленнее из-за извлечения файлов. После закрытия приложения временные файлы удаляются автоматически.
> - Никаких ручных флагов вроде `--appimage-extract-and-run` или установки пакетов не требуется.

> **Встроенный плеер MPV:** AppImage уже содержит MPV и FFmpeg. При необходимости использовать свой собственный плеер или системную версию MPV вы можете указать путь к нему в настройках приложения (`player_path`).

#### Запуск Linux-архива (.tar.gz)
Для обновления существующих директорий и работы без AppImage:
```bash
tar -xzf pirate-cinema-linux.tar.gz
cd pirate-cinema-linux
chmod +x pirate-cinema-linux
./pirate-cinema-linux
```
Папка `_internal` должна оставаться рядом с исполняемым файлом. Журнал запуска: `~/.local/share/Pirate Cinema/startup.log` (или `$XDG_DATA_HOME/Pirate Cinema/startup.log`). Ошибки загрузчика до старта Python видны только при запуске из терминала.

### Просмотр на телефоне и сопряжение
1. Подключите ПК и телефон к одной локальной сети. Откройте веб-пульт в приложении на ПК и отсканируйте актуальный QR-код либо скопируйте **весь адрес**, включая `#pair=…`. Одного IP-адреса или обновления старой страницы недостаточно для первого сопряжения.
2. В браузере телефона нажмите «Смотреть текущее видео на телефоне» или выберите «Смотреть на телефоне» в поиске/списке серий. Мобильный просмотр не запускает и не останавливает плеер на ПК.
3. Выберите «Продолжить с ММ:СС» или «Смотреть с начала». При переключении серий время предыдущей серии сбрасывается; сохранённая позиция предлагается только для выбранной серии. Кнопки «Предыдущая серия» и «Следующая серия» появляются, если соответствующий файл однозначно найден в текущем сезоне. Полный экран включается в самом видеоплеере.

Подключение сохраняется между вкладками и перезапусками ПК до истечения 12 часов. После истечения срока, смены адреса ПК или при открытии пульта с другого адреса (`.local` вместо IP) снова откройте актуальный QR-код. Если ПК недоступен с телефона, проверьте разрешение для приложения/порта `APP_PORT` в частной сети брандмауэра.

Просмотр на телефоне предназначен для **торрент-файлов**; онлайн-провайдеры запускаются отдельно на ПК. Для неподдерживаемых телефоном кодеков FFmpeg использует процессор ПК; подготовка HLS выполняется в памяти, без сохранения сегментов видео на диск. При запуске из исходников установите `ffmpeg` и `ffprobe` вместе с `mpv`; под Windows компоненты можно подготовить командой `python -m backend.infrastructure.downloader`.

### Переменные окружения (опционально)
- `PIRATE_CINEMA_GUI=browser` — принудительно запускать приложение в Browser App Mode.
- `PIRATE_CINEMA_GUI=webview` — использовать нативный движок PyWebView (WebKitGTK/WebView2).
- `APP_HOST` / `APP_PORT` — хост и порт локального веб-сервера (по умолчанию: `0.0.0.0:8000`, с доступом из локальной сети). При `APP_HOST=127.0.0.1` пульт с другого устройства недоступен.

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
**v0.4.4**

---

## English Version

Pirate Cinema is a desktop streaming application that allows you to instantly search and stream movies, TV shows, and online video streams without downloading them first.

This is a **Python rework** of the original project written in Rust by cyberboy1999: [https://github.com/cyberboy1999/pirate-cinema](https://github.com/cyberboy1999/pirate-cinema).

### Features

- **Embedded MPV Player:** Stream torrents and online media directly inside the app, resume playback from saved timecode, switch audio/subtitle tracks, and auto-advance episodes.
- **Local Web Remote via QR Code:** Control playback (play/pause, seekbar, ±10s skip, volume, next episode, audio and subtitle tracks) from a smartphone on the local Wi-Fi network without installing apps.
- **Torrent Playback on Your Phone:** Open the current PC video or select a torrent file from search in the phone browser. Compatible MP4/H.264/AAC streams play directly; other formats are prepared on the PC as HLS/H.264/AAC using FFmpeg. Includes resume from the PC position or the selected episode's saved progress, previous/next episode buttons, the current file name, and fullscreen through the browser player's own controls.
- **Series Continuation:** Progress belongs to the selected episode. Catalog-linked titles support resuming the same episode from another release and offering the next episode using confirmed metadata; ambiguous files require a user choice.
- **Chapters & Intro Skipping:** MPV chapter navigation and skipping verified intros and recaps. Optional automatic skipping has an eight-second countdown with cancellation; credits are skipped manually.
- **Anime Catalogs:** Shikimori and YummyAnime, configurable YummyAnime keys, and the AnimeGo online provider with episode and voiceover selection.
- **Picture-in-Picture (PiP) Mini-Player:** Compact TopMost floating playback mode with hover controls and instant double-click restore.
- **Linux without WebKitGTK (Browser App Mode):** Runs out of the box on Arch Linux, Ubuntu, Fedora, SteamOS, and other distros **without needing `webkit2gtk-4.1`** by launching a dedicated standalone Chromium window (`--app=http://...`) or Firefox.
- **Online Video Streaming:** Native support for Rutube, direct HLS streams, playlist management, and dedicated online watch history.
- **TorrServer Integration:** Embedded background TorrServer manages torrent caching, peer discovery, and P2P streaming.
- **Frameless UI:** Seamless frameless window with custom controls (minimize, maximize/restore, close) and integrated title bar drag region.
- **Library 2.0 with Advanced Filters:** Filter by type (Movies/Series), watch status (Watched/In Progress/Unwatched), genre, year range; sort and scroll with infinite pagination.
- **Search & Aggregation:** Search through Jackett (Torznab) and Rutor with filters for quality, voiceover, season, and audio language.
- **System Diagnostics:** Dedicated diagnostics panel monitoring TorrServer status, MPV version, database integrity, and disk space.
- **In-App Updater:** Automated background update checks via GitHub Releases with notification banner and safe atomic restart.
- **Favorites, Watch Later & History:** Persistent lists for titles and saved searches, idempotent episode deletion, and auto-sync between views.
- **Backups & System Tray:** Export/import application settings as ZIP archives; minimize to system tray on close with restore actions.

### Requirements
- **Windows:** Windows 10/11 (WebView2 included by default).
- **Linux:** x86_64, glibc 2.35+ (for example, Ubuntu 22.04+).
  - **Bundled Media Tools:** MPV, the `ffmpeg` / `ffprobe` tools, and their multimedia libraries are included in the AppImage and Linux tarball. These builds do not require system `mpv` or `ffmpeg` installations.
  - **FUSE-agnostic execution:** Works out of the box on all Linux systems with or without FUSE. If FUSE is available, standard high-performance mounting is used; if FUSE is unavailable (e.g. containers, minimal distros, Ubuntu 24.04+ without `libfuse2`), an automatic fallback extracts files to a private temporary directory and executes the app without manual flags.
  - System `mpv` is supported as an automatic fallback or when running from source (`sudo apt install mpv` / `sudo dnf install mpv` / `sudo pacman -S mpv`).
  - WebKitGTK is not required — Browser App Mode runs via an installed Chromium browser or Firefox.
- **Python:** 3.12+ (when running from source).
- **Node.js:** 20 (20.19 or later) or 22.12+ — only when rebuilding the Vite 8 frontend.

### Automatic Binaries Download
Missing TorrServer and Windows MPV binaries are downloaded automatically at startup. Run `python -m backend.infrastructure.downloader` to explicitly prepare components, including missing Windows `ffmpeg` / `ffprobe` tools. Downloaded files live in the user data directory:
- Windows: `%LOCALAPPDATA%\Pirate Cinema\vendor\`
- Linux: `~/.local/share/Pirate Cinema/vendor/` (MPV and FFmpeg are already included in AppImage and tarball builds).

### Linux Launch (AppImage)

The launch instructions are identical across all Linux systems — with or without FUSE (Docker, WSL2, minimal containers, Ubuntu 24.04/22.04 without `libfuse2`):

```bash
chmod +x Pirate_Cinema-x86_64.AppImage
./Pirate_Cinema-x86_64.AppImage
```

> **Automatic Fallback without FUSE:**
> - When FUSE is available, standard zero-overhead mounting is used.
> - When FUSE is missing or inaccessible, the AppImage automatically falls back to an isolated userland extraction into a private temporary directory (`/tmp`, 0700 permissions) and launches transparently. Note that launching without FUSE may be slightly slower due to extracting files on startup. All temporary files are cleaned up automatically upon exit.
> - No manual flags (like `--appimage-extract-and-run`) or root package installations (`libfuse2`) are needed.

> **Embedded MPV Player:** The AppImage already includes MPV and FFmpeg. If you prefer to use your own custom MPV build, you can specify its path under Settings (`player_path`).

#### Running from Linux Tarball (.tar.gz)
For legacy installations or manual folder extraction:
```bash
tar -xzf pirate-cinema-linux.tar.gz
cd pirate-cinema-linux
chmod +x pirate-cinema-linux
./pirate-cinema-linux
```
Keep the `_internal` directory alongside the binary. Startup log is written to `~/.local/share/Pirate Cinema/startup.log` (or `$XDG_DATA_HOME/Pirate Cinema/startup.log`).

### Phone Playback & Pairing
1. Connect the PC and phone to the same LAN. Open the remote-control dialog on the PC and scan the current QR code or copy the **entire URL**, including `#pair=…`. An IP address alone or reloading an old page does not establish initial pairing.
2. In the phone browser, choose the current PC video or use “Watch on phone” from search or the episode list. Phone playback does not start or stop the PC player.
3. Resume from the displayed timestamp or start from the beginning. Switching episodes clears the previous episode's resume time; only progress for the selected episode is offered. Previous/next buttons appear when an unambiguous matching file exists in the current season. Use the video player's own fullscreen control.

Pairing survives new tabs and PC restarts until its 12-hour expiry. Scan the current QR code again after expiry, a PC address change, or switching between the IP and `.local` URLs. If the phone cannot reach the PC, check the application's or `APP_PORT` port's private-network firewall permission.

Phone playback supports **torrent files**; online providers run separately on the PC. FFmpeg uses the PC's CPU to convert codecs unsupported by the phone. HLS segments are prepared in memory without writing video segments to disk. When running from source, install `ffmpeg` and `ffprobe` alongside `mpv`; on Windows, prepare the tools with `python -m backend.infrastructure.downloader`.

### Environment Variables (Optional)
- `PIRATE_CINEMA_GUI=browser` — Force Browser App Mode.
- `PIRATE_CINEMA_GUI=webview` — Force native PyWebView shell (WebKitGTK/WebView2).
- `APP_HOST` / `APP_PORT` — Local server host and port (default: `0.0.0.0:8000`, reachable on the LAN). Setting `APP_HOST=127.0.0.1` prevents access from other devices.

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
**v0.4.4**
