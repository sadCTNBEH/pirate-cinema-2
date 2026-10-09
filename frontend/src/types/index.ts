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

/** Информация о раздаче / торренте из поисковой выдачи Jackett/TorrServer */
export interface TorrentResult {
  title: string;
  source?: string;
  seeders?: number;
  peers?: number;
  size?: number | string;
  magnet: string;
  hash: string;
  category?: string;
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
  poster_url?: string;
  year?: number | string;
  rating?: number;
  overview?: string;
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
  poster_url?: string;
  year?: number | string;
  rating?: number;
  overview?: string;
  type?: 'movie' | 'series';
  videos?: SeriesEpisode[];
}

/** Системные настройки приложения */
export interface SystemSettings {
  torrserver_url: string;
  language: 'ru' | 'en';
  jackett_url?: string;
  jackett_api_key?: string;
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
