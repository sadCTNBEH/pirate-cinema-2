import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { playerEnded, preferredYummyPlayer } from '../src/services/webPlayer';

Object.defineProperty(globalThis, 'location', {value:{href:'http://127.0.0.1:8018/'},configurable:true});

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

test('Alloha observer attaches only on its host and reports content end once per play', () => {
  const source=readFileSync(new URL('../../backend/infrastructure/web_player_events.py',import.meta.url),'utf8').split('r"""')[1].split('"""')[0];
  const run=(hostname: string)=>{
    const events:Record<string,()=>void>={};const messages:unknown[]=[];let poll:(()=>void)|undefined;
    const window={parent:{postMessage:(value:unknown)=>messages.push(value)},addEventListener:()=>{}};
    vm.runInNewContext(source,{location:{protocol:'https:',hostname},window,player:{on:(key:string,callback:()=>void)=>{events[key]=callback;}},setInterval:(callback:()=>void)=>{poll=callback;return 1;},clearInterval:()=>{}});
    poll?.();return {events,messages};
  };
  assert.deepEqual(run('unrelated.test').events,{});
  const {events,messages}=run('alloha.yani.tv');
  assert.deepEqual(Object.keys(events),['play','ended']);
  events.ended();events.ended();events.play();events.ended();
  assert.equal(messages.length,3); // Ready, then one completion for each play.
});

