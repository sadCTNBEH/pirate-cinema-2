/**
 * @file components/home/HomeView.tsx
 * @description Главный экран каталога Pirate Cinema.
 * Отображает блок "Продолжить просмотр", витрину популярных фильмов
 * и сериалов, синхронизированных с бэкендом.
 */

import React, { useEffect, useState, useCallback } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { RecentItem, MediaItem } from '../../types';
import { formatTime } from '../../utils/torrentParser';
import { Play, Trash2, Film, Star, Loader2, Tv } from 'lucide-react';
import { Progress } from '../ui/UIComponents';

// Клиентский кэш популярных подборок для мгновенного первого рендера и исключения повторных запросов
const POPULAR_CACHE: { movies?: MediaItem[]; series?: MediaItem[] } = {};
let RECENT_CACHE: RecentItem[] = [];

function getInitialRecent(): RecentItem[] {
  if (RECENT_CACHE.length > 0) return RECENT_CACHE;
  try {
    const raw = sessionStorage.getItem('pc_recent_items');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        RECENT_CACHE = parsed;
        return parsed;
      }
    }
  } catch {}
  return [];
}

function getInitialCatalog(key: 'movies' | 'series'): MediaItem[] {
  if (POPULAR_CACHE[key]?.length) {
    return POPULAR_CACHE[key]!;
  }
  try {
    const raw = sessionStorage.getItem(`pc_catalog_${key}`);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        POPULAR_CACHE[key] = parsed;
        return parsed;
      }
    }
  } catch {}
  return [];
}

interface CatalogPosterImageProps {
  posterSrc?: string | null;
  displayTitle: string;
}

const CatalogPosterImage = React.memo<CatalogPosterImageProps>(({ posterSrc, displayTitle }) => {
  const [hasError, setHasError] = useState<boolean>(false);

  useEffect(() => {
    setHasError(false);
  }, [posterSrc]);

  if (!posterSrc || hasError) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center p-3 text-center bg-slate-900 select-none">
        <Film className="w-8 h-8 text-slate-700 mb-2 shrink-0" />
        <span className="text-slate-500 text-xs font-tech line-clamp-3 leading-tight">
          {displayTitle}
        </span>
      </div>
    );
  }

  return (
    <img
      src={posterSrc}
      alt={displayTitle}
      onError={() => setHasError(true)}
      decoding="async"
      className="w-full h-full object-cover"
    />
  );
});

interface CatalogMediaCardProps {
  item: MediaItem;
  type: 'movie' | 'series';
  onNavigate: (imdb: string, title: string, type: 'movie' | 'series', poster?: string) => void;
}

const CatalogMediaCard = React.memo<CatalogMediaCardProps>(({ item, type, onNavigate }) => {
  const posterSrc = item.poster_local_url || item.poster_url;
  const displayTitle = item.title_ru || item.title;
  const subTitle = item.title_ru ? (item.original_title || item.title) : undefined;
  const hoverBorder = type === 'movie' ? 'group-hover:border-cyan-400/70' : 'group-hover:border-sky-400/70';

  return (
    <button
      type="button"
      title={item.overview_ru || item.overview}
      onClick={() => onNavigate(item.id, displayTitle, type, posterSrc || undefined)}
      className="card text-left bg-transparent border-0 p-0 group cursor-pointer [contain:layout_paint]"
    >
      <div className={`poster aspect-[2/3] w-full rounded-lg overflow-hidden bg-slate-900 border border-slate-800/80 ${hoverBorder} relative`}>
        <CatalogPosterImage posterSrc={posterSrc} displayTitle={displayTitle} />
        {item.rating && (
          <div className="absolute top-2 right-2 bg-[#060910]/90 border border-amber-500/40 text-amber-300 px-1.5 py-0.5 rounded-md font-code text-[11px] font-bold flex items-center gap-1 shadow">
            <Star className="w-3 h-3 fill-amber-400 text-amber-400" />
            {item.rating.toFixed(1)}
          </div>
        )}
      </div>
      <strong className="block mt-2 font-tech text-sm font-semibold text-slate-200 truncate group-hover:text-cyan-400">
        {displayTitle}
      </strong>
      <small className="block font-code text-xs text-slate-400 truncate">
        {subTitle ? subTitle : (item.year || '')}
        {subTitle && item.year ? ` · ${item.year}` : ''}
      </small>
    </button>
  );
});

const CatalogSkeletonGrid: React.FC = () => (
  <div className="poster-grid grid grid-cols-2 gap-5 sm:grid-cols-3 lg:[grid-template-columns:repeat(auto-fill,210px)] lg:justify-start">
    {Array.from({ length: 10 }).map((_, i) => (
      <div key={i} className="animate-pulse">
        <div className="aspect-[2/3] w-full rounded-lg bg-slate-800/40 border border-slate-800/60" />
        <div className="h-4 bg-slate-800/50 rounded mt-2.5 w-3/4" />
        <div className="h-3 bg-slate-800/30 rounded mt-1.5 w-1/2" />
      </div>
    ))}
  </div>
);

export const HomeView: React.FC = () => {
  const { t, navigate } = useApp();

  const [recentItems, setRecentItems] = useState<RecentItem[]>(() => getInitialRecent());
  const [popularMovies, setPopularMovies] = useState<MediaItem[]>(() => getInitialCatalog('movies'));
  const [popularSeries, setPopularSeries] = useState<MediaItem[]>(() => getInitialCatalog('series'));
  
  const [isLoadingRecent, setIsLoadingRecent] = useState<boolean>(() => !getInitialRecent().length);
  const [isLoadingMovies, setIsLoadingMovies] = useState<boolean>(() => !getInitialCatalog('movies').length);
  const [isLoadingSeries, setIsLoadingSeries] = useState<boolean>(() => !getInitialCatalog('series').length);
  const [playingHash, setPlayingHash] = useState<string | null>(null);
  const [catalogType, setCatalogType] = useState<'movies' | 'series'>('movies');

  /**
   * Загрузка истории просмотров
   */
  const loadRecent = async () => {
    if (!RECENT_CACHE.length) {
      setIsLoadingRecent(true);
    }
    try {
      const items = await API.getRecent();
      const valid = Array.isArray(items) ? items : [];
      RECENT_CACHE = valid;
      try {
        sessionStorage.setItem('pc_recent_items', JSON.stringify(valid));
      } catch {}
      setRecentItems((prev) => {
        if (
          prev.length === valid.length &&
          prev.every(
            (it, idx) =>
              it.torrent_hash === valid[idx].torrent_hash &&
              it.file_index === valid[idx].file_index &&
              it.playback_timecode === valid[idx].playback_timecode
          )
        ) {
          return prev;
        }
        return valid;
      });
    } catch (e) {
      console.warn('Ошибка загрузки истории просмотров:', e);
    } finally {
      setIsLoadingRecent(false);
    }
  };

  /**
   * Загрузка подборки популярных фильмов (фоновая актуализация без очистки интерфейса)
   */
  const loadMovies = async () => {
    if (!POPULAR_CACHE.movies?.length) {
      setIsLoadingMovies(true);
    }
    try {
      const data = await API.getPopular('movies');
      if (Array.isArray(data) && data.length > 0) {
        POPULAR_CACHE.movies = data;
        try {
          sessionStorage.setItem('pc_catalog_movies', JSON.stringify(data));
        } catch {}
        setPopularMovies((prev) => {
          if (
            prev.length === data.length &&
            prev.every((it, idx) => it.id === data[idx].id && it.poster_local_url === data[idx].poster_local_url)
          ) {
            return prev;
          }
          return data;
        });
      }
    } catch (e) {
      console.warn('Ошибка загрузки фильмов:', e);
    } finally {
      setIsLoadingMovies(false);
    }
  };

  /**
   * Загрузка подборки популярных сериалов (фоновая актуализация без очистки интерфейса)
   */
  const loadSeries = async () => {
    if (!POPULAR_CACHE.series?.length) {
      setIsLoadingSeries(true);
    }
    try {
      const data = await API.getPopular('series');
      if (Array.isArray(data) && data.length > 0) {
        POPULAR_CACHE.series = data;
        try {
          sessionStorage.setItem('pc_catalog_series', JSON.stringify(data));
        } catch {}
        setPopularSeries((prev) => {
          if (
            prev.length === data.length &&
            prev.every((it, idx) => it.id === data[idx].id && it.poster_local_url === data[idx].poster_local_url)
          ) {
            return prev;
          }
          return data;
        });
      }
    } catch (e) {
      console.warn('Ошибка загрузки сериалов:', e);
    } finally {
      setIsLoadingSeries(false);
    }
  };

  useEffect(() => {
    loadRecent();
    loadMovies();
    loadSeries();
  }, []);

  /**
   * Запуск воспроизведения недавнего файла через MPV
   */
  const handlePlayRecent = async (item: RecentItem) => {
    setPlayingHash(item.torrent_hash);
    try {
      await API.playFile({
        hash: item.torrent_hash,
        file_id: item.file_index,
        file_name: item.file_name,
        start_time: item.playback_timecode || 0,
      });
    } catch (err: any) {
      alert(t('mpv_start_error', { error: err.message }) || err.message);
    } finally {
      setPlayingHash(null);
    }
  };

  /**
   * Удаление позиции из истории просмотров
   */
  const handleRemoveHistory = async (e: React.MouseEvent, hash: string) => {
    e.stopPropagation();
    if (!window.confirm(t('confirm_delete_history'))) return;

    try {
      await API.removeHistory(hash);
      setRecentItems((prev) => {
        const next = prev.filter((item) => item.torrent_hash !== hash);
        RECENT_CACHE = next;
        try {
          sessionStorage.setItem('pc_recent_items', JSON.stringify(next));
        } catch {}
        return next;
      });
    } catch (err: any) {
      alert(t('error', { error: err.message }) || err.message);
    }
  };

  const handleNavigate = useCallback(
    (imdb: string, title: string, type: 'movie' | 'series', poster?: string) => {
      navigate('meta', { imdb, title, type, poster });
    },
    [navigate]
  );

  const activeCatalog = catalogType === 'movies' ? popularMovies : popularSeries;
  const isLoadingCatalog = catalogType === 'movies' ? isLoadingMovies : isLoadingSeries;
  const activeType = catalogType === 'movies' ? 'movie' : 'series';

  return (
    <div className="space-y-6 animate-fade-in">
      {/* ── Блок "Продолжить просмотр" ── */}
      <section id="continue-section" className={recentItems.length > 0 ? '' : 'hidden'}>
        {recentItems.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-tech font-bold uppercase tracking-wider text-slate-100 flex items-center gap-2">
                <span className="w-1.5 h-4 bg-cyan-400" />
                {t('continue_watching')}
              </h2>
            </div>

            <div className="continue-list grid gap-3 max-w-4xl">
              {recentItems.map((item) => {
                const isItemPlaying = playingHash === item.torrent_hash;
                return (
                  <div
                    key={item.torrent_hash + item.file_index}
                    className="continue-item-wrapper flex items-center gap-2 group"
                  >
                    <button
                      type="button"
                      onClick={() => handlePlayRecent(item)}
                      disabled={isItemPlaying}
                      className="continue-item flex-1 grid grid-cols-[56px_minmax(0,1fr)_180px_auto] gap-4 items-center p-3 rounded-sm bg-[#0a0e18] border border-cyan-900/30 hover:border-cyan-500/50 hover:bg-[#0d1424] transition-colors duration-75 text-left cursor-pointer shadow-sm [contain:layout_paint]"
                    >
                      {/* Постер */}
                      <div className="w-14 h-20 rounded-sm overflow-hidden bg-slate-900 flex items-center justify-center border border-slate-800">
                        {item.poster_url ? (
                          <img
                            src={item.poster_url}
                            alt={item.title || item.file_name}
                            className="w-full h-full object-cover"
                            decoding="async"
                            loading="lazy"
                          />
                        ) : (
                          <Film className="w-6 h-6 text-slate-600" />
                        )}
                      </div>

                      {/* Информация о релизе */}
                      <div className="min-w-0 pr-2">
                        <strong className="block text-sm font-semibold text-slate-100 truncate group-hover:text-cyan-400 transition-colors">
                          {item.title || item.file_name}
                        </strong>
                        <small className="block mt-1 font-code text-xs text-slate-400 truncate">
                          {item.file_name}
                        </small>
                      </div>

                      {/* Прогресс таймкода */}
                      <div className="w-full">
                        <Progress
                          value={item.playback_timecode || 0}
                          max={item.playback_duration || 1}
                        />
                      </div>

                      {/* Длительность и действие */}
                      <div className="flex items-center gap-3">
                        <span className="font-code text-xs text-slate-400">
                          {item.is_watched
                            ? t('watched')
                            : formatTime(item.playback_timecode || 0)}
                        </span>
                        <div className="w-8 h-8 rounded-sm bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 flex items-center justify-center group-hover:bg-cyan-500 group-hover:text-black transition-colors">
                          {isItemPlaying ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <Play className="w-3.5 h-3.5 fill-current" />
                          )}
                        </div>
                      </div>
                    </button>

                    {/* Удалить из истории */}
                    <button
                      type="button"
                      onClick={(e) => handleRemoveHistory(e, item.torrent_hash)}
                      title={t('remove_from_history')}
                      className="p-3 text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 rounded-sm border border-transparent hover:border-rose-500/30 transition-all cursor-pointer"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </section>

      <section id="popular-catalog" aria-label={t('nav_catalog')}>
        <div className="mb-5 flex flex-col gap-4 border-b border-slate-800 pb-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-tech font-bold uppercase tracking-wider text-slate-100">
              <span className={`h-4 w-1.5 ${catalogType === 'movies' ? 'bg-cyan-400' : 'bg-sky-400'}`} />
              {catalogType === 'movies' ? t('popular_movies') : t('popular_series')}
            </h2>
          </div>

          <div
            role="tablist"
            aria-label={t('filter_type')}
            className="grid w-full grid-cols-2 rounded-md border border-slate-800 bg-[#080c14] p-1 sm:w-auto"
          >
            <button
              type="button"
              role="tab"
              aria-selected={catalogType === 'movies'}
              onClick={() => setCatalogType('movies')}
              className={`flex h-10 items-center justify-center gap-2 rounded-sm px-4 font-tech text-xs font-semibold uppercase tracking-wider transition-colors ${
                catalogType === 'movies'
                  ? 'bg-cyan-500/20 text-cyan-300 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.35)]'
                  : 'text-slate-500 hover:bg-slate-800/70 hover:text-slate-200'
              }`}
            >
              <Film className="h-4 w-4" />
              {t('movies')}
              <span className="font-code text-[10px] opacity-70">{popularMovies.length}</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={catalogType === 'series'}
              onClick={() => setCatalogType('series')}
              className={`flex h-10 items-center justify-center gap-2 rounded-sm px-4 font-tech text-xs font-semibold uppercase tracking-wider transition-colors ${
                catalogType === 'series'
                  ? 'bg-sky-500/20 text-sky-300 shadow-[inset_0_0_0_1px_rgba(56,189,248,0.35)]'
                  : 'text-slate-500 hover:bg-slate-800/70 hover:text-slate-200'
              }`}
            >
              <Tv className="h-4 w-4" />
              {t('series_plural')}
              <span className="font-code text-[10px] opacity-70">{popularSeries.length}</span>
            </button>
          </div>
        </div>

        {isLoadingCatalog && activeCatalog.length === 0 ? (
          <CatalogSkeletonGrid />
        ) : activeCatalog.length > 0 ? (
          <div className="poster-grid grid grid-cols-2 gap-5 sm:grid-cols-3 lg:[grid-template-columns:repeat(auto-fill,210px)] lg:justify-start">
            {activeCatalog.map((item) => (
              <CatalogMediaCard
                key={item.id}
                item={item}
                type={activeType}
                onNavigate={handleNavigate}
              />
            ))}
          </div>
        ) : null}
      </section>
    </div>
  );
};
