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
- **Отдельное окно на Linux:** AppImage по умолчанию открывает интерфейс в собственном окне на встроенном Qt WebEngine. Режим браузера можно включить через `PIRATE_CINEMA_GUI=browser`.
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
- **Linux (AppImage и tar.gz):** x86_64, glibc 2.38+ (например, Ubuntu 24.04+).
  - **Встроенные медиакомпоненты:** MPV, утилиты `ffmpeg` / `ffprobe` и их мультимедийные библиотеки входят в AppImage и Linux-архив. Устанавливать системные `mpv` и `ffmpeg` для этих сборок не требуется.
  - **Автоматический запуск с FUSE и без него:** При наличии FUSE используется быстрое стандартное монтирование. При отсутствии или недоступности FUSE AppImage запускается автоматически через приватное изолированное извлечение без `sudo`, `libfuse2` или дополнительных флагов.
  - Системный `mpv` поддерживается как автоматический резервный вариант (fallback) или при запуске из исходного кода (`sudo apt install mpv` / `sudo dnf install mpv` / `sudo pacman -S mpv`).
  - AppImage и Linux-архив включают Qt WebEngine. Для встраивания MPV используется X11, а в сеансе Wayland приложение по умолчанию использует XWayland, если он доступен.
- **Python:** 3.12+ (при запуске из исходников).
- **Node.js:** 20 (от 20.19) или 22.12+ — только для пересборки фронтенда на Vite 8.

### Автоматическая загрузка компонентов
На Linux x86_64 запуск из исходников через `./run.sh` загружает недостающий TorrServer и скачивает MPV, FFmpeg и FFprobe из GitHub Releases с проверкой SHA-256. AppImage и Linux-архив содержат TorrServer, MPV, FFmpeg и FFprobe и используют встроенные компоненты. На Windows при запуске автоматически загружается недостающий MPV. Команда `python -m backend.infrastructure.downloader` явно подготавливает эти компоненты и при необходимости скачивает FFmpeg и FFprobe на Windows. Загруженные файлы хранятся в каталоге пользователя:
- Windows: `%LOCALAPPDATA%\Pirate Cinema\vendor\`
- Linux: `~/.local/share/Pirate Cinema/vendor/` (в AppImage и Linux-архиве MPV и FFmpeg уже встроены).

### Запуск на Linux (AppImage)

Команды одинаковы с FUSE и без него. Приложению нужны X11 или XWayland и системные
библиотеки графики и звука. В минимальной установке могут потребоваться библиотеки
XCB и клиентская библиотека JACK (`libjack-jackd2-0` на Ubuntu).

```bash
chmod +x Pirate_Cinema-x86_64.AppImage
./Pirate_Cinema-x86_64.AppImage
```

> **Автоматический запуск без FUSE:**
> - Если FUSE доступен в системе, используется стандартное мгновенное монтирование образа.
> - Если FUSE отсутствует или доступ к нему ограничен, AppImage автоматически переключается в безопасный fallback-режим: распаковывает компоненты в приватную временную директорию (`/tmp`, права 0700) и сразу запускает приложение. При отсутствии FUSE первый и последующие запуски могут происходить чуть медленнее из-за извлечения файлов. После закрытия приложения временные файлы удаляются автоматически.
> - Никаких ручных флагов вроде `--appimage-extract-and-run` или установки пакетов не требуется.

> **Встроенный плеер MPV:** AppImage уже содержит MPV и FFmpeg. При необходимости использовать свой собственный плеер или системную версию MPV вы можете указать путь к нему в настройках приложения (`player_path`).

### Установка Flatpak (Linux x86_64)

Скачайте `Pirate_Cinema-x86_64.flatpak` и `SHA256SUMS` из одного [GitHub Release](https://github.com/sadCTNBEH/pirate-cinema-2/releases/latest). Выполните в каталоге загрузок:

```bash
grep '  Pirate_Cinema-x86_64.flatpak$' SHA256SUMS | sha256sum --check
flatpak install --user ./Pirate_Cinema-x86_64.flatpak
flatpak run io.github.sadctnbeh.PirateCinema
```

`.flatpak` — единственный файл приложения; в нём задан Flathub как источник runtime. Flatpak автоматически скачивает KDE Platform **6.11** и нужные графические расширения из сети. Нужны установленный Flatpak, доступ к Flathub и настроенный Flathub remote; если remote ещё не добавлен, выполните `flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo` один раз. Сам файл не содержит runtime и не подходит для офлайн-установки. Для обновления скачайте новый файл из GitHub Release и выполните `flatpak install --user --reinstall ./Pirate_Cinema-x86_64.flatpak`.

```bash
flatpak uninstall --user io.github.sadctnbeh.PirateCinema
# Чтобы удалить пакет вместе с пользовательскими данными, добавьте --delete-data.
```

- Настройки и библиотека хранятся отдельно в `~/.var/app/io.github.sadctnbeh.PirateCinema/data/Pirate Cinema/`. По умолчанию API слушает localhost. Для веб-пульта в доверенной локальной сети можно запустить с `flatpak run --env=APP_HOST=0.0.0.0 io.github.sadctnbeh.PirateCinema`.
- Сетевой доступ нужен для TorrServer, пиров, каталогов и локального API. Для встраивания MPV используется X11 и общий IPC, в сеансе Wayland нужен XWayland. Разрешение DRI даёт доступ к графическому устройству. Звук идёт через PulseAudio или `pipewire-pulse`. Qt WebEngine использует sandbox-интеграцию официального PyQt WebEngine BaseApp внутри Flatpak.
- Пункт в меню приложений, magnet-ссылки BTIH и файлы `.torrent` до 16 МиБ регистрируются через экспортированный desktop-файл. Выберите Pirate Cinema в настройках приложений по умолчанию, например `xdg-mime default io.github.sadctnbeh.PirateCinema.desktop x-scheme-handler/magnet`. При открытии `.torrent` окружение рабочего стола передаёт выбранный файл через портал документов. Доступ ко всему домашнему каталогу и запуск внешних плееров с хоста пакету не предоставляются.

Диагностика запускает временный TorrServer, проверяет Qt xcb, GLX/FBConfig, WebEngine и воспроизведение H.264 во встроенном MPV. Она выводит графический драйвер и выбранный режим декодирования. Добавьте `--require-audio` для строгой проверки звука.

```bash
flatpak run io.github.sadctnbeh.PirateCinema --flatpak-diagnostics
flatpak --gl-drivers
flatpak list --runtime
```

Если графический тест падает, обновите расширения командой `flatpak update`. На NVIDIA проверьте, что версия расширения GL совпадает с версией загруженного драйвера. Аппаратное декодирование зависит от драйвера и кодека. При сбое декодирования можно проверить запуск с `--env=PIRATE_CINEMA_HWDEC=no` перед application ID. Проверка под Xvfb не подтверждает работу конкретной видеокарты AMD, Intel или NVIDIA.

### Запуск Linux-архива (.tar.gz)
Для обновления существующих директорий и работы без AppImage:
```bash
tar -xzf pirate-cinema-linux.tar.gz
cd pirate-cinema-linux
chmod +x pirate-cinema-linux
./pirate-cinema-linux
```
Папка `_internal` должна оставаться рядом с исполняемым файлом. Журнал запуска: `~/.local/share/Pirate Cinema/startup.log` (или `$XDG_DATA_HOME/Pirate Cinema/startup.log`). Ошибки загрузчика до старта Python видны только при запуске из терминала.

### Блокировка рекламы в Linux

В AppImage и Flatpak откройте **Настройки → Видеоплеер (MPV)** и включите **Блокировать рекламу и трекеры**. При первом включении нужен интернет: приложение загрузит сетевые правила AdGuard Base Filter и Tracking Protection. Копии списков сохраняются для работы без сети и обновляются автоматически. В настройках видно, активна ли защита, сколько запросов заблокировано за сеанс, и можно добавить домен сайта в исключения.

Защита применяется к внешним страницам во встроенном Qt WebEngine. Она фильтрует сетевые запросы; скриптлеты, косметические правила и сетевые запросы самого MPV не обрабатываются.

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
   На Linux создайте `.venv` и запускайте `./run.sh`. Если в системе установлены `qt6-webengine`, `python-pyqt6-webengine` и `python-pyqt6`, собранные с proprietary codecs, launcher использует системный PyQt6 для H.264/AAC, оставляя остальные Python-зависимости в `.venv`. В противном случае используется изолированный Qt из `.venv`. Для Arch/CachyOS системный вариант можно установить командой `sudo pacman -S --needed qt6-webengine python-pyqt6-webengine python-pyqt6`. Переключение: `PIRATE_CINEMA_QT_RUNTIME=system ./run.sh` (требовать системную сборку) или `PIRATE_CINEMA_QT_RUNTIME=wheel ./run.sh` (использовать Qt из `.venv`). Этот выбор не применяется к Windows.
2. Сборка фронтенда (опционально, готовая сборка уже находится в `static/`):
   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   ```
3. Запустите приложение (`./run.sh` на Linux, `python -m run` на Windows):
   ```bash
   ./run.sh
   ```

### Проверка Qt WebEngine на Linux

`./run.sh --smoke-test-webengine`, `./Pirate_Cinema-x86_64.AppImage --smoke-test-webengine` и
`flatpak run io.github.sadctnbeh.PirateCinema --smoke-test-webengine` открывают штатное окно,
воспроизводят локальные H.264/AAC, фрагментированный MP4 через MSE и VP9/Opus,
проверяют отрисовку кадров, аудиосигнал и продолжение воспроизведения после перемотки.
Проверке нужны X11 или XWayland и FFmpeg с соответствующими энкодерами
(в упакованных вариантах используется FFmpeg из пакета).

Linux release CI запускает проверки H.264/AAC и MSE в штатном окне приложения,
проверяет, что AppImage не загружает системный Qt, и показывает версии Qt WebEngine
и Chromium в логе и сводке job. Chromium patch `155.0.8059.85` остаётся справочным
минимумом. В обычном релизном workflow более старый patch выводит предупреждение и
не блокирует успешный smoke test воспроизведения. Чтобы включить строгую проверку,
задайте `PIRATE_CINEMA_STRICT_CHROMIUM_SECURITY=1`. Отсутствие версии WebEngine и
любая ошибка функционального воспроизведения остаются блокирующими.

Текущая конфигурация AppImage использует Ubuntu Qt WebEngine 6.4.2 / Chromium 102
с security patch `108.0.5359.94`. Flatpak использует KDE Platform 6.11 и PyQt BaseApp
6.11; проверенная сборка Qt WebEngine 6.11.2 сообщала Chromium 140 с security patch
`151.0.7922.71`. В Linux-сборках используется Chromium с устаревшими security patch;
не следует называть их актуальными или полностью обновлёнными по безопасности.
Локальная проверка кодеков и успешное воспроизведение не подтверждают права на
распространение. AppImage включает собственный стек Qt/PyQt/Qt WebEngine, но
использует системные glibc, X11/XCB,
графические драйверы и аудио-библиотеки. Сборка AppImage на Ubuntu 24.04 требует
glibc не ниже 2.38 по ELF-символам; Ubuntu 22.04 с glibc 2.35 этой сборкой не
поддерживается.

До публичного распространения также требуется отдельная проверка лицензий Qt,
PyQt6 и патентных прав H.264/AAC. В репозитории добавлен перечень вопросов и
официальных источников в [Linux distribution licensing](licenses/LINUX_DISTRIBUTION.md).
У проекта пока отсутствует корневой `LICENSE`; CI продолжит собирать и тестировать,
но пропустит загрузку бинарных артефактов, пока владелец проекта не определит и не
зафиксирует лицензию исходного кода. Workflow также блокирует публикацию, пока
ответственный за права явно не установит
`PIRATE_CINEMA_CODEC_REDISTRIBUTION_APPROVED=true`; эта переменная является
подтверждением человека, а не лицензией. Страница [GitHub Release v0.5.2](https://github.com/sadCTNBEH/pirate-cinema-2/releases/tag/v0.5.2)
содержит только автоматические архивы исходников; проверенных установочных файлов там
нет. Запуск workflow через `workflow_dispatch` с ветки `main` проверяет сборку, но не
публикует и не обновляет release: публикация разрешена только для тега `v*`.

### Архитектура
- **Бэкенд:** FastAPI (Python 3.12) обрабатывает REST/IPC запросы, управляет процессами (TorrServer, MPV), парсингом каталогов и SQLite-базой данных.
- **Оконная оболочка:** `pywebview` с WebView2 на Windows и Qt WebEngine в Linux AppImage. Browser App Mode доступен отдельно.
- **Фронтенд:** React 19, TypeScript, Tailwind CSS, сборка через Vite в директорию `static/`.
- **Плеер:** MPV с управлением через двусторонний сокет/пайп IPC и автопереходом по сериям.

### Версия
**0.5.3**

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
- **Desktop window on Linux:** The AppImage opens its own window using bundled Qt WebEngine by default. Set `PIRATE_CINEMA_GUI=browser` to use browser mode.
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
- **Linux (AppImage and tar.gz):** x86_64, glibc 2.38+ (for example, Ubuntu 24.04+).
  - **Bundled Media Tools:** MPV, the `ffmpeg` / `ffprobe` tools, and their multimedia libraries are included in the AppImage and Linux tarball. These builds do not require system `mpv` or `ffmpeg` installations.
  - **FUSE-agnostic execution:** Works out of the box on all Linux systems with or without FUSE. If FUSE is available, standard high-performance mounting is used; if FUSE is unavailable (e.g. containers, minimal distros, Ubuntu 24.04+ without `libfuse2`), an automatic fallback extracts files to a private temporary directory and executes the app without manual flags.
  - System `mpv` is supported as an automatic fallback or when running from source (`sudo apt install mpv` / `sudo dnf install mpv` / `sudo pacman -S mpv`).
  - The AppImage and Linux tarball include Qt WebEngine. Embedded MPV uses X11. On Wayland, the app defaults to XWayland when available.
- **Python:** 3.12+ (when running from source).
- **Node.js:** 20 (20.19 or later) or 22.12+ — only when rebuilding the Vite 8 frontend.

### Automatic Binaries Download
On Linux x86_64, running from source via `./run.sh` downloads missing TorrServer and fetches MPV, FFmpeg, and FFprobe from GitHub Releases with SHA-256 verification. The AppImage and Linux tarball ship with TorrServer, MPV, FFmpeg, and FFprobe and use the bundled tools. On Windows, missing MPV is downloaded at startup. Run `python -m backend.infrastructure.downloader` to prepare these components explicitly and fetch missing FFmpeg and FFprobe on Windows. Downloaded files live in the user data directory:
- Windows: `%LOCALAPPDATA%\Pirate Cinema\vendor\`
- Linux: `~/.local/share/Pirate Cinema/vendor/` (MPV and FFmpeg are already included in AppImage and tarball builds).

### Linux Launch (AppImage)

The launch commands are the same with or without FUSE. The app requires X11 or XWayland
and the host's graphics and audio libraries. Minimal installations may need XCB libraries
and the JACK client library (`libjack-jackd2-0` on Ubuntu).

```bash
chmod +x Pirate_Cinema-x86_64.AppImage
./Pirate_Cinema-x86_64.AppImage
```

> **Automatic Fallback without FUSE:**
> - When FUSE is available, standard zero-overhead mounting is used.
> - When FUSE is missing or inaccessible, the AppImage automatically falls back to an isolated userland extraction into a private temporary directory (`/tmp`, 0700 permissions) and launches transparently. Note that launching without FUSE may be slightly slower due to extracting files on startup. All temporary files are cleaned up automatically upon exit.
> - No manual flags (like `--appimage-extract-and-run`) or root package installations (`libfuse2`) are needed.

> **Embedded MPV Player:** The AppImage already includes MPV and FFmpeg. If you prefer to use your own custom MPV build, you can specify its path under Settings (`player_path`).

### Installing the Flatpak (Linux x86_64)

Download `Pirate_Cinema-x86_64.flatpak` and `SHA256SUMS` from the same [GitHub Release](https://github.com/sadCTNBEH/pirate-cinema-2/releases/latest). Run the following from your download directory:

```bash
grep '  Pirate_Cinema-x86_64.flatpak$' SHA256SUMS | sha256sum --check
flatpak install --user ./Pirate_Cinema-x86_64.flatpak
flatpak run io.github.sadctnbeh.PirateCinema
```

The `.flatpak` file is the only application file and references Flathub for its runtime. Flatpak downloads KDE Platform **6.11** and required graphics extensions automatically. Flatpak, network access, and a configured Flathub remote are required; if Flathub is not configured yet, add it once with `flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo`. The app bundle does not contain the runtime and is not an offline installer. To update, download the new bundle from GitHub Releases and run `flatpak install --user --reinstall ./Pirate_Cinema-x86_64.flatpak`.

```bash
flatpak uninstall --user io.github.sadctnbeh.PirateCinema
# Add --delete-data to remove the application data too.
```

- Settings and the library are stored separately in `~/.var/app/io.github.sadctnbeh.PirateCinema/data/Pirate Cinema/`. The API listens on localhost by default. For the web remote on a trusted LAN, launch with `flatpak run --env=APP_HOST=0.0.0.0 io.github.sadctnbeh.PirateCinema`.
- Network access is used for TorrServer, peers, catalogs and the local API. Embedded MPV uses X11 and shared IPC, so Wayland sessions need XWayland. DRI allows graphics device access. Audio uses PulseAudio or `pipewire-pulse`. Qt WebEngine uses the official PyQt WebEngine BaseApp's sandbox integration inside Flatpak.
- The exported desktop entry provides a launcher and registers handlers for BTIH magnet links and `.torrent` files up to 16 MiB. Use your desktop's default-app settings or run `xdg-mime default io.github.sadctnbeh.PirateCinema.desktop x-scheme-handler/magnet`. The document portal passes the selected `.torrent` file into the sandbox. The bundle has no general home-directory or host-player access.

The diagnostics run a temporary TorrServer, check Qt xcb, GLX/FBConfig and WebEngine, and play an H.264 sample in embedded MPV. They print the renderer and active decoding mode. Add `--require-audio` to require a working audio connection.

```bash
flatpak run io.github.sadctnbeh.PirateCinema --flatpak-diagnostics
flatpak --gl-drivers
flatpak list --runtime
```

If the graphics check fails, refresh the extensions with `flatpak update`. On NVIDIA, check that the GL extension matches the loaded driver. Hardware decoding depends on the driver and codec. If decoding fails, try launching with `--env=PIRATE_CINEMA_HWDEC=no` before the application ID. The Xvfb check does not verify any specific AMD, Intel or NVIDIA GPU.

### Running from Linux Tarball (.tar.gz)
For legacy installations or manual folder extraction:
```bash
tar -xzf pirate-cinema-linux.tar.gz
cd pirate-cinema-linux
chmod +x pirate-cinema-linux
./pirate-cinema-linux
```
Keep the `_internal` directory alongside the binary. Startup log is written to `~/.local/share/Pirate Cinema/startup.log` (or `$XDG_DATA_HOME/Pirate Cinema/startup.log`).

### Ad blocking on Linux

In AppImage and Flatpak, open **Settings → Video Player (MPV)** and turn on **Block ads and trackers**. The first enable requires internet access to download the AdGuard Base Filter and Tracking Protection network rules. The lists are cached for offline use and updated automatically. Settings show the protection status and the number of requests blocked during the session, and let you add site domains to the exceptions list.

Protection applies to external pages in the embedded Qt WebEngine browser. It filters network requests; it does not process scriptlets, cosmetic rules, or MPV's own network traffic.

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
   On Linux, create `.venv` and launch with `./run.sh`. If the system has `qt6-webengine`, `python-pyqt6-webengine`, and `python-pyqt6` built with proprietary codecs, the launcher uses system PyQt6 for H.264/AAC while keeping other Python dependencies in `.venv`. Otherwise it uses the isolated Qt runtime from `.venv`. On Arch/CachyOS, install the system option with `sudo pacman -S --needed qt6-webengine python-pyqt6-webengine python-pyqt6`. Select it explicitly with `PIRATE_CINEMA_QT_RUNTIME=system ./run.sh`; force the `.venv` Qt runtime with `PIRATE_CINEMA_QT_RUNTIME=wheel ./run.sh`. Windows is unaffected.
2. Build the frontend (optional, pre-built assets are included in `static/`):
   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   ```
3. Start the application (`./run.sh` on Linux, `python -m run` on Windows):
   ```bash
   ./run.sh
   ```

### Checking Qt WebEngine on Linux

`./run.sh --smoke-test-webengine`, `./Pirate_Cinema-x86_64.AppImage --smoke-test-webengine`, and
`flatpak run io.github.sadctnbeh.PirateCinema --smoke-test-webengine` open the normal window and
play local H.264/AAC, fragmented MP4 via MSE, and VP9/Opus. They check presented frames,
decoded audio, and playback after seeking. The check requires X11 or XWayland and FFmpeg
with the corresponding encoders. Packaged builds use their bundled FFmpeg.

Linux release CI runs H.264/AAC and MSE playback checks in the normal app window,
checks that AppImage does not load host Qt, and reports Qt WebEngine and Chromium
versions in the job log and summary. Chromium patch `155.0.8059.85` remains the
configured reference minimum. In the regular release workflow, a lower patch is a
warning and does not fail an otherwise passing playback smoke test. Set
`PIRATE_CINEMA_STRICT_CHROMIUM_SECURITY=1` to make a below-minimum patch fail the
WebEngine smoke test. Missing or unreported WebEngine versions and all functional
playback failures remain blocking.

The current AppImage configuration uses Ubuntu Qt WebEngine 6.4.2 / Chromium 102
with security patch `108.0.5359.94`. Flatpak uses KDE Platform 6.11 and PyQt BaseApp
6.11; the tested Qt WebEngine 6.11.2 build reported Chromium 140 with security patch
`151.0.7922.71`. These Linux builds use older Chromium security patches and should
not be described as current or security-up-to-date. Local codec tests and successful
playback checks do not establish distribution rights. The AppImage bundles
Qt/PyQt/Qt WebEngine but relies on host glibc, X11/XCB,
graphics drivers, and audio libraries. The Ubuntu 24.04 AppImage build requires glibc
2.38 or newer based on its ELF symbols; Ubuntu 22.04 with glibc 2.35 is not supported
by this build.

Public distribution also requires a separate licensing review for Qt, PyQt6, and
H.264/AAC patent rights. See [Linux distribution licensing](licenses/LINUX_DISTRIBUTION.md).
The project is a Python rework of [cyberboy1999/pirate-cinema](https://github.com/cyberboy1999/pirate-cinema),
which is licensed under GNU GPL version 3. This repository follows that GPLv3
licensing path; upstream copyright remains with its author. See the complete
license in [LICENSE](LICENSE) and package notices in
[THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES). GPLv3 binary distribution requires
providing complete corresponding source and relevant build/install scripts.
That source offer has not yet been published for the v0.5.3 binaries.

The workflow separately blocks binary artifact uploads and publication until
the license file/configuration check passes and a release maintainer explicitly
sets `PIRATE_CINEMA_CODEC_REDISTRIBUTION_APPROVED=true`. That variable is a human
attestation, not a license; H.264/AAC patent obligations still need a written
determination and any required permissions. Previous successful builds do not
mean downloadable artifacts were retained: see the run's artifact list before
reusing any binaries. Publication is restricted to `v*` tags.

### Architecture
- **Backend:** FastAPI (Python 3.12) managing REST/IPC APIs, background processes (TorrServer, MPV), metadata pipelines, and SQLite database.
- **Desktop Shell:** `pywebview` with WebView2 on Windows and Qt WebEngine in the Linux AppImage. Browser App Mode is also available.
- **Frontend:** React 19, TypeScript, Tailwind CSS, built with Vite into `static/`.
- **Player:** MPV with IPC socket/pipe control and automatic playback resume.

### Version
**0.5.3**
