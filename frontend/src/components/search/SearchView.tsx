/**
 * @file components/search/SearchView.tsx
 * @description Экран расширенного поиска по торрент-трекерам через Jackett / TorrServer.
 * Поддерживает фильтрацию по сезону, серии и озвучке.
 */

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { TorrentResult } from '../../types';
import { parseTrans } from '../../utils/torrentParser';
import { Button, Input, Select, SafeHtmlText } from '../ui/UIComponents';
import { ArrowLeft, Search, Mic, Play, Loader2 } from 'lucide-react';

export const SearchView: React.FC = () => {
  const { routeParams, goBack, navigate, t } = useApp();

  const [query, setQuery] = useState<string>(routeParams.query || '');
  const [season, setSeason] = useState<string>('');
  const [episode, setEpisode] = useState<string>('');
  const [selectedVoiceover, setSelectedVoiceover] = useState<string>('all');

  const [searchResults, setSearchResults] = useState<TorrentResult[]>([]);
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState<boolean>(false);

  /**
   * Выполнение поиска по торрент-трекерам (точно как в оригинальном app.js)
   */
  const handleSearch = useCallback(
    async (manualQuery?: string) => {
      const q = (manualQuery !== undefined ? manualQuery : query).trim();
      if (!q) return;

      setIsSearching(true);
      setErrorMessage(null);
      setHasSearched(true);

      try {
        const data = await API.searchTorrents(q);
        setSearchResults(data || []);
      } catch (err: any) {
        setErrorMessage(err.message || 'Ошибка поиска');
        setSearchResults([]);
      } finally {
        setIsSearching(false);
      }
    },
    [query]
  );

  /**
   * Автоматический запуск поиска при переходе с параметром query
   */
  useEffect(() => {
    if (routeParams.query) {
      setQuery(routeParams.query);
      handleSearch(routeParams.query);
    }
  }, [routeParams.query, handleSearch]);

  /**
   * Список уникальных озвучек из найденных результатов
   */
  const availableVoiceovers = useMemo(() => {
    const set = new Set<string>();
    searchResults.forEach((r) => {
      const trans = parseTrans(r.title, t);
      if (trans && trans !== t('unknown')) set.add(trans);
    });
    return Array.from(set).sort();
  }, [searchResults, t]);

  /**
   * Фильтрация результатов по выбранному сезону (алгоритм из оригинального app.js)
   */
  const seasonFiltered = useMemo(() => {
    if (!season.trim()) return searchResults;
    const sStr = season.trim();
    const s0 = sStr.padStart(2, '0');
    const regex = new RegExp(`\\b(s${s0}|s${sStr}|сезон ${sStr}|${sStr} сезон)\\b`, 'i');

    return searchResults.filter((r) => {
      const title = (r.title || '').toLowerCase();
      if (regex.test(title)) return true;
      if (/(сезоны|seasons|s0?1-)/i.test(title)) return true;
      if (!/(s\d+|сезон)/i.test(title)) return true;
      return false;
    });
  }, [searchResults, season]);

  /**
   * Фильтрация результатов по выбранной озвучке
   */
  const finalResults = useMemo(() => {
    if (selectedVoiceover === 'all') return seasonFiltered;
    return seasonFiltered.filter((r) => {
      const trans = parseTrans(r.title, t);
      return trans === selectedVoiceover;
    });
  }, [seasonFiltered, selectedVoiceover, t]);

  /**
   * Переход к воспроизведению раздачи (передает magnet, hash, title, season, episode)
   */
  const handleWatch = (item: TorrentResult) => {
    navigate('detail', {
      hash: item.hash,
      magnet: item.magnet,
      title: item.title,
      targetSeason: season.trim() || undefined,
      targetEpisode: episode.trim() || undefined,
    });
  };

  return (
    <div className="space-y-8 animate-fade-in pb-12">
      {/* Шапка */}
      <div className="flex items-center gap-4">
        <Button
          id="search-back-btn"
          variant="secondary"
          size="sm"
          icon={<ArrowLeft className="w-4 h-4" />}
          onClick={goBack}
        >
          {t('back')}
        </Button>
        <h1 className="text-2xl font-tech font-bold uppercase tracking-wider text-slate-100">
          {t('nav_search')}
        </h1>
      </div>

      {/* Панель фильтров поиска */}
      <div className="filters flex flex-wrap gap-3 p-4 bg-[#0a0e18] border border-cyan-900/40 rounded-sm">
        <div className="flex-1 min-w-[220px]">
          <Input
            id="q"
            type="text"
            placeholder={t('search_placeholder')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSearch();
            }}
            icon={<Search className="w-4 h-4 text-cyan-400" />}
            autoFocus
          />
        </div>

        <div className="w-28">
          <Input
            id="search-season"
            type="number"
            min="1"
            placeholder={t('season_prefix') || 'Сезон'}
            value={season}
            onChange={(e) => setSeason(e.target.value)}
          />
        </div>

        <div className="w-28">
          <Input
            id="search-episode"
            type="number"
            min="1"
            placeholder={t('episode') || 'Серия'}
            value={episode}
            onChange={(e) => setEpisode(e.target.value)}
          />
        </div>

        <Button
          id="do-search"
          variant="cyan"
          loading={isSearching}
          onClick={() => handleSearch()}
        >
          {t('search_btn')}
        </Button>
      </div>

      {/* Фильтр озвучек (если результатов больше 1) */}
      {availableVoiceovers.length > 1 && (
        <div className="flex items-center gap-2">
          <Mic className="w-4 h-4 text-cyan-400" />
          <Select
            id="manual-trans-sel"
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

      {/* Список результатов */}
      <div id="results" className="space-y-3">
        {isSearching ? (
          <div className="p-8 text-center bg-[#0a0e18]/60 border border-cyan-900/30 rounded-sm text-slate-400 font-tech">
            <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2 text-cyan-400" />
            {t('searching')}
          </div>
        ) : errorMessage ? (
          <div className="p-6 bg-rose-500/10 border border-rose-500/30 rounded-sm text-rose-300 text-sm">
            <SafeHtmlText text={t('error', { error: errorMessage }) || errorMessage} />
          </div>
        ) : hasSearched && season && seasonFiltered.length === 0 ? (
          <div className="empty panel p-8 text-center bg-[#0a0e18]/60 border border-cyan-900/30 rounded-sm text-slate-400 font-tech">
            {t('season_not_found')}
          </div>
        ) : hasSearched && finalResults.length === 0 ? (
          <div className="empty panel p-8 text-center bg-[#0a0e18]/60 border border-cyan-900/30 rounded-sm text-slate-400 font-tech">
            {t('nothing_found_try_another')}
          </div>
        ) : (
          finalResults.map((r, idx) => {
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
                        🟢 {r.seeders} {t('seeders')}
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
                    onClick={() => handleWatch(r)}
                  >
                    {t('watch')}
                  </Button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
