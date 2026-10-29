import test from 'node:test';
import assert from 'node:assert/strict';
import { formatEpisodeRelease } from '../src/utils/episodeRelease.ts';

test('episode timestamps use the computer timezone without UTC or milliseconds', () => {
  const previous = process.env.TZ;
  process.env.TZ = 'Asia/Yekaterinburg';
  try {
    assert.equal(formatEpisodeRelease('2026-10-29T21:30:00.000Z'), '30.10.2026, 02:30');
    assert.equal(formatEpisodeRelease('2026-10-29T21:30:00.000Z', 'en'), '30/10/2026, 02:30');
    assert.equal(formatEpisodeRelease('2026-10-29'), '29.10.2026');
    assert.equal(formatEpisodeRelease('invalid'), '');
  } finally {
    if (previous === undefined) delete process.env.TZ; else process.env.TZ = previous;
  }
});
