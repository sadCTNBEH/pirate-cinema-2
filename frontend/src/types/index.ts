/**
 * @file types/index.ts
 * @description Централизованные типы данных и интерфейсы платформы Pirate Cinema.
 * Совместимо с FastAPI бэкендом и спецификацией TorrServer / Jackett / MPV.
 */

/** Статус подключения к TorrServer */
export interface ServerStatus {
  active: boolean;
  message?: string;
}

/** Конфигурация провайдера Torznab */
export interface TorznabConfig {
  enabled: boolean;
  url: string;
  api_key: string;
  categories: number[];
}

/** Результат поиска по торрент-трекерам */
export interface SearchResult {
  title: string;
  magnet?: string;
  infohash?: string;
  hash?: string;
  size?: number | string;
  seeders?: number;
  quality?: string;
  source?: string;
  score?: number;
  peers?: number;
  category?: string;
}

/** Информация о раздаче / торренте из поисковой выдачи (псевдоним SearchResult для обратной совместимости) */
export interface TorrentResult extends SearchResult {
  hash: string;
}

/** Отдельный медиафайл внутри торрент-раздачи */
export interface TorrentFile {
  id: number;
  name: string;
  length: number;
  playback_timecode?: number;
  path?: string;
}

/** Структура файлов торрента, возвращаемая TorrServer */
export interface TorrentFilesResponse {
  type?: 'series' | 'movie';
  flat_files?: TorrentFile[];
  seasons?: Record<string, TorrentFile[]>;
  movies?: TorrentFile[];
  [key: string]: any;
}

/** Сохраненная раздача в локальной библиотеке TorrServer */
export interface LibraryTorrent {
  hash: string;
  title: string;
  poster_url?: string;
  size?: number;
  added_at?: string;
}

/** Фильтры запроса библиотеки */
export interface LibraryFilter {
  type?: 'movie' | 'series';
  status?: 'unwatched' | 'watching' | 'completed';
  year?: number;
  genre?: string;
  sort?: 'title' | 'year' | 'added' | 'progress';
}

/** Карточка элемента в библиотеке */
export interface LibraryItem {
  hash: string;
  torrent_hash: string;
  title: string;
  poster_file?: string | null;
  poster_url?: string | null;
  type?: 'movie' | 'series';
  media_type?: 'movie' | 'series';
  year?: number | null;
  rating?: number | null;
  genres?: string[];
  overview?: string | null;
  overview_ru?: string | null;
  status: 'unwatched' | 'watching' | 'completed' | 'in_progress' | 'watched';
  progress: number;
  total_files: number;
  watched_files: number;
  last_played_at?: string | null;
}

/** Прогресс конкретного сезона */
export interface SeasonProgress {
  season: string;
  total_files: number;
  watched_files: number;
  progress: number;
  is_completed: boolean;
  episodes: TorrentFile[] | any[];
}

/** Ответ прогресса всей раздачи / сериала */
export interface LibraryProgressResponse {
  torrent_hash: string;
  hash?: string;
  total_files: number;
  watched_files: number;
  progress: number;
  is_completed: boolean;
  seasons: Record<string, SeasonProgress>;
}

/** Ответ следующей непросмотренной серии */
export interface NextUnwatchedResponse {
  torrent_hash: string;
  hash?: string;
  file_id: number;
  file_name: string;
  playback_timecode: number;
  playback_duration: number;
  is_watched: boolean;
  season?: number | null;
  episode?: number | null;
}

/** Запись из истории недавних просмотров ("Продолжить просмотр") */
export interface RecentItem {
  torrent_hash: string;
  file_index: number;
  file_name: string;
  title?: string;
  poster_url?: string;
  playback_timecode: number;
  playback_duration: number;
  is_watched?: boolean;
}

/** Карточка фильма или сериала в общем каталоге */
export interface MediaItem {
  id: string;
  title: string;
  title_ru?: string | null;
  original_title?: string | null;
  poster_url?: string;
  poster_local_url?: string | null;
  background_url?: string | null;
  year?: number | string;
  rating?: number;
  overview?: string;
  overview_ru?: string | null;
  genres?: string[];
  type?: 'movie' | 'series';
}

/** Эпизод сериала из метаданных */
export interface SeriesEpisode {
  season: number;
  episode: number;
  name?: string;
  overview?: string;
}

/** Полные метаданные по кинокартине/сериалу */
export interface MediaDetail {
  id: string;
  title: string;
  title_ru?: string | null;
  original_title?: string | null;
  poster_url?: string;
  poster_local_url?: string | null;
  background_url?: string | null;
  year?: number | string;
  rating?: number;
  overview?: string;
  overview_ru?: string | null;
  genres?: string[];
  type?: 'movie' | 'series';
  videos?: SeriesEpisode[];
}

/** Системные настройки приложения */
export interface SystemSettings {
  torrserver_url: string;
  language: 'ru' | 'en';
  jackett_url?: string;
  jackett_api_key?: string;
  torznab?: TorznabConfig;
  torznab_enabled?: boolean;
  torznab_url?: string;
  torznab_api_key?: string;
  torznab_categories?: number[];
  player_type?: string;
  player_path?: string;
  minimize_to_tray?: boolean;
  register_magnet_handler?: boolean;
  onboarding_complete?: boolean;
}

/** Диагностические данные хоста и сервисов */
export interface SystemDiagnostics {
  torrserver_version: string;
  mpv_path: string;
  db_size: number;
  last_error?: string | null;
}

/** Ответ проверки обновлений приложения */
export interface UpdateInfo {
  has_update: boolean;
  latest: string;
  url: string;
  current?: string;
  error?: string;
}

/** Маршруты клиентского SPA */
export type AppRoute = 'home' | 'search' | 'library' | 'settings' | 'meta' | 'detail';

/** Параметры маршрутизации */
export interface RouteParams {
  query?: string;
  imdb?: string;
  title?: string;
  type?: 'movie' | 'series';
  poster?: string;
  hash?: string;
  magnet?: string | null;
  targetSeason?: string | number;
  targetEpisode?: string | number;
}

/** Состояние активного воспроизведения в MPV */
export interface ActivePlaybackState {
  isPlaying: boolean;
  title: string;
  fileName: string;
  hash: string;
  fileId: number;
  startTime?: number;
}
