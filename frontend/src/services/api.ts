/**
 * @file services/api.ts
 * @description Чистый HTTP-клиент для прямого взаимодействия с FastAPI бэкендом.
 * Включает безопасную обработку HTML-ответов от Vite SPA в dev-режиме,
 * предотвращая ошибку SyntaxError: Unexpected token '<'.
 */

import {
  ServerStatus,
  SystemSettings,
  SystemDiagnostics,
  DiagnosticsResponse,
  TorrServerDiagnostics,
  MPVDiagnostics,
  DiskDiagnostics,
  DatabaseDiagnostics,
  DiagnosticError,
  UpdateInfo,
  RecentItem,
  MediaItem,
  MediaDetail,
  TorrentResult,
  SearchFilters,
  LibraryTorrent,
  TorrentFilesResponse,
  LibraryFilter,
  LibraryItem,
  LibraryProgressResponse,
  NextUnwatchedResponse,
  HistoryItem,
  CollectionItem,
  CollectionName,
  BackendActivePlayerStatus,
  OnlineSearchResult,
  OnlinePlaylist,
  OnlineHistoryItem,
  PlayOnlineResponse,
  MarkWatchedPayload,
  UpdateCheckResponse,
  UpdateStatusResponse,
  UpdateActionResponse,
} from '../types';

/**
 * Базовые системные строки интерфейса на случай,
 * если бэкенд FastAPI еще не запущен в окружении предварительного просмотра.
 */
export const DEFAULT_FALLBACK_STRINGS: Record<string, string> = {
  nav_catalog: 'Популярное',
  nav_search: 'Поиск',
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
  db_size_label: 'Размер базы',
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
};

/**
 * Безопасный парсер ответа с защитой от возврата index.html вместо JSON
 */
function parseJsonResponse<T>(text: string, endpoint: string): T {
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
export const API = {
  /**
   * Выполнение GET запроса с валидацией JSON
   */
  async get<T = any>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(path, options);
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

  /* ── Типизированные методы API для модулей ── */

  /** Загрузка словаря локализации и текущего языка из FastAPI */
  async getI18n(): Promise<{ strings: Record<string, string>; lang: string }> {
    try {
      const data = await this.get<{ strings: Record<string, string>; lang: string }>('/api/i18n');
      if (data && data.strings) return data;
      return { strings: DEFAULT_FALLBACK_STRINGS, lang: 'ru' };
    } catch {
      return { strings: DEFAULT_FALLBACK_STRINGS, lang: 'ru' };
    }
  },

  /** Получение состояния демона TorrServer */
  async getServerStatus(): Promise<ServerStatus> {
    try {
      return await this.get<ServerStatus>('/api/settings/status');
    } catch {
      return { active: false, message: 'Офлайн' };
    }
  },

  /** Получение текущих настроек (TorrServer, Jackett, язык) */
  async getSettings(): Promise<SystemSettings> {
    try {
      return await this.get<SystemSettings>('/api/settings');
    } catch {
      return {
        torrserver_url: 'http://127.0.0.1:8090',
        language: 'ru',
        jackett_url: 'http://127.0.0.1:9117/api/v2.0/indexers/all/results/torznab',
        jackett_api_key: '',
      };
    }
  },

  /** Обновление настроек */
  async updateSettings(settings: Partial<SystemSettings>): Promise<any> {
    try {
      return await this.post('/api/settings', settings);
    } catch (e) {
      console.warn('updateSettings warn:', e);
      return { success: true };
    }
  },

  /** Сохранение настроек (псевдоним updateSettings) */
  async saveSettings(settings: Partial<SystemSettings>): Promise<any> {
    return this.updateSettings(settings);
  },

  /** Проверка наличия обновлений репозитория */
  async checkUpdates(): Promise<UpdateInfo> {
    try {
      return await this.get<UpdateInfo>('/api/settings/updates');
    } catch {
      return {
        has_update: false,
        latest: 'v2.0.0',
        url: '',
      };
    }
  },

  /** Получение системной диагностики (TorrServer, MPV, размер БД) */
  async getDiagnostics(): Promise<SystemDiagnostics> {
    try {
      return await this.get<SystemDiagnostics>('/api/settings/diagnostics');
    } catch {
      return {
        torrserver_version: 'Офлайн',
        mpv_path: 'Офлайн',
        db_size: 0,
        last_error: null,
      };
    }
  },

  /** Получение полной системной диагностики (GET /api/diagnostics) - TASK-003/003.1 */
  async getSystemDiagnostics(signal?: AbortSignal): Promise<DiagnosticsResponse> {
    return await this.get<DiagnosticsResponse>('/api/diagnostics', { signal });
  },

  /** Проверка здоровья сервисов */
  async checkHealth(): Promise<{ error?: string }> {
    try {
      return await this.get<{ error?: string }>('/api/settings/health');
    } catch {
      return {};
    }
  },

  /** Запрос к бэкенду на открытие папки с данными в проводнике */
  async openFolder(): Promise<void> {
    try {
      await fetch('/api/settings/open_folder', { method: 'POST' });
    } catch {
      // Игнорируем в автономном режиме
    }
  },

  /** Загрузка недавних просмотров ("Продолжить просмотр") */
  async getRecent(): Promise<RecentItem[]> {
    try {
      const data = await this.get<RecentItem[]>('/api/history/continue');
      if (Array.isArray(data) && data.length > 0) return data;
      const fallback = await this.get<RecentItem[]>('/api/library/recent');
      return Array.isArray(fallback) ? fallback : [];
    } catch {
      return [];
    }
  },

  async getContinueWatching(): Promise<RecentItem[]> {
    return this.getRecent();
  },

  /** Удаление элемента из истории просмотров */
  async removeHistory(hash: string): Promise<void> {
    return this.del(`/api/library/history/${hash}`);
  },

  async getHistory(): Promise<HistoryItem[]> {
    const data = await this.get<HistoryItem[]>('/api/history');
    return Array.isArray(data) ? data : [];
  },

  async markHistoryWatched(hash: string, fileIndex: number): Promise<void> {
    await this.post(`/api/history/${encodeURIComponent(hash)}/${fileIndex}/watched`);
  },

  async markWatched(payload: MarkWatchedPayload): Promise<void> {
    await this.post('/api/history/mark-watched', payload);
  },

  async deleteHistoryEntry(hash: string, fileIndex: number): Promise<void> {
    try {
      await this.del(`/api/history/${encodeURIComponent(hash)}/${fileIndex}`);
    } catch (err: any) {
      if (err?.status === 404 || err?.message?.includes('not found')) {
        return;
      }
      throw err;
    }
  },

  async deleteHistoryById(id: string): Promise<void> {
    try {
      await this.del(`/api/history/${encodeURIComponent(id)}`);
    } catch (err: any) {
      if (err?.status === 404 || err?.message?.includes('not found')) {
        return;
      }
      throw err;
    }
  },

  /** Загрузка каталога популярных фильмов или сериалов */
  async getPopular(type: 'movies' | 'series'): Promise<MediaItem[]> {
    try {
      const endpoint = type === 'series' ? '/api/library/popular/series' : '/api/library/popular';
      const data = await this.get<MediaItem[]>(endpoint);
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  },

  /** Загрузка метаданных кинокартины по IMDb */
  async getMeta(imdb: string, type: 'movie' | 'series'): Promise<MediaDetail> {
    return this.get<MediaDetail>(`/api/library/meta/${imdb}?type=${type}`);
  },

  /** Поиск метаданных по названию */
  async searchMeta(query: string): Promise<any[]> {
    try {
      const data = await this.get<any[]>(`/api/library/meta/search?q=${encodeURIComponent(query)}`);
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  },

  /** Поиск торрентов через Jackett / TorrServer / Torznab */
  async searchTorrents(
    query: string,
    quality?: string,
    min_seeders?: number,
    advanced: SearchFilters = {}
  ): Promise<TorrentResult[]> {
    const params = new URLSearchParams({ q: query });
    const effectiveQuality = advanced.quality || quality;
    if (effectiveQuality) params.set('quality', effectiveQuality);
    if (min_seeders !== undefined && min_seeders !== null) {
      params.set('min_seeders', String(min_seeders));
    }
    if (advanced.language && advanced.language !== 'all') params.set('language', advanced.language);
    if (advanced.minSizeGb !== undefined && advanced.minSizeGb >= 0) {
      params.set('min_size', String(Math.round(advanced.minSizeGb * 1024 ** 3)));
    }
    if (advanced.maxSizeGb !== undefined && advanced.maxSizeGb >= 0) {
      params.set('max_size', String(Math.round(advanced.maxSizeGb * 1024 ** 3)));
    }
    const data = await this.get<TorrentResult[]>(`/api/search?${params.toString()}`);
    return Array.isArray(data) ? data : [];
  },

  /** Загрузка элементов библиотеки с фильтрацией, сортировкой и общим числом результатов (TASK-006 / TASK-006.1) */
  async getLibraryWithCount(
    filters?: LibraryFilter,
    options?: { signal?: AbortSignal }
  ): Promise<{ items: LibraryItem[]; totalCount: number }> {
    const params = new URLSearchParams();
    if (filters?.type) params.set('type', filters.type);
    if (filters?.status) params.set('status', filters.status);
    if (filters?.year !== undefined && filters?.year !== null && !isNaN(filters.year)) {
      params.set('year', String(filters.year));
    }
    if (filters?.year_from !== undefined && filters?.year_from !== null && !isNaN(filters.year_from)) {
      params.set('year_from', String(filters.year_from));
    }
    if (filters?.year_to !== undefined && filters?.year_to !== null && !isNaN(filters.year_to)) {
      params.set('year_to', String(filters.year_to));
    }
    if (filters?.genre) params.set('genre', filters.genre);
    if (filters?.sort) params.set('sort', filters.sort);
    if (filters?.order) params.set('order', filters.order);
    if (filters?.limit !== undefined && filters?.limit !== null && !isNaN(filters.limit)) {
      params.set('limit', String(filters.limit));
    }
    if (filters?.offset !== undefined && filters?.offset !== null && !isNaN(filters.offset)) {
      params.set('offset', String(filters.offset));
    }
    const qs = params.toString();
    const endpoint = qs ? `/api/library?${qs}` : '/api/library';
    const res = await fetch(endpoint, { signal: options?.signal });
    const text = await res.text().catch(() => '');
    if (!res.ok) {
      let errMsg = text || res.statusText;
      try {
        const json = JSON.parse(text);
        if (json.detail) errMsg = json.detail;
      } catch {
        // ignore JSON parse failure
      }
      throw new Error(errMsg);
    }
    const items = parseJsonResponse<LibraryItem[]>(text, endpoint);
    const countHeader = res.headers.get('x-total-count');
    const parsedCount = countHeader ? parseInt(countHeader, 10) : (Array.isArray(items) ? items.length : 0);
    return {
      items: Array.isArray(items) ? items : [],
      totalCount: isNaN(parsedCount) ? 0 : parsedCount,
    };
  },

  /** Загрузка элементов библиотеки с фильтрацией и сортировкой (TASK-006) */
  async getLibrary(filters?: LibraryFilter, options?: { signal?: AbortSignal }): Promise<LibraryItem[]> {
    const res = await this.getLibraryWithCount(filters, options);
    return res.items;
  },

  async getCollection(listName: CollectionName): Promise<CollectionItem[]> {
    const data = await this.get<CollectionItem[]>(`/api/collections/${listName}`);
    return Array.isArray(data) ? data : [];
  },

  async getCollectionMembership(mediaId: string): Promise<Record<CollectionName, boolean>> {
    return this.get<Record<CollectionName, boolean>>(
      `/api/collections/membership/${encodeURIComponent(mediaId)}`
    );
  },

  async saveCollectionItem(listName: CollectionName, item: CollectionItem): Promise<void> {
    await this.put(`/api/collections/${listName}/${encodeURIComponent(item.media_id)}`, item);
  },

  async removeCollectionItem(listName: CollectionName, mediaId: string): Promise<void> {
    await this.del(`/api/collections/${listName}/${encodeURIComponent(mediaId)}`);
  },

  /** Загрузка структуры прогресса сезонов и серий торрента */
  async getLibraryProgress(hash: string): Promise<LibraryProgressResponse> {
    return this.get<LibraryProgressResponse>(`/api/library/${hash}/progress`);
  },

  /** Загрузка следующей непросмотренной серии для автозапуска */
  async getNextUnwatched(
    targetOrParams:
      | string
      | { imdb_id?: string; season?: number; title_id?: string; torrent_hash?: string }
  ): Promise<NextUnwatchedResponse | null> {
    if (typeof targetOrParams === 'string') {
      try {
        return await this.get<NextUnwatchedResponse>(`/api/library/${encodeURIComponent(targetOrParams)}/next-unwatched`);
      } catch {
        return null;
      }
    }
    const query = new URLSearchParams();
    if (targetOrParams.imdb_id) query.set('imdb_id', targetOrParams.imdb_id);
    if (targetOrParams.season !== undefined) query.set('season', String(targetOrParams.season));
    if (targetOrParams.title_id) query.set('title_id', targetOrParams.title_id);
    if (targetOrParams.torrent_hash) query.set('torrent_hash', targetOrParams.torrent_hash);
    try {
      const res = await this.get<NextUnwatchedResponse>(`/api/history/next-unwatched?${query.toString()}`);
      return res && (res.episode !== undefined || res.next_episode !== undefined) ? res : null;
    } catch {
      return null;
    }
  },

  /** Загрузка списка сохраненных торрентов в библиотеке TorrServer */
  async getLibraryTorrents(): Promise<{ torrents: LibraryTorrent[] }> {
    try {
      const data = await this.get<any>('/api/library/torrents');
      if (data && Array.isArray(data.torrents)) return data;
      if (data && Array.isArray(data.Torrents)) return { torrents: data.Torrents };
      return { torrents: [] };
    } catch {
      return { torrents: [] };
    }
  },

  /** Удаление торрента из базы TorrServer */
  async deleteTorrent(hash: string): Promise<void> {
    if (hash.startsWith('online:')) {
      return this.del(`/api/library/torrents/${encodeURIComponent(hash)}`).catch(() => {});
    }
    return this.del(`/api/player/torrent/${hash}`);
  },

  /** Загрузка файловой структуры торрента из TorrServer */
  async getTorrentFiles(hash: string, title?: string): Promise<TorrentFilesResponse> {
    if (hash.startsWith('online:')) {
      return {
        type: 'movie',
        movies: [{ id: 0, name: title || 'Онлайн-видео', length: 0 }],
        flat_files: [{ id: 0, name: title || 'Онлайн-видео', length: 0 }],
      };
    }
    const q = title ? `?title=${encodeURIComponent(title)}` : '';
    return this.get<TorrentFilesResponse>(`/api/library/torrents/${hash}/files${q}`);
  },

  /** Добавление magnet-ссылки в TorrServer */
  async addMagnet(magnet: string, title: string): Promise<{ hash: string }> {
    return this.post<{ hash: string }>('/api/player/add_magnet', { magnet, title });
  },

  /** Алиас: добавление торрента */
  async addTorrent(magnet: string, title: string): Promise<{ hash: string }> {
    return this.addMagnet(magnet, title);
  },

  /** Алиас: получение сохраненных торрентов */
  async getTorrents(): Promise<LibraryTorrent[]> {
    const res = await this.getLibraryTorrents();
    return res.torrents || [];
  },

  /** Алиас: удаление торрента */
  async remTorrent(hash: string): Promise<void> {
    return this.deleteTorrent(hash);
  },

  /** Удаление нескольких торрентов */
  async deleteMultipleTorrents(hashes: string[]): Promise<void> {
    for (const h of hashes) {
      await this.deleteTorrent(h).catch(() => {});
    }
  },

  /** Удаление всех торрентов библиотеки */
  async deleteAllTorrents(hashes?: string[]): Promise<void> {
    let targetHashes = hashes;
    if (!targetHashes || targetHashes.length === 0) {
      const list = await this.getTorrents();
      targetHashes = list.map((item) => item.hash);
    }
    for (const h of targetHashes) {
      if (h) {
        await this.deleteTorrent(h).catch(() => {});
      }
    }
    await this.del('/api/library/torrents').catch(() => {});
  },

  /** Алиас: поиск метаданных по названию */
  async searchMedia(query: string): Promise<any[]> {
    return this.searchMeta(query);
  },

  /** Запуск файла через плеер MPV */
  async playFile(payload: {
    hash: string;
    file_id: number;
    file_name: string;
    start_time?: number;
  }): Promise<void> {
    return this.post('/api/player/play', payload);
  },

  /** Переключение на следующий файл раздачи в MPV */
  async playNext(payload: { hash: string; file_id: number }): Promise<void> {
    return this.post('/api/player/next', payload);
  },

  /** Остановка воспроизведения в MPV */
  async stopPlayback(): Promise<void> {
    await this.hidePlayerPanel();
    return this.post('/api/player/stop', {});
  },

  /** Получение текущего состояния активного плеера MPV */
  async getActivePlayback(): Promise<BackendActivePlayerStatus> {
    try {
      return await this.get<BackendActivePlayerStatus>('/api/player/active');
    } catch {
      return { active: false };
    }
  },

  /** Переключение полноэкранного режима встроенного плеера */
  async togglePlayerFullscreen(fullscreen?: boolean): Promise<boolean> {
    try {
      const q = fullscreen !== undefined ? `?fullscreen=${fullscreen}` : '';
      const res = await this.post<{ is_fullscreen: boolean }>(`/api/player/fullscreen${q}`, {});
      return !!res.is_fullscreen;
    } catch {
      if (window.pywebview?.api?.toggle_fullscreen) {
        return !!(await window.pywebview.api.toggle_fullscreen());
      }
      return false;
    }
  },

  /** Отправка произвольной IPC-команды в MPV (пауза, перемотка, громкость и т.д.) */
  async sendPlayerCommand(command: any[]): Promise<boolean> {
    try {
      await fetch('/api/player/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(command),
      });
      return true;
    } catch {
      return false;
    }
  },

  _isBoundsUpdating: false,

  /** Синхронизация координат нативной панели MPV с DOM-контейнером */
  async setPlayerBounds(bounds: {
    x: number;
    y: number;
    width: number;
    height: number;
    viewport_width: number;
    viewport_height: number;
    clip_top: number;
    clip_left: number;
    clip_right: number;
    clip_bottom: number;
  }): Promise<void> {
    try {
      if (window.pywebview?.api?.set_player_bounds) {
        await window.pywebview.api.set_player_bounds(
          bounds.x,
          bounds.y,
          bounds.width,
          bounds.height,
          bounds.viewport_width,
          bounds.viewport_height,
          bounds.clip_top,
          bounds.clip_left,
          bounds.clip_right,
          bounds.clip_bottom
        );
        return;
      }
      if (this._isBoundsUpdating) return;
      this._isBoundsUpdating = true;
      await fetch('/api/window/player_bounds', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bounds),
      });
    } catch {
      // Игнорируем в браузерном превью
    } finally {
      this._isBoundsUpdating = false;
    }
  },

  /** Скрытие нативной панели встроенного плеера */
  async hidePlayerPanel(): Promise<void> {
    try {
      if (window.pywebview?.api?.hide_player_panel) {
        await window.pywebview.api.hide_player_panel();
        return;
      }
      await fetch('/api/window/hide_player', { method: 'POST' });
    } catch {
      // Игнорируем в браузерном превью
    }
  },

  /** Загрузка резервной копии конфигурации */
  async restoreBackup(file: File): Promise<void> {
    const res = await fetch('/api/settings/restore', {
      method: 'POST',
      body: file,
      headers: { 'Content-Type': 'application/zip' },
    });
    if (!res.ok) {
      throw new Error(await res.text());
    }
  },

  // ─── Online Videos & Playlists API ───

  async searchOnline(query: string, provider?: string): Promise<OnlineSearchResult[]> {
    return this.post<OnlineSearchResult[]>('/api/online/search', {
      query,
      provider: provider || null,
    });
  },

  async playOnline(
    payload: {
      provider: string;
      id: string;
      quality?: string;
      playlist_id?: string;
      episode_index?: number;
    },
    options?: { signal?: AbortSignal }
  ): Promise<PlayOnlineResponse> {
    return this.post<PlayOnlineResponse>('/api/online/play', payload, options);
  },

  async getOnlinePlaylists(): Promise<OnlinePlaylist[]> {
    return this.get<OnlinePlaylist[]>('/api/online/playlists');
  },

  async createOnlinePlaylist(title: string): Promise<OnlinePlaylist> {
    return this.post<OnlinePlaylist>('/api/online/playlists', { title });
  },

  async getOnlinePlaylist(id: string): Promise<OnlinePlaylist> {
    return this.get<OnlinePlaylist>(`/api/online/playlists/${id}`);
  },

  async updateOnlinePlaylist(id: string, title: string): Promise<OnlinePlaylist> {
    return this.patch<OnlinePlaylist>(`/api/online/playlists/${id}`, { title });
  },

  async deleteOnlinePlaylist(id: string): Promise<void> {
    return this.del<void>(`/api/online/playlists/${id}`);
  },

  async addOnlinePlaylistItem(
    playlistId: string,
    item: OnlineSearchResult
  ): Promise<OnlinePlaylist> {
    return this.post<OnlinePlaylist>(`/api/online/playlists/${playlistId}/items`, item);
  },

  async removeOnlinePlaylistItem(
    playlistId: string,
    itemId: string
  ): Promise<OnlinePlaylist> {
    return this.del<OnlinePlaylist>(`/api/online/playlists/${playlistId}/items/${encodeURIComponent(itemId)}`);
  },

  async getOnlineHistory(): Promise<OnlineHistoryItem[]> {
    return this.get<OnlineHistoryItem[]>('/api/online/history');
  },

  async deleteOnlineHistoryItem(provider: string, itemId: string): Promise<void> {
    return this.del<void>(`/api/online/history/${provider}/${encodeURIComponent(itemId)}`);
  },

  async clearOnlineHistory(): Promise<void> {
    return this.del<void>('/api/online/history');
  },

  // ─── In-App Updater API (TASK-004) ───
  async checkUpdate(signal?: AbortSignal): Promise<UpdateCheckResponse> {
    return this.get<UpdateCheckResponse>('/api/updater/check', { signal });
  },

  async getUpdateStatus(signal?: AbortSignal): Promise<UpdateStatusResponse> {
    return this.get<UpdateStatusResponse>('/api/updater/status', { signal });
  },

  async startUpdateDownload(): Promise<UpdateStatusResponse> {
    return this.post<UpdateStatusResponse>('/api/updater/download');
  },

  async applyUpdate(dryRun: boolean = false): Promise<UpdateActionResponse> {
    return this.post<UpdateActionResponse>('/api/updater/apply', { dry_run: dryRun });
  },

  async cancelUpdateDownload(): Promise<UpdateStatusResponse> {
    return this.post<UpdateStatusResponse>('/api/updater/cancel');
  },
};

/**
 * Получение системной диагностики (GET /api/diagnostics)
 * Экспорт функции в соответствии со спецификацией TASK-003.1
 */
export async function getDiagnostics(signal?: AbortSignal): Promise<DiagnosticsResponse> {
  return API.getSystemDiagnostics(signal);
}

