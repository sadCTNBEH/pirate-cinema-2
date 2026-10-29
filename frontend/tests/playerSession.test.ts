import test from 'node:test';
import assert from 'node:assert/strict';
import { canShowNativePlayer, playbackSessionKey, seasonKeyForFile, shouldAdoptBackendPlayback } from '../src/services/playerSession.ts';

const ready = {requestedHash:'new', resolvedHash:'new', running:true, ready:true, loading:false, starting:false, blocked:false};

test('native panel remains hidden on errors, choices, startup and stale backend playback', () => {
  assert.equal(canShowNativePlayer(ready), true);
  for (const patch of [{running:false}, {ready:false}, {loading:true}, {starting:true},
    {blocked:true}, {resolvedHash:'old'}, {requestedHash:undefined}]) {
    assert.equal(canShowNativePlayer({...ready, ...patch}), false);
  }
});

test('background synchronization cannot replace a pending release or reopen stopped playback', () => {
  const local = {hash:'new', title:'New', isPlaying:true};
  const old = {hash:'old', active:true};
  assert.equal(shouldAdoptBackendPlayback(local, old, 'new'), false);
  assert.equal(shouldAdoptBackendPlayback(null, old, 'stopped'), false);
  assert.equal(shouldAdoptBackendPlayback(null, old, null), true);
  assert.equal(shouldAdoptBackendPlayback(local, {hash:'new', active:true}, null), false);
});

test('session identity includes episode and absolute numbering, ignores incidental object identity', () => {
  const local = {hash:'show', title:'Show', isPlaying:true, targetSeason:1, targetEpisode:3};
  assert.equal(playbackSessionKey(local), playbackSessionKey({...local, title:'Updated'}));
  assert.notEqual(playbackSessionKey(local), playbackSessionKey({...local, targetEpisode:4}));
  assert.notEqual(playbackSessionKey(local), playbackSessionKey({...local, absoluteEpisode:25}));
});

test('resumed files select their actual season including specials and nonzero file indices', () => {
  const data = {seasons:{'0':[{id:0,name:'OVA.mkv',length:1}], '2':[{id:7,name:'S02E03.mkv',length:1}]}};
  assert.equal(seasonKeyForFile(data, 7), '2');
  assert.equal(seasonKeyForFile(data, 0), '0');
  assert.equal(seasonKeyForFile(data, 7, 3), '3');
});
