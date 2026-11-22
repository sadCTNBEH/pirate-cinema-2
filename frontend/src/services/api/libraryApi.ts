/**
 * @file services/api/libraryApi.ts
 * @description Доменный модуль API для работы с библиотекой, коллекциями, историей и торрентами.
 */

import {
  CollectionItem,
  CollectionName,
  HistoryItem,
  LibraryFilter,
  LibraryItem,
  LibraryProgressResponse,
  LibraryTorrent,
  MarkWatchedPayload,
  MediaDetail,
  MediaItem,
  NextUnwatchedResponse,
  OnlineHistoryItem,
  OnlinePlaylist,
  OnlineSearchResult,
  RecentItem,
  TorrentFilesResponse,
} from '../../types';
import { httpClient, parseJsonResponse } from './client';

/**
 * Загрузка недавних просмотров ("Продолжить просмотр")
 */
export async function getRecent(): Promise<RecentItem[]> {
  try {
    const data = await httpClient.get<RecentItem[]>('/api/history/continue');
    if (Array.isArray(data) && data.length > 0) return data;
    const fallback = await httpClient.get<RecentItem[]>('/api/library/recent');
    return Array.isArray(fallback) ? fallback : [];
  } catch {
    return [];
  }
}

/**
 * Алиас: продолжить просмотр
 */
export async function getContinueWatching(): Promise<RecentItem[]> {
  return getRecent();
}

/**
 * Удаление элемента из истории просмотров по хэшу
 */
export async function removeHistory(hash: string): Promise<void> {
  return httpClient.del(`/api/library/history/${hash}`);
}

/**
 * Получение полной истории просмотров
 */
export async function getHistory(): Promise<HistoryItem[]> {
  const data = await httpClient.get<HistoryItem[]>('/api/history');
  return Array.isArray(data) ? data : [];
}

/**
 * Отметка файла раздачи просмотренным
 */
export async function markHistoryWatched(hash: string, fileIndex: number): Promise<void> {
  await httpClient.post(`/api/history/${encodeURIComponent(hash)}/${fileIndex}/watched`);
}

/**
 * Отметка элемента просмотренным по payload
 */
export async function markWatched(payload: MarkWatchedPayload): Promise<void> {
  await httpClient.post('/api/history/mark-watched', payload);
}

/**
 * Удаление отдельной серии из истории просмотров
 */
export async function deleteHistoryEntry(hash: string, fileIndex: number): Promise<void> {
  try {
    await httpClient.del(`/api/history/${encodeURIComponent(hash)}/${fileIndex}`);
  } catch (err: any) {
    if (err?.status === 404 || err?.message?.includes('not found')) {
      return;
    }
    throw err;
  }
}

/**
 * Удаление записи истории по ID
 */
export async function deleteHistoryById(id: string): Promise<void> {
  try {
    await httpClient.del(`/api/history/${encodeURIComponent(id)}`);
  } catch (err: any) {
    if (err?.status === 404 || err?.message?.includes('not found')) {
      return;
    }
    throw err;
  }
}

/**
 * Загрузка каталога популярных фильмов или сериалов
 */
export async function getPopular(type: 'movies' | 'series'): Promise<MediaItem[]> {
  try {
    const endpoint = type === 'series' ? '/api/library/popular/series' : '/api/library/popular';
    const data = await httpClient.get<MediaItem[]>(endpoint);
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

/**
 * Загрузка метаданных кинокартины по IMDb
 */
export async function getMeta(imdb: string, type: 'movie' | 'series'): Promise<MediaDetail> {
  return httpClient.get<MediaDetail>(`/api/library/meta/${imdb}?type=${type}`);
}

/**
 * Загрузка элементов библиотеки с фильтрацией, сортировкой и общим числом результатов
 */
export async function getLibraryWithCount(
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
  if (filters?.genre) {
    if (Array.isArray(filters.genre)) {
      filters.genre.forEach((g) => params.append('genre', g));
    } else {
      params.set('genre', filters.genre);
    }
  }
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
}

/**
 * Загрузка элементов библиотеки с фильтрацией и сортировкой
 */
export async function getLibrary(
  filters?: LibraryFilter,
  options?: { signal?: AbortSignal }
): Promise<LibraryItem[]> {
  const res = await getLibraryWithCount(filters, options);
  return res.items;
}

/**
 * Получение элементов коллекции
 */
export async function getCollection(listName: CollectionName): Promise<CollectionItem[]> {
  const data = await httpClient.get<CollectionItem[]>(`/api/collections/${listName}`);
  return Array.isArray(data) ? data : [];
}

/**
 * Проверка принадлежности элемента к коллекциям
 */
export async function getCollectionMembership(mediaId: string): Promise<Record<CollectionName, boolean>> {
  return httpClient.get<Record<CollectionName, boolean>>(
    `/api/collections/membership/${encodeURIComponent(mediaId)}`
  );
}

/**
 * Сохранение элемента в коллекцию
 */
export async function saveCollectionItem(listName: CollectionName, item: CollectionItem): Promise<void> {
  await httpClient.put(`/api/collections/${listName}/${encodeURIComponent(item.media_id)}`, item);
}

/**
 * Удаление элемента из коллекции
 */
export async function removeCollectionItem(listName: CollectionName, mediaId: string): Promise<void> {
  await httpClient.del(`/api/collections/${listName}/${encodeURIComponent(mediaId)}`);
}

/**
 * Загрузка структуры прогресса сезонов и серий торрента
 */
export async function getLibraryProgress(hash: string): Promise<LibraryProgressResponse> {
  return httpClient.get<LibraryProgressResponse>(`/api/library/${hash}/progress`);
}

/**
 * Загрузка следующей непросмотренной серии для автозапуска
 */
export async function getNextUnwatched(
  targetOrParams:
    | string
    | { imdb_id?: string; season?: number; title_id?: string; torrent_hash?: string }
): Promise<NextUnwatchedResponse | null> {
  if (typeof targetOrParams === 'string') {
    try {
      return await httpClient.get<NextUnwatchedResponse>(
        `/api/library/${encodeURIComponent(targetOrParams)}/next-unwatched`
      );
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
    const res = await httpClient.get<NextUnwatchedResponse>(
      `/api/history/next-unwatched?${query.toString()}`
    );
    return res && (res.episode !== undefined || res.next_episode !== undefined) ? res : null;
  } catch {
    return null;
  }
}

/**
 * Загрузка списка сохраненных торрентов в библиотеке TorrServer
 */
export async function getLibraryTorrents(): Promise<{ torrents: LibraryTorrent[] }> {
  try {
    const data = await httpClient.get<any>('/api/library/torrents');
    if (data && Array.isArray(data.torrents)) return data;
    if (data && Array.isArray(data.Torrents)) return { torrents: data.Torrents };
    return { torrents: [] };
  } catch {
    return { torrents: [] };
  }
}

/**
 * Алиас: получение сохраненных торрентов
 */
export async function getTorrents(): Promise<LibraryTorrent[]> {
  const res = await getLibraryTorrents();
  return res.torrents || [];
}

/**
 * Удаление торрента из базы TorrServer
 */
export async function deleteTorrent(hash: string): Promise<void> {
  if (hash.startsWith('online:')) {
    return httpClient.del(`/api/library/torrents/${encodeURIComponent(hash)}`).catch(() => {});
  }
  return httpClient.del(`/api/player/torrent/${hash}`);
}

/**
 * Алиас: удаление торрента
 */
export async function remTorrent(hash: string): Promise<void> {
  return deleteTorrent(hash);
}

/**
 * Удаление нескольких торрентов
 */
export async function deleteMultipleTorrents(hashes: string[]): Promise<void> {
  for (const h of hashes) {
    await deleteTorrent(h).catch(() => {});
  }
}

/**
 * Удаление всех торрентов библиотеки
 */
export async function deleteAllTorrents(hashes?: string[]): Promise<void> {
  let targetHashes = hashes;
  if (!targetHashes || targetHashes.length === 0) {
    const list = await getTorrents();
    targetHashes = list.map((item) => item.hash);
  }
  for (const h of targetHashes) {
    if (h) {
      await deleteTorrent(h).catch(() => {});
    }
  }
  await httpClient.del('/api/library/torrents').catch(() => {});
}

/**
 * Загрузка файловой структуры торрента из TorrServer
 */
export async function getTorrentFiles(
  hash: string,
  title?: string,
  options?: { signal?: AbortSignal }
): Promise<TorrentFilesResponse> {
  if (hash.startsWith('online:')) {
    return {
      type: 'movie',
      movies: [{ id: 0, name: title || 'Онлайн-видео', length: 0 }],
      flat_files: [{ id: 0, name: title || 'Онлайн-видео', length: 0 }],
    };
  }
  const q = title ? `?title=${encodeURIComponent(title)}` : '';
  return httpClient.get<TorrentFilesResponse>(`/api/library/torrents/${hash}/files${q}`, {
    signal: options?.signal || AbortSignal.timeout(8000),
  });
}

// ─── Online Videos & Playlists ───

export async function getOnlinePlaylists(): Promise<OnlinePlaylist[]> {
  return httpClient.get<OnlinePlaylist[]>('/api/online/playlists');
}

export async function createOnlinePlaylist(title: string): Promise<OnlinePlaylist> {
  return httpClient.post<OnlinePlaylist>('/api/online/playlists', { title });
}

export async function getOnlinePlaylist(id: string): Promise<OnlinePlaylist> {
  return httpClient.get<OnlinePlaylist>(`/api/online/playlists/${id}`);
}

export async function updateOnlinePlaylist(id: string, title: string): Promise<OnlinePlaylist> {
  return httpClient.patch<OnlinePlaylist>(`/api/online/playlists/${id}`, { title });
}

export async function deleteOnlinePlaylist(id: string): Promise<void> {
  return httpClient.del<void>(`/api/online/playlists/${id}`);
}

export async function addOnlinePlaylistItem(
  playlistId: string,
  item: OnlineSearchResult
): Promise<OnlinePlaylist> {
  return httpClient.post<OnlinePlaylist>(`/api/online/playlists/${playlistId}/items`, item);
}

export async function removeOnlinePlaylistItem(
  playlistId: string,
  itemId: string
): Promise<OnlinePlaylist> {
  return httpClient.del<OnlinePlaylist>(
    `/api/online/playlists/${playlistId}/items/${encodeURIComponent(itemId)}`
  );
}

export async function getOnlineHistory(): Promise<OnlineHistoryItem[]> {
  return httpClient.get<OnlineHistoryItem[]>('/api/online/history');
}

export async function deleteOnlineHistoryItem(provider: string, itemId: string): Promise<void> {
  return httpClient.del<void>(`/api/online/history/${provider}/${encodeURIComponent(itemId)}`);
}

export async function clearOnlineHistory(): Promise<void> {
  return httpClient.del<void>('/api/online/history');
}

export const libraryApi = {
  getRecent,
  getContinueWatching,
  removeHistory,
  getHistory,
  markHistoryWatched,
  markWatched,
  deleteHistoryEntry,
  deleteHistoryById,
  getPopular,
  getMeta,
  getLibraryWithCount,
  getLibrary,
  getCollection,
  getCollectionMembership,
  saveCollectionItem,
  removeCollectionItem,
  getLibraryProgress,
  getNextUnwatched,
  getLibraryTorrents,
  getTorrents,
  deleteTorrent,
  remTorrent,
  deleteMultipleTorrents,
  deleteAllTorrents,
  getTorrentFiles,
  getOnlinePlaylists,
  createOnlinePlaylist,
  getOnlinePlaylist,
  updateOnlinePlaylist,
  deleteOnlinePlaylist,
  addOnlinePlaylistItem,
  removeOnlinePlaylistItem,
  getOnlineHistory,
  deleteOnlineHistoryItem,
  clearOnlineHistory,
};
