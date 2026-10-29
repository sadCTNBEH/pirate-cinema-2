import test from 'node:test';
import assert from 'node:assert/strict';
import { API } from '../src/services/api.ts';

test('stalled TorrServer requests are aborted; direct online playback skips DHT', { timeout: 20000 }, async () => {
  const original = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = ((_url, options) => {
    requests++;
    return new Promise((_resolve, reject) => {
      const signal = options?.signal;
      assert.ok(signal, 'TorrServer request must have a deadline');
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    });
  }) as typeof fetch;
  const keepAlive = setInterval(() => {}, 1000);
  try {
    const online = await API.getTorrentFiles('online:rutube:example', 'Episode');
    assert.equal(online.flat_files?.length, 1);
    assert.equal(requests, 0);
    const started = Date.now();
    const results = await Promise.allSettled([
      API.getTorrentFiles('dead-hash'), API.addTorrent('magnet:?xt=urn:btih:dead', 'Episode'),
    ]);
    assert.ok(results.every(result => result.status === 'rejected'));
    assert.equal(requests, 2);
    assert.ok(Date.now() - started < 19000, 'a stalled magnet must not leave DHT waiting forever');
  } finally {
    clearInterval(keepAlive);
    globalThis.fetch = original;
  }
});
