/**
 * @file components/meta/MetaView.tsx
 * @description Экран карточки медиа (фильма или сериала).
 * Загружает расширенные метаданные, серии, парсит раздачи,
 * фильтрует по сезонам и аудиодорожкам/переводам.
 */

import React, { useEffect, useState, useMemo, useRef, useCallback } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { CollectionItem, CollectionName, SeriesEpisode, TorrentResult } from '../../types';
import { parseTrans, matchesSeason } from '../../utils/torrentParser';
import { Button, Select, SafeHtmlText } from '../ui/UIComponents';
import {
  ArrowLeft,
  Star,
  Film,
  Mic,
  Play,
  Loader2,
  Radio,
  AlertCircle,
  Clock3,
  Heart,
  RefreshCw,
} from 'lucide-react';
import { InlinePlayer } from '../player/InlinePlayer';

export const MetaView: React.FC = () => {
  const { routeParams, goBack, openPlayback, activePlayback, t } = useApp();
  const { imdb = '', title = '', type = 'movie', poster = '' } = routeParams;

  const [metaOverview, setMetaOverview] = useState<string>('');
  const [metaOverviewRu, setMetaOverviewRu] = useState<string | null>(null);
  const [metaRating, setMetaRating] = useState<number | null>(null);
  const [metaYear, setMetaYear] = useState<number | null>(null);
  const [metaGenres, setMetaGenres] = useState<string[]>([]);
  const [metaPoster, setMetaPoster] = useState<string>(poster);
  const [posterError, setPosterError] = useState<boolean>(false);
  const [metaVideos, setMetaVideos] = useState<SeriesEpisode[]>([]);
  const [isSeries, setIsSeries] = useState<boolean>(type === 'series');
  const [metaTitleRu, setMetaTitleRu] = useState<string | null>(null);
  const [metaOriginalTitle, setMetaOriginalTitle] = useState<string | null>(null);

  const [currentSeason, setCurrentSeason] = useState<number>(1);
  const [currentEpisode, setCurrentEpisode] = useState<number>(1);

  const [rawTorrents, setRawTorrents] = useState<TorrentResult[]>([]);
  const [isSearchingTorrents, setIsSearchingTorrents] = useState<boolean>(true);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [selectedVoiceover, setSelectedVoiceover] = useState<string>('all');
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
    const unsearched = queries
      .map((q) => q.trim())
      .filter((q) => q.length > 0 && !searchedQueriesRef.current.has(q));

    if (unsearched.length === 0) return;

    unsearched.forEach((q) => searchedQueriesRef.current.add(q));

    setIsSearchingTorrents(true);
    setSearchError(null);

    try {
      const results = await Promise.allSettled(
        unsearched.map((q) => API.searchTorrents(q))
      );

      if (!isMountedRef.current) return;

      setRawTorrents((prev) => {
        const map = new Map<string, TorrentResult>();
        prev.forEach((item) => {
          const key = item.hash || item.magnet || item.title;
          if (key) map.set(key, item);
        });

        results.forEach((res) => {
          if (res.status === 'fulfilled' && Array.isArray(res.value)) {
            res.value.forEach((item) => {
              const key = item.hash || item.magnet || item.title;
              if (key && !map.has(key)) {
                map.set(key, item);
              }
            });
          }
        });

        return Array.from(map.values());
      });
    } catch (err: any) {
      if (isMountedRef.current) {
        setSearchError(err?.message || 'Ошибка поиска');
      }
    } finally {
      if (isMountedRef.current) {
        setIsSearchingTorrents(false);
      }
    }
  }, []);

  /**
   * 1. Загрузка метаданных фильма/сериала из FastAPI
   */
  useEffect(() => {
    let isCancelled = false;

    if (imdb) {
      API.getMeta(imdb, isSeries ? 'series' : 'movie')
        .then((data) => {
          if (isCancelled || !data) return;
          if (data.overview) setMetaOverview(data.overview);
          if (data.overview_ru) setMetaOverviewRu(data.overview_ru);
          if (data.rating) setMetaRating(data.rating);
          if (data.year) setMetaYear(Number(data.year));
          if (Array.isArray(data.genres)) setMetaGenres(data.genres);
          const bestPoster = data.poster_local_url || data.poster_url;
          if (bestPoster && !poster) setMetaPoster(bestPoster);
          if (data.title_ru) {
            setMetaTitleRu(data.title_ru);
            setMetaOriginalTitle(data.original_title || null);
          }

          if (data.type === 'series' || isSeries) {
            setIsSeries(true);
            const vids = data.videos || [];
            setMetaVideos(vids);
            if (vids.length > 0) {
              const uniqueSeasons = Array.from(new Set(vids.map((v) => v.season))).sort(
                (a, b) => a - b
              );
              setCurrentSeason(uniqueSeasons[0] || 1);
            }
          }
        })
        .catch((err) => {
          console.warn('Ошибка загрузки метаданных:', err);
        });
    }

    return () => {
      isCancelled = true;
    };
  }, [imdb, isSeries, poster]);

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
   * Список эпизодов для выбранного сезона
   */
  const availableEpisodes = useMemo(() => {
    return metaVideos
      .filter((v) => v.season === Number(currentSeason))
      .sort((a, b) => a.episode - b.episode);
  }, [metaVideos, currentSeason]);

  // Сброс номера серии при смене сезона
  useEffect(() => {
    if (availableEpisodes.length > 0) {
      setCurrentEpisode(availableEpisodes[0].episode);
    }
  }, [currentSeason, availableEpisodes]);

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
  const handleOpenDetail = (r: TorrentResult) => {
    openPlayback({
      hash: r.hash,
      title: r.title,
      magnet: r.magnet,
      targetSeason: isSeries ? currentSeason : undefined,
      targetEpisode: isSeries ? currentEpisode : undefined,
    });
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

  return (
    <div className="space-y-8 animate-fade-in pb-12">
      {/* Кнопка возврата */}
      <div className="flex items-center justify-between">
        <Button
          id="meta-back-btn"
          variant="secondary"
          size="sm"
          icon={<ArrowLeft className="w-4 h-4" />}
          onClick={goBack}
        >
          {t('back')}
        </Button>
      </div>

      {/* Информационный блок медиа */}
      <div className="detail-layout grid grid-cols-1 md:grid-cols-[240px_minmax(0,1fr)] gap-8 bg-[#0a0e18]/80 border border-cyan-900/30 p-6 rounded-sm backdrop-blur-sm">
        {/* Постер */}
        <div className="w-full max-w-[240px] aspect-[2/3] mx-auto md:mx-0 rounded-sm overflow-hidden bg-slate-900 border border-cyan-500/30 shadow-[0_0_20px_rgba(0,240,255,0.15)] flex items-center justify-center">
          {metaPoster && !posterError ? (
            <img
              id="meta-poster"
              src={metaPoster}
              alt={title}
              onError={() => setPosterError(true)}
              className="w-full h-full object-cover"
            />
          ) : (
            <Film className="w-12 h-12 text-slate-700" />
          )}
        </div>

        {/* Описание и контролы серий */}
        <div className="flex flex-col justify-start">
          <h1 id="meta-title" className="text-3xl font-tech font-bold uppercase tracking-wider text-slate-100 mb-1">
            {metaTitleRu || title}
          </h1>
          {(metaOriginalTitle || (metaTitleRu && title !== metaTitleRu)) && (
            <p className="text-sm font-code text-slate-400 mb-3 truncate">
              {metaOriginalTitle || title}
            </p>
          )}

          {metaRating !== null && (
            <div id="meta-rating" className="flex items-center gap-1.5 font-code text-base font-bold text-amber-400 mb-4">
              <Star className="w-4 h-4 fill-amber-400" />
              <span>★ {metaRating.toFixed(1)}</span>
            </div>
          )}

          {(metaOverviewRu || metaOverview) && (
            <p id="meta-overview" className="overview text-slate-300 text-sm leading-relaxed mb-6 font-sans">
              {metaOverviewRu && metaOverviewRu.length > 50
                ? metaOverviewRu
                : metaOverviewRu && metaOverview
                ? `${metaOverviewRu}. ${metaOverview}`
                : metaOverviewRu || metaOverview}
            </p>
          )}

          <div className="flex flex-wrap gap-2 border-t border-cyan-900/30 pt-4">
            <Button
              variant={collectionMembership.favorites ? 'primary' : 'secondary'}
              size="sm"
              icon={<Heart className={`h-3.5 w-3.5 ${collectionMembership.favorites ? 'fill-current' : ''}`} />}
              loading={savingCollection === 'favorites'}
              disabled={!imdb || savingCollection !== null}
              onClick={() => toggleCollection('favorites')}
            >
              {collectionMembership.favorites ? t('remove_from_favorites') : t('add_to_favorites')}
            </Button>
            <Button
              variant={collectionMembership.watch_later ? 'primary' : 'secondary'}
              size="sm"
              icon={<Clock3 className="h-3.5 w-3.5" />}
              loading={savingCollection === 'watch_later'}
              disabled={!imdb || savingCollection !== null}
              onClick={() => toggleCollection('watch_later')}
            >
              {collectionMembership.watch_later ? t('remove_from_watch_later') : t('add_to_watch_later')}
            </Button>
          </div>

          {/* Селектор сезона и серии (если сериал) */}
          {isSeries && (
            <div id="meta-series-controls" className="flex flex-wrap items-center gap-3 pt-4 border-t border-cyan-900/30">
              <div className="flex items-center gap-2">
                <span className="font-tech text-xs text-slate-400 uppercase tracking-wider">
                  {t('season_prefix')}:
                </span>
                <Select
                  id="meta-season-sel"
                  value={currentSeason}
                  onChange={(e) => {
                    const nextSeason = Number(e.target.value);
                    setCurrentSeason(nextSeason);
                    if (activePlayback) {
                      openPlayback({
                        ...activePlayback,
                        targetSeason: nextSeason,
                        targetEpisode: 1,
                      });
                    }
                  }}
                >
                  {availableSeasons.map((s) => (
                    <option key={s} value={s}>
                      {t('season_prefix')} {s}
                    </option>
                  ))}
                </Select>
              </div>

              {availableEpisodes.length > 0 && (
                <div className="flex items-center gap-2">
                  <span className="font-tech text-xs text-slate-400 uppercase tracking-wider">
                    {t('episode')}:
                  </span>
                  <Select
                    id="meta-episode-sel"
                    value={currentEpisode}
                    onChange={(e) => {
                      const nextEp = Number(e.target.value);
                      setCurrentEpisode(nextEp);
                      if (activePlayback) {
                        openPlayback({
                          ...activePlayback,
                          targetSeason: currentSeason,
                          targetEpisode: nextEp,
                        });
                      }
                    }}
                  >
                    {availableEpisodes.map((ep) => (
                      <option key={ep.episode} value={ep.episode}>
                        {t('episode')} {ep.episode} {ep.name ? `(${ep.name})` : ''}
                      </option>
                    ))}
                  </Select>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Секция списка раздач ── */}
      <div>
        <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
          <h2 className="text-xl font-tech font-bold uppercase tracking-wider text-slate-100 flex items-center gap-2">
            <Radio className="w-5 h-5 text-cyan-400" />
            Раздачи
            {isSearchingTorrents && rawTorrents.length > 0 && (
              <Loader2 className="w-4 h-4 animate-spin text-cyan-400 ml-1 inline" />
            )}
          </h2>

          {/* Фильтр озвучек */}
          {availableVoiceovers.length > 1 && (
            <div className="flex items-center gap-2">
              <Mic className="w-4 h-4 text-cyan-400" />
              <Select
                id="meta-trans-sel"
                value={selectedVoiceover}
                onChange={(e) => setSelectedVoiceover(e.target.value)}
              >
                <option value="all">{t('all_voiceovers')}</option>
                {availableVoiceovers.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </Select>
            </div>
          )}
        </div>

        {/* Встроенный плеер появляется прямо здесь над списком раздач, сдвигая раздачи вниз */}
        <InlinePlayer />

        {/* Информационный баннер при отсутствии точного совпадения по сезону */}
        {isSeries && rawTorrents.length > 0 && !hasExactSeasonMatches && (
          <div className="p-3 mb-4 rounded-sm bg-amber-500/10 border border-amber-500/30 text-amber-300 font-sans text-xs flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
              <span>
                Нет точного совпадения по сезону {currentSeason} — показаны все доступные раздачи ({rawTorrents.length})
              </span>
            </div>
          </div>
        )}

        {/* Результаты сканирования раздач */}
        <div id="meta-search-results" className="space-y-3">
          {isSearchingTorrents && rawTorrents.length === 0 ? (
            <div className="p-8 text-center bg-[#0a0e18]/60 border border-cyan-900/30 rounded-sm text-slate-400 font-tech">
              <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2 text-cyan-400" />
              {t('searching_torrents')}
            </div>
          ) : searchError && rawTorrents.length === 0 ? (
            <div className="p-6 bg-rose-500/10 border border-rose-500/30 rounded-sm text-rose-300 font-sans text-sm">
              <SafeHtmlText text={t('search_error', { error: searchError }) || searchError} />
            </div>
          ) : rawTorrents.length === 0 ? (
            <div className="empty panel p-8 text-center bg-[#0a0e18]/60 border border-cyan-900/30 rounded-sm text-slate-400 font-tech space-y-3">
              <Film className="w-8 h-8 text-slate-600 mx-auto" />
              <p>{isSeries ? 'Раздачи для сериала не найдены' : 'Раздачи для фильма не найдены'}</p>
              <Button
                variant="secondary"
                size="sm"
                icon={<RefreshCw className="w-3.5 h-3.5" />}
                onClick={handleRetrySearch}
              >
                Повторить поиск
              </Button>
            </div>
          ) : displayedTorrents.length === 0 ? (
            <div className="empty panel p-8 text-center bg-[#0a0e18]/60 border border-cyan-900/30 rounded-sm text-slate-400 font-tech space-y-2">
              <p>Ничего не найдено с выбранной озвучкой</p>
              <Button variant="secondary" size="sm" onClick={() => setSelectedVoiceover('all')}>
                Показать все озвучки
              </Button>
            </div>
          ) : (
            displayedTorrents.map((r, idx) => {
              const trans = parseTrans(r.title, t);
              return (
                <div
                  key={r.hash || idx}
                  className="result flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-sm bg-[#090d16] border border-cyan-900/30 hover:border-cyan-500/50 hover:bg-[#0c1220] transition-all duration-150 shadow-sm"
                >
                  <div className="result-main min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2 mb-1.5">
                      <h3 className="text-sm font-semibold text-slate-100 truncate max-w-full" title={r.title}>
                        {r.title}
                      </h3>
                      {r.source && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono uppercase bg-cyan-950/80 text-cyan-300 border border-cyan-800/60 shrink-0">
                          {r.source}
                        </span>
                      )}
                      {r.quality && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono uppercase bg-indigo-950/80 text-indigo-300 border border-indigo-800/60 shrink-0">
                          {r.quality}
                        </span>
                      )}
                      {r.seeders !== undefined && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-emerald-950/80 text-emerald-300 border border-emerald-800/60 shrink-0 flex items-center gap-1">
                          🌱 {r.seeders} {t('seeders')}
                        </span>
                      )}
                    </div>
                    <div className="result-meta flex flex-wrap items-center gap-3 font-code text-xs text-slate-400">
                      <span className="text-cyan-400 flex items-center gap-1">
                        🎤 {trans}
                      </span>
                      {r.size && (
                        <span className="text-slate-500">
                          💾 {typeof r.size === 'number' ? (r.size / (1024 * 1024 * 1024)).toFixed(1) + ' GB' : r.size}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="result-actions shrink-0">
                    <Button
                      variant="primary"
                      size="sm"
                      icon={<Play className="w-3.5 h-3.5 fill-current" />}
                      onClick={() => handleOpenDetail(r)}
                    >
                      {t('play')}
                    </Button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
