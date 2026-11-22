"""Small host for the site's official players; never resolves media streams."""
import json
import os


def player_html(data):
    data = dict(data)
    data['require_media_diagnostics'] = os.environ.get('PIRATE_CINEMA_KODIK_MEDIA_DIAGNOSTICS') == '1'
    config = json.dumps(data, ensure_ascii=True).replace('<', '\\u003c')
    return '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<style>html,body,#root,iframe,video-player{margin:0;width:100%;height:100%;border:0;background:#000;color:#fff;overflow:hidden}iframe,video-player{display:block}#status{position:absolute;top:8px;left:12px;font:14px sans-serif;z-index:2}a{color:#fff}</style>
<div id="status">Загружается плеер…</div><div id="root"></div><script>
const data=CONFIG, config=data.config, root=document.getElementById('root'), status=document.getElementById('status'), requireMediaDiagnostics=data.require_media_diagnostics===true;
let frame, phase='loading', timer, mediaFailure='';
function report(next,message=''){
if(next==='page_loaded'&&phase!=='loading')return;
phase=next;status.hidden=next==='playing';if(next==='playing')mediaFailure='';
if(next==='ready')status.textContent=message||'Плеер готов. Нажмите кнопку воспроизведения. Если видео останется чёрным, нажмите «Повторить» или выберите другой источник.';
if(next==='page_loaded')status.textContent='Страница плеера загружена; ожидаем готовности видео…';
if(next==='error')status.textContent=message||'Плеер не запустился. Повторите запуск или выберите другой источник.';
window.parent.postMessage({type:'pc-anime-player-state',phase:next,message:String(message).slice(0,180)},location.origin);
}
function failed(message){clearTimeout(timer);report('error',message);}
function playerReady(){clearTimeout(timer);report('ready');timer=setTimeout(()=>{if(phase==='ready')failed(mediaFailure||'Плеер готов, но видео не началось. Нажмите воспроизведение или выберите другой источник.');},45000);}
function kodikUrl(value,episode){try{const u=new URL(value);if(u.protocol!=='https:'||u.username||u.password||!/(^|\\.)kodik(player)?\\.(com|info|biz|cc)$/.test(u.hostname))return null;
if(episode!==undefined&&u.pathname.startsWith('/serial/')&&u.searchParams.get('episode')!==String(episode))u.searchParams.set('episode',String(episode));
return u.href;}catch{return null;}}
function showFrame(src){
mediaFailure='';
if(!src)return failed('AnimeGo вернул недопустимый адрес плеера.');
clearTimeout(timer);report('loading');
timer=setTimeout(()=>{if(phase==='loading'||phase==='page_loaded')failed(mediaFailure||'Kodik не сообщил о готовности. Проверьте доступность источника и попробуйте ещё раз.');},30000);
frame=document.createElement('iframe');frame.src=src;frame.setAttribute('sandbox','allow-scripts allow-same-origin allow-forms allow-presentation');frame.setAttribute('scrolling','no');frame.style.overflow='hidden';frame.allow='autoplay; fullscreen; encrypted-media; picture-in-picture';frame.allowFullscreen=true;frame.referrerPolicy='strict-origin-when-cross-origin';console.warn('[PC-KODIK-IFRAME]',JSON.stringify({origin:new URL(src).origin,sandbox:frame.sandbox.value,allow:frame.allow,allowFullscreen:frame.allowFullscreen,referrerPolicy:frame.referrerPolicy}));frame.onerror=()=>failed('Не удалось загрузить страницу Kodik. Проверьте сеть или выберите другой источник.');frame.onload=()=>report('page_loaded');root.replaceChildren(frame);}
showFrame(kodikUrl(config.src,data.episode));
window.addEventListener('message',event=>{
if(event.source===window.parent && event.origin===location.origin && event.data?.type==='pc-kodik-api'){
const target=frame && kodikUrl(frame.src);const episode=Number(event.data.episode);
if(target && Number.isInteger(episode) && episode>0)frame.contentWindow.postMessage({key:'kodik_player_api',value:{method:'change_episode',episode,without_reload:true}},new URL(target).origin);return;
}
if(!frame||event.source!==frame.contentWindow)return;
let origin;try{origin=new URL(frame.src).origin;}catch{return;}if(event.origin!==origin)return;
const message=event.data;if(!message||typeof message!=='object'||Array.isArray(message))return;
if(message.type==='pc-kodik-diagnostic'){
console.warn('[PC-KODIK-DIAG-RELAY]',JSON.stringify(message.detail||{}));
window.parent.postMessage({type:'pc-kodik-diagnostic',detail:message.detail},location.origin);
const detail=message.detail;
if(detail?.kind==='video-state'&&detail.hasSource&&detail.readyState>=2)mediaFailure='';
if(phase!=='playing'&&detail?.kind==='mse-type'&&detail.supported===false&&/avc1.*mp4a/i.test(detail.type||'')){
mediaFailure='Встроенный браузер не поддерживает H.264/AAC через MSE, необходимые Kodik.';
}
if(detail?.kind==='video-error'&&detail.error){
const code=detail.error.code;
if(!detail.hasSource)mediaFailure ||= 'Kodik не передал адрес видеопотока.';
else if(code===2)mediaFailure='Сетевая ошибка при загрузке видеопотока Kodik.';
else if(code===3)mediaFailure='Не удалось декодировать видеопоток Kodik.';
else if(code===4)mediaFailure ||= 'Браузер не смог открыть видеопоток, переданный Kodik.';
if(phase==='playing'&&detail.hasSource&&(code===2||code===3))failed(mediaFailure);
}
if(requireMediaDiagnostics&&phase!=='playing'&&message.detail?.kind==='video-state'&&message.detail.confirmed){clearTimeout(timer);report('playing');window.parent.postMessage({type:'pc-kodik',key:'kodik_player_video_started',value:{verified:true}},location.origin);}
return;}
if(message.agp==='kodik'&&typeof message.url==='string'){const url=kodikUrl(message.url);if(url)showFrame(url);return;}
if(message.agp==='ready'){playerReady();return;}
if(typeof message.key!=='string')return;
if(message.key==='kodik_player_ready'){playerReady();return;}
if(message.key==='kodik_player_video_started'||message.key==='kodik_player_play'){
if(requireMediaDiagnostics&&phase==='playing')return;
if(requireMediaDiagnostics){clearTimeout(timer);report('ready','Kodik сообщил о старте. Проверяем декодирование кадров и ход видео…');timer=setTimeout(()=>{if(phase!=='playing')failed(mediaFailure||'Kodik сообщил о старте, но Qt WebEngine не подтвердил кадры и продвижение видео. См. диагностику в startup.log.');},20000);}
else {clearTimeout(timer);report('playing');window.parent.postMessage({type:'pc-kodik',key:'kodik_player_video_started',value:{}},location.origin);}return;}
if(message.key==='kodik_player_error'||message.key==='kodik_player_media_error'){
const detail=typeof message.value?.message==='string'?message.value.message.slice(0,140):'';
return failed(mediaFailure||(detail?'Ошибка воспроизведения Kodik: '+detail:'Kodik сообщил об ошибке воспроизведения. Повторите запуск или выберите другой плеер.'));}
if(message.key==='kodik_player_current_episode'){
if(!message.value||typeof message.value!=='object'||!Number.isInteger(Number(message.value.episode)))return;
if(phase==='loading'||phase==='page_loaded')playerReady();
window.parent.postMessage({type:'pc-kodik',key:message.key,value:{episode:Number(message.value.episode),translation:typeof message.value.translation?.title==='string'?message.value.translation.title.slice(0,100):''}},location.origin);return;
}
if(message.key==='kodik_player_video_ended')window.parent.postMessage({type:'pc-kodik',key:message.key,value:{}},location.origin);
});
</script></html>'''.replace('CONFIG', config)
