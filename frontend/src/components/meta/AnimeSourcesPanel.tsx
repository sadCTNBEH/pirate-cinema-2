import React, { useEffect, useRef, useState } from 'react';
import { YummyPlayerPanel } from './YummyPlayerPanel';
import type { AnimePlayback } from '../../types';
import { EpisodePicker } from './EpisodePicker';
import { WebPlayerControls } from './WebPlayerControls';
import { WebPlayerProtection } from './WebPlayerProtection';
import { prepareWebPlayer, releaseWebPlayer, useWebAutoNext } from '../../services/webPlayer';
import { API } from '../../services/api';
import { scrollPageTo } from '../../services/pageScroll';
import { useApp } from '../../context/AppContext';
import { Play, Loader2 } from 'lucide-react';

type AnimegoCatalog = { anime_id: string; title: string; total_episodes: number | null; episodes: {number: number; id: string}[]; voices: {translation_id: string; label: string; player: string; playback_supported?: boolean}[]; url: string; seasons?: {title: string; url: string}[]; studios?: string[]; notice?: string };

export type EpisodeRequest = { id: number; episode: number; mediaId: string; source: string };
export type EpisodeAvailability = { source: string; busy: boolean; episodes: number[]; isBase?: boolean; title?: string };
export const AnimeSourcesPanel: React.FC<{ mediaId: string; title: string; resume?: AnimePlayback; episodeRequest: EpisodeRequest | null; onAvailabilityChange: (value: EpisodeAvailability) => void; onCompleted: () => Promise<void> }> = ({ mediaId, title, resume, episodeRequest, onAvailabilityChange, onCompleted }) => {
  const { activePlayback, closePlayback } = useApp();
  const [source, setSource] = useState<string>(resume?.source || (mediaId.startsWith('yummy:') ? 'yummy' : 'animego'));
  const frame = useRef<HTMLIFrameElement>(null);
  const adguardLease = useRef<string | null>(null);
  const playingNumber = useRef(resume?.episode || 1);
  const [autoNext, setAutoNext] = useWebAutoNext();
  useEffect(() => () => releaseWebPlayer(adguardLease.current), []);
  const [wantedEpisode, setWantedEpisode] = useState(resume?.episode || 1);
  const historyQueue = useRef<Promise<unknown>>(Promise.resolve());
  const [historyError, setHistoryError] = useState('');
  const [webUrl, setWebUrl] = useState('');
  useEffect(() => {if (!webUrl && adguardLease.current) {releaseWebPlayer(adguardLease.current);adguardLease.current=null;}}, [webUrl]);
  const [webLoaded, setWebLoaded] = useState(false);
  const [yummyId, setYummyId] = useState(resume?.source === 'yummy' ? resume.source_title_id : mediaId.startsWith('yummy:') ? mediaId.slice(6) : '');
  const [selectedYummyId, setSelectedYummyId] = useState('');
  const [yummyParts, setYummyParts] = useState<{id: string; title: string; year?: number; type?: string}[]>([]);
  const [partsError, setPartsError] = useState('');
  const [yummyAvailability, setYummyAvailability] = useState({busy: true, episodes: [] as number[]});
  const baseAnimegoUrl = useRef('');
  const consumedRequest = useRef(0);
  const yummyPartId = selectedYummyId || yummyId;

  useEffect(() => {
    if (!yummyId || source !== 'yummy') return;
    const controller = new AbortController();
    setPartsError('');
    API.get<typeof yummyParts>(`/api/library/anime/yummy/${encodeURIComponent(yummyId)}/parts`, {signal: controller.signal})
      .then(parts => { if (!controller.signal.aborted) setYummyParts(parts); })
      .catch(error => { if (!controller.signal.aborted) setPartsError(error.message || 'Не удалось загрузить сезоны'); });
    return () => controller.abort();
  }, [yummyId, source]);

  const [animegoCatalog, setAnimegoCatalog] = useState<AnimegoCatalog | null>(null);
  const [animegoVoices, setAnimegoVoices] = useState<{translation_id: string; label: string; player: string}[]>([]);
  const [animegoVoice, setAnimegoVoice] = useState('');
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (source !== 'yummy' || yummyId || !mediaId.startsWith('shikimori:')) return;
    const controller = new AbortController();
    API.get<{anime_id: string}>(`/api/library/anime/yummy/for-shikimori/${encodeURIComponent(mediaId.slice(10))}`, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setYummyId(data.anime_id); })
      .catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [source, mediaId, yummyId]);

  useEffect(() => {
    if (source !== 'animego') return;
    const controller = new AbortController();
    setBusy(true); setError(''); setAnimegoCatalog(null); setAnimegoVoices([]); setAnimegoVoice('');
    API.get<AnimegoCatalog>(`/api/online/animego/catalog?media_id=${encodeURIComponent(mediaId)}`, { signal: controller.signal })
      .then(async catalog => {
        baseAnimegoUrl.current = catalog.url;
        if (resume?.source === 'animego' && resume.source_url && resume.source_url !== catalog.url)
          catalog = await API.get<AnimegoCatalog>(`/api/online/animego/card?url=${encodeURIComponent(resume.source_url)}`, {signal: controller.signal});
        if (controller.signal.aborted) return;
        setAnimegoCatalog(catalog); setAnimegoVoices(catalog.voices);
        setIndex(catalog.episodes.findIndex(item => item.number === wantedEpisode));
        const first = catalog.voices.find(item => resume?.source === 'animego' && item.player === resume.player && item.translation_id === resume.voice_id) || catalog.voices.find(item => item.player.toLowerCase() === 'kodik') || catalog.voices[0];
        setAnimegoVoice(first ? `${first.player}:${first.translation_id}` : '');
      })
      .catch(error => { if (!controller.signal.aborted) setError(error.message || 'AnimeGo недоступен'); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [source, mediaId]);

  useEffect(() => { if (activePlayback) setWebUrl(''); }, [activePlayback]);
  useEffect(() => { setWebUrl(''); setWebLoaded(false); }, [source, animegoVoice]);
  const saveHistory = async (selection: {source: 'animego' | 'yummy'; source_title_id: string; episode: number; player: string; voice_id: string; voice: string}, completed = false) => {
    setHistoryError('');
    try {
      const pending = historyQueue.current.catch(() => undefined).then(() => API.post(completed ? '/api/history/anime/complete' : '/api/history/anime', {media_id: mediaId, season: resume?.season || 1, ...selection}));
      historyQueue.current = pending;
      await pending;
      if (completed) await onCompleted();
      setHistoryError('');
    } catch (error: any) { setHistoryError(`Просмотр не сохранён: ${error.message}`); }
  };

  const playWeb = async (number?: number, voiceKey = animegoVoice) => {
    const selected = number ? animegoCatalog?.episodes.find(item => item.number === number) : animegoCatalog?.episodes[index];
    const voice = animegoVoices.find(item => `${item.player}:${item.translation_id}` === voiceKey);
    if (!animegoCatalog || !selected || !voice) return;
    setIndex(animegoCatalog.episodes.indexOf(selected));
    setBusy(true); setError(''); setWebUrl(''); setWebLoaded(false);
    try {
      const result = await API.post<{url: string}>('/api/online/animego/embed', { anime_id: Number(animegoCatalog.anime_id), episode: selected.number, translation_id: voice.translation_id, player: voice.player });
      if (!result.url) throw new Error('AnimeGo не вернул адрес плеера');
      if (activePlayback) await closePlayback();
      const lease = await prepareWebPlayer(voice.player);
      releaseWebPlayer(adguardLease.current); adguardLease.current = lease;
      playingNumber.current = selected.number;
      setWebUrl(result.url);
      setWantedEpisode(selected.number);
      await saveHistory({source: 'animego', source_title_id: animegoCatalog.anime_id, episode: selected.number, player: voice.player, voice_id: voice.translation_id, voice: ''});
    } catch (error: any) { setError(error.message || 'Не удалось открыть веб-плеер AnimeGo'); }
    finally { setBusy(false); }
  };

  useEffect(() => {
    onAvailabilityChange({source, isBase: source === 'animego' ? animegoCatalog?.url === baseAnimegoUrl.current : yummyPartId === yummyId, title: source === 'animego' ? animegoCatalog?.title : yummyParts.find(part => part.id === yummyPartId)?.title, busy: source === 'animego' ? busy : source === 'yummy' ? (!yummyId || yummyAvailability.busy) : false,
      episodes: source === 'animego' && animegoCatalog && animegoVoice ? animegoCatalog.episodes.map(item => item.number) :
        source === 'yummy' ? yummyAvailability.episodes : []});
  }, [source, busy, animegoCatalog, animegoVoice, yummyId, yummyPartId, yummyParts, yummyAvailability, onAvailabilityChange]);

  useEffect(() => {
    if (source !== 'animego' || !episodeRequest || episodeRequest.mediaId !== mediaId || episodeRequest.source !== source || consumedRequest.current === episodeRequest.id || busy || !animegoCatalog) return;
    consumedRequest.current = episodeRequest.id;
    void playWeb(episodeRequest.episode);
  }, [episodeRequest, source, busy, animegoCatalog, animegoVoice]);

  useEffect(() => {
    if (!webUrl || !animegoCatalog) return;
    let timer: number | undefined;
    let handled = false;
    const receive = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow || event.origin !== location.origin || !['pc-kodik','pc-cvh'].includes(event.data?.type)) return;
      if (event.data.key === 'kodik_player_current_episode' || (event.data.type === 'pc-cvh' && event.data.event === 'episode')) {
        const number = Number(event.data.type === 'pc-cvh' ? event.data.episode : event.data.value?.episode);
        const next = animegoCatalog.episodes.findIndex(item => item.number === number);
        if (next < 0 || number === playingNumber.current) return;
        playingNumber.current=number;setIndex(next);setWantedEpisode(number);
        handled = false;
        const voice=animegoVoices.find(item=>`${item.player}:${item.translation_id}`===animegoVoice);
        if (voice) void saveHistory({source:'animego',source_title_id:animegoCatalog.anime_id,episode:number,player:voice.player,voice_id:voice.translation_id,voice:String(event.data.value?.translation?.title || '')});
      }
      if ((event.data.key === 'kodik_player_video_ended' || (event.data.type === 'pc-cvh' && event.data.event === 'ended')) && !handled) {
        handled = true;
        const ended=playingNumber.current;
        const voice=animegoVoices.find(item=>`${item.player}:${item.translation_id}`===animegoVoice);
        if (voice) void saveHistory({source:'animego',source_title_id:animegoCatalog.anime_id,episode:ended,player:voice.player,voice_id:voice.translation_id,voice:''},true);
        if (!autoNext) return;
        timer=window.setTimeout(()=>{
          if (playingNumber.current!==ended) return;
          const current=animegoCatalog.episodes.findIndex(item=>item.number===ended);
          const next=animegoCatalog.episodes[current+1];
          if(next) {
            if(event.data.type === 'pc-cvh') void playWeb(next.number);
            else frame.current?.contentWindow?.postMessage({type:'pc-kodik-api',episode:next.number},location.origin);
          }
        },600);
      }
    };
    window.addEventListener('message',receive);
    return()=>{window.removeEventListener('message',receive);if(timer)clearTimeout(timer);};
  },[webUrl,animegoCatalog,animegoVoice,autoNext]);

  const changeSeason = async (url: string) => {
    setBusy(true); setError(''); setWebUrl('');
    try {
      const catalog = await API.get<AnimegoCatalog>(`/api/online/animego/card?url=${encodeURIComponent(url)}`);
      setAnimegoCatalog(catalog); setAnimegoVoices(catalog.voices); setIndex(0); setWantedEpisode(1);
      const first = catalog.voices.find(item => item.player.toLowerCase() === 'kodik') || catalog.voices[0];
      setAnimegoVoice(first ? `${first.player}:${first.translation_id}` : '');
    } catch (error: any) { setError(error.message || 'Не удалось открыть сезон'); }
    finally { setBusy(false); }
  };

  const load = async () => {
    setBusy(true); setError('');
    try {
      if (source === 'animego' && !animegoCatalog) {
        const catalog = await API.get<AnimegoCatalog>(`/api/online/animego/catalog?media_id=${encodeURIComponent(mediaId)}`);
        baseAnimegoUrl.current = catalog.url;
        setAnimegoCatalog(catalog); setAnimegoVoices(catalog.voices);
        const first = catalog.voices.find(item => item.player.toLowerCase() === 'kodik') || catalog.voices[0];
        setAnimegoVoice(first ? `${first.player}:${first.translation_id}` : '');
        if (!catalog.voices.length) setError(catalog.notice || 'Озвучки не найдены');
        return;
      }
    } catch (error: any) { setError(error.message || 'Не удалось открыть AnimeGo'); }
    finally { setBusy(false); }
  };
  return <section id="anime-sources" className="cinema-section" aria-label="Источники аниме">
    <div className="cinema-section-heading"><h2>Смотреть аниме</h2></div>
    {resume && <p role="status">Продолжить: сезон {resume.season}, серия {wantedEpisode}. Если источник недоступен, выберите другой — номер серии сохранится.</p>}
    {historyError && <p role="alert">{historyError}</p>}
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-2">Источник<select className="cinema-button cinema-button--secondary" value={source} disabled={busy} onChange={event => { setSource(event.target.value); setError(''); }}>
        <option value="animego">AnimeGo</option><option value="yummy">YummyAnime</option><option value="torrent">Торренты</option>
      </select></label>
      {source === 'animego' && animegoCatalog && <div data-animego-id={animegoCatalog.anime_id} role="status"><strong>{animegoCatalog.title}</strong><p>Найдено серий: {animegoCatalog.episodes.length} · Плееров: {animegoCatalog.voices.length}</p>{animegoCatalog.studios?.length ? <p>Озвучки по данным сайта: {animegoCatalog.studios.join(', ')}</p> : null}{animegoCatalog.notice && <p>{animegoCatalog.notice}</p>}</div>}
      {source === 'animego' && <>
        {!!animegoCatalog?.seasons?.length && <label className="flex flex-col gap-2">Сезон / часть<select className="cinema-button cinema-button--secondary" value={animegoCatalog.url} disabled={busy} onChange={event => changeSeason(event.target.value)}><option value={animegoCatalog.url}>{animegoCatalog.title}</option>{animegoCatalog.seasons.filter(item => item.url !== animegoCatalog.url).map(item => <option key={item.url} value={item.url}>{item.title}</option>)}</select></label>}
        {animegoVoices.length > 0 && <label className="flex flex-col gap-2">Плеер<select className="cinema-button cinema-button--secondary" value={animegoVoice} onChange={event => { const voice=event.target.value;setAnimegoVoice(voice);setError('');void playWeb(undefined,voice); }}>{animegoVoices.map(item => <option key={`${item.player}:${item.translation_id}`} value={`${item.player}:${item.translation_id}`}>{item.label}</option>)}</select></label>}
        {animegoCatalog && <EpisodePicker value={String(index)} disabled={busy} options={animegoCatalog.episodes.map((item,i)=>({value:String(i),label:`Серия ${item.number}`}))} onChange={value=>{const next=Number(value);setWebUrl('');setIndex(next);setWantedEpisode(animegoCatalog.episodes[next]?.number || wantedEpisode);}} />}

        <button id="yummy-start" className="cinema-button cinema-button--primary" disabled={busy || (!!animegoCatalog && (!animegoVoice || !animegoCatalog.episodes[index]))} onClick={() => animegoCatalog ? playWeb() : load()}>{busy ? <Loader2 className="animate-spin" /> : <Play />}{animegoCatalog ? 'Смотреть' : 'Найти серии'}</button>
      </>}
      {source === 'torrent' && <button className="cinema-button cinema-button--primary" onClick={() => scrollPageTo('cinema-releases')}>Выбрать раздачу</button>}
    </div>
    {source === 'animego' && webUrl && <div className="anime-web-player">
      <WebPlayerProtection player={animegoVoices.find(item=>`${item.player}:${item.translation_id}`===animegoVoice)?.player || ''} />
      {!webLoaded && <p role="status">Загружается веб-плеер…</p>}
      <iframe sandbox="allow-scripts allow-same-origin allow-forms allow-presentation" ref={frame} key={webUrl} src={webUrl} title={`${title} — AnimeGo, серия ${animegoCatalog?.episodes[index]?.number}`} scrolling="no" className="block w-full aspect-video rounded-xl border-0 bg-black overflow-hidden" allow="autoplay; fullscreen; encrypted-media; picture-in-picture" allowFullScreen referrerPolicy="strict-origin-when-cross-origin" onLoad={() => setWebLoaded(true)} />
      <WebPlayerControls previous={!busy && index>0 ? ()=>void playWeb(animegoCatalog?.episodes[index-1]?.number) : undefined} next={!busy && animegoCatalog?.episodes[index+1] ? ()=>void playWeb(animegoCatalog.episodes[index+1].number) : undefined} close={()=>setWebUrl('')} autoNext={autoNext} setAutoNext={setAutoNext} autoSupported />
      <p className="cinema-secondary">Нажмите воспроизведение внутри плеера. Качество, реклама и доступность определяются источником.</p>
    </div>}
    {source === 'yummy' && yummyId && <>
      {yummyParts.length > 1 && <label className="flex flex-col gap-2">Сезон / фильм<select className="cinema-button cinema-button--secondary" value={yummyPartId} onChange={event => {setSelectedYummyId(event.target.value); setWantedEpisode(1); setYummyAvailability({busy: true, episodes: []});}}>{yummyParts.map(part => <option key={part.id} value={part.id}>{part.title}{part.year ? ` (${part.year})` : ''}{part.type ? ` · ${part.type}` : ''}</option>)}</select></label>}
      {partsError && <p role="alert">{partsError}</p>}
      <YummyPlayerPanel key={yummyPartId} animeId={yummyPartId} title={yummyParts.find(part => part.id === yummyPartId)?.title || title} desiredEpisode={wantedEpisode} resume={resume?.source === 'yummy' ? resume : undefined} onEpisodeSelected={setWantedEpisode} onStarted={item => saveHistory({source:'yummy', source_title_id:yummyPartId, episode:Number(item.episode), player:item.player, voice_id:item.dubbing, voice:item.dubbing})} onCompleted={item => saveHistory({source:'yummy', source_title_id:yummyPartId, episode:Number(item.episode), player:item.player, voice_id:item.dubbing, voice:item.dubbing},true)} episodeRequest={episodeRequest?.mediaId === mediaId && episodeRequest.source === source ? episodeRequest : null} onAvailabilityChange={setYummyAvailability} />
    </>}
    {source === 'yummy' && !yummyId && <p role="status">{error || 'Ищем тайтл на YummyAnime…'}</p>}
    {(source === 'animego') && error && <div role="alert"><p>{error}</p><button className="cinema-button cinema-button--secondary" disabled={busy} onClick={() => animegoCatalog ? playWeb() : load()}>Повторить</button></div>}
  </section>;
};
