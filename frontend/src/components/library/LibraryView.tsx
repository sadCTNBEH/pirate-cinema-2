/**
 * @file components/library/LibraryView.tsx
 * @description Экран каталога локальной библиотеки Pirate Cinema.
 * Поддерживает фильтрацию (тип, статус, год, жанр, сортировка),
 * отображение прогресса серий, автозапуск следующей серии (next-unwatched)
 * и управление раздачами.
 */

import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { LibraryItem, LibraryFilter } from '../../types';
import { Button, Input, Select, Progress, Badge } from '../ui/UIComponents';
import {
  ArrowLeft,
  Trash2,
  Film,
  Tv,
  Play,
  FastForward,
  Loader2,
  CheckSquare,
  Square,
  RotateCcw,
  Star,
} from 'lucide-react';
import { InlinePlayer } from '../player/InlinePlayer';

export const LibraryView: React.FC = () => {
  const { goBack, navigate, openPlayback, t } = useApp();

  // Инициализация фильтров из параметров строки URL
  const [filters, setFilters] = useState<LibraryFilter>(() => {
    const sp = new URLSearchParams(window.location.search);
    const typeParam = sp.get('type') as any;
    const statusParam = sp.get('status') as any;
    const yearParam = sp.get('year') ? parseInt(sp.get('year')!, 10) : undefined;
    const genreParam = sp.get('genre') || undefined;
    const sortParam = sp.get('sort') as any;
    return {
      type: ['movie', 'series'].includes(typeParam) ? typeParam : undefined,
      status: ['unwatched', 'watching', 'completed'].includes(statusParam) ? statusParam : undefined,
      year: yearParam && !isNaN(yearParam) ? yearParam : undefined,
      genre: genreParam || undefined,
      sort: ['title', 'year', 'added', 'progress'].includes(sortParam) ? sortParam : 'added',
    };
  });

  const [items, setItems] = useState<LibraryItem[]>([]);
  const [selectedHashes, setSelectedHashes] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [advancingHash, setAdvancingHash] = useState<string | null>(null);

  /**
   * Синхронизация текущих фильтров с URL
   */
  const syncUrlParams = useCallback((f: LibraryFilter) => {
    const sp = new URLSearchParams();
    if (f.type) sp.set('type', f.type);
    if (f.status) sp.set('status', f.status);
    if (f.year) sp.set('year', String(f.year));
    if (f.genre) sp.set('genre', f.genre);
    if (f.sort) sp.set('sort', f.sort);
    const qs = sp.toString();
    const newUrl = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
    window.history.replaceState(null, '', newUrl);
  }, []);

  /**
   * Загрузка списка библиотеки с учетом фильтров
   */
  const loadLibrary = useCallback(
    async (activeFilters: LibraryFilter) => {
      setIsLoading(true);
      setErrorMessage(null);
      try {
        const data = await API.getLibrary(activeFilters);
        setItems(data || []);
        setSelectedHashes(new Set());
      } catch (err: any) {
        setErrorMessage(err.message || 'Ошибка загрузки библиотеки');
        setItems([]);
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    loadLibrary(filters);
    syncUrlParams(filters);
  }, [filters, loadLibrary, syncUrlParams]);

  /**
   * Обновление значения отдельного фильтра
   */
  const handleFilterChange = (key: keyof LibraryFilter, value: any) => {
    setFilters((prev) => ({
      ...prev,
      [key]: value,
    }));
  };

  /**
   * Сброс всех активных фильтров к значениям по умолчанию
   */
  const handleResetFilters = () => {
    const defaultFilters: LibraryFilter = {
      type: undefined,
      status: undefined,
      year: undefined,
      genre: undefined,
      sort: 'added',
    };
    setFilters(defaultFilters);
  };

  const hasActiveFilters = useMemo(() => {
    return !!(filters.type || filters.status || filters.year || filters.genre || (filters.sort && filters.sort !== 'added'));
  }, [filters]);

  /**
   * Переключение выбора отдельного торрента
   */
  const toggleSelect = (hash: string) => {
    setSelectedHashes((prev) => {
      const next = new Set(prev);
      if (next.has(hash)) {
        next.delete(hash);
      } else {
        next.add(hash);
      }
      return next;
    });
  };

  /**
   * Переключение "Выбрать все / Снять выбор"
   */
  const toggleSelectAll = () => {
    if (selectedHashes.size === items.length) {
      setSelectedHashes(new Set());
    } else {
      setSelectedHashes(new Set(items.map((i) => i.hash || i.torrent_hash)));
    }
  };

  /**
   * Удаление одной раздачи
   */
  const handleRemoveOne = async (hash: string) => {
    if (!window.confirm(t('confirm_delete_from_ts') || 'Удалить эту раздачу из библиотеки?')) return;
    try {
      await API.deleteTorrent(hash);
      setItems((prev) => prev.filter((i) => i.hash !== hash && i.torrent_hash !== hash));
      setSelectedHashes((prev) => {
        const next = new Set(prev);
        next.delete(hash);
        return next;
      });
    } catch (err: any) {
      alert(err.message || 'Ошибка удаления');
    }
  };

  /**
   * Удаление выбранных раздач
   */
  const handleDeleteSelected = async () => {
    if (selectedHashes.size === 0) {
      alert(t('select_torrents_to_delete') || 'Выберите хотя бы одну раздачу');
      return;
    }

    if (
      !window.confirm(
        t('confirm_delete_multiple_ts', { count: selectedHashes.size }) ||
          `Удалить выбранные (${selectedHashes.size})?`
      )
    ) {
      return;
    }

    const hashes = Array.from(selectedHashes);
    try {
      await API.deleteMultipleTorrents(hashes);
      setItems((prev) => prev.filter((i) => !selectedHashes.has(i.hash) && !selectedHashes.has(i.torrent_hash)));
      setSelectedHashes(new Set());
    } catch (err: any) {
      alert(err.message || 'Ошибка удаления выбранных');
    }
  };

  /**
   * Удаление всех сохраненных раздач
   */
  const handleDeleteAll = async () => {
    if (items.length === 0) return;
    if (
      !window.confirm(
        t('confirm_delete_all_ts', { count: items.length }) ||
          `Удалить все раздачи (${items.length})?`
      )
    ) {
      return;
    }

    try {
      const hashes = items.map((i) => i.hash || i.torrent_hash).filter(Boolean) as string[];
      await API.deleteAllTorrents(hashes);
      setItems([]);
      setSelectedHashes(new Set());
    } catch (err: any) {
      alert(err.message || 'Ошибка очистки библиотеки');
    }
  };

  /**
   * Переход к детальному просмотру раздачи
   */
  const handleOpenDetail = (item: LibraryItem) => {
    navigate('detail', {
      hash: item.hash || item.torrent_hash,
      title: item.title,
      poster: item.poster_url || undefined,
    });
  };

  /**
   * Запуск следующей непросмотренной серии для сериала во встроенном плеере
   */
  const handlePlayNextUnwatched = async (e: React.MouseEvent, item: LibraryItem) => {
    e.stopPropagation();
    const h = item.hash || item.torrent_hash;
    setAdvancingHash(h);

    try {
      const nextEp = await API.getNextUnwatched(h);
      if (!nextEp || nextEp.file_id === undefined) {
        alert(t('no_unwatched') || 'Все серии уже просмотрены');
        return;
      }

      openPlayback({
        hash: h,
        title: item.title || nextEp.file_name,
        poster: item.poster_url || undefined,
        fileId: nextEp.file_id,
        fileName: nextEp.file_name,
        startTime: nextEp.playback_timecode || 0,
      });
    } catch (err: any) {
      alert(err.message || t('no_unwatched') || 'Все серии уже просмотрены');
    } finally {
      setAdvancingHash(null);
    }
  };

  return (
    <div className="space-y-8 animate-fade-in pb-16">
      {/* ── Шапка страницы ── */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <Button
            id="lib-back-btn"
            variant="secondary"
            size="sm"
            icon={<ArrowLeft className="w-4 h-4" />}
            onClick={goBack}
          >
            {t('back')}
          </Button>
          <div>
            <h1 className="text-2xl font-tech font-bold uppercase tracking-wider text-slate-100 flex items-center gap-2">
              <Film className="w-6 h-6 text-cyan-400" />
              {t('nav_library') || 'Библиотека'}
            </h1>
          </div>
        </div>

        {/* Групповые действия */}
        {items.length > 0 && (
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              icon={
                selectedHashes.size === items.length ? (
                  <CheckSquare className="w-3.5 h-3.5 text-cyan-400" />
                ) : (
                  <Square className="w-3.5 h-3.5" />
                )
              }
              onClick={toggleSelectAll}
            >
              {selectedHashes.size === items.length ? 'Снять выбор' : 'Выбрать все'}
            </Button>

            <Button
              variant="danger"
              size="sm"
              icon={<Trash2 className="w-3.5 h-3.5" />}
              disabled={selectedHashes.size === 0}
              onClick={handleDeleteSelected}
            >
              {t('delete_selected')}
            </Button>

            <Button
              variant="danger"
              size="sm"
              onClick={handleDeleteAll}
              className="text-rose-400 border-rose-500/40 hover:bg-rose-500/20"
            >
              {t('delete_all')}
            </Button>
          </div>
        )}
      </div>

      {/* ── Панель фильтров и сортировки (Filter Bar) ── */}
      <div className="p-4 bg-[#0a0e18] border border-cyan-900/40 rounded-lg shadow-sm space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* Тип медиа: Все | Фильмы | Сериалы */}
          <div className="flex items-center gap-1 bg-[#060910] border border-slate-800 rounded-md p-1">
            <button
              type="button"
              onClick={() => handleFilterChange('type', undefined)}
              className={`px-3 py-1.5 text-xs font-tech uppercase tracking-wider rounded transition-all cursor-pointer ${
                !filters.type
                  ? 'bg-cyan-500/20 text-cyan-300 font-bold border border-cyan-500/40 shadow-[0_0_8px_rgba(0,240,255,0.2)]'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {t('all') || 'Все'}
            </button>
            <button
              type="button"
              onClick={() => handleFilterChange('type', 'movie')}
              className={`px-3 py-1.5 text-xs font-tech uppercase tracking-wider rounded transition-all cursor-pointer ${
                filters.type === 'movie'
                  ? 'bg-cyan-500/20 text-cyan-300 font-bold border border-cyan-500/40 shadow-[0_0_8px_rgba(0,240,255,0.2)]'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {t('movies') || 'Фильмы'}
            </button>
            <button
              type="button"
              onClick={() => handleFilterChange('type', 'series')}
              className={`px-3 py-1.5 text-xs font-tech uppercase tracking-wider rounded transition-all cursor-pointer ${
                filters.type === 'series'
                  ? 'bg-cyan-500/20 text-cyan-300 font-bold border border-cyan-500/40 shadow-[0_0_8px_rgba(0,240,255,0.2)]'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {t('series') || 'Сериалы'}
            </button>
          </div>

          {/* Фильтр статуса */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-tech text-slate-400 uppercase tracking-wider hidden sm:inline">
              {t('filter_status') || 'Статус'}:
            </span>
            <Select
              id="filter-status-select"
              value={filters.status || 'all'}
              onChange={(e) =>
                handleFilterChange('status', e.target.value === 'all' ? undefined : e.target.value)
              }
              className="text-xs py-1.5 h-[34px]"
            >
              <option value="all">{t('all') || 'Все'}</option>
              <option value="unwatched">{t('unwatched') || 'Не просмотрено'}</option>
              <option value="watching">{t('watching') || 'Смотрю'}</option>
              <option value="completed">{t('completed') || 'Завершено'}</option>
            </Select>
          </div>

          {/* Фильтр года */}
          <div className="w-24">
            <Input
              id="filter-year-input"
              type="number"
              placeholder={t('filter_year') || 'Год'}
              value={filters.year || ''}
              onChange={(e) =>
                handleFilterChange('year', e.target.value ? parseInt(e.target.value, 10) : undefined)
              }
              className="text-xs py-1.5 px-3 h-[34px]"
            />
          </div>

          {/* Фильтр жанра */}
          <div className="w-32 sm:w-40">
            <Input
              id="filter-genre-input"
              type="text"
              placeholder={t('filter_genre') || 'Жанр...'}
              value={filters.genre || ''}
              onChange={(e) => handleFilterChange('genre', e.target.value.trim() || undefined)}
              className="text-xs py-1.5 px-3 h-[34px]"
            />
          </div>

          {/* Сортировка */}
          <div className="flex items-center gap-2 ml-auto">
            <span className="text-xs font-tech text-slate-400 uppercase tracking-wider hidden sm:inline">
              {t('filter_sort') || 'Сортировка'}:
            </span>
            <Select
              id="filter-sort-select"
              value={filters.sort || 'added'}
              onChange={(e) => handleFilterChange('sort', e.target.value as any)}
              className="text-xs py-1.5 h-[34px]"
            >
              <option value="added">{t('sort_added') || 'По дате'}</option>
              <option value="title">{t('sort_title') || 'По названию'}</option>
              <option value="year">{t('sort_year') || 'По году'}</option>
              <option value="progress">{t('sort_progress') || 'По прогрессу'}</option>
            </Select>
          </div>

          {/* Кнопка сброса */}
          {hasActiveFilters && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleResetFilters}
              title="Сбросить фильтры"
              className="text-slate-400 hover:text-cyan-400 p-2"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </Button>
          )}
        </div>
      </div>

      {/* ── Встроенный видеоплеер в главном окне ── */}
      <InlinePlayer />

      {/* ── Сетка карточек библиотеки ── */}
      <div id="lib-list">
        {isLoading ? (
          <div className="p-12 text-center bg-[#0a0e18]/60 border border-cyan-900/30 rounded-lg text-slate-400 font-tech">
            <Loader2 className="w-8 h-8 animate-spin mx-auto mb-3 text-cyan-400" />
            {t('searching') || 'Загрузка библиотеки...'}
          </div>
        ) : errorMessage ? (
          <div className="p-6 bg-rose-500/10 border border-rose-500/30 rounded-lg text-rose-300 text-sm">
            {t('error', { error: errorMessage }) || errorMessage}
          </div>
        ) : items.length === 0 ? (
          <div className="empty panel p-12 text-center bg-[#0a0e18]/60 border border-cyan-900/30 rounded-lg text-slate-400 font-tech space-y-2">
            <Film className="w-10 h-10 mx-auto text-slate-600 mb-2" />
            <div className="text-base font-semibold text-slate-300">
              {t('library_empty') || 'В библиотеке пока нет раздач'}
            </div>
            {hasActiveFilters && (
              <p className="text-xs text-slate-500">
                Попробуйте изменить или сбросить фильтры
              </p>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-5">
            {items.map((item) => {
              const h = item.hash || item.torrent_hash;
              const isSelected = selectedHashes.has(h);
              const isSeries = item.media_type === 'series' || item.type === 'series' || item.total_files > 1;
              const isAdvancing = advancingHash === h;

              const isCompleted =
                item.status === 'completed' ||
                item.status === 'watched' ||
                (item.total_files > 0 && item.watched_files >= item.total_files);

              const percent =
                item.total_files > 0
                  ? Math.round((item.watched_files / item.total_files) * 100)
                  : Math.round((item.progress || 0) * 100);

              const overviewText = item.overview_ru || item.overview || '';

              return (
                <div
                  key={h}
                  onClick={() => handleOpenDetail(item)}
                  className={`card group relative flex flex-col bg-[#090d16] border rounded-lg overflow-hidden transition-all duration-200 cursor-pointer shadow-sm hover:shadow-[0_0_20px_rgba(0,240,255,0.18)] ${
                    isSelected
                      ? 'border-cyan-400/90 bg-cyan-950/20 shadow-[0_0_15px_rgba(0,240,255,0.2)]'
                      : 'border-slate-800/80 hover:border-cyan-500/50 hover:bg-[#0c1220]'
                  }`}
                >
                  {/* Верхняя панель: Чекбокс и кнопка удаления */}
                  <div
                    className="absolute top-2 left-2 z-10"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <label className="flex items-center justify-center p-1 bg-[#060910]/80 border border-slate-700/60 rounded cursor-pointer hover:border-cyan-400 transition-colors">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSelect(h)}
                        className="w-3.5 h-3.5 accent-cyan-400 cursor-pointer"
                      />
                    </label>
                  </div>

                  <div
                    className="absolute top-2 right-2 z-10"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      type="button"
                      onClick={() => handleRemoveOne(h)}
                      title="Удалить из библиотеки"
                      className="p-1.5 bg-[#060910]/80 border border-slate-700/60 rounded text-slate-400 hover:text-rose-400 hover:border-rose-500/50 transition-colors cursor-pointer"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  {/* Постер с бейджами */}
                  <div className="relative aspect-[2/3] w-full bg-slate-900 overflow-hidden flex items-center justify-center">
                    {item.poster_url ? (
                      <img
                        src={item.poster_url}
                        alt={item.title}
                        loading="lazy"
                        className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      />
                    ) : (
                      <div className="text-slate-600 flex flex-col items-center gap-2 p-4 text-center">
                        {isSeries ? <Tv className="w-10 h-10" /> : <Film className="w-10 h-10" />}
                        <span className="font-tech text-xs truncate max-w-[120px]">{item.title}</span>
                      </div>
                    )}

                    {/* Бейдж типа (Сериал / Фильм) */}
                    <div className="absolute bottom-2 left-2 flex items-center gap-1.5">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-tech font-bold uppercase tracking-wider ${
                          isSeries
                            ? 'bg-sky-500/80 text-black border border-sky-300'
                            : 'bg-cyan-500/80 text-black border border-cyan-300'
                        }`}
                      >
                        {isSeries ? (t('series') || 'Сериал') : (t('movie') || 'Фильм')}
                      </span>

                      {/* Бейдж статуса */}
                      {isCompleted ? (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-tech font-bold uppercase tracking-wider bg-emerald-500/80 text-black border border-emerald-300">
                          {t('completed') || 'Завершено'}
                        </span>
                      ) : item.status === 'watching' || item.status === 'in_progress' ? (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-tech font-bold uppercase tracking-wider bg-amber-500/80 text-black border border-amber-300">
                          {t('watching') || 'Смотрю'}
                        </span>
                      ) : null}
                    </div>

                    {/* Рейтинг */}
                    {item.rating !== null && item.rating !== undefined && (
                      <div className="absolute bottom-2 right-2 bg-[#060910]/90 border border-amber-500/40 text-amber-300 px-1.5 py-0.5 rounded font-code text-[11px] font-bold flex items-center gap-1 shadow">
                        <Star className="w-3 h-3 fill-amber-400 text-amber-400" />
                        {Number(item.rating).toFixed(1)}
                      </div>
                    )}
                  </div>

                  {/* Информация карточки */}
                  <div className="p-3.5 flex flex-col flex-1 justify-between gap-3">
                    <div className="space-y-1.5">
                      <div className="flex items-start justify-between gap-2">
                        <h3
                          className="font-tech text-sm font-semibold text-slate-100 group-hover:text-cyan-400 transition-colors line-clamp-1"
                          title={item.title}
                        >
                          {item.title}
                        </h3>
                        {item.year && (
                          <span className="font-code text-xs text-slate-400 shrink-0">
                            {item.year}
                          </span>
                        )}
                      </div>

                      {/* Жанры (Chips / Tags) */}
                      {Array.isArray(item.genres) && item.genres.length > 0 && (
                        <div className="flex flex-wrap items-center gap-1">
                          {item.genres.slice(0, 3).map((g) => (
                            <span
                              key={g}
                              className="px-1.5 py-0.5 text-[10px] font-sans rounded bg-[#060910] border border-slate-800 text-slate-300"
                            >
                              {g}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* Синопсис (Metadata enrichment) */}
                      {overviewText && (
                        <p className="text-xs text-slate-400 font-sans line-clamp-2 leading-relaxed">
                          {overviewText}
                        </p>
                      )}
                    </div>

                    {/* Блок прогресса серий (для сериалов) */}
                    <div className="space-y-2 pt-2 border-t border-slate-800/80">
                      {isSeries && (
                        <div className="space-y-1">
                          <div className="flex items-center justify-between text-[11px] font-code text-slate-400">
                            <span>Прогресс</span>
                            <span className="text-cyan-300 font-semibold">
                              {item.total_files > 0 ? `${item.watched_files}/${item.total_files}` : ''} ({percent}%)
                            </span>
                          </div>
                          <Progress
                            value={item.watched_files}
                            max={item.total_files || 1}
                            className="h-1.5"
                          />
                        </div>
                      )}

                      {/* Кнопки управления */}
                      <div className="flex items-center gap-2 pt-1" onClick={(e) => e.stopPropagation()}>
                        {isSeries ? (
                          <Button
                            variant="primary"
                            size="sm"
                            loading={isAdvancing}
                            disabled={isCompleted}
                            icon={<FastForward className="w-3.5 h-3.5" />}
                            onClick={(e) => handlePlayNextUnwatched(e, item)}
                            className="flex-1 text-xs"
                            title={isCompleted ? (t('no_unwatched') || 'Все серии просмотрены') : (t('next_episode') || 'Следующая серия')}
                          >
                            {isCompleted ? 'Просмотрено' : (t('next_episode') || 'След. серия')}
                          </Button>
                        ) : (
                          <Button
                            variant="primary"
                            size="sm"
                            icon={<Play className="w-3.5 h-3.5 fill-current" />}
                            onClick={() => handleOpenDetail(item)}
                            className="flex-1 text-xs"
                          >
                            {t('watch') || 'Смотреть'}
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
