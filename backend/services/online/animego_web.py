"""Small host for the site's official players; never resolves media streams."""
import json


def player_html(data):
    config = json.dumps(data, ensure_ascii=True).replace('<', '\\u003c')
    return '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<style>html,body,#root,iframe,video-player{margin:0;width:100%;height:100%;border:0;background:#000;color:#fff;overflow:hidden}iframe,video-player{display:block}#status{position:absolute;top:8px;left:12px;font:14px sans-serif;z-index:2}a{color:#fff}</style>
<div id="status">Загружается плеер…</div><div id="root"></div><script>
const data=CONFIG, config=data.config, root=document.getElementById('root'), status=document.getElementById('status');
let frame, ready=false;
function failed(){status.textContent='Плеер не ответил. Повторите запуск или выберите другой плеер.';}
function loaded(){ready=true;status.hidden=true;}
function kodikUrl(value){try{const u=new URL(value);if(u.protocol!=='https:'||!/(^|\\.)kodik(player)?\\.(com|info|biz|cc)$/.test(u.hostname))return null;
if(u.pathname.startsWith('/serial/'))u.searchParams.set('episode',String(data.episode));return u.href;}catch{return null;}}
function showFrame(src){frame=document.createElement('iframe');frame.src=src;frame.setAttribute('sandbox','allow-scripts allow-same-origin allow-forms allow-presentation');frame.setAttribute('scrolling','no');frame.style.overflow='hidden';frame.allow='autoplay; fullscreen; encrypted-media; picture-in-picture';frame.allowFullscreen=true;frame.referrerPolicy='strict-origin-when-cross-origin';frame.onerror=failed;frame.onload=loaded;root.replaceChildren(frame);}
showFrame(kodikUrl(config.src));
window.addEventListener('message',event=>{
if(event.source===window.parent && event.origin===location.origin && event.data?.type==='pc-kodik-api'){
const target=frame && kodikUrl(frame.src);const episode=Number(event.data.episode);
if(target && Number.isInteger(episode) && episode>0)frame.contentWindow.postMessage({key:'kodik_player_api',value:{method:'change_episode',episode,without_reload:true}},new URL(target).origin);return;
}
if(!frame||event.source!==frame.contentWindow)return;
let origin;try{origin=new URL(frame.src).origin;}catch{return;}if(event.origin!==origin)return;
if(event.data?.agp==='kodik'){const url=kodikUrl(event.data.url);if(url){showFrame(url);loaded();}}
if(event.data?.key?.startsWith('kodik_player_')){loaded();
if(kodikUrl(frame.src) && ['kodik_player_current_episode','kodik_player_video_ended'].includes(event.data.key))window.parent.postMessage({type:'pc-kodik',key:event.data.key,value:event.data.value},location.origin);
}
if(event.data?.agp==='ready')loaded();
});
setTimeout(()=>{if(!ready)failed();},20000);
</script></html>'''.replace('CONFIG', config)
