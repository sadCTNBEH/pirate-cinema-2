/**
 * @file components/home/HomeView.tsx
 * @description Главный экран каталога Pirate Cinema.
 * Отображает блок "Продолжить просмотр", витрину популярных фильмов
 * и сериалов, синхронизированных с бэкендом.
 */

import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { RecentItem, MediaItem } from '../../types';
import { Header } from '../layout/Header';
import { formatTime } from '../../utils/torrentParser';
import { Play, Trash2, Film, Star, Loader2 } from 'lucide-react';
import { Progress } from '../ui/UIComponents';

// Клиентский кэш популярных подборок для исключения лишних повторных запросов
const POPULAR_CACHE: { movies?: MediaItem[]; series?: MediaItem[] } = {};

export const HomeView: React.FC = () => {
  const { t, navigate } = useApp();

  const [recentItems, setRecentItems] = useState<RecentItem[]>([]);
  const [popularMovies, setPopularMovies] = useState<MediaItem[]>([]);
  const [popularSeries, setPopularSeries] = useState<MediaItem[]>([]);
  
  const [isLoadingRecent, setIsLoadingRecent] = useState<boolean>(true);
  const [isLoadingMovies, setIsLoadingMovies] = useState<boolean>(true);
  const [isLoadingSeries, setIsLoadingSeries] = useState<boolean>(true);
  const [playingHash, setPlayingHash] = useState<string | null>(null);

  /**
   * Загрузка истории просмотров
   */
  const loadRecent = async () => {
    setIsLoadingRecent(true);
    try {
      const items = await API.getRecent();
      setRecentItems(Array.isArray(items) ? items : []);
    } catch (e) {
      console.warn('Ошибка загрузки истории просмотров:', e);
    } finally {
      setIsLoadingRecent(false);
    }
  };

  /**
   * Загрузка подборки популярных фильмов
   */
  const loadMovies = async () => {
    if (POPULAR_CACHE.movies) {
      setPopularMovies(POPULAR_CACHE.movies);
      setIsLoadingMovies(false);
      return;
    }
    setIsLoadingMovies(true);
    try {
      const data = await API.getPopular('movies');
      if (Array.isArray(data)) {
        POPULAR_CACHE.movies = data;
        setPopularMovies(data);
      }
    } catch (e) {
      console.warn('Ошибка загрузки фильмов:', e);
    } finally {
      setIsLoadingMovies(false);
    }
  };

  /**
   * Загрузка подборки популярных сериалов
   */
  const loadSeries = async () => {
    if (POPULAR_CACHE.series) {
      setPopularSeries(POPULAR_CACHE.series);
      setIsLoadingSeries(false);
      return;
    }
    setIsLoadingSeries(true);
    try {
      const data = await API.getPopular('series');
      if (Array.isArray(data)) {
        POPULAR_CACHE.series = data;
        setPopularSeries(data);
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
      setRecentItems((prev) => prev.filter((item) => item.torrent_hash !== hash));
    } catch (err: any) {
      alert(t('error', { error: err.message }) || err.message);
    }
  };

  return (
    <div className="space-y-10 animate-fade-in">
      <Header titleKey="nav_catalog" />

      {/* ── Блок "Продолжить просмотр" ── */}
      <section id="continue-section">
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
                      className="continue-item flex-1 grid grid-cols-[56px_minmax(0,1fr)_180px_auto] gap-4 items-center p-3 rounded-sm bg-[#0a0e18] border border-cyan-900/30 hover:border-cyan-500/50 hover:bg-[#0d1424] transition-all duration-150 text-left cursor-pointer shadow-sm"
                    >
                      {/* Постер */}
                      <div className="w-14 h-20 rounded-sm overflow-hidden bg-slate-900 flex items-center justify-center border border-slate-800">
                        {item.poster_url ? (
                          <img
                            src={item.poster_url}
                            alt={item.title || item.file_name}
                            className="w-full h-full object-cover"
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

      {/* ── Блок "Популярные фильмы" ── */}
      <section id="popular-movies">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-tech font-bold uppercase tracking-wider text-slate-100 flex items-center gap-2">
            <span className="w-1.5 h-4 bg-cyan-400" />
            {t('popular_movies')}
          </h2>
        </div>

        {isLoadingMovies ? (
          <div className="py-8 text-center text-slate-500 font-tech">
            <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2 text-cyan-400" />
            {t('searching')}
          </div>
        ) : popularMovies.length > 0 ? (
          <div className="poster-grid grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
            {popularMovies.map((movie) => (
              <button
                key={movie.id}
                type="button"
                onClick={() =>
                  navigate('meta', {
                    imdb: movie.id,
                    title: movie.title,
                    type: 'movie',
                    poster: movie.poster_url,
                  })
                }
                className="card text-left bg-transparent border-0 p-0 group cursor-pointer"
              >
                <div className="poster aspect-[2/3] w-full rounded-lg overflow-hidden bg-slate-900 border border-slate-800/80 group-hover:border-cyan-400/80 group-hover:shadow-[0_0_18px_rgba(0,240,255,0.2)] transition-all duration-200 relative">
                  {movie.poster_url ? (
                    <img
                      src={movie.poster_url}
                      alt={movie.title}
                      loading="lazy"
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-slate-600 text-xs text-center p-2">
                      {movie.title}
                    </div>
                  )}
                  {movie.rating && (
                    <div className="absolute top-2 right-2 bg-[#060910]/90 border border-amber-500/40 text-amber-300 px-1.5 py-0.5 rounded-md font-code text-[11px] font-bold flex items-center gap-1 shadow">
                      <Star className="w-3 h-3 fill-amber-400 text-amber-400" />
                      {movie.rating.toFixed(1)}
                    </div>
                  )}
                </div>
                <strong className="block mt-2 font-tech text-sm font-semibold text-slate-200 truncate group-hover:text-cyan-400 transition-colors">
                  {movie.title}
                </strong>
                <small className="block font-code text-xs text-slate-400">
                  {movie.year || ''}
                </small>
              </button>
            ))}
          </div>
        ) : null}
      </section>

      {/* ── Блок "Популярные сериалы" ── */}
      <section id="popular-series">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-tech font-bold uppercase tracking-wider text-slate-100 flex items-center gap-2">
            <span className="w-1.5 h-4 bg-sky-400" />
            {t('popular_series')}
          </h2>
        </div>

        {isLoadingSeries ? (
          <div className="py-8 text-center text-slate-500 font-tech">
            <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2 text-sky-400" />
            {t('searching')}
          </div>
        ) : popularSeries.length > 0 ? (
          <div className="poster-grid grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
            {popularSeries.map((series) => (
              <button
                key={series.id}
                type="button"
                onClick={() =>
                  navigate('meta', {
                    imdb: series.id,
                    title: series.title,
                    type: 'series',
                    poster: series.poster_url,
                  })
                }
                className="card text-left bg-transparent border-0 p-0 group cursor-pointer"
              >
                <div className="poster aspect-[2/3] w-full rounded-lg overflow-hidden bg-slate-900 border border-slate-800/80 group-hover:border-cyan-400/80 group-hover:shadow-[0_0_18px_rgba(0,240,255,0.2)] transition-all duration-200 relative">
                  {series.poster_url ? (
                    <img
                      src={series.poster_url}
                      alt={series.title}
                      loading="lazy"
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-slate-600 text-xs text-center p-2">
                      {series.title}
                    </div>
                  )}
                  {series.rating && (
                    <div className="absolute top-2 right-2 bg-[#060910]/90 border border-amber-500/40 text-amber-300 px-1.5 py-0.5 rounded-md font-code text-[11px] font-bold flex items-center gap-1 shadow">
                      <Star className="w-3 h-3 fill-amber-400 text-amber-400" />
                      {series.rating.toFixed(1)}
                    </div>
                  )}
                </div>
                <strong className="block mt-2 font-tech text-sm font-semibold text-slate-200 truncate group-hover:text-cyan-400 transition-colors">
                  {series.title}
                </strong>
                <small className="block font-code text-xs text-slate-400">
                  {series.year || ''}
                </small>
              </button>
            ))}
          </div>
        ) : null}
      </section>
    </div>
  );
};
