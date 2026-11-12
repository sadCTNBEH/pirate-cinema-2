import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { animegoPlayerStatus, playerEnded, playerStarted, preferredYummyPlayer } from '../src/services/webPlayer';

Object.defineProperty(globalThis, 'location', {value:{href:'http://127.0.0.1:8018/',origin:'http://127.0.0.1:8018'},configurable:true});

test('Yummy always prefers CVH then Alloha, retaining voice within that player',()=>{
  const items=[{player:'Плеер Kodik',dubbing:'Old voice'},{player:'Плеер Alloha',dubbing:'Old voice'},{player:'Плеер CVH',dubbing:'Default'},{player:'Плеер CVH',dubbing:'Preferred'}];
  assert.equal(preferredYummyPlayer(items,'Preferred'),items[3]);
  assert.equal(preferredYummyPlayer(items,'Old voice'),items[2]);
  assert.equal(preferredYummyPlayer(items.slice(0,2),'Old voice'),items[1]);
  assert.equal(preferredYummyPlayer(items.slice(0,1)),items[0]);
  assert.equal(preferredYummyPlayer([]),undefined);
});

test('provider end messages are accepted only from the selected player origin', () => {
  assert.equal(playerEnded('CVH','https://ru.yummyani.me/iframeCVH.html','https://ru.yummyani.me',{key:'player_video_ended'}),true);
  assert.equal(playerEnded('CVH','https://ru.yummyani.me/iframeCVH.html','https://other.test',{key:'player_video_ended'}),false);
  assert.equal(playerEnded('Kodik','https://kodikplayer.com/serial/1','https://kodikplayer.com',{key:'kodik_player_video_ended'}),true);
  assert.equal(playerEnded('Alloha','https://alloha.yani.tv/','https://alloha.yani.tv',{type:'pc-alloha',event:'ended'}),true);
  for(const data of [{event:'adEnd'},'{invalid}',{type:'pc-alloha',event:'ready'}])
    assert.equal(playerEnded('Alloha','https://alloha.yani.tv/','https://alloha.yani.tv',data),false);
});

test('playback start messages require the selected origin and a known event shape', () => {
  assert.equal(playerStarted('Kodik','https://kodikplayer.com/serial/1','https://kodikplayer.com',{key:'kodik_player_video_started'}),true);
  assert.equal(playerStarted('Kodik','https://kodikplayer.com/serial/1','https://kodikplayer.com',{key:'kodik_player_play'}),true);
  assert.equal(playerStarted('Kodik','https://kodikplayer.com/serial/1','https://evil.test',{key:'kodik_player_video_started'}),false);
  assert.equal(playerStarted('CVH','https://ru.yummyani.me/iframeCVH.html','https://ru.yummyani.me',{key:'player_video_started'}),true);
  assert.equal(playerStarted('CHV','https://ru.yummyani.me/iframeCVH.html','https://ru.yummyani.me',{key:'player_video_started'}),true);
  assert.equal(playerStarted('CVH','https://ru.yummyani.me/iframeCVH.html','https://ru.yummyani.me',{key:'player_time_update',value:1.2}),true);
  assert.equal(playerStarted('CVH','https://ru.yummyani.me/iframeCVH.html','https://ru.yummyani.me',{key:'player_time_update',value:0}),false);
  assert.equal(playerStarted('Alloha','https://alloha.yani.tv/','https://alloha.yani.tv',{type:'pc-alloha',event:'started'}),true);
  for(const value of [{key:'play'},{key:'kodik_player_video_ended'},'{invalid}',null])
    assert.equal(playerStarted('Kodik','https://kodikplayer.com/serial/1','https://kodikplayer.com',value),false);
});

test('AnimeGo iframe lifecycle distinguishes document load, player ready, actual start, error, and timeout', () => {
  const state=(phase:string,message='')=>animegoPlayerStatus('http://127.0.0.1:8018',{type:'pc-anime-player-state',phase,message});
  assert.deepEqual(state('page_loaded'),{phase:'page_loaded',message:''});
  assert.deepEqual(state('ready'),{phase:'ready',message:''});
  assert.deepEqual(state('playing'),{phase:'playing',message:''});
  assert.deepEqual(state('error','Kodik не ответил'),{phase:'error',message:'Kodik не ответил'});
  assert.equal(animegoPlayerStatus('https://evil.test',{type:'pc-anime-player-state',phase:'playing'}),null);
  assert.equal(animegoPlayerStatus('http://127.0.0.1:8018',{type:'pc-anime-player-state',phase:'ended'}),null);
  assert.notEqual(state('page_loaded')?.phase,'playing');
});

test('Alloha observer attaches only on its host and reports content end once per play', () => {
  const source=readFileSync(new URL('../../backend/infrastructure/web_player_events.py',import.meta.url),'utf8').split('r"""')[1].split('"""')[0];
  const run=(hostname: string)=>{
    const events:Record<string,()=>void>={};const messages:unknown[]=[];let poll:(()=>void)|undefined;
    const window={parent:{postMessage:(value:unknown)=>messages.push(value)},addEventListener:()=>{}};
    const styles: {textContent: string}[] = [];
    const document = {documentElement: {appendChild: (style: {textContent: string}) => styles.push(style)},
      createElement: () => ({textContent: ''})};
    vm.runInNewContext(source,{location:{protocol:'https:',hostname},window,document,player:{on:(key:string,callback:()=>void)=>{events[key]=callback;}},setInterval:(callback:()=>void)=>{poll=callback;return 1;},clearInterval:()=>{}});
    poll?.();return {events,messages,styles};
  };
  assert.deepEqual(run('unrelated.test').events,{});
  const {events,messages,styles}=run('alloha.yani.tv');
  assert.match(styles[0].textContent, /\.allplay__ads--loader, \.allplay__poster\s*\{\s*cursor: default !important/);
  assert.deepEqual(Object.keys(events),['play','ended']);
  events.play();events.ended();events.ended();events.play();events.ended();
  assert.equal(messages.length,5); // Ready, actual play starts, and one completion per play.
});

