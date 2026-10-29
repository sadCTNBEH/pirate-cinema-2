import type { RecentItem, RouteParams } from '../types';

export function resumeDestination(item: RecentItem): {route: 'meta' | 'detail'; params: RouteParams} | null {
  if (item.anime_playback || item.torrent_hash.startsWith('online:')) return null;
  const title = item.title || item.file_name;
  const poster = item.poster_url || (item.poster_file
    ? `/api/library/poster/${encodeURIComponent(item.torrent_hash)}` : undefined);
  const type = item.media_type === 'series' || item.season != null || item.episode != null ? 'series' : 'movie';
  const params: RouteParams = {
    title, poster, type, hash: item.torrent_hash,
    targetSeason: item.season ?? undefined, targetEpisode: item.episode ?? undefined,
    torrentResume: {
      hash: item.torrent_hash, title, poster, fileId: item.file_index, fileName: item.file_name,
      startTime: item.is_watched ? 0 : item.playback_timecode || 0,
      targetSeason: item.season ?? undefined, targetEpisode: item.episode ?? undefined,
    },
  };
  if (item.imdb_id && item.imdb_id !== item.torrent_hash) {
    return {route: 'meta', params: {...params, imdb: item.imdb_id}};
  }
  return {route: 'detail', params};
}
