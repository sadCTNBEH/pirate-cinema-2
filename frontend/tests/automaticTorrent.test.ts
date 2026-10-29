import test from 'node:test';
import assert from 'node:assert/strict';
import { findPlayableRelease } from '../src/services/automaticTorrent.ts';

const releases = [{hash:'partial', title:'VisionQuest (Season 1)', magnet:'magnet:partial'},
  {hash:'complete', title:'VisionQuest (Season 1)', magnet:'magnet:complete'}];

test('automatic release choice verifies actual file availability and skips a misleading season pack', async () => {
  const calls: string[] = [];
  const result = await findPlayableRelease(releases, {season:1, episode:3}, {
    async addTorrent() {throw Error('Known metadata must not be fetched again');},
    async selectTorrentFile(request) {
      calls.push(request.hash);
      const file = request.hash === 'complete' ? {id:7, name:'S01E03.mkv', length:100, season:1, episode:3} : null;
      return {file, candidates:file ? [file] : [], reason:'', metadata_ready:true};
    },
  }, new AbortController().signal);
  assert.equal(result?.hash, 'complete');
  assert.deepEqual(calls, ['partial', 'complete']);
});

test('no verified episode means no automatic release, requests are capped at three', async () => {
  let calls = 0;
  const result = await findPlayableRelease([...releases, ...releases], {season:1, episode:3}, {
    async addTorrent() {throw Error('Do not add known torrents');},
    async selectTorrentFile() {calls++; return {file:null,candidates:[],reason:'missing',metadata_ready:true};},
  }, new AbortController().signal);
  assert.equal(result, null);
  assert.equal(calls, 3);
});

test('a cancelled selection never inspects or opens another release', async () => {
  const controller = new AbortController(); controller.abort();
  await assert.rejects(findPlayableRelease(releases, {}, {
    async addTorrent() {throw Error('Must not run');},
    async selectTorrentFile() {throw Error('Must not run');},
  }, controller.signal), {name:'AbortError'});
});
