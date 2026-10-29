import test from 'node:test';
import assert from 'node:assert/strict';
import { rankReleases } from '../src/utils/torrentSelection.ts';

const release = (title: string, seeders = 10) => ({title, seeders, hash: title});

test('title aliases and year reject remakes, unrelated titles and sequels regardless of seeds', () => {
  const results = rankReleases([
    release('Dune (1984) 1080p', 9999), release('Dune Part Two (2024) 1080p', 9999),
    release('Дюна / Dune (2021) 1080p', 1), release('Dune Messiah (2021) 1080p', 900),
  ], ['Dune', 'Дюна'], 2021);
  assert.deepEqual(results.map(r => r.title), ['Дюна / Dune (2021) 1080p']);
});

test('season and episode identity precede seeds and support season collections', () => {
  const results = rankReleases([
    release('Show (2020) S02E03', 999), release('Show (2020) S01E02', 999),
    release('Show (2020) S01E03', 1), release('Show (2020) S01-S03', 50),
  ], ['Show'], 2020, 1, 3);
  assert.deepEqual(results.map(r => r.title), ['Show (2020) S01E03', 'Show (2020) S01-S03']);
});

test('unknown year requires user selection, a movie never chooses a series pack', () => {
  assert.equal(rankReleases([release('Dune 1080p')], ['Dune'], 2021).length, 1);
  assert.equal(rankReleases([release('Dune 1080p')], ['Dune'], 2021, undefined, undefined, true).length, 0);
  assert.equal(rankReleases([release('Dune (2021) S01')], ['Dune'], 2021).length, 0);
});

test('known quality wins over high seeds only after identity has matched', () => {
  const results = rankReleases([release('Movie (2020) 480p', 99999),
    release('Movie (2020) 1080p', 1)], ['Movie'], 2020);
  assert.equal(results[0].title, 'Movie (2020) 1080p');
});

test('VisionQuest partial season ranges never advertise a missing episode', () => {
  const partial = release('Квест Вижна / Квест Вижена / VisionQuest [01x01-02 из 08] (2026) WEB-DL 1080p', 999);
  const available = release('Квест Вижна / VisionQuest [01x01-05 из 08] (2026) WEB-DL 1080p', 1);
  assert.deepEqual(rankReleases([partial, available], ['VisionQuest', 'Квест Вижна'], 2026, 1, 3), [available]);
  assert.deepEqual(rankReleases([partial, available], ['VisionQuest'], 2026, 1, 6), []);
  assert.equal(rankReleases([partial], ['VisionQuest'], 2026, 1, 2).length, 1);
  assert.equal(rankReleases([release('Show (2026) [01-02 из 08]')], ['Show'], 2026, 1, 3).length, 0);
});
