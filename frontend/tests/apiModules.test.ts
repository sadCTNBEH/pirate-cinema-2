import test from 'node:test';
import assert from 'node:assert/strict';
import { API, DEFAULT_FALLBACK_STRINGS, parseJsonResponse } from '../src/services/api';
import { playbackApi } from '../src/services/api/playbackApi';
import { libraryApi } from '../src/services/api/libraryApi';
import { searchApi } from '../src/services/api/searchApi';
import { settingsApi } from '../src/services/api/settingsApi';

test('api modules: domain modules export dedicated methods', () => {
  // playbackApi
  assert.equal(typeof playbackApi.playFile, 'function');
  assert.equal(typeof playbackApi.stopPlayback, 'function');
  assert.equal(typeof playbackApi.getActivePlayback, 'function');
  assert.equal(typeof playbackApi.togglePip, 'function');
  assert.equal(typeof playbackApi.togglePlayerFullscreen, 'function');
  assert.equal(typeof playbackApi.addMagnet, 'function');
  assert.equal(typeof playbackApi.selectTorrentFile, 'function');

  // libraryApi
  assert.equal(typeof libraryApi.getLibrary, 'function');
  assert.equal(typeof libraryApi.getLibraryWithCount, 'function');
  assert.equal(typeof libraryApi.getRecent, 'function');
  assert.equal(typeof libraryApi.getCollection, 'function');
  assert.equal(typeof libraryApi.getHistory, 'function');
  assert.equal(typeof libraryApi.getTorrentFiles, 'function');
  assert.equal(typeof libraryApi.deleteTorrent, 'function');

  // searchApi
  assert.equal(typeof searchApi.searchTorrents, 'function');
  assert.equal(typeof searchApi.searchAnime, 'function');
  assert.equal(typeof searchApi.searchMeta, 'function');
  assert.equal(typeof searchApi.searchOnline, 'function');

  // settingsApi
  assert.equal(typeof settingsApi.getSettings, 'function');
  assert.equal(typeof settingsApi.saveSettings, 'function');
  assert.equal(typeof settingsApi.getServerStatus, 'function');
  assert.equal(typeof settingsApi.getI18n, 'function');
  assert.equal(typeof settingsApi.getSystemDiagnostics, 'function');
  assert.equal(typeof settingsApi.checkUpdate, 'function');
});

test('api modules: API facade contains all domain methods for backward compatibility', () => {
  assert.equal(typeof API.playFile, 'function');
  assert.equal(typeof API.stopPlayback, 'function');
  assert.equal(typeof API.getLibrary, 'function');
  assert.equal(typeof API.searchTorrents, 'function');
  assert.equal(typeof API.getSettings, 'function');
  assert.equal(typeof API.getServerStatus, 'function');
  assert.equal(typeof API.getI18n, 'function');
  assert.equal(typeof API.getTorrentFiles, 'function');
});

test('api modules: parseJsonResponse validates and parses JSON or throws on HTML', () => {
  assert.deepEqual(parseJsonResponse('{"ok": true}', '/test'), { ok: true });
  assert.deepEqual(parseJsonResponse('', '/test'), {});
  assert.throws(() => parseJsonResponse('<!DOCTYPE html><html></html>', '/api/test'), /HTML вместо JSON/);
});

test('api modules: fallback strings are defined and accessible', () => {
  assert.ok(DEFAULT_FALLBACK_STRINGS.nav_library);
  assert.ok(DEFAULT_FALLBACK_STRINGS.nav_settings);
});
