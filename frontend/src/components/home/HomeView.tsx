/**
 * @file components/home/HomeView.tsx
 * @description Главный экран каталога Pirate Cinema.
 * Отображает блок "Продолжить просмотр", витрину популярных фильмов
 * и сериалов, синхронизированных с бэкендом.
 */

import React, { useEffect, useState, useCallback } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { resumeDestination } from '../../services/resumeDestination';
import { useCatalog } from '../../services/catalogCache';
import { RecentItem, MediaItem, AnimePlayback } from '../../types';
import { formatTime } from '../../utils/torrentParser';
import { Play, Trash2, Film, Star, Loader2, Tv, ChevronRight, Search, RefreshCw, Sparkles } from 'lucide-react';
import { CinemaHero, CinemaImage } from '../ui/Cinema';
import { InlinePlayer } from '../player/InlinePlayer';

// Клиентский кэш популярных подборок для мгновенного первого рендера и исключения повторных запросов
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

const CatalogMediaCard = React.memo<{
  item: MediaItem;
  type: 'movie' | 'series';
  onNavigate: (imdb: string, title: string, type: 'movie' | 'series', poster?: string) => void;
}>(({ item, type, onNavigate }) => {
  const poster = item.poster_local_url || item.poster_url;
  const { lang } = useApp();
  const title = lang === 'en' ? item.original_title || item.title : item.title_ru || item.title;
  return (
    <button type="button" className="cinema-media-card" onClick={() => onNavigate(item.id, title, type, poster || undefined)}>
      <CinemaImage src={poster} title={title} className="cinema-poster" />
      <strong>{title}</strong>
      <span className="cinema-card-meta">
        <span>{item.year || (type === 'series' ? 'Сериал' : 'Фильм')}</span>
        {Boolean(item.rating) && <span className="cinema-rating"><Star aria-hidden="true" />{item.rating!.toFixed(1)}</span>}
      </span>
      {item.episodes && <span className="cinema-card-meta">{item.episodes} эпизодов</span>}
    </button>
  );
});

const CatalogSkeletonGrid: React.FC = () => (
  <div className="cinema-poster-grid" aria-label="Загрузка каталога" aria-busy="true">
    {Array.from({ length: 10 }, (_, i) => <div key={i} className="cinema-skeleton"><div className="cinema-poster" /><div /><div /></div>)}
  </div>
);

export const HomeView: React.FC = () => {
  const { t, navigate, openPlayback, route, lang } = useApp();

  const [recentItems, setRecentItems] = useState<RecentItem[]>(() => getInitialRecent());
  const [catalogType, setCatalogType] = useState<'movies' | 'series' | 'anime'>('movies');
  const movies = useCatalog<MediaItem[]>(`/api/library/popular?lang=${encodeURIComponent(lang || 'ru')}`);
  const series = useCatalog<MediaItem[]>(catalogType === 'series' ? `/api/library/popular/series?lang=${encodeURIComponent(lang || 'ru')}` : null);
  const [animeCategory, setAnimeCategory] = useState('popular');
  const anime = useCatalog<MediaItem[]>(catalogType === 'anime' ? `/api/library/popular/anime?category=${animeCategory}` : null);
  const popularMovies = movies.data || [];
  const popularSeries = series.data || [];

  
  const [, setIsLoadingRecent] = useState<boolean>(() => !getInitialRecent().length);
  const isLoadingMovies = movies.loading;
  const isLoadingSeries = series.loading;
  const [playingHash, setPlayingHash] = useState<string | null>(null);

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
              it.playback_timecode === valid[idx].playback_timecode &&
              it.episode === valid[idx].episode && it.season === valid[idx].season &&
              it.imdb_id === valid[idx].imdb_id && it.media_type === valid[idx].media_type &&
              JSON.stringify(it.anime_playback) === JSON.stringify(valid[idx].anime_playback) &&
              it.title === valid[idx].title && it.poster_url === valid[idx].poster_url &&
              it.poster_file === valid[idx].poster_file
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

  useEffect(() => {
    loadRecent();

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
    if (item.anime_playback) {
      try {
      const resume = await API.get<AnimePlayback>(`/api/history/anime/${encodeURIComponent(item.anime_playback.media_id)}`);
      navigate('meta', {imdb: resume.card_media_id, title: resume.title, type: resume.media_type || 'series', poster: resume.poster_url || undefined, animeResume: resume});
      } catch (error: any) { await loadRecent(); alert(error.message || 'Не удалось восстановить просмотр'); }
      return;
    }
    setPlayingHash(item.torrent_hash);
    try {
      const destination = resumeDestination(item);
      if (destination) {
        navigate(destination.route, destination.params);
        return;
      }
      openPlayback({
        hash: item.torrent_hash,
        title: item.title || item.file_name,
        poster: item.poster_url || (item.poster_file ? `/api/library/poster/${encodeURIComponent(item.torrent_hash)}` : undefined),
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

  const activeCatalog = catalogType === 'anime' ? anime.data || [] : catalogType === 'movies' ? popularMovies : popularSeries;
  const isLoadingCatalog = catalogType === 'anime' ? anime.loading : catalogType === 'movies' ? isLoadingMovies : isLoadingSeries;
  const activeType = catalogType === 'movies' ? 'movie' : 'series';

  const featured = activeCatalog[0];
  const featuredTitle = featured?.title_ru || featured?.title || '';

  return (
    <div className="cinema-page cinema-home">
      {route === 'home' && <InlinePlayer />}
      <header className="cinema-page-heading">
        <h1>Рекомендации</h1>
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
                    <CinemaImage src={item.poster_url || (item.poster_file ? `/api/library/poster/${encodeURIComponent(item.torrent_hash)}` : undefined)} title={item.title || item.file_name} className="cinema-resume-art" />
                    <span className="cinema-resume-info">
                      <strong>{item.title || item.file_name}</strong>
                      <small>{item.season != null && item.episode != null ? `Сезон ${item.season}, серия ${item.episode}` : item.file_name}</small>
                      <span className="cinema-resume-time">{item.anime_playback ? 'Продолжить просмотр' : item.is_watched ? t('watched') : `Продолжить с ${formatTime(item.playback_timecode || 0)}`}</span>
                      {!item.anime_playback && <span className="cinema-progress" role="progressbar" aria-label="Просмотрено" aria-valuenow={Math.round(progress)} aria-valuemin={0} aria-valuemax={100}><span style={{width: `${progress}%`}} /></span>}
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
          <h2>{catalogType === 'anime' ? 'Аниме' : catalogType === 'movies' ? t('popular_movies') : t('popular_series')}</h2>
          <div className="cinema-switch" role="tablist" aria-label={t('filter_type')} onKeyDown={event => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            const tabs = ['movies', 'series', 'anime'] as const;
            const next = tabs[event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (tabs.indexOf(catalogType) + (event.key === 'ArrowRight' ? 1 : 2)) % 3];
            setCatalogType(next);
            event.currentTarget.querySelector<HTMLButtonElement>(`#catalog-tab-${next}`)?.focus();
          }}>
            <button id="catalog-tab-movies" type="button" role="tab" aria-selected={catalogType === 'movies'} aria-controls="catalog-panel" tabIndex={catalogType === 'movies' ? 0 : -1} onClick={() => setCatalogType('movies')}><Film aria-hidden="true" />{t('movies')}</button>
            <button id="catalog-tab-series" type="button" role="tab" aria-selected={catalogType === 'series'} aria-controls="catalog-panel" tabIndex={catalogType === 'series' ? 0 : -1} onClick={() => setCatalogType('series')}><Tv aria-hidden="true" />{t('series_plural')}</button>
            <button id="catalog-tab-anime" type="button" role="tab" aria-selected={catalogType === 'anime'} aria-controls="catalog-panel" tabIndex={catalogType === 'anime' ? 0 : -1} onClick={() => setCatalogType('anime')}><Sparkles aria-hidden="true" />Аниме</button>
          </div>
        </div>
        {catalogType === 'anime' && <div className="cinema-switch" aria-label="Подборка аниме">{[['popular', 'Популярное'], ['season', 'Новинки сезона'], ['rated', 'Высокий рейтинг']].map(([key, label]) => <button key={key} type="button" aria-pressed={animeCategory === key} onClick={() => setAnimeCategory(key)}>{label}</button>)}</div>}
        <div id="catalog-panel" role="tabpanel" aria-labelledby={`catalog-tab-${catalogType}`}>
        {isLoadingCatalog && !activeCatalog.length ? <CatalogSkeletonGrid /> : activeCatalog.length > 0 ? (
          <div className="cinema-poster-grid">
            {activeCatalog.map(item => <CatalogMediaCard key={item.id} item={item} type={item.type || activeType} onNavigate={handleNavigate} />)}
          </div>
        ) : (
          <div className="cinema-empty"><Film aria-hidden="true" /><p>Не удалось загрузить подборку</p><button type="button" className="cinema-button cinema-button--secondary" onClick={() => catalogType === 'anime' ? anime.reload() : catalogType === 'movies' ? movies.reload() : series.reload()}><RefreshCw />Повторить загрузку</button></div>
        )}
        </div>
      </section>


    </div>
  );
};
