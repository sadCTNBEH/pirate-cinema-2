import test from 'node:test';
import assert from 'node:assert/strict';
import type { BackendActivePlayerStatus } from '../src/types';
import { createPlaybackScope, pollActivePlayback, preparePlayback } from '../src/components/player/playbackSessionFlow';

const release = { hash: 'show', title: 'Show', isPlaying: true };
const file = { id: 7, name: 'S02E03.mkv', length: 1, season: 2, playback_timecode: 123 };
const files = { flat_files: [file] };
const updates = { files() {}, loading() {}, selecting() {} };

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

function sessionApi(overrides: Partial<Parameters<typeof preparePlayback>[0]> = {}) {
  return {
    getActivePlayback: async (): Promise<BackendActivePlayerStatus> => ({ active: false }),
    getTorrentFiles: async () => files,
    addTorrent: async () => ({ hash: release.hash }),
    selectTorrentFile: async () => ({ file: { id: 7, name: file.name, length: 1 }, candidates: [], reason: '' }),
    ...overrides,
  };
}

test('adopts the matching MPV session and does not request a second launch', async () => {
  const api = sessionApi({
    getActivePlayback: async () => ({
      active: true, hash: 'show', file_id: 7, file_name: file.name, is_ready: true,
    }),
    selectTorrentFile: async () => assert.fail('active MPV session needs no file selection'),
  });
  const result = await preparePlayback(api, { ...release, fileId: 7, fileName: file.name },
    createPlaybackScope().signal, updates);
  assert.deepEqual(result, { kind: 'active', hash: 'show', id: 7, name: file.name, ready: true });

  const differentFile = await preparePlayback(api, { ...release, fileId: 0, fileName: 'Special.mkv', startTime: 42 },
    createPlaybackScope().signal, updates);
  assert.deepEqual(differentFile, { kind: 'launch', hash: 'show', id: 0, name: 'Special.mkv', startTime: 42 });
});

test('online playback uses its already-requested stream and skips torrent metadata', async () => {
  const api = sessionApi({ getTorrentFiles: async () => assert.fail('online playback skips TorrServer') });
  const result = await preparePlayback(api, { ...release, hash: 'online:video', isOnline: true },
    createPlaybackScope().signal, updates);
  assert.equal(result?.kind, 'active');
  assert.equal(result.onlinePending, true);
});

test('release selection restores saved position and respects an explicit start time of zero', async () => {
  for (const [startTime, expected] of [[undefined, 123], [0, 0]]) {
    const result = await preparePlayback(sessionApi(), { ...release, startTime },
      createPlaybackScope().signal, updates);
    assert.deepEqual(result, {
      kind: 'launch', hash: 'show', id: 7, name: file.name, seasonKey: '2', startTime: expected,
    });
  }
});

test('switching releases invalidates an older lookup and ignores its result', async () => {
  const old = createPlaybackScope();
  const status = deferred<BackendActivePlayerStatus>();
  const preparing = preparePlayback(sessionApi({ getActivePlayback: () => status.promise }),
    release, old.signal, {
      files: () => assert.fail('stale files'),
      loading: () => assert.fail('stale status'),
      selecting: () => assert.fail('stale selection'),
    });
  old.dispose();
  const current = await preparePlayback(sessionApi(), { ...release, hash: 'new' },
    createPlaybackScope().signal, updates);
  assert.equal(current?.kind === 'launch' && current.hash, 'new');
  status.resolve({ active: true, hash: 'show', file_id: 7 });
  assert.equal(await preparing, undefined);
});

test('latest file selection and launch win, and disposal invalidates all pending work', () => {
  const scope = createPlaybackScope();
  const firstLaunch = scope.nextLaunch();
  const firstChoice = scope.nextSelection();
  const secondChoice = scope.nextSelection();
  assert.equal(scope.isCurrent(firstLaunch, firstChoice), false);
  assert.equal(scope.isCurrent(firstLaunch, secondChoice), true);
  const secondLaunch = scope.nextLaunch();
  assert.equal(scope.isCurrent(firstLaunch), false);
  assert.equal(scope.isCurrent(secondLaunch), true);
  scope.dispose();
  assert.equal(scope.isCurrent(secondLaunch), false);
});

test('metadata retries run on schedule and unmount cancels the pending retry', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'] });
  const attempts: number[] = [];
  let requests = 0;
  const scope = createPlaybackScope();
  const pending = preparePlayback(sessionApi({ getTorrentFiles: async () => {
    requests++;
    return { flat_files: [] };
  } }), release, scope.signal, {
    ...updates,
    loading: (_message, attempt) => { if (attempt) attempts.push(attempt); },
  });
  await new Promise<void>(resolve => queueMicrotask(() => queueMicrotask(resolve)));
  assert.deepEqual(attempts, [1]);
  t.mock.timers.tick(2000);
  await new Promise<void>(resolve => queueMicrotask(() => queueMicrotask(resolve)));
  assert.deepEqual(attempts, [1, 2]);
  scope.dispose();
  assert.equal(await pending, undefined);
  t.mock.timers.tick(60000);
  assert.equal(requests, 2);
});

test('metadata polling stops once the session deadline expires', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'] });
  let requests = 0;
  const pending = preparePlayback(sessionApi({ getTorrentFiles: async () => {
    requests++;
    return { flat_files: [] };
  } }), release, createPlaybackScope().signal, updates);
  await new Promise<void>(resolve => queueMicrotask(() => queueMicrotask(resolve)));
  assert.equal(requests, 1);
  t.mock.timers.tick(60000);
  assert.deepEqual(await pending, { kind: 'dead' });
  assert.equal(requests, 1);
});

test('active polling avoids overlapping reads and discards an in-flight response on cleanup', async t => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const response = deferred<BackendActivePlayerStatus>();
  const statuses: BackendActivePlayerStatus[] = [];
  let reads = 0;
  const stop = pollActivePlayback(() => {
    reads++;
    return reads === 1 ? Promise.resolve({ active: true }) : response.promise;
  }, status => statuses.push(status), () => true);

  t.mock.timers.tick(500);
  await Promise.resolve();
  assert.deepEqual(statuses, [{ active: true }]);
  t.mock.timers.tick(500);
  t.mock.timers.tick(1000);
  assert.equal(reads, 2);
  stop();
  response.resolve({ active: false });
  await Promise.resolve();
  t.mock.timers.tick(1000);
  assert.equal(reads, 2);
  assert.deepEqual(statuses, [{ active: true }]);
});
