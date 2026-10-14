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
  nav_watch_later: 'Посмотреть позже',
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
  movie: 'Фильм',
  movies: 'Фильмы',
  series: 'Сериал',
  unwatched: 'Не просмотрено',
  watching: 'Смотрю',
  completed: 'Завершено',
  sort_title: 'Название',
  sort_year: 'Год',
  sort_added: 'Дата добавления',
  sort_progress: 'Прогресс',
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
  async get<T = any>(path: string): Promise<T> {
    const res = await fetch(path);
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
  async post<T = any>(path: string, body: any = {}): Promise<T> {
    const res = await fetch(path, {
      method: 'POST',
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
      const data = await this.get<RecentItem[]>('/api/library/recent');
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
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

  async deleteHistoryEntry(hash: string, fileIndex: number): Promise<void> {
    await this.del(`/api/history/${encodeURIComponent(hash)}/${fileIndex}`);
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

  /** Загрузка элементов библиотеки с фильтрацией и сортировкой */
  async getLibrary(filters?: LibraryFilter): Promise<LibraryItem[]> {
    const params = new URLSearchParams();
    if (filters?.type) params.set('type', filters.type);
    if (filters?.status) params.set('status', filters.status);
    if (filters?.year !== undefined && filters?.year !== null && !isNaN(filters.year)) {
      params.set('year', String(filters.year));
    }
    if (filters?.genre) params.set('genre', filters.genre);
    if (filters?.sort) params.set('sort', filters.sort);
    const qs = params.toString();
    const endpoint = qs ? `/api/library?${qs}` : '/api/library';
    const data = await this.get<LibraryItem[]>(endpoint);
    return Array.isArray(data) ? data : [];
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
  async getNextUnwatched(hash: string): Promise<NextUnwatchedResponse> {
    return this.get<NextUnwatchedResponse>(`/api/library/${hash}/next-unwatched`);
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
    return this.del(`/api/player/torrent/${hash}`);
  },

  /** Загрузка файловой структуры торрента из TorrServer */
  async getTorrentFiles(hash: string, title?: string): Promise<TorrentFilesResponse> {
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
    return this.post('/api/player/stop', {});
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
};
