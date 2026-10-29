/**
 * @file components/meta/MetaView.tsx
 * @description Экран карточки медиа (фильма или сериала).
 * Загружает расширенные метаданные, серии, парсит раздачи,
 * фильтрует по сезонам и аудиодорожкам/переводам.
 */

import React, { useEffect, useState, useMemo, useRef, useCallback } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { useCatalog } from '../../services/catalogCache';
import {
  CollectionItem,
  CollectionName,
  LibraryProgressResponse,
  NextUnwatchedResponse,
  SeriesEpisode,
  MediaDetail,
  TorrentResult,
} from '../../types';
import { parseTrans, matchesSeason } from '../../utils/torrentParser';
import { SafeHtmlText } from '../ui/UIComponents';
import { CinemaHero } from '../ui/Cinema';
import {
  ArrowLeft,
  Star,
  Film,
  Mic,
  Play,
  Loader2,
  AlertCircle,
  Clock3,
  Heart,
  RefreshCw,
  CheckCircle2,
  Circle,
  Check,
} from 'lucide-react';
import { AnimeSourcesPanel, EpisodeAvailability, EpisodeRequest } from './AnimeSourcesPanel';
import { InlinePlayer } from '../player/InlinePlayer';

export const MetaView: React.FC = () => {
  const { routeParams, goBack, openPlayback, activePlayback, t, lang } = useApp();
  const { imdb = '', title = '', type = 'movie', poster = '' } = routeParams;

  const { data: metadata, loading: loadingMetadata } = useCatalog<MediaDetail>(imdb ? `/api/library/meta/${encodeURIComponent(imdb)}?type=${encodeURIComponent(type)}&lang=${encodeURIComponent(lang || 'ru')}` : null, 7 * 86400000, 30 * 86400000);
  const metaOverview = metadata?.overview || '';
  const metaOverviewRu = lang === 'en' ? null : metadata?.overview_ru || null;
  const metaRating = metadata?.rating || null;
  const metaYear = metadata?.year ? Number(metadata.year) : null;
  const metaGenres = useMemo(() => metadata?.genres || [], [metadata?.genres]);
  const metaPoster = metadata?.poster_local_url || metadata?.poster_url || poster;
  const metaBackdrop = metadata?.background_url || null;
  const metaVideos: SeriesEpisode[] = useMemo(() => metadata?.videos || [], [metadata?.videos]);
  const isSeries = type === 'series' || metadata?.type === 'series';
  const metaTitleRu = lang === 'en' ? metadata?.original_title || metadata?.title || null : metadata?.title_ru || metadata?.title || null;
  const metaOriginalTitle = metadata?.original_title || null;

  const isAnime = imdb.startsWith('yummy:') || imdb.startsWith('shikimori:');
  const [episodeRequest, setEpisodeRequest] = useState<EpisodeRequest | null>(null);
  const [episodeAvailability, setEpisodeAvailability] = useState<EpisodeAvailability>({source: 'animego', busy: true, episodes: []});
  const onlineEpisodes = isAnime && episodeAvailability.source !== 'torrent';
  const differentOnlinePart = onlineEpisodes && episodeAvailability.isBase === false;
  const canPlayOnlineEpisode = (episode: number) => !episodeAvailability.busy && episodeAvailability.episodes.includes(episode);
  const playOnlineEpisode = (episode: number) => {
    setEpisodeRequest(previous => ({id: (previous?.id || 0) + 1, episode, mediaId: imdb, source: episodeAvailability.source}));
    document.getElementById('anime-sources')?.scrollIntoView({block: 'start', behavior: 'smooth'});
  };

  const [currentSeason, setCurrentSeason] = useState<number>(1);
  const initializedSeason = useRef('');

  const [rawTorrents, setRawTorrents] = useState<TorrentResult[]>([]);
  const [isSearchingTorrents, setIsSearchingTorrents] = useState<boolean>(true);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [selectedVoiceover, setSelectedVoiceover] = useState<string>('all');
  const [progressData, setProgressData] = useState<LibraryProgressResponse | null>(null);
  const [nextUnwatched, setNextUnwatched] = useState<NextUnwatchedResponse | null>(null);
  const [collectionMembership, setCollectionMembership] = useState<Record<CollectionName, boolean>>({
    favorites: false,
    watch_later: false,
  });
  const [savingCollection, setSavingCollection] = useState<CollectionName | null>(null);

  const isMountedRef = useRef<boolean>(true);
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const searchedQueriesRef = useRef<Set<string>>(new Set());

  /**
   * Параллельный поиск нескольких вариантов названий с объединением и дедупликацией
   */
  const searchQueries = useCallback(async (queries: string[]) => {
    const unique = new Map<string, string>();
    queries.forEach((q) => {
      const normalized = q.trim().replace(/\s+/g, ' ');
      if (normalized) unique.set(normalized.toLocaleLowerCase(), normalized);
    });
    const unsearched = Array.from(unique.values())
      .filter((q) => !searchedQueriesRef.current.has(q.toLocaleLowerCase()))
      .slice(0, 6);

    if (unsearched.length === 0) return;

    unsearched.forEach((q) => searchedQueriesRef.current.add(q.toLocaleLowerCase()));

    setIsSearchingTorrents(true);
    setSearchError(null);

    try {
      const items = await API.searchTorrents(unsearched[0], undefined, undefined, {}, unsearched.slice(1));

      if (!isMountedRef.current) return;

      setRawTorrents((prev) => {
        const map = new Map<string, TorrentResult>();
        prev.forEach((item) => {
          const key = item.hash || item.magnet || item.title;
          if (key) map.set(key, item);
        });

        if (Array.isArray(items)) {
          items.forEach((item) => {
            const key = item.hash || item.magnet || item.title;
            if (key && (!map.has(key) || (item.score || 0) > (map.get(key)?.score || 0))) {
              map.set(key, item);
            }
          });
        }

        return Array.from(map.values()).sort((a, b) => (b.score || 0) - (a.score || 0));
      });
    } catch (err: any) {
      unsearched.forEach((q) => searchedQueriesRef.current.delete(q.toLocaleLowerCase()));
      if (isMountedRef.current) {
        setSearchError(err?.message || 'Ошибка поиска');
      }
    } finally {
      if (isMountedRef.current) {
        setIsSearchingTorrents(false);
      }
    }
  }, []);

  useEffect(() => {
    setCurrentSeason(1);
  }, [imdb, type]);

  useEffect(() => {
    const identity = `${type}:${imdb}`;
    if (!metadata || initializedSeason.current === identity) return;
    initializedSeason.current = identity;
    const seasons = metaVideos.map(video => video.season).filter(season => season > 0);
    setCurrentSeason(seasons.length ? Math.min(...seasons) : 1);
  }, [imdb, type, metadata, metaVideos]);

  useEffect(() => {
    let isCancelled = false;
    if (!imdb) return;

    API.getCollectionMembership(imdb)
      .then((membership) => {
        if (!isCancelled) setCollectionMembership(membership);
      })
      .catch(() => {
        if (!isCancelled) {
          setCollectionMembership({ favorites: false, watch_later: false });
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [imdb]);

  /**
   * Загрузка прогресса по сезонам и следующей серии (TASK-002)
   */
  const loadProgress = useCallback(async () => {
    if (!imdb || !isSeries) return;
    try {
      const [progRes, nextRes] = await Promise.allSettled([
        API.getLibraryProgress(imdb),
        API.getNextUnwatched({ imdb_id: imdb, season: currentSeason }),
      ]);
      if (!isMountedRef.current) return;
      if (progRes.status === 'fulfilled' && progRes.value) {
        setProgressData(progRes.value);
      }
      if (nextRes.status === 'fulfilled' && nextRes.value) {
        setNextUnwatched(nextRes.value);
      }
    } catch (err: any) {
      console.warn('Failed to load season progress:', err);
    }
  }, [imdb, isSeries, currentSeason]);

  useEffect(() => {
    loadProgress();
  }, [loadProgress]);

  const handleToggleEpisodeWatched = async (seasonNum: number, episodeNum: number, currentWatched: boolean) => {
    if (!imdb) return;
    try {
      await API.markWatched({
        imdb_id: imdb,
        season: seasonNum,
        episode: episodeNum,
        watched: !currentWatched,
      });
      await loadProgress();
    } catch (err: any) {
      console.error('Failed to toggle watched status', err);
    }
  };

  /**
   * 2. Первоначальный поиск по названию
   */
  useEffect(() => {
    if (title?.trim()) {
      searchQueries([title.trim()]);
    }
  }, [title, searchQueries]);

  /**
   * 3. Дополнительный параллельный поиск при появлении метаданных и смене сезона
   */
  useEffect(() => {
    const queries: string[] = [];
    if (metaOriginalTitle && metaOriginalTitle !== title) {
      queries.push(metaOriginalTitle);
    }
    if (metaTitleRu && metaTitleRu !== title && metaTitleRu !== metaOriginalTitle) {
      queries.push(metaTitleRu);
    }

    if (isSeries && currentSeason) {
      const s0 = String(currentSeason).padStart(2, '0');
      const en = metaOriginalTitle || title;
      const ru = metaTitleRu || title;
      if (en) {
        queries.push(`${en} S${s0}`);
      }
      if (ru) {
        queries.push(`${ru} сезон ${currentSeason}`);
        queries.push(`${ru} ${currentSeason} сезон`);
      }
    }

    if (queries.length > 0) {
      searchQueries(queries);
    }
  }, [metaOriginalTitle, metaTitleRu, isSeries, currentSeason, title, searchQueries]);

  /**
   * Сброс и повторный полный поиск
   */
  const handleRetrySearch = useCallback(() => {
    searchedQueriesRef.current.clear();
    setRawTorrents([]);
    const queries: string[] = [];
    if (title) queries.push(title);
    if (metaOriginalTitle) queries.push(metaOriginalTitle);
    if (metaTitleRu) queries.push(metaTitleRu);
    if (isSeries && currentSeason) {
      const s0 = String(currentSeason).padStart(2, '0');
      const en = metaOriginalTitle || title;
      const ru = metaTitleRu || title;
      if (en) queries.push(`${en} S${s0}`);
      if (ru) queries.push(`${ru} сезон ${currentSeason}`);
    }
    searchQueries(queries);
  }, [title, metaOriginalTitle, metaTitleRu, isSeries, currentSeason, searchQueries]);

  /**
   * Список уникальных сезонов для выпадающего списка
   */
  const availableSeasons = useMemo(() => {
    if (!metaVideos.length) return [1];
    return Array.from(new Set(metaVideos.map((v) => v.season))).sort((a, b) => a - b);
  }, [metaVideos]);

  /**
   * Фильтрация раздач по выбранному сезону сериала
   */
  const seasonFilteredTorrents = useMemo(() => {
    if (!isSeries) return rawTorrents;
    return rawTorrents.filter((r) => matchesSeason(r.title, currentSeason));
  }, [rawTorrents, isSeries, currentSeason]);

  /**
   * Если точных совпадений по сезону нет, но есть общие раздачи в rawTorrents — показываем все
   */
  const hasExactSeasonMatches = !isSeries || seasonFilteredTorrents.length > 0;
  const effectiveTorrents = hasExactSeasonMatches ? seasonFilteredTorrents : rawTorrents;

  /**
   * Список доступных переводов/озвучек для фильтра
   */
  const availableVoiceovers = useMemo(() => {
    const set = new Set<string>();
    effectiveTorrents.forEach((r) => {
      const parsed = parseTrans(r.title, t);
      if (parsed) set.add(parsed);
    });
    return Array.from(set).sort();
  }, [effectiveTorrents, t]);

  /**
   * Фильтрация по выбранной озвучке
   */
  const displayedTorrents = useMemo(() => {
    if (selectedVoiceover === 'all') return effectiveTorrents;
    return effectiveTorrents.filter(
      (r) => parseTrans(r.title, t) === selectedVoiceover
    );
  }, [effectiveTorrents, selectedVoiceover, t]);

  /**
   * Запуск встроенного плеера прямо на странице раздач (раздачи сдвигаются вниз под плеер)
   */
  const handleOpenDetail = (r: TorrentResult, episode?: number) => {
    openPlayback({
      hash: r.hash,
      title: r.title,
      magnet: r.magnet,
      targetSeason: isSeries ? currentSeason : undefined,
      targetEpisode: episode,
    });
  };

  const watchedEpisodeKeys = useMemo(() => {
    const set = new Set<string>();
    if (!progressData) return set;
    if (progressData.watched_episode_keys && Array.isArray(progressData.watched_episode_keys)) {
      progressData.watched_episode_keys.forEach((k) => set.add(k));
    }
    const seasons = progressData.seasons;
    if (seasons) {
      const seasonList = Array.isArray(seasons) ? seasons : Object.values(seasons);
      seasonList.forEach((s) => {
        if (s.episodes && Array.isArray(s.episodes)) {
          s.episodes.forEach((ep: any) => {
            if (ep.is_watched) {
              set.add(`${ep.season}:${ep.episode}`);
            }
          });
        }
      });
    }
    return set;
  }, [progressData]);

  const curSeasonProgress = useMemo(() => {
    if (!progressData?.seasons) return null;
    if (Array.isArray(progressData.seasons)) {
      return progressData.seasons.find((s) => Number(s.season) === currentSeason) || null;
    }
    return progressData.seasons[String(currentSeason)] || null;
  }, [progressData, currentSeason]);

  const currentSeasonEpisodes = useMemo(() => {
    if (!isSeries) return [];
    if (onlineEpisodes && !episodeAvailability.busy) {
      return episodeAvailability.episodes.map(episode => !differentOnlinePart && metaVideos.find(video => video.season === currentSeason && video.episode === episode) || {season: currentSeason, episode, title: `Серия ${episode}`});
    }
    if (!metaVideos.length) return [];
    return metaVideos
      .filter((v) => Number(v.season) === currentSeason)
      .sort((a, b) => Number(a.episode) - Number(b.episode));
  }, [isSeries, metaVideos, currentSeason, onlineEpisodes, episodeAvailability, differentOnlinePart]);

  const curSeasonEpisodesCount = currentSeasonEpisodes.length;
  const curSeasonWatched = curSeasonProgress?.watched ?? curSeasonProgress?.watched_files ?? 0;
  const curSeasonTotal = Math.max(
    curSeasonProgress?.total ?? 0,
    curSeasonProgress?.total_files ?? 0,
    curSeasonEpisodesCount
  );
  const curSeasonPercent = curSeasonTotal > 0
    ? (curSeasonProgress?.progress_percent ?? Math.round((curSeasonWatched / curSeasonTotal) * 100))
    : 0;
  const isCurSeasonCompleted =
    curSeasonProgress?.is_completed || (curSeasonTotal > 0 && curSeasonWatched >= curSeasonTotal);

  const nextUnwatchedEpisode = nextUnwatched?.found
    ? (nextUnwatched.episode ?? nextUnwatched.next_episode ?? null)
    : (nextUnwatched?.next_episode ?? nextUnwatched?.episode ?? null);
  const nextUnwatchedSeason = nextUnwatched?.season ?? currentSeason;
  const nextEpVideo = useMemo(() => {
    if (!nextUnwatchedEpisode) return null;
    return metaVideos.find(
      (v) => Number(v.season) === nextUnwatchedSeason && Number(v.episode) === nextUnwatchedEpisode
    );
  }, [metaVideos, nextUnwatchedSeason, nextUnwatchedEpisode]);

  const handlePlayNextUnwatched = (seasonNum: number, episodeNum: number) => {
    setCurrentSeason(seasonNum);
    if (onlineEpisodes) { playOnlineEpisode(episodeNum); return; }
    if (effectiveTorrents.length > 0) {
      const release = effectiveTorrents[0];
      openPlayback({ hash: release.hash, title: release.title, magnet: release.magnet, targetSeason: seasonNum, targetEpisode: episodeNum });
    }
  };

  const toggleCollection = async (listName: CollectionName) => {
    if (!imdb || savingCollection) return;

    setSavingCollection(listName);
    try {
      if (collectionMembership[listName]) {
        await API.removeCollectionItem(listName, imdb);
      } else {
        const item: CollectionItem = {
          media_id: imdb,
          title: metaOriginalTitle || title,
          title_ru: metaTitleRu,
          poster_url: metaPoster || undefined,
          year: metaYear,
          rating: metaRating,
          overview: metaOverview || undefined,
          overview_ru: metaOverviewRu,
          genres: metaGenres,
          media_type: isSeries ? 'series' : 'movie',
        };
        await API.saveCollectionItem(listName, item);
      }
      setCollectionMembership((current) => ({
        ...current,
        [listName]: !current[listName],
      }));
    } catch (err: any) {
      alert(err?.message || 'Ошибка сохранения подборки');
    } finally {
      setSavingCollection(null);
    }
  };

  const displayTitle = metaTitleRu || title;
  const overview = metaOverviewRu || metaOverview;
  const selectSeason = (season: number) => {
    initializedSeason.current = `${type}:${imdb}`;
    setCurrentSeason(season);
    if (activePlayback) openPlayback({ ...activePlayback, targetSeason: season, targetEpisode: undefined });
  };
  const primaryRelease = displayedTorrents[0] || rawTorrents[0];

  return (
    <div className="cinema-page cinema-detail">
      <button id="meta-back-btn" type="button" className="cinema-button cinema-button--quiet cinema-back" onClick={goBack}><ArrowLeft aria-hidden="true" />{t('back')}</button>

      {imdb.startsWith('yummy:') && <div className="cinema-secondary" role="note"><p>Каталог YummyAnime · {metadata?.translations?.join(' · ')}</p>{metadata?.blocked && <p>YummyAnime сообщает об ограничениях доступа к видео этого тайтла.</p>}</div>}
      <CinemaHero title={displayTitle} poster={metaPoster} backdrop={metaBackdrop}>
        <h1 id="meta-title">{displayTitle}</h1>
        {metaOriginalTitle && metaOriginalTitle !== displayTitle && <p className="cinema-original-title">{metaOriginalTitle}</p>}
        <div className="cinema-metadata">
          {metaRating !== null && <span id="meta-rating" className="cinema-rating"><Star aria-hidden="true" />{metaRating.toFixed(1)}</span>}
          {metaYear && <span>{metaYear}</span>}
          <span>{isSeries ? 'Сериал' : 'Фильм'}</span>
          {metaGenres.map(genre => <span key={genre}>{genre}</span>)}
        </div>
        {loadingMetadata && <div className="cinema-skeleton" aria-label={t('loading')} aria-busy="true"><div /><div /><div /></div>}
        {overview && <p id="meta-overview" className="cinema-detail-overview">{overview}</p>}
        <div className="cinema-hero-actions">
          <button type="button" className="cinema-button cinema-button--primary" disabled={!(imdb.startsWith('yummy:') || imdb.startsWith('shikimori:')) && !primaryRelease && isSearchingTorrents} onClick={() => {
            if ((imdb.startsWith('yummy:') || imdb.startsWith('shikimori:'))) {
              document.getElementById('anime-sources')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
              document.getElementById('yummy-start')?.focus({ preventScroll: true });
              return;
            }
            if (primaryRelease) {
              if (isSeries && nextUnwatchedEpisode) handlePlayNextUnwatched(nextUnwatchedSeason, nextUnwatchedEpisode);
              else handleOpenDetail(primaryRelease, isSeries ? currentSeasonEpisodes[0]?.episode : undefined);
            } else document.getElementById('cinema-releases')?.scrollIntoView({block: 'start'});
          }}>
            {!(imdb.startsWith('yummy:') || imdb.startsWith('shikimori:')) && isSearchingTorrents && !primaryRelease ? <Loader2 className="animate-spin" /> : <Play className="fill-current" aria-hidden="true" />}
            {(imdb.startsWith('yummy:') || imdb.startsWith('shikimori:')) ? 'Смотреть онлайн' : isSearchingTorrents && !primaryRelease ? t('searching') : primaryRelease ? t('watch') : 'Выбрать раздачу'}
          </button>
          <button type="button" className="cinema-button cinema-button--secondary" aria-pressed={collectionMembership.favorites} disabled={!imdb || savingCollection !== null} onClick={() => toggleCollection('favorites')}>
            {savingCollection === 'favorites' ? <Loader2 className="animate-spin" /> : <Heart aria-hidden="true" className={collectionMembership.favorites ? 'fill-current' : ''} />}
            {collectionMembership.favorites ? t('remove_from_favorites') : t('add_to_favorites')}
          </button>
          <button type="button" className="cinema-button cinema-button--quiet" aria-pressed={collectionMembership.watch_later} disabled={!imdb || savingCollection !== null} onClick={() => toggleCollection('watch_later')}>
            {savingCollection === 'watch_later' ? <Loader2 className="animate-spin" /> : <Clock3 aria-hidden="true" />}
            {collectionMembership.watch_later ? t('remove_from_watch_later') : t('add_to_watch_later')}
          </button>
        </div>
      </CinemaHero>
      {(imdb.startsWith('yummy:') || imdb.startsWith('shikimori:')) && <AnimeSourcesPanel key={imdb} mediaId={imdb} title={displayTitle} resume={routeParams.animeResume} episodeRequest={episodeRequest} onAvailabilityChange={setEpisodeAvailability} onCompleted={loadProgress} />}

      {isSeries && (
        <section className="cinema-section" aria-label="Сезоны и серии">
          <div className="cinema-section-heading cinema-season-heading">
            <h2>Сезоны и серии</h2>
            {!differentOnlinePart && curSeasonTotal > 0 && <span className="cinema-secondary">{curSeasonWatched} из {curSeasonTotal} просмотрено{isCurSeasonCompleted ? ' · Сезон просмотрен' : ''}</span>}
          </div>
          {differentOnlinePart && <p className="cinema-secondary">{episodeAvailability.title}</p>}
          {!differentOnlinePart && <div className="cinema-season-list" role="group" aria-label="Выбрать сезон">
            {availableSeasons.map(season => {
              const sp = progressData?.seasons ? (Array.isArray(progressData.seasons) ? progressData.seasons.find(s => Number(s.season) === season) : progressData.seasons[String(season)]) : null;
              return <button type="button" key={season} aria-pressed={season === currentSeason} onClick={() => selectSeason(season)}>{t('season_prefix')} {season}{sp?.is_completed && <Check aria-label="Просмотрен" />}</button>;
            })}
          </div>}
          {!differentOnlinePart && curSeasonTotal > 0 && <div className="cinema-progress cinema-season-progress" role="progressbar" aria-label="Прогресс сезона" aria-valuenow={Math.round(Math.max(0, Math.min(100, curSeasonPercent)))} aria-valuemin={0} aria-valuemax={100}><span style={{width: `${Math.max(0, Math.min(100, curSeasonPercent))}%`}} /></div>}
          {!differentOnlinePart && nextUnwatchedEpisode && (
            <div className="cinema-next-episode">
              <div><p className="cinema-secondary">Следующая к просмотру</p><strong>Сезон {nextUnwatchedSeason}, серия {nextUnwatchedEpisode}{nextEpVideo?.title || nextEpVideo?.name ? ` — ${nextEpVideo.title || nextEpVideo.name}` : ''}</strong></div>
              <div className="cinema-inline-actions">
                <button type="button" className="cinema-button cinema-button--secondary" disabled={onlineEpisodes ? !canPlayOnlineEpisode(nextUnwatchedEpisode) : !effectiveTorrents.length} onClick={() => handlePlayNextUnwatched(nextUnwatchedSeason, nextUnwatchedEpisode)}><Play aria-hidden="true" />{t('play')}</button>
                <button type="button" className="cinema-icon-button" title="Отметить просмотренной" aria-label="Отметить следующую серию просмотренной" onClick={() => handleToggleEpisodeWatched(nextUnwatchedSeason, nextUnwatchedEpisode, false)}><CheckCircle2 /></button>
              </div>
            </div>
          )}
          {currentSeasonEpisodes.length ? (
            <div className="cinema-episode-list">
              {currentSeasonEpisodes.map(ep => {
                const watched = watchedEpisodeKeys.has(`${ep.season}:${ep.episode}`);
                return (
                  <div className="cinema-episode" key={`${ep.season}-${ep.episode}`}>
                    <span className="cinema-episode-number">{String(ep.episode).padStart(2, '0')}</span>
                    <div className="cinema-episode-copy"><h3>{ep.title || ep.name || `Серия ${ep.episode}`}</h3>{ep.overview && <p>{ep.overview}</p>}{ep.released && <small>{ep.released}</small>}</div>
                    {!differentOnlinePart && <button type="button" className="cinema-icon-button" aria-pressed={watched} aria-label={watched ? `Серия ${ep.episode}: отметить непросмотренной` : `Серия ${ep.episode}: отметить просмотренной`} title={watched ? 'Отметить непросмотренной' : 'Отметить просмотренной'} onClick={() => handleToggleEpisodeWatched(ep.season, ep.episode, watched)}>{watched ? <CheckCircle2 /> : <Circle />}</button>}
                    <button type="button" className="cinema-button cinema-button--quiet cinema-episode-play" disabled={onlineEpisodes ? !canPlayOnlineEpisode(ep.episode) : !primaryRelease} aria-label={`${t('play')}: серия ${ep.episode}`} onClick={() => onlineEpisodes ? playOnlineEpisode(ep.episode) : primaryRelease && handleOpenDetail(primaryRelease, ep.episode)}><Play aria-hidden="true" /><span>{t('play')}</span></button>
                  </div>
                );
              })}
            </div>
          ) : <p className="cinema-secondary cinema-episodes-empty">Список серий пока недоступен. Выберите сезон и раздачу ниже.</p>}
        </section>
      )}

      <section id="cinema-releases" className="cinema-section" aria-label="Раздачи">
        <div className="cinema-section-heading cinema-release-heading">
          <h2>Раздачи{isSearchingTorrents && <Loader2 className="animate-spin" aria-label="Идёт поиск" />}</h2>
          <div className="cinema-filters">
            {isSeries && <label id="meta-series-controls">Сезон<select id="meta-season-sel" value={currentSeason} onChange={e => selectSeason(Number(e.target.value))}>{availableSeasons.map(s => <option value={s} key={s}>{t('season_prefix')} {s}</option>)}</select></label>}
            {availableVoiceovers.length > 1 && <label><Mic aria-hidden="true" /><span className="sr-only">Озвучка</span><select id="meta-trans-sel" value={selectedVoiceover} onChange={e => setSelectedVoiceover(e.target.value)}><option value="all">{t('all_voiceovers')}</option>{availableVoiceovers.map(v => <option key={v} value={v}>{v}</option>)}</select></label>}
          </div>
        </div>
        <InlinePlayer />
        {isSeries && rawTorrents.length > 0 && !hasExactSeasonMatches && <p className="cinema-notice"><AlertCircle aria-hidden="true" />Нет точного совпадения по сезону {currentSeason}. Показаны все доступные раздачи ({rawTorrents.length}).</p>}
        <div id="meta-search-results" aria-busy={isSearchingTorrents}>
          {isSearchingTorrents && !rawTorrents.length ? (
            <div className="cinema-empty" role="status"><Loader2 className="animate-spin" /><p>{t('searching_torrents')}</p></div>
          ) : searchError && !rawTorrents.length ? (
            <div className="cinema-empty" role="alert"><AlertCircle /><SafeHtmlText text={t('search_error', {error: searchError}) || searchError} /><button type="button" className="cinema-button cinema-button--secondary" onClick={handleRetrySearch}><RefreshCw />Повторить поиск</button></div>
          ) : !rawTorrents.length ? (
            <div className="cinema-empty"><Film /><p>{isSeries ? 'Раздачи для сериала не найдены' : 'Раздачи для фильма не найдены'}</p><button type="button" className="cinema-button cinema-button--secondary" onClick={handleRetrySearch}><RefreshCw />Повторить поиск</button></div>
          ) : !displayedTorrents.length ? (
            <div className="cinema-empty"><p>Ничего не найдено с выбранной озвучкой</p><button type="button" className="cinema-button cinema-button--secondary" onClick={() => setSelectedVoiceover('all')}>Показать все озвучки</button></div>
          ) : displayedTorrents.map((r, idx) => (
            <div key={r.hash || idx} className="cinema-release">
              <div className="cinema-release-copy"><h3 title={r.title}>{r.title}</h3><div className="cinema-release-meta">
                {r.quality && <span className="cinema-quality">{r.quality}</span>}
                {r.source && <span>{r.source}</span>}
                <span>{parseTrans(r.title, t)}</span>
                {r.size && <span>{typeof r.size === 'number' ? (r.size / (1024 ** 3)).toFixed(1) + ' GB' : r.size}</span>}
                {r.seeders !== undefined && <span>{r.seeders} {t('seeders')}</span>}
              </div></div>
              <button type="button" className="cinema-button cinema-button--secondary" onClick={() => handleOpenDetail(r)} aria-label={`${t('play')}: ${r.title}`}><Play aria-hidden="true" />{t('play')}</button>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
};
