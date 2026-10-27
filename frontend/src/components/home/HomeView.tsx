/**
 * @file components/home/HomeView.tsx
 * @description Главный экран каталога Pirate Cinema.
 * Отображает блок "Продолжить просмотр", витрину популярных фильмов
 * и сериалов, синхронизированных с бэкендом.
 */

import React, { useEffect, useState, useCallback } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { RecentItem, MediaItem, OnlinePlaylist } from '../../types';
import { formatTime } from '../../utils/torrentParser';
import { Play, Trash2, Film, Star, Loader2, Tv, ChevronRight, Search, RefreshCw } from 'lucide-react';
import { CinemaHero, CinemaImage } from '../ui/Cinema';
import { InlinePlayer } from '../player/InlinePlayer';

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

const CatalogMediaCard = React.memo<{
  item: MediaItem;
  type: 'movie' | 'series';
  onNavigate: (imdb: string, title: string, type: 'movie' | 'series', poster?: string) => void;
}>(({ item, type, onNavigate }) => {
  const poster = item.poster_local_url || item.poster_url;
  const title = item.title_ru || item.title;
  return (
    <button type="button" className="cinema-media-card" onClick={() => onNavigate(item.id, title, type, poster || undefined)}>
      <CinemaImage src={poster} title={title} className="cinema-poster" />
      <strong>{title}</strong>
      <span className="cinema-card-meta">
        <span>{item.year || (type === 'series' ? 'Сериал' : 'Фильм')}</span>
        {Boolean(item.rating) && <span className="cinema-rating"><Star aria-hidden="true" />{item.rating!.toFixed(1)}</span>}
      </span>
    </button>
  );
});

const CatalogSkeletonGrid: React.FC = () => (
  <div className="cinema-poster-grid" aria-label="Загрузка каталога" aria-busy="true">
    {Array.from({ length: 10 }, (_, i) => <div key={i} className="cinema-skeleton"><div className="cinema-poster" /><div /><div /></div>)}
  </div>
);

export const HomeView: React.FC = () => {
  const { t, navigate, openPlayback, route } = useApp();

  const [recentItems, setRecentItems] = useState<RecentItem[]>(() => getInitialRecent());
  const [popularMovies, setPopularMovies] = useState<MediaItem[]>(() => getInitialCatalog('movies'));
  const [popularSeries, setPopularSeries] = useState<MediaItem[]>(() => getInitialCatalog('series'));
  const [onlinePlaylists, setOnlinePlaylists] = useState<OnlinePlaylist[]>([]);
  
  const [, setIsLoadingRecent] = useState<boolean>(() => !getInitialRecent().length);
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
    API.getOnlinePlaylists()
      .then((data) => setOnlinePlaylists(Array.isArray(data) ? data : []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (route === 'home') {
      loadRecent();
    }
  }, [route]);

  /**
   * Запуск воспроизведения недавнего файла во встроенном плеере
   */
  const handlePlayRecent = async (item: RecentItem) => {
    setPlayingHash(item.torrent_hash);
    try {
      openPlayback({
        hash: item.torrent_hash,
        title: item.title || item.file_name,
        poster: item.poster_url || undefined,
        fileId: item.file_index,
        fileName: item.file_name,
        startTime: item.playback_timecode || 0,
      });
    } finally {
      setPlayingHash(null);
    }
  };

  /**
   * Удаление позиции из истории просмотров (выборочное удаление отдельного файла/эпизода)
   */
  const handleRemoveHistory = async (e: React.MouseEvent, item: RecentItem) => {
    e.stopPropagation();
    if (!window.confirm(t('confirm_delete_history'))) return;

    try {
      await API.deleteHistoryEntry(item.torrent_hash, item.file_index);
    } catch (err: any) {
      if (!err?.message?.includes('not found')) {
        alert(t('error', { error: err.message }) || err.message);
        return;
      }
    }

    setRecentItems((prev) => {
      const next = prev.filter(
        (it) => !(it.torrent_hash === item.torrent_hash && it.file_index === item.file_index)
      );
      RECENT_CACHE = next;
      try {
        sessionStorage.setItem('pc_recent_items', JSON.stringify(next));
      } catch {}
      return next;
    });
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

  const featured = activeCatalog[0];
  const featuredTitle = featured?.title_ru || featured?.title || '';

  return (
    <div className="cinema-page cinema-home">
      {route === 'home' && <InlinePlayer />}
      <header className="cinema-page-heading">
        <h1>Сегодня в кино</h1>
        <button type="button" className="cinema-button cinema-button--quiet" onClick={() => navigate('search')}>
          <Search aria-hidden="true" />{t('nav_search')}
        </button>
      </header>

      {featured && (
        <CinemaHero title={featuredTitle} poster={featured.poster_local_url || featured.poster_url} backdrop={featured.background_url}>
          <h2>{featuredTitle}</h2>
          <div className="cinema-metadata">
            {Boolean(featured.rating) && <span className="cinema-rating"><Star aria-hidden="true" />{featured.rating!.toFixed(1)}</span>}
            {featured.year && <span>{featured.year}</span>}
            <span>{activeType === 'series' ? 'Сериал' : 'Фильм'}</span>
            {featured.genres?.slice(0, 2).map(genre => <span key={genre}>{genre}</span>)}
          </div>
          {(featured.overview_ru || featured.overview) && <p className="cinema-hero-overview">{featured.overview_ru || featured.overview}</p>}
          <button type="button" className="cinema-button cinema-button--primary" onClick={() => handleNavigate(featured.id, featuredTitle, activeType, featured.poster_local_url || featured.poster_url)}>
            Подробнее<ChevronRight aria-hidden="true" />
          </button>
        </CinemaHero>
      )}

      {recentItems.length > 0 && (
        <section id="continue-section" className="cinema-section">
          <div className="cinema-section-heading"><h2>{t('continue_watching')}</h2></div>
          <div className="cinema-continue-grid">
            {recentItems.map(item => {
              const isItemPlaying = playingHash === item.torrent_hash;
              const progress = Math.min(100, Math.max(0, ((item.playback_timecode || 0) / (item.playback_duration || 1)) * 100));
              return (
                <div key={item.torrent_hash + item.file_index} className="cinema-continue-item">
                  <button type="button" className="cinema-resume" disabled={isItemPlaying} onClick={() => handlePlayRecent(item)}>
                    <CinemaImage src={item.poster_url} title={item.title || item.file_name} className="cinema-resume-art" />
                    <span className="cinema-resume-info">
                      <strong>{item.title || item.file_name}</strong>
                      <small>{item.season != null && item.episode != null ? `Сезон ${item.season}, серия ${item.episode}` : item.file_name}</small>
                      <span className="cinema-resume-time">{item.is_watched ? t('watched') : `Продолжить с ${formatTime(item.playback_timecode || 0)}`}</span>
                      <span className="cinema-progress" role="progressbar" aria-label="Просмотрено" aria-valuenow={Math.round(progress)} aria-valuemin={0} aria-valuemax={100}><span style={{width: `${progress}%`}} /></span>
                    </span>
                    {isItemPlaying ? <Loader2 className="animate-spin cinema-resume-play" /> : <Play className="cinema-resume-play" aria-hidden="true" />}
                  </button>
                  <button type="button" className="cinema-icon-button cinema-remove" onClick={e => handleRemoveHistory(e, item)} aria-label={`${t('delete_history_entry')}: ${item.title || item.file_name}`} title={t('delete_history_entry')}><Trash2 /></button>
                </div>
              );
            })}
          </div>
        </section>
      )}

      <section id="popular-catalog" className="cinema-section" aria-label={t('nav_catalog')}>
        <div className="cinema-section-heading cinema-catalog-heading">
          <h2>{catalogType === 'movies' ? t('popular_movies') : t('popular_series')}</h2>
          <div className="cinema-switch" role="tablist" aria-label={t('filter_type')} onKeyDown={event => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            const next = event.key === 'Home' ? 'movies' : event.key === 'End' ? 'series' : catalogType === 'movies' ? 'series' : 'movies';
            setCatalogType(next);
            event.currentTarget.querySelector<HTMLButtonElement>(`#catalog-tab-${next}`)?.focus();
          }}>
            <button id="catalog-tab-movies" type="button" role="tab" aria-selected={catalogType === 'movies'} aria-controls="catalog-panel" tabIndex={catalogType === 'movies' ? 0 : -1} onClick={() => setCatalogType('movies')}><Film aria-hidden="true" />{t('movies')}</button>
            <button id="catalog-tab-series" type="button" role="tab" aria-selected={catalogType === 'series'} aria-controls="catalog-panel" tabIndex={catalogType === 'series' ? 0 : -1} onClick={() => setCatalogType('series')}><Tv aria-hidden="true" />{t('series_plural')}</button>
          </div>
        </div>
        <div id="catalog-panel" role="tabpanel" aria-labelledby={`catalog-tab-${catalogType}`}>
        {isLoadingCatalog && !activeCatalog.length ? <CatalogSkeletonGrid /> : activeCatalog.length > 0 ? (
          <div className="cinema-poster-grid">
            {activeCatalog.map(item => <CatalogMediaCard key={item.id} item={item} type={activeType} onNavigate={handleNavigate} />)}
          </div>
        ) : (
          <div className="cinema-empty"><Film aria-hidden="true" /><p>Не удалось загрузить подборку</p><button type="button" className="cinema-button cinema-button--secondary" onClick={() => catalogType === 'movies' ? loadMovies() : loadSeries()}><RefreshCw />Повторить загрузку</button></div>
        )}
        </div>
      </section>

      {onlinePlaylists.length > 0 && (
        <section id="online-playlists-section" className="cinema-section">
          <div className="cinema-section-heading"><h2>{t('online_playlists') || 'Онлайн-плейлисты'}</h2><button type="button" className="cinema-button cinema-button--quiet" onClick={() => navigate('online')}>Все плейлисты<ChevronRight /></button></div>
          <div className="cinema-playlist-grid">
            {onlinePlaylists.map(pl => (
              <button key={pl.id} type="button" onClick={() => navigate('online', {onlinePlaylistId: pl.id})} className="cinema-media-card">
                <CinemaImage src={pl.items[0]?.thumbnail} title={pl.title} className="cinema-playlist-art" />
                <strong>{pl.title}</strong><span className="cinema-card-meta">{pl.items.length} видео</span>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
};
