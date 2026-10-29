// SWR hook mounted in real React: controlled network responses exercise races and offline use.
const { chromium } = require('playwright');
const esbuild = require('../frontend/node_modules/esbuild');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, 'build', 'catalog-swr-qa');
  fs.mkdirSync(output, {recursive:true});
  const entry = path.join(output, 'entry.tsx');
  fs.writeFileSync(entry, `import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import {useCatalog} from '../../frontend/src/services/catalogCache';
function Item({url}) { const {data,loading,reload}=useCatalog(url,1000,100000); return <section><span data-result>{data?.title || (loading?'skeleton':'empty')}</span><button onClick={reload}>retry</button></section>; }
function App(){ const [url,setURL]=useState('/api/library/meta/tt1?type=movie&lang=ru'); window.change=setURL; return <><Item url={url}/><Item url={url}/></>; }
createRoot(document.getElementById('root')).render(<App/>);`);
  await esbuild.build({entryPoints:[entry],bundle:true,outfile:path.join(output,'app.js'),jsx:'automatic',platform:'browser',nodePaths:[path.join(root,'frontend/node_modules')]});
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  try {
    const page = await browser.newPage();
    const calls=[];
    const held=[];
    let mode='hold';
    await page.route('http://swr.test/**',async route=>{
      const url = new URL(route.request().url());
      if (url.pathname==='/app.js') return route.fulfill({contentType:'text/javascript',body:fs.readFileSync(path.join(output,'app.js'))});
      if (!url.pathname.startsWith('/api/')) return route.fulfill({contentType:'text/html',body:'<div id="root"></div><script src="/app.js"></script>'});
      calls.push(url.pathname+url.search);
      if(mode==='hold'){held.push(route);return;}
      if(mode==='error') return route.fulfill({status:503,body:'offline'});
      return route.fulfill({contentType:'application/json',body:JSON.stringify({title:'Fresh'})});
    });
    const key='/api/library/meta/tt1?type=movie&lang=ru';
    const storage='pc_catalog_swr_v1';
    const expectTitle=async text=>page.waitForFunction(text=>[...document.querySelectorAll('[data-result]')].every(el=>el.textContent===text),text);
    const respond=async(title,stale=false,index=0)=>held.splice(index,1)[0].fulfill({contentType:'application/json',headers:{'X-Catalog-Stale':stale?'1':'0'},body:JSON.stringify({title})});
    await page.goto('http://swr.test/');
    await expectTitle('skeleton');
    await page.waitForFunction(()=>!!document.querySelector('[data-result]'));
    await page.waitForTimeout(60);
    assert.equal(calls.length,1,'two consumers must share a cold request');
    await respond('Cold');
    await expectTitle('Cold');
    mode='error';
    await page.reload();
    await expectTitle('Cold');
    assert.equal(calls.length,1,'fresh session cache must not request the server');

    // An old entry remains visible while the shared revalidation is held.
    await page.evaluate(({key,storage})=>sessionStorage.setItem(storage,JSON.stringify([[key,{data:{title:'Stale'},updated:Date.now()-2000}]])),{key,storage});
    mode='hold';
    await page.reload();
    await expectTitle('Stale');
    await page.waitForTimeout(60);
    assert.equal(calls.length,2);
    await respond('Updated');
    await expectTitle('Updated');

    // Network failure keeps the stale entry and does not renew its timestamp.
    await page.evaluate(({key,storage})=>sessionStorage.setItem(storage,JSON.stringify([[key,{data:{title:'Offline'},updated:Date.now()-2000}]])),{key,storage});
    mode='error';
    await page.reload();
    await expectTitle('Offline');
    await page.waitForTimeout(80);
    const persisted=await page.evaluate(storage=>JSON.parse(sessionStorage.getItem(storage))[0][1],storage);
    assert.ok(Date.now()-persisted.updated>=2000);

    // No browser cache: server stale content must appear before background response.
    await page.evaluate(()=>sessionStorage.clear());
    mode='hold';
    await page.reload();
    await expectTitle('skeleton');
    await page.waitForTimeout(60);
    await respond('Disk stale',true);
    await expectTitle('Disk stale');
    await page.waitForTimeout(60);
    assert.ok(calls.at(-1).endsWith('refresh=true'));
    await respond('Disk updated');
    await expectTitle('Disk updated');

    // Switch keys before an old response finishes: never paint the old movie on the new page.
    await page.evaluate(()=>window.change('/api/library/meta/tt2?type=series&lang=en'));
    await expectTitle('skeleton');
    await page.waitForTimeout(60);
    assert.ok(calls.at(-1).includes('tt2?type=series&lang=en'));
    const old=held.shift();
    await page.evaluate(()=>window.change('/api/library/meta/tt3?type=movie&lang=ru'));
    await page.waitForTimeout(60);
    await respond('Third');
    await expectTitle('Third');
    await old.fulfill({contentType:'application/json',body:JSON.stringify({title:'Wrong old response'})}).catch(()=>{});
    await page.waitForTimeout(60);
    await expectTitle('Third');
    assert.equal(calls.filter(call=>call.includes('tt2?')).length,1);
    console.log('SWR UI: fresh, stale, updates, offline, deduplication, cold skeleton, disk cache, parameter isolation and late-response race passed.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
