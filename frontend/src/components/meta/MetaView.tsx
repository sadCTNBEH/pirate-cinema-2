/**
 * @file components/meta/MetaView.tsx
 * @description Экран карточки медиа (фильма или сериала).
 * Загружает расширенные метаданные, серии, парсит раздачи,
 * фильтрует по сезонам и аудиодорожкам/переводам.
 */

import React, { useEffect, useState, useMemo } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { TorrentResult, SeriesEpisode } from '../../types';
import { parseTrans } from '../../utils/torrentParser';
import { Button, Select, SafeHtmlText } from '../ui/UIComponents';
import { ArrowLeft, Star, Film, Mic, Play, Loader2, Radio } from 'lucide-react';

export const MetaView: React.FC = () => {
  const { routeParams, goBack, navigate, t } = useApp();
  const { imdb = '', title = '', type = 'movie', poster = '' } = routeParams;

  const [metaOverview, setMetaOverview] = useState<string>('');
  const [metaRating, setMetaRating] = useState<number | null>(null);
  const [metaPoster, setMetaPoster] = useState<string>(poster);
  const [metaVideos, setMetaVideos] = useState<SeriesEpisode[]>([]);
  const [isSeries, setIsSeries] = useState<boolean>(type === 'series');

  const [currentSeason, setCurrentSeason] = useState<number>(1);
  const [currentEpisode, setCurrentEpisode] = useState<number>(1);

  const [rawTorrents, setRawTorrents] = useState<TorrentResult[]>([]);
  const [isSearchingTorrents, setIsSearchingTorrents] = useState<boolean>(true);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [selectedVoiceover, setSelectedVoiceover] = useState<string>('all');

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
          if (data.rating) setMetaRating(data.rating);
          if (data.poster_url && !poster) setMetaPoster(data.poster_url);

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

  /**
   * 2. Поиск доступных торрент-раздач для этого тайтла
   */
  useEffect(() => {
    let isCancelled = false;
    if (!title) return;

    setIsSearchingTorrents(true);
    setSearchError(null);

    API.searchTorrents(title)
      .then((data) => {
        if (isCancelled) return;
        setRawTorrents(Array.isArray(data) ? data : []);
      })
      .catch((err) => {
        if (isCancelled) return;
        setSearchError(err.message || 'Ошибка поиска');
      })
      .finally(() => {
        if (!isCancelled) setIsSearchingTorrents(false);
      });

    return () => {
      isCancelled = true;
    };
  }, [title]);

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

    const sStr = currentSeason.toString();
    const s0 = sStr.padStart(2, '0');

    return rawTorrents.filter((r) => {
      const tLower = (r.title || '').toLowerCase();
      // Проверка на совпадение сезона в названии
      if (
        new RegExp(
          `\\b(s${s0}|s${sStr}|сезон\\s*${sStr}|${sStr}\\s*сезон)\\b`,
          'i'
        ).test(tLower)
      ) {
        return true;
      }
      if (/(сезоны|seasons|s0?1-)/i.test(tLower)) return true;
      if (!/(s\d+|сезон)/i.test(tLower)) return true;
      return false;
    });
  }, [rawTorrents, isSeries, currentSeason]);

  /**
   * Список доступных переводов/озвучек для фильтра
   */
  const availableVoiceovers = useMemo(() => {
    const set = new Set<string>();
    seasonFilteredTorrents.forEach((r) => {
      const parsed = parseTrans(r.title, t);
      if (parsed) set.add(parsed);
    });
    return Array.from(set).sort();
  }, [seasonFilteredTorrents, t]);

  /**
   * Фильтрация по выбранной озвучке
   */
  const displayedTorrents = useMemo(() => {
    if (selectedVoiceover === 'all') return seasonFilteredTorrents;
    return seasonFilteredTorrents.filter(
      (r) => parseTrans(r.title, t) === selectedVoiceover
    );
  }, [seasonFilteredTorrents, selectedVoiceover, t]);

  /**
   * Переход на экран воспроизведения/файлов
   */
  const handleOpenDetail = (r: TorrentResult) => {
    navigate('detail', {
      hash: r.hash,
      title: r.title,
      magnet: r.magnet,
      targetSeason: isSeries ? currentSeason : undefined,
      targetEpisode: isSeries ? currentEpisode : undefined,
    });
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
          {metaPoster ? (
            <img
              id="meta-poster"
              src={metaPoster}
              alt={title}
              className="w-full h-full object-cover"
            />
          ) : (
            <Film className="w-12 h-12 text-slate-700" />
          )}
        </div>

        {/* Описание и контролы серий */}
        <div className="flex flex-col justify-start">
          <h1 id="meta-title" className="text-3xl font-tech font-bold uppercase tracking-wider text-slate-100 mb-3">
            {title}
          </h1>

          {metaRating !== null && (
            <div id="meta-rating" className="flex items-center gap-1.5 font-code text-base font-bold text-amber-400 mb-4">
              <Star className="w-4 h-4 fill-amber-400" />
              <span>★ {metaRating.toFixed(1)}</span>
            </div>
          )}

          {metaOverview && (
            <p id="meta-overview" className="overview text-slate-300 text-sm leading-relaxed mb-6 font-sans">
              {metaOverview}
            </p>
          )}

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
                  onChange={(e) => setCurrentSeason(Number(e.target.value))}
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
                    onChange={(e) => setCurrentEpisode(Number(e.target.value))}
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

        {/* Результаты сканирования раздач */}
        <div id="meta-search-results" className="space-y-3">
          {isSearchingTorrents ? (
            <div className="p-8 text-center bg-[#0a0e18]/60 border border-cyan-900/30 rounded-sm text-slate-400 font-tech">
              <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2 text-cyan-400" />
              {t('searching_torrents')}
            </div>
          ) : searchError ? (
            <div className="p-6 bg-rose-500/10 border border-rose-500/30 rounded-sm text-rose-300 font-sans text-sm">
              <SafeHtmlText text={t('search_error', { error: searchError }) || searchError} />
            </div>
          ) : seasonFilteredTorrents.length === 0 ? (
            <div className="empty panel p-8 text-center bg-[#0a0e18]/60 border border-cyan-900/30 rounded-sm text-slate-400 font-tech">
              {t('season_not_found')}
            </div>
          ) : displayedTorrents.length === 0 ? (
            <div className="empty panel p-8 text-center bg-[#0a0e18]/60 border border-cyan-900/30 rounded-sm text-slate-400 font-tech">
              {t('nothing_found')}
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
                    <h3 className="text-sm font-semibold text-slate-100 truncate mb-1.5" title={r.title}>
                      {r.title}
                    </h3>
                    <div className="result-meta flex flex-wrap items-center gap-3 font-code text-xs text-slate-400">
                      <span className="text-slate-500">{r.source || 'TorrServer'}</span>
                      {r.seeders !== undefined && (
                        <span className="text-emerald-400 flex items-center gap-1">
                          🌱 {r.seeders} {t('seeders')}
                        </span>
                      )}
                      <span className="text-cyan-400 flex items-center gap-1">
                        🎤 {trans}
                      </span>
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
