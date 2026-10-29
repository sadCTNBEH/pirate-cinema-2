import test from 'node:test';
import assert from 'node:assert/strict';
import { resumeDestination } from '../src/services/resumeDestination.ts';

const recent = {torrent_hash:'release', file_index:7, file_name:'Show.S02E03.mkv', title:'Show',
  imdb_id:'tt1234567', media_type:'series' as const, season:2, episode:3,
  playback_timecode:137, playback_duration:1800};

test('continue watching opens the original card and preserves the exact torrent, file, season and position', () => {
  const destination = resumeDestination(recent)!;
  assert.equal(destination.route, 'meta');
  assert.equal(destination.params.imdb, 'tt1234567');
  assert.equal(destination.params.type, 'series');
  assert.equal(destination.params.targetSeason, 2);
  assert.deepEqual(destination.params.torrentResume, {
    hash:'release', title:'Show', poster:undefined, fileId:7, fileName:'Show.S02E03.mkv',
    startTime:137, targetSeason:2, targetEpisode:3,
  });
});

test('a movie opens its card; watched files restart and index zero is preserved', () => {
  const destination = resumeDestination({...recent, file_index:0, season:null, episode:null,
    media_type:'movie', is_watched:true})!;
  assert.equal(destination.params.type, 'movie');
  assert.equal(destination.params.torrentResume?.fileId, 0);
  assert.equal(destination.params.torrentResume?.startTime, 0);
});

test('missing catalog identity opens the existing torrent detail page with a file list', () => {
  const destination = resumeDestination({...recent, imdb_id:null, season:0})!;
  assert.equal(destination.route, 'detail');
  assert.equal(destination.params.hash, 'release');
  assert.equal(destination.params.targetSeason, 0);
  assert.equal(destination.params.torrentResume?.fileId, 7);
  assert.equal(resumeDestination({...recent, imdb_id:'release'})?.route, 'detail');
});

test('online and anime playback keep their existing resume flows', () => {
  assert.equal(resumeDestination({...recent, torrent_hash:'online:rutube:id'}), null);
  assert.equal(resumeDestination({...recent, anime_playback:{} as never}), null);
});
