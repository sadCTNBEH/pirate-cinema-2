import type { TorrentFile, TorrentResult } from '../types';

export type TorrentIntent = {season?: number; episode?: number; absolute?: number};
type Selection = {file: TorrentFile | null; candidates: TorrentFile[]; reason: string; metadata_ready?: boolean};
type SelectionClient = {
  addTorrent: (magnet: string, title: string, options?: {signal?: AbortSignal}) => Promise<{hash: string}>;
  selectTorrentFile: (request: TorrentIntent & {hash: string; release_title?: string}, options?: {signal?: AbortSignal}) => Promise<Selection>;
};

export async function findPlayableRelease(releases: TorrentResult[], intent: TorrentIntent,
  client: SelectionClient, signal: AbortSignal): Promise<TorrentResult | null> {
  for (const release of releases.slice(0, 3)) {
    signal.throwIfAborted();
    try {
      let hash = release.hash;
      // Check existing metadata first. A missing torrent is registered by TorrServer's client.
      let selection = await client.selectTorrentFile({...intent, hash, release_title: release.title}, {signal});
      if (!selection.file && !selection.candidates.length && !selection.metadata_ready && release.magnet) {
        const added = await client.addTorrent(release.magnet, release.title, {signal});
        hash = added.hash || hash;
        selection = await client.selectTorrentFile({...intent, hash, release_title: release.title}, {signal});
      }
      const exactVariants = intent.episode !== undefined && selection.candidates.some(file =>
        file.season === intent.season && file.episode === intent.episode && !file.multiple);
      if (selection.file || exactVariants) return {...release, hash};
    } catch (error) {
      if (signal.aborted) throw error;
    }
  }
  return null;
}
