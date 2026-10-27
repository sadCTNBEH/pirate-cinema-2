/**
 * @file components/search/SearchView.tsx
 * @description Экран расширенного поиска по торрент-трекерам через Jackett / TorrServer.
 * Поддерживает фильтрацию по сезону и озвучке.
 */

import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { CollectionItem, CollectionName, SearchFilters, SearchSort, TorrentResult } from '../../types';
import { parseTrans } from '../../utils/torrentParser';
import { Button, Input, Select, SafeHtmlText } from '../ui/UIComponents';
import { ArrowLeft, Search, Play, Loader2, SlidersHorizontal, RotateCcw, Heart, Clock3, Mic, HardDrive } from 'lucide-react';
import { InlinePlayer } from '../player/InlinePlayer';

const formatTorrentSize = (size?: number | string): string => {
  const bytes = typeof size === 'number' ? size : Number(size);
  if (!Number.isFinite(bytes) || bytes <= 0) return 'Размер не указан';

  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** unitIndex;
  return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
};

export const SearchView: React.FC = () => {
  const { routeParams, goBack, openPlayback, t } = useApp();

  const [query, setQuery] = useState<string>(routeParams.query || '');
  const [season, setSeason] = useState<string>('');
  const [selectedVoiceover, setSelectedVoiceover] = useState<string>('all');
  const [filters, setFilters] = useState<SearchFilters>({ language: 'all' });
  const [sort, setSort] = useState<SearchSort>('seeders');
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);

  const [searchResults, setSearchResults] = useState<TorrentResult[]>([]);
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState<boolean>(false);
  const [savedSearchQuery, setSavedSearchQuery] = useState<string>('');
  const [collectionMembership, setCollectionMembership] = useState<Record<CollectionName, boolean>>({
    favorites: false,
    watch_later: false,
  });
  const [savingCollection, setSavingCollection] = useState<CollectionName | null>(null);
  const handledRouteQuery = useRef<string | null>(null);

  const collectionMediaId = useMemo(() => {
    const normalized = savedSearchQuery.toLocaleLowerCase();
    return normalized ? `search:${normalized.slice(0, 120)}` : '';
  }, [savedSearchQuery]);

  useEffect(() => {
    let cancelled = false;
    if (!collectionMediaId) {
      setCollectionMembership({ favorites: false, watch_later: false });
      return undefined;
    }
    API.getCollectionMembership(collectionMediaId)
      .then((membership) => {
        if (!cancelled) setCollectionMembership(membership);
      })
      .catch(() => {
        if (!cancelled) setCollectionMembership({ favorites: false, watch_later: false });
      });
    return () => {
      cancelled = true;
    };
  }, [collectionMediaId]);

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
      setSavedSearchQuery(q);

      try {
        const data = await API.searchTorrents(q, undefined, undefined, filters);
        setSearchResults(data || []);
      } catch (err: any) {
        setErrorMessage(err.message || 'Ошибка поиска');
        setSearchResults([]);
      } finally {
        setIsSearching(false);
      }
    },
    [query, filters]
  );

  /**
   * Автоматический запуск поиска при переходе с параметром query
   */
  useEffect(() => {
    if (routeParams.query && handledRouteQuery.current !== routeParams.query) {
      handledRouteQuery.current = routeParams.query;
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
    const filtered = seasonFiltered.filter((result) => {
      if (selectedVoiceover !== 'all' && parseTrans(result.title, t) !== selectedVoiceover) {
        return false;
      }
      return true;
    });

    return filtered.sort((left, right) => {
      if (sort === 'size') return (Number(right.size) || 0) - (Number(left.size) || 0);
      if (sort === 'date') {
        return (
          new Date(right.published_at || 0).getTime() -
          new Date(left.published_at || 0).getTime()
        );
      }
      return (right.seeders || 0) - (left.seeders || 0);
    });
  }, [seasonFiltered, selectedVoiceover, sort, t]);

  const updateFilter = <K extends keyof SearchFilters>(key: K, value: SearchFilters[K]) => {
    setFilters((current) => ({ ...current, [key]: value }));
  };

  const resetFilters = () => {
    setSeason('');
    setSelectedVoiceover('all');
    setFilters({ language: 'all' });
    setSort('seeders');
    setShowAdvancedFilters(false);
  };

  /**
   * Запуск встроенного плеера прямо над списком найденных раздач
   */
  const handleWatch = (item: TorrentResult) => {
    openPlayback({
      hash: item.hash,
      magnet: item.magnet,
      title: item.title,
      targetSeason: season.trim() || undefined,
    });
  };

  const toggleCollection = async (listName: CollectionName) => {
    const title = savedSearchQuery;
    if (!collectionMediaId || !title || savingCollection) return;

    setSavingCollection(listName);
    try {
      if (collectionMembership[listName]) {
        await API.removeCollectionItem(listName, collectionMediaId);
      } else {
        const item: CollectionItem = {
          media_id: collectionMediaId,
          title,
          genres: [],
          media_type: season.trim() ? 'series' : null,
        };
        await API.saveCollectionItem(listName, item);
      }
      setCollectionMembership((current) => ({
        ...current,
        [listName]: !current[listName],
      }));
    } catch (err: any) {
      setErrorMessage(err?.message || 'Не удалось обновить подборку');
    } finally {
      setSavingCollection(null);
    }
  };

  return (
    <div className="ui-page searchview space-y-8 animate-fade-in pb-12">
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
        <h1 className="text-2xl font-sans font-semibold text-film-text">
          {t('nav_search')}
        </h1>
      </div>

      {/* Панель фильтров поиска */}
      <div className="ui-content-row filters flex flex-wrap items-center gap-3 p-4">
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
            icon={<Search className="w-4 h-4 text-film-accent" />}
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

        <Select
          value={filters.quality || 'all'}
          onChange={(event) => updateFilter('quality', event.target.value === 'all' ? undefined : event.target.value)}
          className="h-10 text-xs"
        >
          <option value="all">{t('quality')}</option>
          <option value="2160p">2160p / 4K</option>
          <option value="1080p">1080p</option>
          <option value="720p">720p</option>
          <option value="WEB-DL">WEB-DL</option>
          <option value="BDRip">BDRip / Remux</option>
        </Select>

        <Select
          id="manual-trans-sel"
          value={selectedVoiceover}
          onChange={(event) => setSelectedVoiceover(event.target.value)}
          className="h-10 text-xs"
        >
          <option value="all">{t('all_voiceovers')}</option>
          {availableVoiceovers.map((voiceover) => (
            <option key={voiceover} value={voiceover}>{voiceover}</option>
          ))}
        </Select>

        <Select
          value={filters.language || 'all'}
          onChange={(event) => updateFilter('language', event.target.value as SearchFilters['language'])}
          className="h-10 text-xs"
        >
          <option value="all">{t('language_track')}</option>
          <option value="russian">{t('russian_track')}</option>
          <option value="english">{t('english_track')}</option>
          <option value="original">{t('original_track')}</option>
        </Select>

        <Button
          id="do-search"
          variant="cyan"
          loading={isSearching}
          onClick={() => handleSearch()}
          className="w-28"
        >
          {t('search_btn')}
        </Button>

        <Button
          variant="secondary"
          size="sm"
          icon={<SlidersHorizontal className="w-4 h-4" />}
          onClick={() => setShowAdvancedFilters((visible) => !visible)}
          aria-expanded={showAdvancedFilters}
        >
          {t('advanced_filters')}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          icon={<RotateCcw className="w-4 h-4" />}
          onClick={resetFilters}
        >
          {t('reset_filters')}
        </Button>
      </div>

      {showAdvancedFilters && (
        <div className="flex flex-wrap items-end gap-3 border-b border-film-line pb-5">
          <div className="w-36">
            <Input
              type="number"
              min="0"
              placeholder={t('min_size')}
              value={filters.minSizeGb ?? ''}
              onChange={(event) => updateFilter('minSizeGb', event.target.value ? Number(event.target.value) : undefined)}
              className="h-9 text-xs"
            />
          </div>
          <div className="w-36">
            <Input
              type="number"
              min="0"
              placeholder={t('max_size')}
              value={filters.maxSizeGb ?? ''}
              onChange={(event) => updateFilter('maxSizeGb', event.target.value ? Number(event.target.value) : undefined)}
              className="h-9 text-xs"
            />
          </div>
        </div>
      )}

      <div className="flex justify-end">
        <Select
          value={sort}
          onChange={(event) => setSort(event.target.value as SearchSort)}
          className="h-9 text-xs"
          aria-label={t('filter_sort')}
        >
          <option value="seeders">{t('sort_seeders')}</option>
          <option value="size">{t('sort_size')}</option>
          <option value="date">{t('sort_date')}</option>
        </Select>
      </div>

      {hasSearched && savedSearchQuery && (
        <div className="flex flex-wrap items-center justify-end gap-2 border-b border-film-line pb-4">
          <Button
            variant={collectionMembership.favorites ? 'primary' : 'secondary'}
            size="sm"
            icon={<Heart className={`h-3.5 w-3.5 ${collectionMembership.favorites ? 'fill-current' : ''}`} />}
            loading={savingCollection === 'favorites'}
            disabled={savingCollection !== null}
            onClick={() => toggleCollection('favorites')}
          >
            {collectionMembership.favorites ? t('remove_from_favorites') : t('add_to_favorites')}
          </Button>
          <Button
            variant={collectionMembership.watch_later ? 'primary' : 'secondary'}
            size="sm"
            icon={<Clock3 className="h-3.5 w-3.5" />}
            loading={savingCollection === 'watch_later'}
            disabled={savingCollection !== null}
            onClick={() => toggleCollection('watch_later')}
          >
            {collectionMembership.watch_later ? t('remove_from_watch_later') : t('add_to_watch_later')}
          </Button>
        </div>
      )}

      {/* Встроенный плеер появляется прямо здесь над списком раздач */}
      <InlinePlayer />

      {/* Список результатов */}
      <div id="results" className="space-y-3">
        {isSearching ? (
          <div className="p-8 text-center bg-film-base border border-film-line rounded-sm text-film-muted font-sans">
            <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2 text-film-accent" />
            {t('searching')}
          </div>
        ) : errorMessage ? (
          <div className="p-6 bg-rose-500/10 border border-rose-500/30 rounded-sm text-rose-300 text-sm">
            <SafeHtmlText text={t('error', { error: errorMessage }) || errorMessage} />
          </div>
        ) : hasSearched && season && seasonFiltered.length === 0 ? (
          <div className="empty panel p-8 text-center bg-film-base border border-film-line rounded-sm text-film-muted font-sans">
            {t('season_not_found')}
          </div>
        ) : hasSearched && finalResults.length === 0 ? (
          <div className="empty panel p-8 text-center bg-film-base border border-film-line rounded-sm text-film-muted font-sans">
            {t('nothing_found_try_another')}
          </div>
        ) : (
          finalResults.map((r, idx) => {
            const trans = parseTrans(r.title, t);
            return (
              <div
                key={r.hash || idx}
                className="ui-content-row result flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4       transition-all duration-150"
              >
                <div className="result-main min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 mb-1.5">
                    <h3 className="text-sm font-semibold text-film-text truncate max-w-full" title={r.title}>
                      {r.title}
                    </h3>
                    {r.source && (
                      <span className="text-xs text-film-muted shrink-0">
                        {r.source}
                      </span>
                    )}
                    {r.quality && (
                      <span className="text-xs text-film-muted shrink-0">
                        {r.quality}
                      </span>
                    )}
                    {r.seeders !== undefined && (
                      <span className="text-xs text-emerald-300 shrink-0">
                        {r.seeders} {t('seeders')}
                      </span>
                    )}
                  </div>
                  <div className="result-meta flex flex-wrap items-center gap-3 font-sans text-xs text-film-muted">
                    <span className="text-film-accent flex items-center gap-1">
                      <Mic className="w-3.5 h-3.5" aria-hidden="true" />{trans}
                    </span>
                    <span className={r.size ? 'text-film-muted' : 'text-film-muted'}>
                      <HardDrive className="w-3.5 h-3.5 inline mr-1" aria-hidden="true" />{formatTorrentSize(r.size)}
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
