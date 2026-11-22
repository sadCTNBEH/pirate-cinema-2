/**
 * @file services/api/searchApi.ts
 * @description Доменный модуль API для поиска торрентов, метаданных и онлайн-видео.
 */

import {
  MediaItem,
  OnlineSearchResult,
  SearchFilters,
  TorrentResult,
} from '../../types';
import { httpClient } from './client';

/**
 * Поиск торрентов через Jackett / TorrServer / Torznab
 */
export async function searchTorrents(
  query: string,
  quality?: string,
  min_seeders?: number,
  advanced: SearchFilters = {},
  titles: string[] = []
): Promise<TorrentResult[]> {
  const params = new URLSearchParams({ q: query });
  titles.forEach((title) => params.append('titles', title));
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
  const data = await httpClient.get<TorrentResult[]>(`/api/search?${params.toString()}`, {
    signal: AbortSignal.timeout(20000),
  });
  return Array.isArray(data) ? data : [];
}

/**
 * Поиск аниме-метаданных по названию
 */
export async function searchAnime(query: string): Promise<MediaItem[]> {
  try {
    const data = await httpClient.get<MediaItem[]>(
      `/api/library/meta/anime?q=${encodeURIComponent(query)}`
    );
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

/**
 * Поиск метаданных по названию
 */
export async function searchMeta(query: string): Promise<any[]> {
  try {
    const data = await httpClient.get<any[]>(
      `/api/library/meta/search?q=${encodeURIComponent(query)}`
    );
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

/**
 * Алиас: поиск метаданных по названию
 */
export async function searchMedia(query: string): Promise<any[]> {
  return searchMeta(query);
}

/**
 * Поиск онлайн-видео по провайдерам (Rutube и др.)
 */
export async function searchOnline(
  query: string,
  provider?: string
): Promise<OnlineSearchResult[]> {
  return httpClient.post<OnlineSearchResult[]>('/api/online/search', {
    query,
    provider: provider || null,
  });
}

export const searchApi = {
  searchTorrents,
  searchAnime,
  searchMeta,
  searchMedia,
  searchOnline,
};
