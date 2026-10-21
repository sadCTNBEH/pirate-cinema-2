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
  published_at?: string;
  score?: number;
  peers?: number;
  category?: string;
}

/** Информация о раздаче / торренте из поисковой выдачи (псевдоним SearchResult для обратной совместимости) */
export interface TorrentResult extends SearchResult {
  hash: string;
}

export interface SearchFilters {
  quality?: string;
  language?: 'all' | 'russian' | 'english' | 'original';
  minSizeGb?: number;
  maxSizeGb?: number;
}

export type SearchSort = 'seeders' | 'size' | 'date';

/** Отдельный медиафайл внутри торрент-раздачи */
export interface TorrentFile {
  id: number;
  name: string;
  length: number;
  playback_timecode?: number;
  is_watched?: boolean;
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

/** Фильтры запроса библиотеки (TASK-006) */
export interface LibraryFilter {
  type?: 'movie' | 'series';
  status?: 'unwatched' | 'watching' | 'completed' | 'planned' | 'in_progress' | 'watched';
  year?: number;
  year_from?: number;
  year_to?: number;
  genre?: string;
  sort?: 'title' | 'year' | 'added' | 'progress';
  order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
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
  status: 'unwatched' | 'watching' | 'completed' | 'planned' | 'in_progress' | 'watched';
  progress: number;
  total_files: number;
  watched_files: number;
  last_played_at?: string | null;
  added_at?: string | null;
}

/** Прогресс конкретного сезона */
export interface SeasonProgress {
  season: string | number;
  total_files: number;
  watched_files: number;
  progress: number;
  is_completed: boolean;
  watched?: number;
  total?: number;
  progress_percent?: number;
  next_episode?: number | null;
  episodes: TorrentFile[] | any[];
}

/** Ответ прогресса всей раздачи / сериала */
export interface LibraryProgressResponse {
  title_id?: string;
  torrent_hash: string;
  hash?: string;
  total_files: number;
  watched_files: number;
  progress: number;
  is_completed: boolean;
  seasons: Record<string, SeasonProgress>;
  seasons_list?: SeasonProgress[];
  watched_episode_keys?: string[];
}

/** Ответ следующей непросмотренной серии */
export interface NextUnwatchedResponse {
  found?: boolean;
  title_id?: string;
  torrent_hash?: string;
  hash?: string;
  file_id?: number;
  file_index?: number;
  file_name?: string;
  playback_timecode?: number;
  playback_duration?: number;
  is_watched?: boolean;
  season?: number | null;
  episode?: number | null;
  next_episode?: number | null;
  imdb_id?: string | null;
  title?: string | null;
}

/** Запись из истории недавних просмотров ("Продолжить просмотр") */
export interface RecentItem {
  id?: string;
  torrent_hash: string;
  file_index: number;
  file_name: string;
  title?: string;
  poster_url?: string;
  playback_timecode: number;
  playback_duration: number;
  is_watched?: boolean;
  season?: number | null;
  episode?: number | null;
  imdb_id?: string | null;
  media_type?: 'movie' | 'series' | null;
}

export interface HistoryItem {
  id?: string;
  torrent_hash: string;
  file_index: number;
  file_name: string;
  file_path?: string | null;
  playback_timecode?: number | null;
  playback_duration?: number | null;
  is_watched: boolean;
  last_played_at: string;
  title?: string | null;
  poster_file?: string | null;
  year?: number | null;
  media_type?: 'movie' | 'series' | null;
  season?: number | null;
  episode?: number | null;
  imdb_id?: string | null;
}

export interface MarkWatchedPayload {
  title_id?: string;
  imdb_id?: string;
  torrent_hash?: string;
  file_index?: number;
  season?: number;
  episode?: number;
  watched?: boolean;
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
  title?: string;
  released?: string;
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

export type CollectionName = 'favorites' | 'watch_later';

export interface CollectionItem {
  media_id: string;
  title: string;
  title_ru?: string | null;
  poster_url?: string | null;
  year?: number | null;
  rating?: number | null;
  overview?: string | null;
  overview_ru?: string | null;
  genres: string[];
  media_type?: 'movie' | 'series' | null;
  created_at?: string | null;
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

/** Диагностические данные хоста и сервисов (legacy settings) */
export interface SystemDiagnostics {
  torrserver_version: string;
  mpv_path: string;
  db_size: number;
  last_error?: string | null;
}

/** Диагностика TorrServer (TASK-003/003.1) */
export interface TorrServerDiagnostics {
  running: boolean;
  port: number | null;
  pid: number | null;
  last_error: string | null;
}

/** Диагностика MPV (TASK-003/003.1) */
export interface MPVDiagnostics {
  available: boolean;
  path: string | null;
  version: string | null;
}

/** Диагностика дискового пространства (TASK-003/003.1) */
export interface DiskDiagnostics {
  data_dir: string;
  used_mb: number | null;
  free_mb: number | null;
}

/** Диагностика SQLite (TASK-003/003.1) */
export interface DatabaseDiagnostics {
  ok: boolean;
  size_mb: number | null;
}

/** Диагностическая ошибка (TASK-003/003.1) */
export interface DiagnosticError {
  timestamp: string;
  component: string;
  error_type: string;
  message: string;
}

/** Ответ комплексной системной диагностики (GET /api/diagnostics) */
export interface DiagnosticsResponse {
  version: string;
  status: 'healthy' | 'degraded' | 'unhealthy' | string;
  checked_at: string;
  response_time_ms: number;
  torrserver: TorrServerDiagnostics;
  mpv: MPVDiagnostics;
  disk: DiskDiagnostics;
  db: DatabaseDiagnostics;
  last_errors: DiagnosticError[];
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
export type AppRoute =
  | 'home'
  | 'search'
  | 'library'
  | 'collections'
  | 'watch_later'
  | 'history'
  | 'online'
  | 'settings'
  | 'meta'
  | 'detail'
  | 'diagnostics';

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
  onlinePlaylistId?: string;
  onlineProvider?: string;
}

export interface OnlineSearchResult {
  id: string;
  title: string;
  provider: string;
  thumbnail?: string | null;
  duration?: number | null;
  is_playlist?: boolean;
}

export interface OnlinePlaylist {
  id: string;
  title: string;
  items: OnlineSearchResult[];
  created_at: string;
}

export interface OnlineHistoryItem {
  item_id: string;
  provider: string;
  title: string;
  thumbnail?: string | null;
  duration?: number | null;
  playback_timecode: number;
  playback_duration: number;
  is_watched: boolean;
  last_played_at: string;
  launch_count: number;
}

export interface PlayOnlineResponse {
  url: string;
  title: string;
  thumbnail?: string | null;
  duration?: number | null;
  quality?: string | null;
  timecode: number;
  provider: string;
  id: string;
  available_qualities: string[];
  status: string;
}

/** Состояние активного воспроизведения во встроенном плеере MPV */
export interface ActivePlaybackState {
  isPlaying: boolean;
  title: string;
  poster?: string;
  fileName?: string;
  hash: string;
  magnet?: string | null;
  fileId?: number;
  startTime?: number;
  targetSeason?: string | number;
  targetEpisode?: string | number;
  preloadedFiles?: TorrentFilesResponse | null;
  isOnline?: boolean;
  onlineProvider?: string;
  onlineId?: string;
  playlistId?: string;
  episodeIndex?: number;
}

/** Ответ статуса активного плеера с бэкенда (/api/player/active) */
export interface BackendActivePlayerStatus {
  active: boolean;
  hash?: string;
  file_id?: number;
  file_name?: string;
  timecode?: number;
  duration?: number;
  audio_track?: number;
  subtitle_track?: number;
  is_watched?: boolean;
  is_fullscreen?: boolean;
  is_paused?: boolean;
  volume?: number;
  is_online?: boolean;
  is_ready?: boolean;
  online_provider?: string | null;
  online_id?: string | null;
  playlist_id?: string | null;
  episode_index?: number | null;
}

/** Информация о доступном обновлении */
export interface UpdateCheckResponse {
  current_version: string;
  has_update: boolean;
  version: string;
  release_notes: string;
  download_url: string;
  release_url: string;
  asset_name: string;
  size_bytes?: number | null;
  can_auto_update: boolean;
  reason?: string | null;
  published_at?: string | null;
  sha256?: string | null;
}

/** Состояние процесса обновления */
export interface UpdateStatusResponse {
  state:
    | 'idle'
    | 'checking'
    | 'available'
    | 'downloading'
    | 'verifying'
    | 'ready'
    | 'applying'
    | 'restarting'
    | 'completed'
    | 'failed'
    | 'rolled_back';
  version?: string | null;
  downloaded_bytes: number;
  total_bytes?: number | null;
  progress_percent: number;
  error?: string | null;
  can_auto_update: boolean;
  asset_name?: string | null;
}

/** Ответ на действие над обновлением */
export interface UpdateActionResponse {
  status: string;
  message: string;
}

