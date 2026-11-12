import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useApp } from '../../context/AppContext';
import type { AnimePlayback } from '../../types';
import type { EpisodeRequest } from './AnimeSourcesPanel';
import { EpisodePicker } from './EpisodePicker';
import { prepareWebPlayer, releaseWebPlayer, useWebAutoNext, playerEnded, playerStarted, useAllohaEvents, preferredYummyPlayer, supportsH264AacMse } from '../../services/webPlayer';
import { WebPlayerControls } from './WebPlayerControls';
import { WebPlayerProtection } from './WebPlayerProtection';
import { API } from '../../services/api';
import { Play, RefreshCw } from 'lucide-react';

type YummyPlayer = { id: string; player: string; dubbing: string; episode: string; url: string };

export const YummyPlayerPanel: React.FC<{ animeId: string; title: string; desiredEpisode?: number; resume?: AnimePlayback; onEpisodeSelected?: (episode: number) => void; onStarted?: (item: YummyPlayer) => Promise<void>; onCompleted?: (item: YummyPlayer) => Promise<void>; episodeRequest?: EpisodeRequest | null; onAvailabilityChange?: (value: {busy: boolean; episodes: number[]}) => void }> = ({ animeId, title, desiredEpisode, resume, onEpisodeSelected, onStarted, onCompleted, episodeRequest, onAvailabilityChange }) => {
  const { activePlayback, closePlayback } = useApp();
  const frame = useRef<HTMLIFrameElement>(null);
  const adguardLease = useRef<string | null>(null);
  const playRequest = useRef(0);
  const [autoNext,setAutoNext] = useWebAutoNext();
  const allohaEvents = useAllohaEvents();
  const [allohaReady, setAllohaReady] = useState(false);
  const [webCodecsSupported] = useState(supportsH264AacMse);
  const [takingLong, setTakingLong] = useState(false);
  const [playError,setPlayError] = useState('');
  const [playPhase,setPlayPhase] = useState<'loading' | 'page_loaded' | 'playing' | 'error'>('loading');
  const historySaved = useRef(false);
  useEffect(()=>()=>{++playRequest.current;releaseWebPlayer(adguardLease.current);},[]);
  const consumedRequest = useRef(episodeRequest?.id || 0);
  const [missingEpisode, setMissingEpisode] = useState(false);
  const [items, setItems] = useState<YummyPlayer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [player, setPlayer] = useState('');
  const [dubbing, setDubbing] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [playing, setPlaying] = useState<YummyPlayer | null>(null);
  const [playerAttempt, setPlayerAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    ++playRequest.current;
    setLoading(true); setError(''); setPlaying(null); setItems([]);
    API.get<YummyPlayer[]>(`/api/library/anime/yummy/${encodeURIComponent(animeId)}/players`, { signal: controller.signal })
      .then(data => {
        if (controller.signal.aborted) return;
        let remembered: YummyPlayer | undefined;
        try { remembered = data.find(item => item.id === localStorage.getItem(`pc_yummy_last_${animeId}`)); } catch {}
        const preference = preferredYummyPlayer(data, resume?.voice || remembered?.dubbing);
        const matching = data.filter(item => item.player === preference?.player && item.dubbing === preference?.dubbing);
        const first = desiredEpisode ? matching.find(item => Number(item.episode) === desiredEpisode) : preference;
        setMissingEpisode(!!desiredEpisode && !first);
        setItems(data); setPlayer(preference?.player || '');
        setDubbing(preference?.dubbing || ''); setSelectedId(first?.id || '');
      })
      .catch(error => { if (!controller.signal.aborted) setError(error.message || 'Не удалось загрузить плееры'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [animeId, reload]);

  useEffect(() => { if (activePlayback) setPlaying(null); }, [activePlayback]);

  const players = useMemo(() => [...new Set(items.map(item => item.player))], [items]);
  const dubbings = useMemo(() => [...new Set(items.filter(item => item.player === player).map(item => item.dubbing))], [items, player]);
  const episodes = useMemo(() => items.filter(item => item.player === player && item.dubbing === dubbing)
    .sort((a, b) => a.episode.localeCompare(b.episode, 'ru', { numeric: true })), [items, player, dubbing]);
  const selected = episodes.find(item => item.id === selectedId) || (missingEpisode ? undefined : episodes[0]);
  const index = episodes.findIndex(item => item.id === selected?.id);
  const selectVoice = (nextPlayer: string, nextDubbing: string) => {
    const number = Number(selected?.episode) || desiredEpisode || 1;
    const next = items.find(item => item.player === nextPlayer && item.dubbing === nextDubbing && Number(item.episode) === number);
    setPlayer(nextPlayer); setDubbing(nextDubbing); setSelectedId(next?.id || '');
    setMissingEpisode(!next); setPlaying(null);
    ++playRequest.current;
    onEpisodeSelected?.(number);
    if (next) void start(next);
  };
  const selectPlayer = (value: string) => {
    const nextDubbing = items.some(item => item.player === value && item.dubbing === dubbing) ? dubbing : items.find(item => item.player === value)?.dubbing || '';
    selectVoice(value, nextDubbing);
  };
  const start = async (item?: YummyPlayer) => {
    if (!item) return;
    const request = ++playRequest.current;
    setPlayError('');
    try {
      if (activePlayback) await closePlayback();
      const lease = webCodecsSupported ? await prepareWebPlayer(item.player) : null;
      if (request !== playRequest.current) {releaseWebPlayer(lease);return;}
      releaseWebPlayer(adguardLease.current);adguardLease.current=lease;
      setPlayPhase('loading'); setTakingLong(false); historySaved.current = false;
      setPlayerAttempt(attempt => attempt + 1);
      setAllohaReady(false);setSelectedId(item.id); setPlaying(item); setMissingEpisode(false);
      onEpisodeSelected?.(Number(item.episode));
      try { localStorage.setItem(`pc_yummy_last_${animeId}`, item.id); } catch {}
    } catch (error) {
      if (request === playRequest.current) {
        setPlayPhase('error');
        setPlayError(error instanceof Error ? error.message : 'Не удалось открыть плеер');
      }
    }
  };
  useEffect(()=>{if(!playing && adguardLease.current){releaseWebPlayer(adguardLease.current);adguardLease.current=null;}},[playing]);
  useEffect(()=>{
    if (!playing || !webCodecsSupported || playPhase === 'playing' || playPhase === 'error') return;
    const timeout = window.setTimeout(() => setTakingLong(true), 45000);
    return()=>window.clearTimeout(timeout);
  },[playing, playerAttempt, playPhase, webCodecsSupported]);
  useEffect(()=>{
    if(!playing)return;
    const receive=(event: MessageEvent)=>{
      if(event.source!==frame.current?.contentWindow)return;
      if(playerStarted(playing.player,playing.url,event.origin,event.data)){
        setPlayPhase('playing');setTakingLong(false);
        if (!historySaved.current) {
          historySaved.current = true;
          setPlayError('');
          void onStarted?.(playing).catch((error: Error) => setPlayError(`Просмотр не сохранён: ${error.message}`));
        }
        return;
      }
      if(event.origin!==new URL(playing.url,location.href).origin||!event.data||typeof event.data!=='object'||Array.isArray(event.data))return;
      const data=event.data as {key?:unknown;type?:unknown;event?:unknown};
      const isKodik=/kodik/i.test(playing.player)&&/kodik/i.test(event.origin);
      const isCvh=/cvh|chv/i.test(playing.player);
      const isAlloha=/alloha/i.test(playing.player)&&event.origin==='https://alloha.yani.tv';
      const failed=(isKodik&&['kodik_player_error','kodik_player_media_error'].includes(String(data.key)))||
        (isCvh&&['player_error','player_media_error'].includes(String(data.key)))||
        (isAlloha&&data.type==='pc-alloha'&&data.event==='error');
      if(failed){setPlayPhase('error');setPlayError('Источник сообщил об ошибке видео. Попробуйте повторить запуск или выбрать другой плеер.');}
    };
    window.addEventListener('message',receive);return()=>window.removeEventListener('message',receive);
  },[playing,onStarted]);
  useEffect(()=>{
    if(!playing || !/alloha/i.test(playing.player))return;
    const receive=(event: MessageEvent)=>{
      if(event.source===frame.current?.contentWindow && event.origin==='https://alloha.yani.tv' && event.data?.type==='pc-alloha' && event.data.event==='ready')setAllohaReady(true);
    };
    window.addEventListener('message',receive);return()=>window.removeEventListener('message',receive);
  },[playing, playerAttempt]);
  useEffect(()=>{
    if(!playing || (/alloha/i.test(playing.player) && !allohaEvents))return;
    let handled=false;
    const receive=(event: MessageEvent)=>{
      if(handled || !historySaved.current || event.source!==frame.current?.contentWindow || !playerEnded(playing.player,playing.url,event.origin,event.data))return;
      handled=true;
      void onCompleted?.(playing).catch((error: Error)=>setPlayError(`Просмотр не сохранён: ${error.message}`));
      if(autoNext)void start(episodes[index+1]);
    };
    window.addEventListener('message',receive);return()=>window.removeEventListener('message',receive);
  },[playing,playerAttempt,autoNext,episodes,index,allohaEvents]);

  useEffect(() => {
    onAvailabilityChange?.({busy: loading, episodes: episodes.map(item => Number(item.episode)).filter(Number.isInteger)});
  }, [loading, episodes, onAvailabilityChange]);

  useEffect(() => {
    if (!episodeRequest || loading || consumedRequest.current === episodeRequest.id) return;
    consumedRequest.current = episodeRequest.id;
    void start(episodes.find(item => Number(item.episode) === episodeRequest.episode));
  }, [episodeRequest, loading, episodes]);

  return <section id="yummy-player" className="cinema-section" aria-label="Просмотр YummyAnime">
    <div className="cinema-section-heading"><h2>Смотреть онлайн · YummyAnime</h2></div>
    {playError && <p role="alert">{playError}</p>}
    {loading ? <p role="status">Загружаем плееры и серии…</p> : error ? <div role="alert"><p>{error}</p><button className="cinema-button cinema-button--secondary" onClick={() => setReload(value => value + 1)}><RefreshCw />Повторить</button></div> : !items.length ? <p className="cinema-secondary">Для этого аниме YummyAnime пока не возвращает доступных плееров. Можно выбрать раздачу ниже.</p> : <>
      {missingEpisode && <p role="status">Серия {desiredEpisode} недоступна в выбранной озвучке. Выберите другую серию или источник.</p>}
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-2">Плеер<select className="cinema-button cinema-button--secondary" value={player} onChange={event => selectPlayer(event.target.value)}>{players.map(name => <option key={name}>{name}</option>)}</select></label>
        <label className="flex flex-col gap-2">Озвучка / субтитры<select className="cinema-button cinema-button--secondary" value={dubbing} onChange={event => selectVoice(player, event.target.value)}>{dubbings.map(name => <option key={name}>{name}</option>)}</select></label>
        <EpisodePicker value={selected?.id || ''} options={episodes.map(item=>({value:item.id,label:`Серия ${item.episode}`}))} onChange={value=>{++playRequest.current;setSelectedId(value);setMissingEpisode(false);onEpisodeSelected?.(Number(items.find(item=>item.id===value)?.episode || 1));setPlaying(null);}} />

        <button id="yummy-start" type="button" className="cinema-button cinema-button--primary" disabled={!selected} onClick={() => start(selected)}><Play aria-hidden="true" />Смотреть</button>
      </div>
      {playing && <div className="anime-web-player">
        <WebPlayerProtection player={playing.player} />
        <span>{playing.player} · {playing.dubbing} · Серия {playing.episode}</span>
        {webCodecsSupported && playPhase !== 'playing' && playPhase !== 'error' && <p role="status">{takingLong ? 'Видео пока не запустилось. Нажмите воспроизведение в плеере или повторите запуск.' : playPhase === 'page_loaded' ? 'Страница плеера загружена. Нажмите воспроизведение.' : 'Загружаем плеер…'}</p>}
        {webCodecsSupported && takingLong && playPhase !== 'playing' && playPhase !== 'error' && <button type="button" className="cinema-button cinema-button--secondary" onClick={() => void start(playing)}><RefreshCw />Повторить</button>}
        {playPhase === 'error' && <div role="alert"><p>{playError}</p><button className="cinema-button cinema-button--secondary" onClick={() => void start(playing)}><Play />Повторить</button></div>}
        {webCodecsSupported ? <iframe sandbox="allow-scripts allow-same-origin allow-forms allow-presentation" ref={frame} key={`${playing.id}:${playerAttempt}`} src={playing.url} title={`${title} — серия ${playing.episode}, ${playing.dubbing}`} scrolling="no" className="block w-full aspect-video rounded-xl border-0 bg-black overflow-hidden" allow="autoplay; fullscreen; encrypted-media; picture-in-picture" referrerPolicy="strict-origin-when-cross-origin" onLoad={() => setPlayPhase(phase => phase === 'loading' ? 'page_loaded' : phase)} onError={() => {setPlayPhase('error');setPlayError('Не удалось загрузить страницу плеера. Проверьте сеть и повторите запуск.');}} /> :
          <a className="cinema-button cinema-button--secondary" href={playing.url} target="_blank" rel="noopener noreferrer">Открыть серию в браузере</a>}
        <WebPlayerControls previous={index>0 ? ()=>void start(episodes[index-1]) : undefined} next={index>=0 && index<episodes.length-1 ? ()=>void start(episodes[index+1]) : undefined} close={()=>{++playRequest.current;setPlaying(null);}} autoNext={autoNext} setAutoNext={setAutoNext} autoSupported={webCodecsSupported && (/kodik|cvh|chv/i.test(playing.player) || (/alloha/i.test(playing.player) && allohaReady))} />
        <p className="cinema-secondary">Если видео недоступно, выберите другой плеер. Реклама и доступность зависят от источника.</p>
      </div>}
    </>}
  </section>;
};
