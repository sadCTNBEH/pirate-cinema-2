import { test } from 'node:test';
import assert from 'node:assert/strict';
import { scrollPageTo } from '../src/services/pageScroll';

test('release navigation scrolls the content pane, not its outer ancestors',()=>{
  const original=globalThis.document;
  const calls:unknown[]=[];
  const target={getBoundingClientRect:()=>({top:540}),scrollIntoView:()=>{throw new Error('would scroll the shell');}};
  const pane={scrollTop:120,clientTop:0,getBoundingClientRect:()=>({top:36}),contains:(value:unknown)=>value===target,scrollTo:(value:unknown)=>calls.push(value)};
  Object.defineProperty(globalThis,'document',{configurable:true,value:{getElementById:(id:string)=>id==='page-container'?pane:id==='cinema-releases'?target:null}});
  try{
    scrollPageTo('cinema-releases','smooth');
    assert.deepEqual(calls,[{top:624,behavior:'smooth'}]);
    scrollPageTo('missing');
    assert.equal(calls.length,1);
  }finally{Object.defineProperty(globalThis,'document',{configurable:true,value:original});}
});
