# Pirate Cinema

*(Read in [English](#english-version) | Читать на [Русском](#русская-версия))*

---

## English Version

Pirate Cinema is a cyberpunk-themed desktop streaming application that allows you to instantly search and stream movies and TV shows from torrents without downloading them first. It delivers a native desktop experience powered by Python, FastAPI, and `pywebview` (WebView2 on Windows, WebKitGTK on Linux).

This is a **Python rework** of the original project written in Rust by cyberboy1999: [https://github.com/cyberboy1999/pirate-cinema](https://github.com/cyberboy1999/pirate-cinema).

### Features
- **Embedded MPV Player:** Watch torrents inside the app, resume playback, switch audio/subtitle tracks, and navigate seasons and episodes without leaving the player.
- **TorrServer Integration:** Embedded background TorrServer manages torrent caching and P2P streaming.
- **Frameless Cyberpunk UI:** Seamless frameless window with custom controls (minimize, maximize/restore, close) and unified title bar drag region.
- **Popular Movies and Series:** Separate catalog sections with localized metadata and cached poster thumbnails.
- **Search and Filters:** Search through Jackett Torznab and Rutor, filter by season, quality, voiceover, and audio language; sort results by seeds, size, or date.
- **Favorites and Watch Later:** Keep separate, persistent lists for titles and saved searches.
- **Watch History:** Continue watching, mark an item as watched, or remove a single episode from history.
- **Backups:** Export and restore local application data from Settings.
- **System Tray:** Choose whether the close button exits the app or minimizes it to the tray; restore or quit from the tray menu.

### Requirements
- Windows 10/11 or Linux (Ubuntu)
- Python 3.12+
- WebView2 Runtime (included in Windows 11 by default)
- Node.js 18+ (only if building frontend from source)

### Automatic Binaries Download
Pirate Cinema requires `TorrServer` and `mpv` to function. 
You don't need to install them manually. Upon first launch, the application automatically downloads vendor binaries into:
- Windows: `%LOCALAPPDATA%\Pirate Cinema\vendor\`
- Linux: `~/.local/share/Pirate Cinema/vendor/`

### Getting Started
1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Build the frontend (optional, pre-built files in `static/`):
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
- **Backend:** FastAPI (Python 3.12) managing REST/JS APIs, catalog caching, and background workers (TorrServer, MPV).
- **Desktop Shell:** `pywebview` (WebView2 / WinForms on Windows, WebKitGTK on Linux) in seamless frameless mode.
- **Frontend:** React 19, TypeScript, Tailwind CSS, built with Vite into `static/`.
- **Player:** MPV with IPC socket/pipe control and automatic playback resume.

### Version
**v0.1.0**

---

## Русская версия

Pirate Cinema — это десктопное приложение в киберпанк-стиле для мгновенного поиска и стриминга фильмов и сериалов через торренты без предварительного скачивания.

Это **Python-реворк** оригинального проекта на Rust от cyberboy1999: [https://github.com/cyberboy1999/pirate-cinema](https://github.com/cyberboy1999/pirate-cinema).

### Основные возможности
- **Встроенный плеер MPV:** Просмотр торрентов внутри приложения, продолжение с сохранённого места, выбор аудио- и субтитровых дорожек, навигация по сезонам и сериям.
- **Интеграция TorrServer:** Встроенный TorrServer обрабатывает P2P-стриминг и кэширование в фоне.
- **Бесшовное окно (Frameless):** Окно без системной серой полоски Windows со стильными кнопками управления (свернуть, развернуть/восстановить, закрыть) и drag-зоной в шапке.
- **Популярные фильмы и сериалы:** Раздельные разделы каталога с локализованными метаданными и кэшированием постеров.
- **Поиск и фильтры:** Jackett (Torznab) и Rutor, фильтрация по сезону, качеству, озвучке и языку дорожки; сортировка по сидам, размеру и дате.
- **Избранное и «Посмотреть позже»:** Отдельные постоянные списки для тайтлов и сохранённых поисковых запросов.
- **История просмотра:** Продолжение просмотра, отметка «просмотрено» и удаление отдельного эпизода из истории.
- **Резервные копии:** Экспорт и восстановление локальных данных из настроек.
- **Системный трей:** Выбор действия по кнопке закрытия — завершить приложение или свернуть в трей; восстановление и выход из меню трея.

### Требования
- Windows 10/11 или Linux (Ubuntu)
- Python 3.12+
- WebView2 Runtime (встроен в Windows 11 по умолчанию)
- Node.js 18+ (только для сборки фронтенда из исходников)

### Автоматическая загрузка компонентов
При первом запуске приложение **автоматически скачивает** необходимые бинарные файлы (`TorrServer` и `mpv`) в каталог пользователя:
- Windows: `%LOCALAPPDATA%\Pirate Cinema\vendor\`
- Linux: `~/.local/share/Pirate Cinema/vendor/`

### Запуск из исходников
1. Установите Python-зависимости:
   ```bash
   pip install -r requirements.txt
   ```
2. Сборка фронтенда (опционально, готовая сборка находится в `static/`):
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
- **Бэкенд:** FastAPI (Python 3.12) обрабатывает API запросы, управляет процессами (TorrServer, MPV) и кэшированием.
- **Оконная оболочка:** `pywebview` в frameless-режиме с кастомным drag-region и управлением окном через JS API / REST.
- **Фронтенд:** React 19, TypeScript, Tailwind CSS, собирается через Vite в директорию `static/`.
- **Плеер:** MPV с управлением через IPC и автопереходом по сериям.

### Версия
**v0.1.0**
