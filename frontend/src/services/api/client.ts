/**
 * @file services/api/client.ts
 * @description Базовый HTTP-клиент для прямого взаимодействия с FastAPI бэкендом.
 * Включает безопасную обработку HTML-ответов от Vite SPA в dev-режиме,
 * предотвращая ошибку SyntaxError: Unexpected token '<'.
 */

/**
 * Базовые системные строки интерфейса на случай,
 * если бэкенд FastAPI еще не запущен в окружении предварительного просмотра.
 */
export const DEFAULT_FALLBACK_STRINGS: Record<string, string> = {
  nav_catalog: 'Рекомендации',
  nav_search: 'Поиск',
  nav_online: 'Онлайн-видео',
  online_playlists: 'Онлайн-плейлисты',
  nav_library: 'Библиотека',
  nav_collections: 'Избранное',
  nav_watch_later: 'Позже',
  nav_history: 'История',
  history: 'История просмотра',
  history_empty: 'История просмотра пока пуста',
  mark_watched: 'Отметить просмотренным',
  delete_history_entry: 'Удалить эпизод из истории',
  favorites: 'Избранное',
  watch_later: 'Посмотреть позже',
  add_to_favorites: 'В избранное',
  remove_from_favorites: 'Убрать из избранного',
  add_to_watch_later: 'Посмотреть позже',
  remove_from_watch_later: 'Убрать из списка',
  collections_empty: 'В этой подборке пока нет фильмов и сериалов',
  nav_settings: 'Настройки',
  ts_active: 'TorrServer в сети',
  ts_inactive: 'TorrServer офлайн',
  ts_checking: 'Пинг...',
  ts_check_error: 'Ошибка связи',
  popular_movies: 'Популярные фильмы',
  popular_series: 'Популярные сериалы',
  series_plural: 'Сериалы',
  continue_watching: 'Продолжить просмотр',
  search_placeholder: 'Поиск по фильмам, сериалам или трекерам...',
  search_btn: 'Искать',
  seeders: 'сидов',
  play: 'Воспроизвести',
  watch: 'Смотреть',
  continue: 'Далее',
  back: 'Назад',
  delete_selected: 'Удалить выбранные',
  delete_all: 'Удалить всё',
  library_empty: 'В библиотеке пока нет раздач',
  nothing_found: 'Ничего не найдено',
  nothing_found_try_another: 'Попробуйте изменить поисковый запрос',
  season_not_found: 'Раздачи для выбранного сезона не найдены',
  all_voiceovers: 'Все озвучки',
  searching_torrents: 'Идет поиск раздач...',
  searching: 'Идет поиск...',
  loading_files_dht: 'Подключение к DHT и получение файлов...',
  dead_torrent_warning: 'Торрент не отвечает (нет активных сидов)',
  try_again: 'Повторить попытку',
  save_settings: 'Сохранить настройки',
  test_connection: 'Проверить соединение',
  check_updates: 'Проверить обновления',
  open_data_folder: '📂 Открыть папку данных',
  refresh_system: 'Опросить систему',
  diagnostics: 'Диагностика',
  nav_diagnostics: 'Диагностика',
  system_diagnostics: 'Диагностика системы',
  status_healthy: 'Работает',
  status_degraded: 'Есть проблемы',
  status_unhealthy: 'Не удалось проверить',
  last_checked: 'Последняя проверка',
  refresh_diagnostics: 'Обновить',
  copy_report: 'Скопировать отчёт',
  report_copied: 'Отчёт скопирован в буфер обмена',
  report_copy_failed: 'Не удалось скопировать отчёт',
  recent_errors: 'Последние ошибки',
  no_recent_errors: 'Ошибок не зарегистрировано',
  diag_load_error: 'Не удалось получить данные диагностики',
  diag_load_error_hint: 'Проверьте подключение к приложению и попробуйте обновить данные.',
  diag_stale_warning: 'Отображаются устаревшие данные от {time}',
  free_space: 'Свободно',
  used_space: 'Занято',
  total_space: 'Всего',
  data_dir: 'Каталог данных',
  status_running: 'Работает',
  status_stopped: 'Не запущен',
  status_available: 'Доступен',
  status_not_found: 'Не найден',
  status: 'Статус',
  db_size_label: 'Размер базы',
  remote: 'Пульт',
  pid: 'PID',
  port: 'Порт',
  version: 'Версия',
  path: 'Путь к файлу',
  overall_status: 'Общее состояние',
  disk_status: 'Дисковое пространство',
  app_version: 'Версия',
  response_time: 'Ответ',
  collapse: 'Свернуть',
  expand: 'Развернуть',
  latest_version_installed: 'Установлена последняя версия',
  update_available: 'Доступно обновление: {version}',
  saved: 'Настройки сохранены',
  checking: 'Проверка...',
  ts_available: 'TorrServer доступен',
  ts_unavailable: 'TorrServer недоступен',
  confirm_delete_from_ts: 'Удалить эту раздачу из TorrServer?',
  confirm_delete_multiple_ts: 'Удалить выбранные раздачи ({count} шт.)?',
  confirm_delete_all_ts: 'Удалить все сохраненные раздачи ({count} шт.)?',
  confirm_delete_history: 'Удалить запись из истории просмотров?',
  remove_from_history: 'Удалить из истории',
  select_torrents_to_delete: 'Выберите хотя бы одну раздачу',
  watched: 'Просмотрено',
  season_prefix: 'Сезон',
  episode: 'Серия',
  movies_outside_seasons: 'Фильмы / Спецвыпуски',
  language: 'Язык',
  russian: 'Русский',
  english: 'English',
  restore_backup: 'Восстановить бэкап',
  download_backup: 'Скачать бэкап',
  backup_saved: 'Бэкап сохранён: {path}',
  backup_cancelled: 'Сохранение бэкапа отменено',
  close_to_tray: 'Сворачивать в трей при закрытии',
  close_to_tray_hint: 'Действие можно изменить в любой момент.',
  debug_mode: 'Режим отладки (Debug Mode)',
  debug_mode_hint: 'Отображение технической информации, расширенной диагностики и характеристик видео.',
  advanced_settings: 'Дополнительные настройки',
  service_status: 'Статус служб',
  copy_error_report: 'Отчёт об ошибке',
  backup_restore: 'Резервное копирование и восстановление',
  backup_restore_hint: 'Сохранение и восстановление настроек, истории и базы данных.',
  video_player: 'Видеоплеер',
  confirm_restore: 'Восстановить конфигурацию из архива?',
  restore_success: 'Данные восстановлены',
  dubbing: 'Дубляж',
  prof: 'Профессиональный',
  amateur: 'Любительский',
  original: 'Оригинал',
  subtitles: 'Субтитры',
  unknown: 'Не указано',
  gb: 'ГБ',
  mb: 'МБ',
  kb: 'КБ',
  settings: 'Общие',
  general: 'Общие',
  jackett_hint: 'Для поиска торрентов по сторонним трекерам.',
  updates: 'Обновления',
  ts_version: 'Версия TorrServer',
  db_size: 'База данных',
  mpv_path: 'Путь к MPV',
  last_error: 'Последняя ошибка',
  no_errors: 'Ошибок нет',
  download: 'Скачать',
  check_error: 'Ошибка проверки',
  server_url: 'URL сервера',
  api_key: 'Ключ API',
  torznab_title: 'Torznab (Jackett / Prowlarr)',
  torznab_enabled: 'Включить Torznab',
  torznab_url: 'URL Torznab API',
  torznab_key: 'Ключ API Torznab',
  torznab_categories: 'Категории',
  filter_type: 'Тип',
  filter_status: 'Статус',
  filter_year: 'Год',
  filter_genre: 'Жанр',
  filter_sort: 'Сортировка',
  all: 'Все',
  all_types: 'Все типы',
  all_statuses: 'Все статусы',
  movie: 'Фильм',
  movies: 'Фильмы',
  series: 'Сериалы',
  unwatched: 'Не просмотрено',
  watching: 'Смотрю',
  completed: 'Завершено',
  planned: 'Запланировано',
  years_range: 'Годы',
  year_from: 'От',
  year_to: 'До',
  filter_genre_placeholder: 'Введите жанр...',
  apply: 'Применить',
  sort_title: 'Название',
  sort_year: 'Год',
  sort_added: 'Дата добавления',
  sort_progress: 'Прогресс',
  order_asc: 'По возрастанию',
  order_desc: 'По убыванию',
  reset: 'Сбросить',
  reset_all: 'Сбросить всё',
  active_filters: 'Активные фильтры',
  found_count: 'Найдено: {count}',
  library_items_count: 'Медиатека — {count}',
  no_results_filtered: 'Ничего не найдено',
  no_results_filtered_hint: 'Попробуйте изменить параметры фильтрации или сбросить фильтры.',
  reset_filters_btn: 'Сбросить фильтры',
  invalid_year_range: 'Год "От" не может быть больше года "До"',
  loading_more: 'Загрузка...',
  all_items_loaded: 'Все элементы загружены',
  next_episode: 'Следующая серия',
  no_unwatched: 'Все серии просмотрены',
  advanced_filters: 'Фильтры',
  reset_filters: 'Сбросить',
  sort_seeders: 'По сидам',
  sort_size: 'По размеру',
  sort_date: 'По дате',
  quality: 'Качество',
  hdr: 'HDR',
  dolby_vision: 'Dolby Vision',
  min_size: 'Размер от, ГБ',
  max_size: 'Размер до, ГБ',
  source: 'Источник',
  all_sources: 'Все источники',
  language_track: 'Язык дорожки',
  russian_track: 'Русский',
  english_track: 'Английский',
  original_track: 'Оригинал',
  add_to_playlist: 'В плейлист',
  auto_update_unsupported: 'Автоматическое обновление недоступно для этого типа установки',
  autostart: 'Автозапуск при старте Windows',
  autostart_enable: 'Включить автозапуск',
  autostart_hint: 'Запускать свёрнутым в трей при старте ПК.',
  autostart_modal_desc: 'Запускать Pirate Cinema автоматически при включении компьютера?',
  autostart_modal_title: 'Автозапуск при старте Windows',
  autostart_not_now: 'Не сейчас',
  cancel: 'Отмена',
  close: 'Закрыть',
  confirm_clear_online_history: 'Очистить историю онлайн-видео?',
  confirm_delete_playlist: 'Удалить этот плейлист?',
  create_playlist: 'Создать плейлист',
  delete: 'Удалить',
  delete_playlist: 'Удалить плейлист',
  download_update: 'Скачать обновление',
  downloading_update: 'Скачивание обновления...',
  install_and_restart: 'Установить и перезапустить',
  load_error: 'Ошибка загрузки',
  mpv_player: 'Видеоплеер (MPV)',
  no_items_in_playlist: 'В этом плейлисте пока нет видео',
  online_history: 'История',
  online_videos: 'Онлайн-видео',
  open_github_release: 'Открыть релиз на GitHub',
  playlist_title: 'Название плейлиста',
  playlists_empty: 'У вас пока нет сохранённых плейлистов',
  remove_from_playlist: 'Удалить',
  retry: 'Повторить',
  search_online_placeholder: 'Поиск видео на Rutube или прямая ссылка...',
  update_confirm_text: 'Для установки обновления приложение будет закрыто и перезапущено. Сохраните незавершённую работу.',
  update_confirm_title: 'Установка обновления',
  update_ready: 'Обновление загружено и проверено.',
  verifying_update: 'Проверка целостности файла (SHA-256)...',
  whats_new: 'Что нового:',
};

/**
 * Безопасный парсер ответа с защитой от возврата index.html вместо JSON
 */
export function parseJsonResponse<T>(text: string, endpoint: string): T {
  const trimmed = text.trim();

  // Если сервер вернул HTML (<!doctype... или <html>), значит эндпоинт не перехвачен бэкендом
  if (trimmed.startsWith('<')) {
    throw new Error(
      `Эндпоинт ${endpoint} вернул HTML вместо JSON. Убедитесь, что FastAPI сервер запущен.`
    );
  }

  if (!trimmed) {
    return {} as T;
  }

  try {
    return JSON.parse(trimmed);
  } catch (err: any) {
    throw new Error(`Ошибка парсинга JSON для ${endpoint}: ${err.message}`);
  }
}

/**
 * Базовый исполнитель HTTP-запросов к FastAPI
 */
export const httpClient = {
  /**
   * Выполнение GET запроса с валидацией JSON
   */
  async get<T = any>(
    path: string,
    options?: RequestInit & { onResponse?: (response: Response) => void }
  ): Promise<T> {
    const { onResponse, ...request } = options || {};
    const res = await fetch(path, request);
    onResponse?.(res);
    const text = await res.text().catch(() => '');
    if (!res.ok) {
      let errMsg = text || res.statusText;
      try {
        const json = JSON.parse(text);
        if (json.detail) errMsg = json.detail;
      } catch {}
      throw new Error(errMsg);
    }
    return parseJsonResponse<T>(text, path);
  },

  /**
   * Скачивание резервной копии ZIP
   */
  async downloadBackup(): Promise<Blob> {
    const path = '/api/settings/backup';
    const res = await fetch(path, { headers: { Accept: 'application/zip' } });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      let message = text || res.statusText;
      try {
        const payload = JSON.parse(text);
        if (payload.detail) message = payload.detail;
      } catch {}
      throw new Error(message);
    }
    return res.blob();
  },

  /**
   * Выполнение POST запроса с телом JSON
   */
  async post<T = any>(
    path: string,
    body: any = {},
    options: { signal?: AbortSignal } = {}
  ): Promise<T> {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: options.signal,
    });
    const text = await res.text().catch(() => '');
    if (!res.ok) {
      let errMsg = text || res.statusText;
      try {
        const json = JSON.parse(text);
        if (json.detail) errMsg = json.detail;
      } catch {}
      throw new Error(errMsg);
    }
    return parseJsonResponse<T>(text, path);
  },

  /** Выполнение PUT запроса с телом JSON */
  async put<T = any>(path: string, body: any): Promise<T> {
    const res = await fetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const text = await res.text().catch(() => '');
    if (!res.ok) {
      let errMsg = text || res.statusText;
      try {
        const json = JSON.parse(text);
        if (json.detail) errMsg = json.detail;
      } catch {}
      throw new Error(errMsg);
    }
    return parseJsonResponse<T>(text, path);
  },

  /** Выполнение PATCH запроса с телом JSON */
  async patch<T = any>(path: string, body: any): Promise<T> {
    const res = await fetch(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const text = await res.text().catch(() => '');
    if (!res.ok) {
      let errMsg = text || res.statusText;
      try {
        const json = JSON.parse(text);
        if (json.detail) errMsg = json.detail;
      } catch {}
      throw new Error(errMsg);
    }
    return parseJsonResponse<T>(text, path);
  },

  /**
   * Выполнение DELETE запроса
   */
  async del<T = any>(path: string): Promise<T> {
    const res = await fetch(path, { method: 'DELETE' });
    const text = await res.text().catch(() => '');
    if (!res.ok) {
      let errMsg = text || res.statusText;
      try {
        const json = JSON.parse(text);
        if (json.detail) errMsg = json.detail;
      } catch {}
      throw new Error(errMsg);
    }
    if (!text || text.trim().length === 0) {
      return {} as T;
    }
    return parseJsonResponse<T>(text, path);
  },
};
