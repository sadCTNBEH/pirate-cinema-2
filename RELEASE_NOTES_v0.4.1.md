# Pirate Cinema 2 — v0.4.1

**30 октября 2026 / October 30, 2026** · Обновление с / Upgrade from **v0.4.0** · **1 коммит / 1 commit**

[Русский](#русский) · [English](#english) · [Полный список коммитов / Full changelog](https://github.com/sadCTNBEH/pirate-cinema-2/compare/v0.4.0...v0.4.1)

---

## Русский

**Обновление поиска, фильтрации и интеграции с аниме-сервисами.** Закреплённая строка поиска, опциональный вывод аниме под отдельным переключателем, сквозные фильтры для всех категорий результатов, настраиваемые ключи YummyAnime API и исправления линтера.

### Главное

- **Строка поиска и фильтры всегда под рукой.** Панель поиска с фильтрами зафиксирована вверху экрана (`sticky`), оставаясь доступной при прокрутке любых объёмов результатов.
- **Аниме под отдельным чекбоксом.** Результаты аниме больше не смешиваются с основным каталогом и включаются отдельным тумблером (по аналогии с Rutube).
- **Сквозные фильтры для всех источников.** Фильтрация по сезонам, озвучке, качеству и языку работает согласованно для торрент-раздач, онлайн-видео Rutube и тайтлов аниме.
- **Настройка ключей YummyAnime API.** В настройках появились поля для указания публичного и приватного ключей с сохранением рабочего ключа проекта по умолчанию.
- **Чистый код и исправления.** Исправлены скрытые ошибки метаданных, устранены все замечания `ruff`, обновлена сборка фронтенда.

### Скачать v0.4.1

| Платформа | Сборка | Ссылка |
| --- | --- | --- |
| Windows | Установщик (`.exe`) | [Скачать установщик](https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/v0.4.1/pirate-cinema-installer.exe) |
| Windows | Портативная (`.exe`) | [Скачать портативную версию](https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/v0.4.1/pirate-cinema-portable.exe) |
| Linux | Архив (`.tar.gz`) | [Скачать архив](https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/v0.4.1/pirate-cinema-linux.tar.gz) |
| Linux | Портативная | [Скачать портативную сборку](https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/v0.4.1/pirate-cinema-portable-linux) |

[Страница релиза и все файлы](https://github.com/sadCTNBEH/pirate-cinema-2/releases/tag/v0.4.1)


### Интерфейс и поиск

- Панель поиска и параметров фильтрации перенесена в начало страницы и закреплена в верхней части рабочей области (`sticky header` с эффектом размытия фона и плавной тенью).
- Добавлен переключатель «Искать аниме» рядом с переключателем Rutube. По умолчанию поиск по аниме выключен, благодаря чему основной каталог фильмов и сериалов остаётся чистым.
- Карточки найденного аниме и видео с Rutube выводятся в собственных независимых секциях с счётчиком совпадений.

### Фильтры результатов

- **Фильтр по сезону:** отсекает нерелевантные сезоны не только в торрентах, но и в сериях Rutube и сезонах аниме.
- **Фильтр по озвучке:** собирает варианты озвучек из названий раздач, видео Rutube и переводов YummyAnime (`translations`), позволяя отфильтровать нужную студию дубляжа по всем источникам сразу.
- **Фильтры качества и языка:** поддерживают проверку разрешения и языковых дорожек для потоковых видео и аниме.
- **Сортировка:** для аниме адаптирована сортировка по рейтингу, году выхода и числу серий; для Rutube — по длительности видео.

### Настройки YummyAnime API

- Добавлен раздел «YummyAnime API» в окно настроек (`SettingsView`).
- Добавлены поля для публичного ключа приложения (`X-Application`) и приватного секретного ключа (`Secret`).
- Текущий ключ проекта (`bz7uk_nr9bouyrn9`) зашит в качестве значения по умолчанию.
- Адаптер `YummyAnimeProvider` динамически считывает ключи из настроек без необходимости перезапускать клиент.

### Стабильность и качество кода

- Устранена ошибка в сервисе метаданных, связанная с необъявленным аргументом `refresh`.
- Выполнена полная проверка и очистка кодовой базы через `ruff check . --fix` (устранены B008, C408, UP031, неиспользуемые распакованные переменные и некорректные перехваты исключений).
- Успешно пройдены проверки TypeScript (`tsc --noEmit`), тесты бэкенда (`pytest`) и регрессионные тесты фронтенда.

---

## English

**Search, filtering, and anime integration improvements.** A sticky search and filter bar, optional anime search toggle, unified cross-source filters, configurable YummyAnime API credentials, and linter cleanups.

### Highlights

- **Search bar and filters always accessible.** The search controls and filter panel are now pinned to the top of the viewport (`sticky`), staying in view while scrolling through results.
- **Anime under a dedicated toggle.** Anime catalog results no longer clutter general movie and series results; they are enabled via a toggle switch (matching Rutube).
- **Cross-source filtering.** Season, voiceover/dubbing, quality, and language filters apply consistently to torrents, Rutube online videos, and anime.
- **YummyAnime API settings.** Added settings fields for public and private application keys, with the project's current key built-in as the default.
- **Cleaner code and bug fixes.** Fixed an unhandled metadata refresh bug, resolved all `ruff` linter issues, and refreshed production frontend assets.

### Download v0.4.1

| Platform | Package | Link |
| --- | --- | --- |
| Windows | Installer (`.exe`) | [Download installer](https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/v0.4.1/pirate-cinema-installer.exe) |
| Windows | Portable (`.exe`) | [Download portable version](https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/v0.4.1/pirate-cinema-portable.exe) |
| Linux | Archive (`.tar.gz`) | [Download archive](https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/v0.4.1/pirate-cinema-linux.tar.gz) |
| Linux | Portable | [Download portable build](https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/v0.4.1/pirate-cinema-portable-linux) |

[Release page and all assets](https://github.com/sadCTNBEH/pirate-cinema-2/releases/tag/v0.4.1)


### Interface and search

- The search input and filter controls are moved to the top of the page and pinned (`sticky header` with background blur and elevation shadow).
- Added an "Search anime" toggle next to the Rutube toggle. Anime search is disabled by default, keeping standard catalog search clean.
- Matched anime cards and Rutube videos render in their own dedicated sections with result counters.

### Result filtering

- **Season filter:** Filters out mismatched seasons across torrents, Rutube video titles, and anime entries.
- **Voiceover filter:** Dynamically aggregates translations and dubbing studios from torrents, Rutube titles, and YummyAnime translations (`translations`), filtering all sources simultaneously.
- **Quality and language filters:** Accurately match video resolution markers and language tracks for streaming sources and anime.
- **Sorting:** Anime results sort by rating, release year, or episode count; Rutube results sort by duration.

### YummyAnime API settings

- Added a dedicated "YummyAnime API" section in Settings.
- Added inputs for the public application key (`X-Application`) and private key (`Secret`).
- The project's existing key (`bz7uk_nr9bouyrn9`) is configured as the default.
- `YummyAnimeProvider` reads credentials directly from settings without requiring an app restart.

### Reliability and code quality

- Fixed an undefined `refresh` argument bug in the metadata pipeline.
- Resolved all issues detected by `ruff check . --fix` (B008, C408, UP031, unused variables, and blind exception handling).
- Verified TypeScript compilation (`tsc --noEmit`), backend pytest suites, and frontend regression test suites.

---

<details>
<summary><strong>Проверки перед выпуском / Release validation</strong></summary>

| Проверка / Check | Результат / Result |
| --- | --- |
| Linter — `ruff check . --fix` | **All checks passed!** |
| TypeScript — `tsc --noEmit` | **Passed (0 errors)** |
| Frontend production build (`vite build`) | **Passed** |
| Frontend regression tests (`tsx --test`) | **33 passed** |
| Anime & YummyAnime catalog tests | **17 passed** |
| YummyAnime API key persistence & defaults | **Verified** |
| Sticky search bar & multi-source filtering | **Verified** |

</details>

<details>
<summary><strong>Коммиты после v0.4.0 / Commits since v0.4.0</strong></summary>

| Коммит / Commit | Изменения / Changes |
| --- | --- |
| `ff1ff4e` | Закреплённая строка поиска, фильтрация аниме/Rutube, настройки YummyAnime API, ruff fix и v0.4.1 / Sticky search bar, anime filter toggle, yummyanime api settings, ruff fix and v0.4.1 |

</details>

**Tag:** [`v0.4.1`](https://github.com/sadCTNBEH/pirate-cinema-2/releases/tag/v0.4.1) · **Commit:** [`ff1ff4e`](https://github.com/sadCTNBEH/pirate-cinema-2/commit/ff1ff4e9f516850bf8a5f56426ebe855573c855b)
