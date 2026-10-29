/**
 * @file components/library/LibraryView.tsx
 * @description Экран каталога локальной библиотеки Pirate Cinema.
 * Поддерживает расширенную фильтрацию (тип, статус, диапазон годов, жанр, сортировка, направление),
 * отображение прогресса серий, автозапуск следующей серии (next-unwatched),
 * бесконечную прокрутку (infinite scroll) и групповое управление раздачами.
 */

import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { LibraryItem, LibraryFilter } from '../../types';
import { ResponsiveToolbar } from '../ui/ResponsiveToolbar';
import { Button, Progress } from '../ui/UIComponents';
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
  Star,
  SlidersHorizontal,
  RotateCcw,
} from 'lucide-react';
import { InlinePlayer } from '../player/InlinePlayer';
import { LibraryFilters } from './LibraryFilters';

const PAGE_SIZE = 24;

export const LibraryView: React.FC = () => {
  const { goBack, navigate, openPlayback, t } = useApp();

  // Инициализация фильтров из параметров строки URL
  const [filters, setFilters] = useState<LibraryFilter>(() => {
    const sp = new URLSearchParams(window.location.search);
    const typeParam = sp.get('type') as 'movie' | 'series' | null;
    const statusParam = sp.get('status') as LibraryFilter['status'];
    const yFrom = sp.get('year_from') ? parseInt(sp.get('year_from')!, 10) : undefined;
    const yTo = sp.get('year_to') ? parseInt(sp.get('year_to')!, 10) : undefined;
    const ySingle = sp.get('year') ? parseInt(sp.get('year')!, 10) : undefined;
    const genreParam = sp.get('genre') || undefined;
    const sortParam = sp.get('sort') as LibraryFilter['sort'];
    const orderParam = sp.get('order') as 'asc' | 'desc' | null;

    const fromVal = !isNaN(Number(yFrom)) ? yFrom : (!isNaN(Number(ySingle)) ? ySingle : undefined);
    const toVal = !isNaN(Number(yTo)) ? yTo : (!isNaN(Number(ySingle)) ? ySingle : undefined);

    return {
      type: typeParam && ['movie', 'series'].includes(typeParam) ? typeParam : undefined,
      status:
        statusParam && ['watching', 'completed', 'planned', 'unwatched', 'in_progress', 'watched'].includes(statusParam)
          ? statusParam
          : undefined,
      year_from: fromVal,
      year_to: toVal,
      genre: genreParam || undefined,
      sort: sortParam && ['title', 'year', 'added', 'progress'].includes(sortParam) ? sortParam : 'added',
      order: orderParam && ['asc', 'desc'].includes(orderParam) ? orderParam : 'desc',
    };
  });

  const [items, setItems] = useState<LibraryItem[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [selectedHashes, setSelectedHashes] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isLoadingMore, setIsLoadingMore] = useState<boolean>(false);
  const [hasMore, setHasMore] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [advancingHash, setAdvancingHash] = useState<string | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  /**
   * Синхронизация текущих фильтров с URL
   */
  const syncUrlParams = useCallback((f: LibraryFilter) => {
    const sp = new URLSearchParams();
    if (f.type) sp.set('type', f.type);
    if (f.status) sp.set('status', f.status);
    if (f.year_from !== undefined && !isNaN(f.year_from)) sp.set('year_from', String(f.year_from));
    if (f.year_to !== undefined && !isNaN(f.year_to)) sp.set('year_to', String(f.year_to));
    if (f.genre) sp.set('genre', f.genre);
    if (f.sort && f.sort !== 'added') sp.set('sort', f.sort);
    if (f.order && f.order !== 'desc') sp.set('order', f.order);
    const qs = sp.toString();
    const newUrl = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
    window.history.replaceState(null, '', newUrl);
  }, []);

  /**
   * Загрузка начальной страницы списка библиотеки с учетом активных фильтров (с защитой от race condition)
   */
  const loadLibraryInitial = useCallback(async (activeFilters: LibraryFilter) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsLoading(true);
    setErrorMessage(null);

    try {
      const res = await API.getLibraryWithCount(
        {
          ...activeFilters,
          offset: 0,
          limit: PAGE_SIZE,
        },
        { signal: controller.signal }
      );

      setItems(res.items);
      setTotalCount(res.totalCount);
      setHasMore(res.items.length < res.totalCount && res.items.length > 0);
      setSelectedHashes(new Set());
    } catch (err: unknown) {
      if ((err as Error)?.name === 'AbortError') {
        return;
      }
      const message = err instanceof Error ? err.message : 'Ошибка загрузки библиотеки';
      setErrorMessage(message);
      setItems([]);
      setTotalCount(0);
      setHasMore(false);
    } finally {
      if (abortControllerRef.current === controller) {
        setIsLoading(false);
      }
    }
  }, []);

  /**
   * Подгрузка следующей страницы для бесконечного скролла
   */
  const loadMore = useCallback(async () => {
    if (isLoading || isLoadingMore || !hasMore || items.length === 0) {
      return;
    }

    setIsLoadingMore(true);
    try {
      const res = await API.getLibraryWithCount(
        {
          ...filters,
          offset: items.length,
          limit: PAGE_SIZE,
        },
        { signal: abortControllerRef.current?.signal }
      );

      setItems((prev) => {
        const existing = new Set(prev.map((i) => i.hash || i.torrent_hash));
        const newUnique = res.items.filter((i) => !existing.has(i.hash || i.torrent_hash));
        const combined = [...prev, ...newUnique];
        setHasMore(combined.length < res.totalCount && newUnique.length > 0);
        return combined;
      });
      setTotalCount(res.totalCount);
    } catch (err: unknown) {
      if ((err as Error)?.name !== 'AbortError') {
        console.error('Ошибка загрузки следующей страницы:', err);
      }
    } finally {
      setIsLoadingMore(false);
    }
  }, [filters, hasMore, isLoading, isLoadingMore, items.length]);

  // Запуск загрузки при изменении фильтров
  useEffect(() => {
    loadLibraryInitial(filters);
    syncUrlParams(filters);
  }, [filters, loadLibraryInitial, syncUrlParams]);

  // IntersectionObserver для автоматической подгрузки при прокрутке
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const container = document.getElementById('page-container');
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !isLoading && !isLoadingMore) {
          loadMore();
        }
      },
      {
        root: container,
        rootMargin: '250px',
        threshold: 0.1,
      }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasMore, isLoading, isLoadingMore, loadMore]);

  /**
   * Сброс всех активных фильтров к значениям по умолчанию
   */
  const handleResetFilters = useCallback(() => {
    const defaultFilters: LibraryFilter = {
      type: undefined,
      status: undefined,
      year_from: undefined,
      year_to: undefined,
      genre: undefined,
      sort: 'added',
      order: 'desc',
    };
    setFilters(defaultFilters);
  }, []);

  const hasActiveFilters = useMemo(() => {
    return !!(
      filters.type ||
      filters.status ||
      filters.year_from ||
      filters.year_to ||
      filters.genre ||
      (filters.sort && filters.sort !== 'added') ||
      (filters.order && filters.order !== 'desc')
    );
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
      setTotalCount((prev) => Math.max(0, prev - 1));
      setSelectedHashes((prev) => {
        const next = new Set(prev);
        next.delete(hash);
        return next;
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Ошибка удаления';
      alert(msg);
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
      setTotalCount((prev) => Math.max(0, prev - selectedHashes.size));
      setSelectedHashes(new Set());
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Ошибка удаления выбранных';
      alert(msg);
    }
  };

  /**
   * Удаление всех сохраненных раздач
   */
  const handleDeleteAll = async () => {
    if (items.length === 0) return;
    if (
      !window.confirm(
        t('confirm_delete_all_ts', { count: totalCount || items.length }) ||
          `Удалить все раздачи (${totalCount || items.length})?`
      )
    ) {
      return;
    }

    try {
      const hashes = items.map((i) => i.hash || i.torrent_hash).filter(Boolean) as string[];
      await API.deleteAllTorrents(hashes);
      setItems([]);
      setTotalCount(0);
      setHasMore(false);
      setSelectedHashes(new Set());
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Ошибка очистки библиотеки';
      alert(msg);
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
        title: item.title || nextEp.file_name || '',
        poster: item.poster_url || undefined,
        fileId: nextEp.file_id,
        fileName: nextEp.file_name,
        startTime: nextEp.playback_timecode || 0,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : (t('no_unwatched') || 'Все серии уже просмотрены');
      alert(msg);
    } finally {
      setAdvancingHash(null);
    }
  };

  return (
    <div className="ui-page libraryview space-y-8 animate-fade-in pb-16">
      {/* ── Шапка страницы ── */}
      <div className="ui-library-heading">
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
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-sans font-semibold text-film-text flex items-center gap-2">
                <Film className="w-6 h-6 text-film-accent" />
                {t('nav_library') || 'Библиотека'}
              </h1>
              {!isLoading && (
                <span className="text-xs font-sans text-film-accent font-semibold bg-film-hover border border-film-line px-2 py-0.5 rounded">
                  {hasActiveFilters
                    ? (t('found_count', { count: totalCount }) || `Найдено: ${totalCount}`)
                    : (t('library_items_count', { count: totalCount }) || `Всего: ${totalCount}`)}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Групповые действия */}
        {items.length > 0 && (
          <ResponsiveToolbar className="library-toolbar" label="Действия библиотеки" items={[
{ id: 'select', priority: 100, content: (<Button
              variant="secondary"
              size="sm"
              icon={
                selectedHashes.size === items.length ? (
                  <CheckSquare className="w-3.5 h-3.5 text-film-accent" />
                ) : (
                  <Square className="w-3.5 h-3.5" />
                )
              }
              onClick={toggleSelectAll}
            >
              {selectedHashes.size === items.length ? 'Снять выбор' : 'Выбрать все'}
            </Button>) },
{ id: 'delete-selected', priority: 70, content: (<Button
              variant="danger"
              size="sm"
              icon={<Trash2 className="w-3.5 h-3.5" />}
              disabled={selectedHashes.size === 0}
              onClick={handleDeleteSelected}
            >
              {t('delete_selected')}
            </Button>) },
{ id: 'delete-all', priority: 20, content: (<Button
              variant="danger"
              size="sm"
              onClick={handleDeleteAll}
              className="text-rose-400 border-rose-500/40 hover:bg-rose-500/20"
            >
              {t('delete_all')}
            </Button>) }
          ]} />
        )}
      </div>

      {/* ── Панель фильтров и сортировки (Filter Bar) ── */}
      <LibraryFilters
        filters={filters}
        onChange={setFilters}
        onReset={handleResetFilters}
        hasActiveFilters={hasActiveFilters}
      />

      {/* ── Встроенный видеоплеер в главном окне ── */}
      <InlinePlayer />

      {/* ── Сетка карточек библиотеки ── */}
      <div id="lib-list">
        {isLoading ? (
          <div className="p-12 text-center bg-film-base border border-film-line rounded-md text-film-muted font-sans">
            <Loader2 className="w-8 h-8 animate-spin mx-auto mb-3 text-film-accent" />
            {t('searching') || 'Загрузка библиотеки...'}
          </div>
        ) : errorMessage ? (
          <div className="p-6 bg-rose-500/10 border border-rose-500/30 rounded-md text-rose-300 text-sm flex flex-col sm:flex-row items-center justify-between gap-4">
            <div>
              <div className="font-sans font-semibold mb-1">
                {t('load_error', { error: '' }) || 'Ошибка загрузки'}
              </div>
              <div className="text-xs text-rose-200/80">{errorMessage}</div>
            </div>
            <Button
              variant="danger"
              size="sm"
              onClick={() => loadLibraryInitial(filters)}
              className="shrink-0"
            >
              {t('retry') || 'Повторить'}
            </Button>
          </div>
        ) : items.length === 0 ? (
          <div className="empty panel p-12 text-center bg-film-base border border-film-line rounded-md text-film-muted font-sans space-y-3">
            {hasActiveFilters ? (
              <>
                <SlidersHorizontal className="w-10 h-10 mx-auto text-film-muted mb-2" />
                <div className="text-base font-semibold text-film-text">
                  {t('no_results_filtered') || 'Ничего не найдено'}
                </div>
                <p className="text-xs text-film-muted max-w-md mx-auto">
                  {t('no_results_filtered_hint') || 'Попробуйте изменить параметры фильтрации или сбросить фильтры.'}
                </p>
                <div className="pt-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<RotateCcw className="w-3.5 h-3.5" />}
                    onClick={handleResetFilters}
                    className="text-film-accent border-film-line hover:bg-film-hover"
                  >
                    {t('reset_filters_btn') || 'Сбросить фильтры'}
                  </Button>
                </div>
              </>
            ) : (
              <>
                <Film className="w-10 h-10 mx-auto text-film-muted mb-2" />
                <div className="text-base font-semibold text-film-text">
                  {t('library_empty') || 'В библиотеке пока нет раздач'}
                </div>
              </>
            )}
          </div>
        ) : (
          <div className="space-y-6">
            <div className="ui-library-grid">
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
                    role="button"
                    tabIndex={0}
                    aria-label={`Открыть: ${item.title}`}
                    data-selected={isSelected}
                    className={`ui-library-item card group relative flex flex-col bg-film-base border rounded-md overflow-hidden transition-all duration-200 cursor-pointer   ${
                      isSelected
                        ? 'border-film-line bg-film-hover '
                        : 'border-film-line hover:border-film-line hover:bg-film-base'
                    }`}
                  >
                    {/* Верхняя панель: Чекбокс и кнопка удаления */}
                    <div
                      className="absolute top-2 left-2 z-10"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <label className="flex items-center justify-center p-1 bg-film-base border border-film-line rounded cursor-pointer hover:border-film-line transition-colors">
                        <input
                          type="checkbox"
                          aria-label={`Выбрать: ${item.title}`}
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
                        className="p-1.5 bg-film-base border border-film-line rounded text-film-muted hover:text-rose-400 hover:border-rose-500/50 transition-colors cursor-pointer"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>

                    {/* Постер с бейджами */}
                    <div className="ui-media-image relative aspect-[2/3] w-full bg-film-surface overflow-hidden flex items-center justify-center">
                      {item.poster_url ? (
                        <img
                          src={item.poster_url}
                          alt={item.title}
                          loading="lazy"
                          className="w-full h-full object-cover transition-transform duration-300"
                        />
                      ) : (
                        <div className="text-film-muted flex flex-col items-center gap-2 p-4 text-center">
                          {isSeries ? <Tv className="w-10 h-10" /> : <Film className="w-10 h-10" />}
                          <span className="font-sans text-xs truncate max-w-[120px]">{item.title}</span>
                        </div>
                      )}

                      {/* Бейдж типа (Сериал / Фильм) */}
                      <div className="absolute bottom-2 left-2 flex items-center gap-1.5">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-sans font-semibold   ${
                            isSeries
                              ? 'bg-film-base/90 text-film-text'
                              : 'bg-film-base/90 text-film-text'
                          }`}
                        >
                          {isSeries ? (t('series') || 'Сериал') : (t('movie') || 'Фильм')}
                        </span>

                        {/* Бейдж статуса */}
                        {isCompleted ? (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-sans font-semibold bg-emerald-500/80 text-black border border-emerald-300">
                            {t('completed') || 'Завершено'}
                          </span>
                        ) : item.status === 'watching' || item.status === 'in_progress' ? (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-sans font-semibold bg-amber-500/80 text-black border border-amber-300">
                            {t('watching') || 'Смотрю'}
                          </span>
                        ) : item.status === 'planned' ? (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-sans font-semibold bg-film-base/90 text-film-text">
                            {t('planned') || 'Запланировано'}
                          </span>
                        ) : null}
                      </div>

                      {/* Рейтинг */}
                      {item.rating !== null && item.rating !== undefined && (
                        <div className="absolute bottom-2 right-2 bg-film-base border border-amber-500/40 text-amber-300 px-1.5 py-0.5 rounded font-sans text-[11px] font-semibold flex items-center gap-1">
                          <Star className="w-3 h-3 fill-amber-400 text-amber-400" />
                          {Number(item.rating).toFixed(1)}
                        </div>
                      )}
                    </div>

                    {/* Информация карточки */}
                    <div className="ui-media-copy p-3.5 flex flex-col flex-1 justify-between gap-3">
                      <div className="space-y-1.5">
                        <div className="flex items-start justify-between gap-2">
                          <h3
                            className="font-sans text-sm font-semibold text-film-text group-hover:text-film-accent transition-colors line-clamp-1"
                            title={item.title}
                          >
                            {item.title}
                          </h3>
                          {item.year && (
                            <span className="font-sans text-xs text-film-muted shrink-0">
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
                                className="text-[11px] font-sans text-film-muted"
                              >
                                {g}
                              </span>
                            ))}
                          </div>
                        )}

                        {/* Синопсис (Metadata enrichment) */}
                        {overviewText && (
                          <p className="text-xs text-film-muted font-sans line-clamp-2 leading-relaxed">
                            {overviewText}
                          </p>
                        )}
                      </div>

                      {/* Блок прогресса серий (для сериалов) */}
                      <div className="space-y-2 pt-2 border-t border-film-line">
                        {isSeries && (
                          <div className="space-y-1">
                            <div className="flex items-center justify-between text-[11px] font-sans text-film-muted">
                              <span>Прогресс</span>
                              <span className="text-film-accent font-semibold">
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

            {/* Sentinel для IntersectionObserver infinite scroll */}
            <div ref={sentinelRef} className="h-6 w-full pointer-events-none" />

            {/* Индикатор загрузки следующей страницы */}
            {isLoadingMore && (
              <div className="py-6 flex items-center justify-center gap-2 text-film-muted font-sans text-xs">
                <Loader2 className="w-4 h-4 animate-spin text-film-accent" />
                <span>{t('loading_more') || 'Загрузка...'}</span>
              </div>
            )}

            {/* Индикатор завершения списка */}
            {!hasMore && items.length > 0 && items.length >= totalCount && (
              <div className="py-6 text-center text-xs font-sans text-film-muted">
                — {t('all_items_loaded') || 'Все элементы загружены'} —
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
