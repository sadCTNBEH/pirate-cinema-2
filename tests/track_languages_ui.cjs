const {chromium}=require('playwright');
const esbuild=require('../frontend/node_modules/esbuild');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'..'),output=path.join(root,'build','track-languages-qa');
 fs.mkdirSync(output,{recursive:true});
 const stub=path.join(output,'context.ts');
 fs.writeFileSync(stub,`export const useApp=()=>({lang:'ru',t:key=>({save_settings:'Сохранить настройки',mpv_player:'Видеоплеер MPV',mpv_path:'Путь к MPV',saved:'Настройки сохранены'}[key]||key),reloadI18n:async()=>{},route:'settings',navigate:()=>{}});`);
 const input=path.join(output,'input.ts');
 fs.writeFileSync(input,`export const useInput=()=>({bindings:{},save:async()=>{},record:()=>{},recording:null,error:null});`);
 const entry=path.join(output,'entry.tsx');
 fs.writeFileSync(entry,`import React from 'react';import{createRoot}from'react-dom/client';import{SettingsView}from'../../frontend/src/components/settings/SettingsView';createRoot(document.getElementById('root')).render(<div className="cinema-theme" style={{padding:24}}><SettingsView hideHeader/></div>);`);
 await esbuild.build({entryPoints:[entry],bundle:true,outfile:path.join(output,'app.js'),jsx:'automatic',platform:'browser',nodePaths:[path.join(root,'frontend/node_modules')],define:{__APP_VERSION__:'"test"'},plugins:[{name:'context',setup(build){build.onResolve({filter:/context\/AppContext$/},()=>({path:stub}));build.onResolve({filter:/InputProvider$/},()=>({path:input}));}}]});
 const css=fs.readFileSync(path.join(root,'static/assets',fs.readdirSync(path.join(root,'static/assets')).find(file=>file.endsWith('.css'))));
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 let settings={torrserver_url:'http://localhost',language:'ru',audio_languages:['ru','en'],subtitle_languages:['off']},saved;
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  await page.route('http://tracks.test/**',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/app.js')return route.fulfill({contentType:'text/javascript',body:fs.readFileSync(path.join(output,'app.js'))});
   if(url.pathname==='/app.css')return route.fulfill({contentType:'text/css',body:css});
   if(url.pathname==='/api/settings'){
    if(route.request().method()==='POST'){saved=route.request().postDataJSON();settings={...settings,...saved};return route.fulfill({json:{success:true}});}
    return route.fulfill({json:settings});
   }
   if(url.pathname.startsWith('/api/')||url.pathname==='/version.json')return route.fulfill({json:{}});
   return route.fulfill({contentType:'text/html',body:'<link rel="stylesheet" href="/app.css"><div id="root"></div><script src="/app.js"></script>'});
  });
  page.on('pageerror',error=>console.error('Page error:',error.message));
  await page.goto('http://tracks.test/');
  await page.waitForFunction(()=>document.querySelector('#audio-language-1')?.value==='en');
  assert.equal(await page.locator('#subtitle-language-0').inputValue(),'off');
  await page.locator('#audio-language-0').selectOption('en');
  await page.locator('#audio-language-1').selectOption('ru');
  await page.locator('#audio-language-2').selectOption('original');
  await page.getByRole('button',{name:'Сохранить настройки',exact:true}).click();
  await page.waitForTimeout(100);
  assert.deepEqual(saved.audio_languages,['en','ru','original']);
  assert.deepEqual(saved.subtitle_languages,['off']);
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#audio-language-2')?.value==='original');
  const section=page.locator('.ui-settings-section').filter({has:page.locator('#player-path')});
  await section.screenshot({path:path.join(output,'settings-1280.png')});
  await page.setViewportSize({width:390,height:900});
  await section.screenshot({path:path.join(output,'settings-390.png')});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'settings must not overflow');
  await page.locator('#audio-language-0').selectOption('auto');
  assert.equal(await page.locator('#audio-language-1').count(),0);
  await page.locator('#subtitle-language-0').selectOption('ru');
  await page.locator('#subtitle-language-1').selectOption('en');
  assert.equal(await page.locator('#subtitle-language-2').inputValue(),'');
  console.log('Language settings UI: ordered priorities, subtitle off, save/reload, automatic mode and responsive layout passed.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
