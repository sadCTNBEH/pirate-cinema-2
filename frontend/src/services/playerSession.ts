import type { ActivePlaybackState, BackendActivePlayerStatus, TorrentFilesResponse } from '../types';

export function seasonKeyForFile(data: TorrentFilesResponse, fileId?: number,
  requestedSeason?: string | number): string {
  if (requestedSeason !== undefined) return String(requestedSeason);
  return Object.entries(data.seasons || {}).find(([, files]) =>
    files.some(file => file.id === fileId))?.[0] || '1';
}

export function playbackSessionKey(playback: ActivePlaybackState | null): string | null {
  return playback ? JSON.stringify([playback.hash, playback.fileId, playback.magnet,
    playback.targetSeason, playback.targetEpisode, playback.absoluteEpisode, playback.startTime]) : null;
}

export function canShowNativePlayer(state: {
  requestedHash?: string; resolvedHash: string; running: boolean; ready: boolean;
  loading: boolean; starting: boolean; blocked: boolean;
}): boolean {
  return Boolean(state.requestedHash && state.requestedHash === state.resolvedHash &&
    state.running && state.ready && !state.loading && !state.starting && !state.blocked);
}

export function shouldAdoptBackendPlayback(local: ActivePlaybackState | null,
  backend: BackendActivePlayerStatus, pendingHash: string | null): boolean {
  return Boolean(backend.active && backend.hash && pendingHash === null && local?.hash !== backend.hash);
}
