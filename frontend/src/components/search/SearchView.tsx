/**
 * @file components/search/SearchView.tsx
 * @description Экран расширенного поиска по торрент-трекерам через Jackett / TorrServer,
 * онлайн-видео Rutube и каталогу аниме.
 * Поддерживает фильтрацию по сезону, озвучке, качеству и языку для всех источников.
 */

import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { CollectionItem, CollectionName, SearchFilters, SearchSort, TorrentResult, MediaItem, OnlineSearchResult } from '../../types';
import { parseTrans } from '../../utils/torrentParser';
import { Button, Input, Select, SafeHtmlText } from '../ui/UIComponents';
import { ArrowLeft, Search, Play, Loader2, SlidersHorizontal, RotateCcw, Heart, Clock3, Mic, HardDrive, Sparkles, Film } from 'lucide-react';
import { ResponsiveToolbar } from '../ui/ResponsiveToolbar';
import { CinemaImage } from '../ui/Cinema';
import { InlinePlayer } from '../player/InlinePlayer';

const formatTorrentSize = (size?: number | string): string => {
  const bytes = typeof size === 'number' ? size : Number(size);
  if (!Number.isFinite(bytes) || bytes <= 0) return 'Размер не указан';

  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** unitIndex;
  return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
};

const matchesSeason = (title: string, seasonStr: string): boolean => {
  if (!seasonStr.trim()) return true;
  const sStr = seasonStr.trim();
  const s0 = sStr.padStart(2, '0');
  const regex = new RegExp(`\\b(s${s0}|s${sStr}|сезон\\s*${sStr}|${sStr}\\s*сезон|season\\s*${sStr}|${sStr}(?:st|nd|rd|th)?\\s*season|тв-?\\s*${sStr}|tv-?\\s*${sStr})\\b`, 'i');
  const lower = (title || '').toLowerCase();
  if (regex.test(lower)) return true;
  if (/(сезоны|seasons|s0?1-)/i.test(lower)) return true;
  if (!/(s\d+|сезон|\b\d+\s*сезон|\b\d+(?:st|nd|rd|th)\s*season|тв-\d+|tv-\d+)/i.test(lower)) {
    return true;
  }
  return false;
};

const matchesVoiceover = (item: { title: string; translations?: string[] }, selected: string, tFunc: (k: string) => string): boolean => {
  if (selected === 'all') return true;
  const target = selected.toLowerCase();
  const trans = parseTrans(item.title, tFunc);
  if (trans && trans.toLowerCase() === target) return true;
  if ((item.title || '').toLowerCase().includes(target)) return true;
  if (Array.isArray(item.translations)) {
    if (item.translations.some((tr) => (tr || '').toLowerCase().includes(target))) {
      return true;
    }
  }
  return false;
};

const matchesQuality = (title: string, quality?: string): boolean => {
  if (!quality || quality === 'all') return true;
  const lower = (title || '').toLowerCase();
  const q = quality.toLowerCase();
  if (q === '2160p') {
    return lower.includes('2160') || lower.includes('4k') || lower.includes('uhd');
  }
  if (q === '1080p') {
    return lower.includes('1080');
  }
  if (q === '720p') {
    return lower.includes('720');
  }
  if (q === 'web-dl') {
    return lower.includes('web-dl') || lower.includes('webdl') || lower.includes('web');
  }
  if (q === 'bdrip') {
    return lower.includes('bdrip') || lower.includes('remux') || lower.includes('bluray');
  }
  if (/(2160|1080|720|480|4k)/i.test(lower)) {
    return lower.includes(q);
  }
  return true;
};

const matchesLanguage = (item: { title: string; original_title?: string | null; translations?: string[] }, langFilter?: string): boolean => {
  if (!langFilter || langFilter === 'all') return true;
  const hasCyrillic = /[а-яА-ЯёЁ]/.test(item.title || '');
  if (langFilter === 'russian') {
    return hasCyrillic || (Array.isArray(item.translations) && item.translations.length > 0);
  }
  if (langFilter === 'english') {
    const isLatin = /^[a-zA-Z0-9\s:!?,.'"-]+$/.test(item.title || '');
    return isLatin || Boolean(item.original_title && /^[a-zA-Z0-9\s:!?,.'"-]+$/.test(item.original_title));
  }
  if (langFilter === 'original') {
    return true;
  }
  return true;
};

export const SearchView: React.FC = () => {
  const { routeParams, goBack, openPlayback, navigate, t, lang } = useApp();

  const [includeRutube, setIncludeRutube] = useState(false);
  const [includeAnime, setIncludeAnime] = useState(false);
  const [catalogResults, setCatalogResults] = useState<MediaItem[]>([]);
  const [onlineResults, setOnlineResults] = useState<OnlineSearchResult[]>([]);
  const [animeResults, setAnimeResults] = useState<MediaItem[]>([]);
  const searchGeneration = useRef(0);
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
   * Выполнение поиска по торрентам, каталогу, Rutube и Аниме
   */
  const handleSearch = useCallback(
    async (manualQuery?: string) => {
      const q = (manualQuery !== undefined ? manualQuery : query).trim();
      if (!q) return;

      setIsSearching(true);
      setErrorMessage(null);
      setHasSearched(true);
      setSavedSearchQuery(q);

      const generation = ++searchGeneration.current;
      const results = await Promise.allSettled([
        API.searchTorrents(q, undefined, undefined, filters),
        API.get<MediaItem[]>(`/api/library/meta/unified?q=${encodeURIComponent(q)}&lang=${lang || 'ru'}&include_anime=false`),
        includeRutube ? API.searchOnline(q, 'rutube') : Promise.resolve([]),
        includeAnime ? API.searchAnime(q) : Promise.resolve([]),
      ]);
      if (generation !== searchGeneration.current) return;
      setSearchResults(results[0].status === 'fulfilled' ? results[0].value : []);
      setCatalogResults(results[1].status === 'fulfilled' ? results[1].value : []);
      setOnlineResults(results[2].status === 'fulfilled' ? results[2].value : []);
      setAnimeResults(results[3].status === 'fulfilled' ? results[3].value : []);
      if (results.some((result) => result.status === 'rejected')) {
        setErrorMessage('Часть источников недоступна. Повторите поиск позже.');
      }
      setIsSearching(false);
    },
    [query, filters, includeRutube, includeAnime, lang]
  );

  /**
   * Автоматический запуск поиска при переходе с параметром query
   */
  useEffect(() => {
    if (routeParams.query && handledRouteQuery.current !== routeParams.query) {
      handledRouteQuery.current = routeParams.query;
      setQuery(routeParams.query);
    }
  }, [routeParams.query]);

  useEffect(() => {
    if (!query.trim()) {
      searchGeneration.current += 1;
      setCatalogResults([]);
      setOnlineResults([]);
      setAnimeResults([]);
      setSearchResults([]);
      setIsSearching(false);
      return;
    }
    const timer = window.setTimeout(() => { void handleSearch(query); }, 600);
    return () => {
      window.clearTimeout(timer);
      searchGeneration.current += 1;
    };
  }, [query, includeRutube, includeAnime, handleSearch]);

  /**
   * Список уникальных озвучек из всех найденных результатов (торренты, Rutube, аниме)
   */
  const availableVoiceovers = useMemo(() => {
    const set = new Set<string>();
    searchResults.forEach((r) => {
      const trans = parseTrans(r.title, t);
      if (trans && trans !== t('unknown')) set.add(trans);
    });
    onlineResults.forEach((r) => {
      const trans = parseTrans(r.title, t);
      if (trans && trans !== t('unknown')) set.add(trans);
    });
    animeResults.forEach((r) => {
      const trans = parseTrans(r.title, t);
      if (trans && trans !== t('unknown')) set.add(trans);
      if (Array.isArray(r.translations)) {
        r.translations.forEach((tr: string) => {
          if (tr && tr !== t('unknown')) set.add(tr);
        });
      }
    });
    return Array.from(set).sort();
  }, [searchResults, onlineResults, animeResults, t]);

  /**
   * Фильтрация торрентов по сезону и озвучке
   */
  const seasonFiltered = useMemo(() => {
    return searchResults.filter((r) => matchesSeason(r.title, season));
  }, [searchResults, season]);

  const finalResults = useMemo(() => {
    const filtered = seasonFiltered.filter((result) => {
      return matchesVoiceover(result, selectedVoiceover, t);
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

  /**
   * Фильтрация и сортировка результатов аниме
   */
  const finalAnimeResults = useMemo(() => {
    const filtered = animeResults.filter((item) => {
      if (!matchesSeason(item.title, season)) return false;
      if (!matchesVoiceover(item, selectedVoiceover, t)) return false;
      if (!matchesQuality(item.title, filters.quality)) return false;
      if (!matchesLanguage(item, filters.language)) return false;
      return true;
    });

    return filtered.sort((a, b) => {
      if (sort === 'date') {
        return (Number(b.year) || 0) - (Number(a.year) || 0);
      }
      if (sort === 'size') {
        return (Number(b.episodes) || 0) - (Number(a.episodes) || 0);
      }
      return (Number(b.rating) || 0) - (Number(a.rating) || 0);
    });
  }, [animeResults, season, selectedVoiceover, filters.quality, filters.language, sort, t]);

  /**
   * Фильтрация и сортировка результатов Rutube
   */
  const finalOnlineResults = useMemo(() => {
    const filtered = onlineResults.filter((item) => {
      if (!matchesSeason(item.title, season)) return false;
      if (!matchesVoiceover(item, selectedVoiceover, t)) return false;
      if (!matchesQuality(item.title, filters.quality)) return false;
      if (!matchesLanguage(item, filters.language)) return false;
      return true;
    });

    return filtered.sort((a, b) => {
      if (sort === 'size') {
        return (Number(b.duration) || 0) - (Number(a.duration) || 0);
      }
      return 0;
    });
  }, [onlineResults, season, selectedVoiceover, filters.quality, filters.language, sort, t]);

  /**
   * Фильтрация каталога фильмов и сериалов
   */
  const finalCatalogResults = useMemo(() => {
    return catalogResults.filter((item) => {
      if (!matchesSeason(item.title, season)) return false;
      if (!matchesLanguage(item, filters.language)) return false;
      return true;
    });
  }, [catalogResults, season, filters.language]);

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

  const [playingOnline, setPlayingOnline] = useState(false);
  const handleOnline = async (item: OnlineSearchResult) => {
    if (playingOnline) return;
    setPlayingOnline(true);
    try {
      const result = await API.playOnline({ provider: item.provider, id: item.id });
      openPlayback({
        hash: `online:${item.provider}:${item.id}`,
        title: result.title || item.title,
        poster: result.thumbnail || item.thumbnail || undefined,
        fileId: 0,
        fileName: result.title || item.title,
        startTime: result.timecode || 0,
        isOnline: true,
        onlineProvider: item.provider,
        onlineId: item.id,
      });
    } catch (error: any) {
      setErrorMessage(error?.message || 'Не удалось запустить Rutube');
    } finally {
      setPlayingOnline(false);
    }
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
    <div className="ui-page searchview space-y-6 animate-fade-in pb-12">
      {/* ── Фиксированная верхняя панель: Шапка и поисковая строка с фильтрами ── */}
      <div className="sticky -top-6 md:-top-10 z-30 bg-[#06080d]/95 backdrop-blur-md -mx-6 md:-mx-10 px-6 md:px-10 pt-4 pb-4 border-b border-film-line/40 space-y-3 shadow-lg shadow-black/25">
        <div className="flex items-center justify-between gap-4">
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

          <div className="flex items-center gap-2">
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
        </div>

        {/* Панель фильтров поиска */}
        <div className="ui-content-row filters flex flex-wrap items-center gap-3 p-3 bg-film-base/80 border border-film-line rounded-md">
          <div className="flex-1 min-w-[200px]">
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

          <div className="w-24">
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
          <div className="flex flex-wrap items-end gap-3 p-3 bg-film-base/60 border border-film-line rounded-md">
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
      </div>

      {/* ── Чекбоксы источников: Rutube и Аниме ── */}
      <div className="flex flex-wrap items-center gap-6 pt-1">
        <label className="flex items-center gap-3 cursor-pointer select-none font-sans text-sm text-film-text">
          <input
            type="checkbox"
            role="switch"
            checked={includeRutube}
            onChange={(event) => {
              setIncludeRutube(event.target.checked);
              setOnlineResults([]);
              searchGeneration.current += 1;
              setIsSearching(false);
            }}
            className="cursor-pointer"
          />
          Искать на Rutube — {includeRutube ? 'Вкл.' : 'Выкл.'}
        </label>

        <label className="flex items-center gap-3 cursor-pointer select-none font-sans text-sm text-film-text">
          <input
            type="checkbox"
            role="switch"
            checked={includeAnime}
            onChange={(event) => {
              setIncludeAnime(event.target.checked);
              setAnimeResults([]);
              searchGeneration.current += 1;
              setIsSearching(false);
            }}
            className="cursor-pointer"
          />
          Искать аниме — {includeAnime ? 'Вкл.' : 'Выкл.'}
        </label>
      </div>

      {/* ── Секция Аниме (под чекбоксом аниме) ── */}
      {includeAnime && (
        <div className="space-y-3">
          <h2 className="text-base font-semibold text-film-text flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-film-accent" />
            Аниме {finalAnimeResults.length > 0 && <span className="text-xs text-film-muted font-normal">({finalAnimeResults.length})</span>}
          </h2>
          {finalAnimeResults.length > 0 ? (
            <div className="cinema-poster-grid">
              {finalAnimeResults.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="cinema-media-card"
                  onClick={() =>
                    navigate('meta', {
                      imdb: item.id,
                      title: item.title,
                      type: item.type || 'series',
                      poster: item.poster_url,
                    })
                  }
                >
                  <CinemaImage
                    src={item.poster_local_url || item.poster_url}
                    title={item.title}
                    className="cinema-poster"
                  />
                  <strong>{item.title}</strong>
                  <span className="cinema-card-meta">
                    {item.year || ''} {item.episodes ? `· ${item.episodes} эпизодов` : ''} · Аниме
                  </span>
                </button>
              ))}
            </div>
          ) : hasSearched && !isSearching ? (
            <div className="p-4 text-center bg-film-base/50 border border-film-line/40 rounded-sm text-film-muted text-xs font-sans">
              Аниме не найдено (с учетом активных фильтров)
            </div>
          ) : null}
        </div>
      )}

      {/* ── Секция Rutube (под чекбоксом Rutube) ── */}
      {includeRutube && (
        <div className="space-y-3">
          <h2 className="text-base font-semibold text-film-text flex items-center gap-2">
            <Play className="w-4 h-4 text-film-accent" />
            Rutube {finalOnlineResults.length > 0 && <span className="text-xs text-film-muted font-normal">({finalOnlineResults.length})</span>}
          </h2>
          {finalOnlineResults.length > 0 ? (
            <div className="cinema-poster-grid">
              {finalOnlineResults.map((item) => (
                <button
                  key={`${item.provider}:${item.id}`}
                  type="button"
                  className="cinema-media-card"
                  disabled={playingOnline}
                  onClick={() => handleOnline(item)}
                >
                  <CinemaImage
                    src={item.thumbnail}
                    title={item.title}
                    className="cinema-poster"
                  />
                  <strong>{item.title}</strong>
                  <span className="cinema-card-meta">
                    Rutube {item.duration ? `· ${Math.round(item.duration / 60)} мин` : ''}
                  </span>
                </button>
              ))}
            </div>
          ) : hasSearched && !isSearching ? (
            <div className="p-4 text-center bg-film-base/50 border border-film-line/40 rounded-sm text-film-muted text-xs font-sans">
              На Rutube ничего не найдено (с учетом активных фильтров)
            </div>
          ) : null}
        </div>
      )}

      {/* ── Секция Фильмы и сериалы ── */}
      {finalCatalogResults.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-base font-semibold text-film-text flex items-center gap-2">
            <Film className="w-4 h-4 text-film-accent" />
            Фильмы и сериалы {finalCatalogResults.length > 0 && <span className="text-xs text-film-muted font-normal">({finalCatalogResults.length})</span>}
          </h2>
          <div className="cinema-poster-grid">
            {finalCatalogResults.map((item) => (
              <button
                key={item.id}
                type="button"
                className="cinema-media-card"
                onClick={() =>
                  navigate('meta', {
                    imdb: item.id,
                    title: item.title,
                    type: item.type || 'movie',
                    poster: item.poster_url,
                  })
                }
              >
                <CinemaImage
                  src={item.poster_local_url || item.poster_url}
                  title={item.title}
                  className="cinema-poster"
                />
                <strong>{item.title}</strong>
                <span className="cinema-card-meta">
                  {item.year} {item.episodes ? `· ${item.episodes} эпизодов` : ''}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {hasSearched && savedSearchQuery && (
        <ResponsiveToolbar
          className="border-b border-film-line pb-4"
          label="Коллекции"
          items={[
            {
              id: 'favorite',
              priority: 100,
              content: (
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
              ),
            },
            {
              id: 'watch-later',
              priority: 60,
              content: (
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
              ),
            },
          ]}
        />
      )}

      {/* Встроенный плеер появляется прямо здесь над списком раздач */}
      <InlinePlayer />

      {/* ── Список результатов торрентов ── */}
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
                className="ui-content-row result flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 transition-all duration-150"
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
