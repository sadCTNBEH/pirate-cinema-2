import type { ActivePlaybackState, BackendActivePlayerStatus, TorrentFile, TorrentFilesResponse } from '../../types';
import type { API } from '../../services/api';
import type { TorrentIntent } from '../../services/automaticTorrent';

type SessionApi = Pick<typeof API, 'getActivePlayback' | 'getTorrentFiles' | 'addTorrent' | 'selectTorrentFile'>;
type Selection = Awaited<ReturnType<SessionApi['selectTorrentFile']>>;

const MAX_ATTEMPTS = 30;
const METADATA_TIMEOUT = 60000;

export function createPlaybackScope() {
  const controller = new AbortController();
  let launch = 0;
  let selection = 0;
  return {
    signal: controller.signal,
    dispose: () => controller.abort(),
    get launch() { return launch; },
    nextLaunch: () => ++launch,
    isCurrent: (generation: number, choice?: number) =>
      !controller.signal.aborted && generation === launch && (choice === undefined || choice === selection),
    nextSelection: () => ++selection,
    seenActive: false,
  };
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise(resolve => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const finish = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', finish);
      resolve();
    };
    const timer = setTimeout(finish, ms);
    signal.addEventListener('abort', finish, { once: true });
  });
}

export function isOnlinePlayback(playback: ActivePlaybackState, hash: string) {
  return playback.isOnline || hash.startsWith('online:');
}

type SessionResult =
  | { kind: 'active'; hash: string; id: number; name: string; ready: boolean; embedded?: boolean; onlinePending?: boolean }
  | { kind: 'launch'; hash: string; id: number; name: string; startTime?: number; seasonKey?: string }
  | { kind: 'choice'; hash: string; selection: Selection; intent: TorrentIntent }
  | { kind: 'error'; message: string }
  | { kind: 'dead' };

export async function preparePlayback(
  api: SessionApi,
  playback: ActivePlaybackState,
  signal: AbortSignal,
  updates: {
    files: (data: TorrentFilesResponse) => void;
    loading: (message: string, attempt?: number) => void;
    selecting: (data: TorrentFilesResponse) => void;
  },
): Promise<SessionResult | undefined> {
  let hash = playback.hash || '';
  const online = isOnlinePlayback(playback, hash);
  const loadFilesInBackground = () => {
    if (playback.preloadedFiles) {
      updates.files(playback.preloadedFiles);
    } else {
      void api.getTorrentFiles(hash, playback.mediaId ? undefined : playback.title, {
        signal: AbortSignal.any([signal, AbortSignal.timeout(8000)]),
      }).then(data => {
        if (!signal.aborted && data) updates.files(data);
      }).catch(() => {});
    }
  };

  const active = await api.getActivePlayback().catch(() => null);
  if (signal.aborted) return;
  const hasTarget = playback.fileId !== undefined || playback.targetSeason !== undefined ||
    playback.targetEpisode !== undefined;
  if (active?.active && active.hash === hash && (!hasTarget || active.file_id === playback.fileId)) {
    if (!online) loadFilesInBackground();
    return {
      kind: 'active', hash, id: active.file_id ?? 0,
      name: active.file_name || playback.title, ready: Boolean(active.is_ready),
      ...(active.is_embedded !== undefined ? { embedded: active.is_embedded } : {}),
    };
  }

  if (online) {
    const name = playback.fileName || playback.title;
    const file = { id: 0, name, length: 0 };
    updates.files({ type: 'movie', movies: [file], flat_files: [file] });
    return { kind: 'active', hash, id: 0, name, ready: false, onlinePending: true };
  }

  if (hash && playback.fileId !== undefined && playback.fileName && !playback.magnet) {
    loadFilesInBackground();
    return { kind: 'launch', hash, id: playback.fileId, name: playback.fileName, startTime: playback.startTime };
  }

  updates.loading('Подключение к торрент-сети (DHT)...');
  if (playback.magnet) {
    updates.loading('Добавление magnet-ссылки в TorrServer...');
    try {
      const added = await api.addTorrent(playback.magnet, playback.title, { signal });
      if (added?.hash) hash = added.hash;
      await wait(1500, signal);
    } catch (error) {
      if (signal.aborted) return;
      return { kind: 'error', message: error instanceof Error ? error.message : 'Не удалось подключиться к раздаче' };
    }
  }
  if (signal.aborted) return;
  if (!hash) return { kind: 'dead' };

  const intent: TorrentIntent = {
    season: playback.targetSeason === undefined ? undefined : Number(playback.targetSeason),
    episode: playback.targetEpisode === undefined ? undefined : Number(playback.targetEpisode),
    absolute: playback.absoluteEpisode,
  };
  const deadline = Date.now() + METADATA_TIMEOUT;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS && Date.now() < deadline; attempt++) {
    if (signal.aborted) return;
    updates.loading(`Поиск метаданных в DHT (попытка ${attempt} из 30)...`, attempt);
    try {
      const data = await api.getTorrentFiles(hash, playback.mediaId ? undefined : playback.title, {
        signal: AbortSignal.any([signal, AbortSignal.timeout(Math.max(1, Math.min(8000, deadline - Date.now())))]),
      });
      if (signal.aborted) return;
      if (data && (data.metadata_ready || data.files?.length || data.flat_files?.length)) {
        updates.selecting(data);
        let selection: Selection | null = null;
        try {
          selection = await api.selectTorrentFile({
            hash, ...intent, release_title: playback.title, media_id: playback.mediaId,
          }, { signal: AbortSignal.any([signal, AbortSignal.timeout(Math.max(1, deadline - Date.now()))]) });
        } catch (error) {
          if (signal.aborted) return;
          return { kind: 'error', message: error instanceof Error ? error.message : 'Не удалось выбрать видеофайл' };
        }
        if (signal.aborted || !selection) return;

        const withMetadata = (file: TorrentFile) => ({
          ...(data.flat_files || data.files || []).find((old: TorrentFile) => old.id === file.id),
          ...file,
        });
        if (!selection.file) {
          return {
            kind: 'choice', hash, intent,
            selection: { ...selection, candidates: selection.candidates.map(withMetadata) },
          };
        }
        const file = withMetadata(selection.file);
        return {
          kind: 'launch', hash, id: file.id, name: file.name,
          seasonKey: String(playback.targetSeason ?? file.season ?? 1),
          startTime: playback.startTime ?? (file.playback_timecode || undefined),
        };
      }
    } catch {
      if (signal.aborted) return;
    }
    if (attempt < MAX_ATTEMPTS && Date.now() < deadline) await wait(2000, signal);
  }
  if (!signal.aborted) return { kind: 'dead' };
}

export function pollActivePlayback(
  read: () => Promise<BackendActivePlayerStatus>,
  onStatus: (status: BackendActivePlayerStatus) => void,
  isCurrent: () => boolean,
) {
  let stopped = false;
  let pending = false;
  const timer = setInterval(async () => {
    if (pending || stopped || !isCurrent()) return;
    pending = true;
    try {
      const status = await read();
      if (!stopped && isCurrent()) onStatus(status);
    } catch {} finally {
      pending = false;
    }
  }, 500);
  return () => {
    stopped = true;
    clearInterval(timer);
  };
}
