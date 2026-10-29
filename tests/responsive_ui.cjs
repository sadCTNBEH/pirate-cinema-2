// Real React controls with mocked API data; no application processes are changed.
const { chromium } = require('playwright');
const esbuild = require('../frontend/node_modules/esbuild');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, 'build', 'responsive-qa');
  fs.mkdirSync(output, { recursive: true });
  const stub = path.join(output, 'context.ts');
  fs.writeFileSync(stub, `export const useApp=()=>({t:(key)=>({continue_watching:'Продолжить просмотр',history:'История',continue:'Продолжить'}[key]||key),route:'home',activePlayback:null,isPip:false,isAnyModalOpen:false,navigate:()=>{},goBack:()=>{},openPlayback:()=>{},closePlayback:()=>{},togglePip:()=>{}});`);
  const entry = path.join(output, 'entry.tsx');
  fs.writeFileSync(entry, `import React from 'react';
import {createRoot} from 'react-dom/client';
import {ResponsiveToolbar} from '../../frontend/src/components/ui/ResponsiveToolbar';
import {Button,Select} from '../../frontend/src/components/ui/UIComponents';
import {HistoryView} from '../../frontend/src/components/history/HistoryView';
import {HomeView} from '../../frontend/src/components/home/HomeView';
import {moveFocus} from '../../frontend/src/input/focus';
window.actions=[]; window.pad=moveFocus;
function Fixture(){ return <div className="cinema-shell" style={{padding:24}}>
{location.pathname==='/history'?<HistoryView/>:location.pathname==='/home'?<HomeView/>:
<div style={{width:'100%'}}><ResponsiveToolbar label="Тест" items={[
{id:'play',priority:100,content:<Button onClick={()=>window.actions.push('play')}>Основное действие</Button>},
{id:'favorite',priority:50,content:<Button onClick={()=>window.actions.push('favorite')}>Добавить в избранное</Button>},
{id:'delete',priority:10,content:<Button onClick={()=>window.actions.push('delete')}>Удалить запись</Button>},
{id:'season',priority:5,content:<Select aria-label="Сезон" value="1" onChange={e=>window.actions.push(e.target.value)}><option value="1">Первый сезон</option><option value="2">Второй сезон</option></Select>}
]}/></div>}</div>}
createRoot(document.getElementById('root')).render(<Fixture/>);`);
  await esbuild.build({entryPoints:[entry], bundle:true, outfile:path.join(output,'app.js'),
    jsx:'automatic', platform:'browser', nodePaths:[path.join(root,'frontend/node_modules')], plugins:[{name:'mock-context',setup(build){
      build.onResolve({filter:/context\/AppContext$/},()=>({path:stub}));
    }}]});
  const cssName = fs.readdirSync(path.join(root,'static/assets')).find(name=>name.endsWith('.css'));
  const browser = await chromium.launch({headless:true, channel:'chrome'});
  const entryData = {id:'torrent:1', torrent_hash:'torrent',file_index:1,file_name:'Release.S01E02.1080p.mkv',
    title:'Понятное название сериала',poster_url:'/poster.png',season:1,episode:2,
    playback_timecode:120,playback_duration:1800,is_watched:false,last_played_at:'2026-10-29T00:00:00Z'};
  const errors=[];
  try {
    const page = await browser.newPage({viewport:{width:1200,height:900}});
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('http://ui.test/**',route=>{
      const url=new URL(route.request().url());
      if(['/','/history','/home'].includes(url.pathname)) return route.fulfill({contentType:'text/html',body:'<html lang="ru"><head><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/app.css"></head><body><div id="root"></div><script src="/app.js"></script></body></html>'});
      if(url.pathname==='/app.js') return route.fulfill({contentType:'text/javascript',body:fs.readFileSync(path.join(output,'app.js'))});
      if(url.pathname==='/app.css') return route.fulfill({contentType:'text/css',body:fs.readFileSync(path.join(root,'static/assets',cssName))});
      if(url.pathname==='/poster.png') return route.fulfill({contentType:'image/png',body:fs.readFileSync(path.join(root,'static/logo.png'))});
      if(url.pathname==='/api/history'||url.pathname==='/api/history/continue') return route.fulfill({json:[entryData]});
      return route.fulfill({json:[]});
    });
    await page.goto('http://ui.test/');
    assert.equal(await page.getByRole('button',{name:'Ещё: Тест'}).count(),0);
    await page.getByRole('button',{name:'Основное действие',exact:true}).click();
    await page.setViewportSize({width:390,height:844});
    await page.getByRole('button',{name:'Ещё: Тест'}).waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.getByRole('button',{name:'Ещё: Тест'}).click();
    await page.getByRole('menu').getByRole('button',{name:'Добавить в избранное'}).click();
    assert.deepEqual(await page.evaluate(()=>window.actions),['play','favorite']);
    await page.getByRole('button',{name:'Ещё: Тест'}).click();
    await page.keyboard.press('Escape');
    assert.equal(await page.getByRole('menu').count(),0);
    await page.getByRole('button',{name:'Ещё: Тест'}).click();
    await page.evaluate(()=>window.pad('down'));
    assert.equal(await page.getByRole('menu').evaluate(el=>el.contains(document.activeElement)),true);
    await page.evaluate(()=>window.dispatchEvent(new CustomEvent('cinema-select',{detail:document.querySelector('[role="menu"] select')})));
    await page.getByRole('button',{name:'Второй сезон',exact:true}).click();
    assert.equal((await page.evaluate(()=>window.actions)).at(-1),'2');
    await page.getByRole('button',{name:'Ещё: Тест'}).click();
    await page.evaluate(()=>document.querySelector('[data-focus-scope] [data-dialog-close]').click());
    assert.equal(await page.getByRole('menu').count(),0);
    await page.setViewportSize({width:1200,height:900});
    await page.getByRole('button',{name:'Добавить в избранное',exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'Ещё: Тест'}).count(),0);
    await page.addInitScript(item=>sessionStorage.setItem('pc_recent_items',JSON.stringify([{...item,title:'Old.Release',poster_url:null}])),entryData);
    for(const route of ['home','history']){
      for(const width of [390,1280]){
        await page.setViewportSize({width,height:900});
        await page.goto('http://ui.test/'+route);
        await page.getByText(entryData.title,{exact:true}).first().waitFor();
        await page.getByRole('img',{name:entryData.title}).first().waitFor();
        assert.equal(await page.getByRole('img',{name:entryData.title}).first().evaluate(img=>img.complete&&img.naturalWidth>0),true);
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,route+' overflow at '+width);
        await page.screenshot({path:path.join(output,route+'-'+width+'.png'),fullPage:true});
      }
    }
    assert.deepEqual(errors,[]);
    console.log('Responsive actions, keyboard/gamepad focus, select menu, restored actions, home/history artwork passed.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
