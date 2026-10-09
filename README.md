# Pirate Cinema

*(Read in [English](#english-version) | Читать на [Русском](#русская-версия))*

---

## English Version

Pirate Cinema is a minimalist desktop streaming application that allows you to instantly search and stream movies and TV shows from torrents without downloading them first. It provides a native Windows/Linux desktop experience powered by Python, FastAPI, and `pywebview`.

This is a **Python rework** of the original project written in Rust by cyberboy1999: [https://github.com/cyberboy1999/pirate-cinema](https://github.com/cyberboy1999/pirate-cinema).

### Features
- **Instant Streaming:** Stream torrents instantly via the built-in MPV player.
- **TorrServer Integration:** Uses a bundled TorrServer instance to handle torrent protocols in the background.
- **Search & Catalog:** Search TMDB via Cinemeta and automatically fetch corresponding torrents.
- **Library:** Keep track of your continued watching and saved torrents.
- **Native Desktop App:** Runs as a lightweight native window using WebView2 (via `pywebview`) or GTK/WebKit on Linux.
- **No Build Steps:** Vanilla JS and CSS frontend-no React, no bundlers, no node_modules.

### Requirements
- Windows 10/11 or Linux (Ubuntu)
- Python 3.12+
- WebView2 Runtime (Included in Windows 11 by default)

### Automatic Binaries Download
Pirate Cinema requires `TorrServer` and `mpv` to function. 
You don't need to download them manually. When you start the application for the first time, it will automatically download the necessary binaries into the configuration folder (`%LOCALAPPDATA%\Pirate Cinema\vendor\` on Windows or `~/.local/share/Pirate Cinema/vendor/` on Linux).

### Getting Started
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the application:
   ```bash
   python -m run
   ```

### Architecture
- **Backend:** FastAPI (Python) handles the API routes and manages background processes (TorrServer).
- **Frontend:** Pure HTML/JS/CSS, rendered via PyWebView.
- **Player:** MPV handles video playback.

### Version
**v0.0.6**

---

## Русская версия

Pirate Cinema — это минималистичное десктопное приложение для мгновенного поиска и стриминга фильмов и сериалов через торренты без предварительного скачивания. 

Это **Python-реворк** оригинального проекта на Rust от cyberboy1999: [https://github.com/cyberboy1999/pirate-cinema](https://github.com/cyberboy1999/pirate-cinema).

### Основные возможности
- **Мгновенный стриминг:** Смотрите торренты сразу же с помощью встроенного плеера MPV.
- **Интеграция TorrServer:** Использует TorrServer для обработки торрент-протокола в фоне.
- **Поиск и Каталог:** Удобный поиск по базе TMDB (Cinemeta) и автоматический подбор раздач (Jackett / Rutor).
- **Библиотека:** Сохраняйте историю просмотров, чтобы продолжить с того же места, а также откладывайте торренты на потом.
- **Нативное окно:** Работает как легковесное приложение рабочего стола на базе WebView2 (через `pywebview`) или GTK/WebKit на Linux.
- **Никаких сложных сборок:** Фронтенд написан на чистом JS и CSS — никаких React, бандлеров и node_modules.

### Требования
- Windows 10/11 или Linux (Ubuntu)
- Python 3.12+
- WebView2 Runtime (По умолчанию встроен в Windows 11)

### Автоматическая загрузка компонентов
Вам не нужно скачивать дополнительные плееры и сервера вручную. При первом запуске приложение **автоматически скачает** необходимые бинарники (MPV для Windows и TorrServer) в папку конфигурации (`%LOCALAPPDATA%\Pirate Cinema\vendor\` на Windows или `~/.local/share/Pirate Cinema/vendor/` на Linux).

### Запуск из исходников
1. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
2. Запустите приложение:
   ```bash
   python -m run
   ```

### Архитектура
- **Бэкенд:** FastAPI (Python) обрабатывает API запросы и управляет фоновыми процессами (TorrServer, MPV).
- **Фронтенд:** Чистый HTML/JS/CSS, рендерится через PyWebView.
- **Плеер:** MPV обеспечивает плавное воспроизведение видео.

### Версия
**v0.0.6**
