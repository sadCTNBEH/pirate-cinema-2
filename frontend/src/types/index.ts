/**
 * @file types/index.ts
 * @description Централизованные типы данных и интерфейсы платформы Pirate Cinema.
 * Строго синхронизированы с FastAPI Pydantic схемами и спецификацией TorrServer / MPV / Torznab.
 */

/** Статус подключения к TorrServer */
export interface ServerStatus {
  active: boolean;
  url?: string;
  message?: string;
}

export type ServerStatusResponse = ServerStatus;

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
  season?: number | null;
  episode?: number | null;
  multiple?: boolean;
}

/** Структура файлов торрента, возвращаемая TorrServer */
export interface TorrentFilesResponse {
  type?: 'series' | 'movie';
  flat_files?: TorrentFile[];
  seasons?: Record<string, TorrentFile[]>;
  movies?: TorrentFile[];
  [key: string]: any;
}

export type TorrentFilesStructureResponse = TorrentFilesResponse;

/** Сохраненная раздача в локальной библиотеке TorrServer */
export interface LibraryTorrent {
  hash: string;
  title: string;
  poster_url?: string;
  size?: number;
  added_at?: string;
}

/** Фильтры запроса библиотеки (TASK-006 / schemas/library.py) */
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

/** Карточка элемента в библиотеке (schemas/library.py: LibraryItemResponse) */
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

export type LibraryItemResponse = LibraryItem;

/** Прогресс конкретного сезона (schemas/library.py: SeasonProgress) */
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

/** Ответ прогресса всей раздачи / сериала (schemas/library.py: LibraryProgressResponse) */
export interface LibraryProgressResponse {
  title_id?: string;
  torrent_hash: string;
  hash?: string;
  total_files: number;
  watched_files: number;
  progress: number;
  is_completed: boolean;
  seasons: Record<string, SeasonProgress> | SeasonProgress[];
  seasons_list?: SeasonProgress[];
  watched_episode_keys?: string[];
}

/** Ответ следующей непросмотренной серии (schemas/library.py, schemas/history.py) */
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

export type NextUnwatchedItem = NextUnwatchedResponse;

export interface AnimePlayback {
  media_id: string;
  card_media_id: string;
  source: 'animego' | 'yummy';
  source_title_id: string;
  source_url?: string | null;
  season: number;
  episode: number;
  player: string;
  voice_id: string;
  voice: string;
  title: string;
  poster_url?: string | null;
  media_type?: 'movie' | 'series';
  year?: number | null;
}

export interface AnimePlaybackRequest {
  media_id: string;
  source: 'animego' | 'yummy';
  source_title_id: string;
  season: number;
  episode: number;
  player?: string;
  voice_id?: string;
  voice?: string;
}

/** Запись из истории недавних просмотров ("Продолжить просмотр") */
export interface RecentItem {
  anime_playback?: AnimePlayback | null;
  id?: string;
  torrent_hash: string;
  file_index: number;
  file_name: string;
  title?: string;
  poster_url?: string;
  poster_file?: string | null;
  playback_timecode: number;
  playback_duration: number;
  is_watched?: boolean | number;
  season?: number | null;
  episode?: number | null;
  imdb_id?: string | null;
  media_type?: 'movie' | 'series' | null;
  last_played_at?: string;
}

export type RecentMediaItem = RecentItem;

export interface HistoryItem {
  anime_playback?: AnimePlayback | null;
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
  poster_url?: string | null;
  year?: number | null;
  media_type?: 'movie' | 'series' | null;
  season?: number | null;
  episode?: number | null;
  imdb_id?: string | null;
}

export type HistoryItemResponse = HistoryItem;

export interface FileHistoryEntry {
  id: string;
  title_id: string;
  imdb_id?: string | null;
  infohash?: string | null;
  torrent_hash?: string | null;
  file_index?: number | null;
  season?: number | null;
  episode?: number | null;
  position_seconds?: number;
  duration_seconds?: number | null;
  playback_timecode?: number;
  playback_duration?: number;
  watched?: boolean;
  is_watched?: boolean;
  last_played_at: string;
  file_name?: string | null;
  title?: string | null;
  anime_playback?: Record<string, any> | null;
  poster_file?: string | null;
  poster_url?: string | null;
  media_type?: string | null;
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

export type MarkWatchedRequest = MarkWatchedPayload;

/** Карточка фильма или сериала в общем каталоге (backend/models/catalog.py) */
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
  source?: string;
  episodes?: number;
  aliases?: string[];
  translations?: string[];
}

/** Эпизод сериала из метаданных */
export interface SeriesEpisode {
  absolute_episode?: number;
  season: number;
  episode: number;
  name?: string;
  title?: string;
  released?: string;
  overview?: string;
}

/** Полные метаданные по кинокартине/сериалу */
export interface MediaDetail extends MediaItem {
  videos?: SeriesEpisode[] | any[];
  playback_notice?: string;
  blocked?: boolean;
  blocked_in?: string[];
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

export type CollectionItemRequest = CollectionItem;
export type CollectionItemResponse = CollectionItem;

export interface CollectionMembershipResponse {
  favorites: boolean;
  watch_later: boolean;
}

export interface SubtitleSettings {
  font: string;
  font_size: number;
  color: string;
  border_size: number;
  border_color: string;
  shadow_offset: number;
  position: number;
  speed: number;
}

/** Системные настройки приложения (schemas/settings.py: SettingsResponse) */
export interface SystemSettings {
  hotkeys?: Record<string, string>;
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
  autostart?: boolean;
  autostart_prompted?: boolean;
  auto_next?: boolean;
  auto_skip_intro?: boolean;
  register_magnet_handler?: boolean;
  onboarding_complete?: boolean;
  audio_languages?: string[];
  subtitle_languages?: string[];
  subtitle_settings?: SubtitleSettings;
  seek_step?: 5 | 10 | 15 | 30 | 60;
  yummyanime_public_key?: string;
  yummyanime_private_key?: string;
  debug_mode?: boolean;
}

export type SettingsResponse = SystemSettings;

export type SystemSettingsUpdate = Partial<Omit<SystemSettings, 'subtitle_settings'>> & {
  subtitle_settings?: Partial<SubtitleSettings>;
};

export type SettingsUpdate = SystemSettingsUpdate;

/** Диагностические данные хоста и сервисов (legacy settings) */
export interface SystemDiagnostics {
  torrserver_version: string;
  mpv_path: string;
  db_size: number;
  data_folder?: string;
  last_error?: string | null;
}

/** Диагностика TorrServer (TASK-003/003.1, schemas/diagnostics.py) */
export interface TorrServerDiagnostics {
  state?: 'running' | 'stopped' | 'recovering' | 'error';
  managed?: boolean;
  can_restart?: boolean;
  path?: string | null;
  log_path?: string | null;
  version?: string | null;
  recovery_attempts?: number;
  running: boolean;
  port: number | null;
  pid: number | null;
  last_error: string | null;
}

/** Диагностика MPV (TASK-003/003.1, schemas/diagnostics.py) */
export interface MPVDiagnostics {
  state?: 'running' | 'starting' | 'stopped' | 'error';
  last_error?: string | null;
  can_resume?: boolean;
  available: boolean;
  path: string | null;
  version: string | null;
}

/** Диагностика дискового пространства (TASK-003/003.1, schemas/diagnostics.py) */
export interface DiskDiagnostics {
  data_dir: string;
  used_mb: number | null;
  free_mb: number | null;
}

/** Диагностика SQLite (TASK-003/003.1, schemas/diagnostics.py) */
export interface DatabaseDiagnostics {
  ok: boolean;
  size_mb: number | null;
}

/** Диагностическая ошибка (TASK-003/003.1, schemas/diagnostics.py) */
export interface DiagnosticError {
  timestamp: string;
  component: string;
  error_type: string;
  message: string;
}

/** Ответ комплексной системной диагностики (GET /api/diagnostics, schemas/diagnostics.py) */
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
  error?: string | null;
}

export type UpdatesResponse = UpdateInfo;

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
  animeResume?: AnimePlayback;
  torrentResume?: Omit<ActivePlaybackState, 'isPlaying'>;
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

export interface OnlineSearchRequest {
  query: string;
  provider?: string | null;
}

export interface PlayOnlineRequest {
  provider: string;
  id: string;
  quality?: string;
  playlist_id?: string;
  episode_index?: number;
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

export interface PlaylistCreateRequest {
  title: string;
}

export interface PlaylistUpdateRequest {
  title: string;
}

export interface PlaylistItemCreateRequest {
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

/** Запросы управления плеером (schemas/player.py) */
export interface PlayRequest {
  hash: string;
  file_id: number;
  file_name: string;
  start_time?: number | null;
  audio_track?: number | null;
  subtitle_track?: number | null;
}

export interface NextRequest {
  hash: string;
  file_id: number;
}

export interface MagnetRequest {
  magnet: string;
  title?: string;
}

export interface MagnetResponse {
  hash: string;
  title?: string;
}

export interface FileSelectionRequest {
  hash: string;
  season?: number | null;
  episode?: number | null;
  absolute?: number | null;
  release_title?: string;
  media_id?: string | null;
  file_id?: number | null;
}

export interface FileSelectionResponse {
  file: TorrentFile | null;
  candidates: TorrentFile[];
  reason: string;
}

export interface PlayerStatusResponse {
  status: string;
}

export interface PlaybackStateResponse {
  hash: string;
  file_id: number;
  timecode: number;
  duration: number;
  audio_track: number;
  subtitle_track: number;
  is_watched: boolean;
}

export interface PlayerBounds {
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
}

/** Прогресс и тайминг воспроизведения для PlayerContext */
export interface PlayerProgress {
  currentTime: number;
  duration: number;
  isBuffering: boolean;
  isPaused: boolean;
}

/** Детали события time-update */
export interface TimeUpdateDetail {
  currentTime?: number;
  timecode?: number;
  duration?: number;
  isBuffering?: boolean;
  buffering?: boolean;
  isPaused?: boolean;
}

/** Значение PlayerContext для изоляции состояния воспроизведения */
export interface PlayerContextValue extends PlayerProgress {
  activePlayback: ActivePlaybackState | null;
  openPlayback: (payload: Omit<ActivePlaybackState, 'isPlaying'>) => void;
  closePlayback: () => Promise<void>;
  isPip: boolean;
  isPipActive: () => boolean;
  togglePip: (pip?: boolean) => Promise<boolean>;
  updateProgress: (progress: Partial<PlayerProgress>) => void;
}

/** Свойства для компонента InlinePlayer */
export interface InlinePlayerProps {
  playback?: ActivePlaybackState | null;
  onClose?: () => void;
  className?: string;
}

/** Состояние активного воспроизведения во встроенном плеере MPV */
export interface ActivePlaybackState {
  mediaId?: string;
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
  absoluteEpisode?: number;
  preloadedFiles?: TorrentFilesResponse | null;
  isOnline?: boolean;
  onlineProvider?: string;
  onlineId?: string;
  playlistId?: string;
  episodeIndex?: number;
}

/** Ответ статуса активного плеера с бэкенда (/api/player/active) */
export interface BackendActivePlayerStatus {
  osd_menu?: boolean;
  continuation?: { status: string } | null;
  continuation_token?: number;
  failure?: { message: string; timecode: number; can_resume: boolean } | null;
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
  is_embedded?: boolean;
  online_provider?: string | null;
  online_id?: string | null;
  playlist_id?: string | null;
  episode_index?: number | null;
}

/** Ответ данных пульта ДУ (schemas/remote.py: RemoteInfoResponse) */
export interface RemoteInfoResponse {
  url: string;
  local_url?: string;
  ip_url?: string;
  hostname?: string;
  ip: string;
  port: number;
  qr_svg: string;
  ip_qr_svg?: string;
}

/** Информация о доступном обновлении (schemas/updater.py: UpdateCheckResponse) */
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

/** Состояние процесса обновления (schemas/updater.py: UpdateStatusResponse) */
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

/** Ответ на действие над обновлением (schemas/updater.py: UpdateActionResponse) */
export interface UpdateActionResponse {
  status: string;
  message: string;
}

export interface StatusResponse {
  status: string;
}

export interface ErrorResponse {
  detail: string;
}
