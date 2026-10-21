/**
 * @file components/library/LibraryFilters.tsx
 * @description Панель расширенной фильтрации, сортировки и отображения активных фильтров медиатеки.
 */

import React, { useState, useEffect, useRef } from 'react';
import { useApp } from '../../context/AppContext';
import { LibraryFilter } from '../../types';
import { Button, Select } from '../ui/UIComponents';
import {
  Calendar,
  Tag,
  ArrowDownWideNarrow,
  ArrowUpNarrowWide,
  RotateCcw,
  X,
  Check,
  ChevronDown,
} from 'lucide-react';

interface LibraryFiltersProps {
  filters: LibraryFilter;
  onChange: (newFilters: LibraryFilter) => void;
  onReset: () => void;
  hasActiveFilters: boolean;
}

const POPULAR_GENRES = [
  { label: 'Боевик', value: 'Action,Боевик' },
  { label: 'Комедия', value: 'Comedy,Комедия' },
  { label: 'Драма', value: 'Drama,Драма' },
  { label: 'Фантастика', value: 'Sci-Fi,Фантастика' },
  { label: 'Триллер', value: 'Thriller,Триллер' },
  { label: 'Ужасы', value: 'Horror,Ужасы' },
  { label: 'Анимация', value: 'Animation,Анимация' },
  { label: 'Приключения', value: 'Adventure,Приключения' },
];

export const LibraryFilters: React.FC<LibraryFiltersProps> = ({
  filters,
  onChange,
  onReset,
  hasActiveFilters,
}) => {
  const { t } = useApp();

  // Состояние popover диапазона годов
  const [isYearOpen, setIsYearOpen] = useState(false);
  const [tempYearFrom, setTempYearFrom] = useState<string>(
    filters.year_from ? String(filters.year_from) : ''
  );
  const [tempYearTo, setTempYearTo] = useState<string>(
    filters.year_to ? String(filters.year_to) : ''
  );
  const [yearError, setYearError] = useState<string | null>(null);
  const yearPopoverRef = useRef<HTMLDivElement>(null);

  // Состояние ввода жанра
  const [isGenreOpen, setIsGenreOpen] = useState(false);
  const [genreInput, setGenreInput] = useState<string>(filters.genre || '');
  const genrePopoverRef = useRef<HTMLDivElement>(null);

  // Синхронизация временных полей с пропсами при их изменении
  useEffect(() => {
    setTempYearFrom(filters.year_from ? String(filters.year_from) : '');
    setTempYearTo(filters.year_to ? String(filters.year_to) : '');
    setYearError(null);
  }, [filters.year_from, filters.year_to]);

  useEffect(() => {
    setGenreInput(filters.genre || '');
  }, [filters.genre]);

  // Закрытие popover при клике снаружи
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      if (yearPopoverRef.current && !yearPopoverRef.current.contains(target)) {
        setIsYearOpen(false);
      }
      if (genrePopoverRef.current && !genrePopoverRef.current.contains(target)) {
        setIsGenreOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  /** Применение диапазона годов */
  const handleApplyYear = () => {
    const fromVal = tempYearFrom ? parseInt(tempYearFrom, 10) : undefined;
    const toVal = tempYearTo ? parseInt(tempYearTo, 10) : undefined;

    if (fromVal !== undefined && toVal !== undefined && fromVal > toVal) {
      setYearError(t('invalid_year_range') || 'Год "От" не может быть больше года "До"');
      return;
    }

    setYearError(null);
    setIsYearOpen(false);
    onChange({
      ...filters,
      year_from: fromVal,
      year_to: toVal,
      year: undefined,
    });
  };

  /** Сброс диапазона годов */
  const handleResetYear = () => {
    setTempYearFrom('');
    setTempYearTo('');
    setYearError(null);
    setIsYearOpen(false);
    onChange({
      ...filters,
      year_from: undefined,
      year_to: undefined,
      year: undefined,
    });
  };

  /** Применение жанра */
  const handleApplyGenre = (genreValue?: string) => {
    const val = genreValue !== undefined ? genreValue : genreInput.trim();
    setIsGenreOpen(false);
    onChange({
      ...filters,
      genre: val || undefined,
    });
  };

  /** Переключение направления сортировки */
  const toggleOrder = () => {
    const nextOrder = filters.order === 'asc' ? 'desc' : 'asc';
    onChange({
      ...filters,
      order: nextOrder,
    });
  };

  // Метка для кнопки диапазона годов
  const yearButtonLabel = (() => {
    if (filters.year_from && filters.year_to) {
      if (filters.year_from === filters.year_to) return String(filters.year_from);
      return `${filters.year_from}–${filters.year_to}`;
    }
    if (filters.year_from) {
      return `${t('year_from') || 'От'} ${filters.year_from}`;
    }
    if (filters.year_to) {
      return `${t('year_to') || 'До'} ${filters.year_to}`;
    }
    return t('years_range') || 'Годы';
  })();

  const isYearActive = !!(filters.year_from || filters.year_to);

  // Метка статуса для бейджа
  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'watching':
      case 'in_progress':
        return t('watching') || 'Смотрю';
      case 'completed':
      case 'watched':
        return t('completed') || 'Просмотрено';
      case 'planned':
        return t('planned') || 'Запланировано';
      case 'unwatched':
        return t('unwatched') || 'Не просмотрено';
      default:
        return status;
    }
  };

  return (
    <div className="p-4 bg-[#0a0e18] border border-cyan-900/40 rounded-lg shadow-sm space-y-3">
      {/* ── Основная строка фильтров и сортировки ── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Тип медиа: Все | Фильмы | Сериалы */}
        <div className="flex items-center gap-1 bg-[#060910] border border-slate-800 rounded-md p-1">
          <button
            type="button"
            id="filter-type-all-btn"
            onClick={() => onChange({ ...filters, type: undefined })}
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
            id="filter-type-movie-btn"
            onClick={() => onChange({ ...filters, type: 'movie' })}
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
            id="filter-type-series-btn"
            onClick={() => onChange({ ...filters, type: 'series' })}
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
              onChange({
                ...filters,
                status: e.target.value === 'all' ? undefined : (e.target.value as any),
              })
            }
            className="text-xs py-1.5 h-[34px]"
          >
            <option value="all">{t('all_statuses') || 'Все статусы'}</option>
            <option value="watching">{t('watching') || 'Смотрю'}</option>
            <option value="completed">{t('completed') || 'Просмотрено'}</option>
            <option value="planned">{t('planned') || 'Запланировано'}</option>
            {filters.status === 'unwatched' && (
              <option value="unwatched">{t('unwatched') || 'Не просмотрено'}</option>
            )}
          </Select>
        </div>

        {/* Фильтр диапазона годов (Popover) */}
        <div className="relative" ref={yearPopoverRef}>
          <button
            type="button"
            id="filter-year-popover-btn"
            onClick={() => setIsYearOpen((prev) => !prev)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-tech rounded-md border transition-all h-[34px] cursor-pointer ${
              isYearActive
                ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-300 font-bold shadow-[0_0_8px_rgba(0,240,255,0.2)]'
                : 'bg-[#090d16] border-slate-800 text-slate-300 hover:border-slate-700 hover:text-white'
            }`}
            title={t('filter_year') || 'Диапазон годов'}
          >
            <Calendar className="w-3.5 h-3.5 text-cyan-400" />
            <span>{yearButtonLabel}</span>
            <ChevronDown className="w-3 h-3 opacity-60" />
          </button>

          {isYearOpen && (
            <div className="absolute top-full left-0 mt-2 w-64 p-3.5 bg-[#0c1220] border border-cyan-900/60 rounded-lg shadow-2xl z-30 space-y-3 animate-fade-in">
              <div className="text-xs font-tech font-bold uppercase tracking-wider text-slate-200">
                {t('filter_year') || 'Год выпуска'}
              </div>

              <div className="flex items-center gap-2">
                <div className="flex-1 space-y-1">
                  <span className="text-[10px] text-slate-400 uppercase font-tech">
                    {t('year_from') || 'От'}
                  </span>
                  <input
                    type="number"
                    min="1900"
                    max="2100"
                    placeholder="1990"
                    value={tempYearFrom}
                    onChange={(e) => {
                      setTempYearFrom(e.target.value);
                      setYearError(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleApplyYear();
                    }}
                    className="w-full bg-[#060910] border border-slate-800 focus:border-cyan-400 text-slate-100 rounded px-2 py-1 text-xs outline-none"
                  />
                </div>
                <div className="flex-1 space-y-1">
                  <span className="text-[10px] text-slate-400 uppercase font-tech">
                    {t('year_to') || 'До'}
                  </span>
                  <input
                    type="number"
                    min="1900"
                    max="2100"
                    placeholder="2026"
                    value={tempYearTo}
                    onChange={(e) => {
                      setTempYearTo(e.target.value);
                      setYearError(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleApplyYear();
                    }}
                    className="w-full bg-[#060910] border border-slate-800 focus:border-cyan-400 text-slate-100 rounded px-2 py-1 text-xs outline-none"
                  />
                </div>
              </div>

              {yearError && (
                <div className="text-[11px] text-rose-400 leading-tight">{yearError}</div>
              )}

              <div className="flex items-center justify-between gap-2 pt-1 border-t border-slate-800/80">
                <button
                  type="button"
                  onClick={handleResetYear}
                  className="text-xs text-slate-400 hover:text-slate-200 cursor-pointer font-tech"
                >
                  {t('reset') || 'Сбросить'}
                </button>
                <Button variant="primary" size="sm" onClick={handleApplyYear} className="py-1 px-3 min-h-[28px] text-xs">
                  {t('apply') || 'Применить'}
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* Фильтр жанра (Input с подсказками) */}
        <div className="relative" ref={genrePopoverRef}>
          <div className="flex items-center bg-[#090d16] border border-slate-800 rounded-md h-[34px] px-2.5 focus-within:border-cyan-400/80 focus-within:shadow-[0_0_10px_rgba(0,240,255,0.18)] transition-all">
            <Tag className="w-3.5 h-3.5 text-slate-500 shrink-0 mr-1.5" />
            <input
              id="filter-genre-input"
              type="text"
              placeholder={t('filter_genre_placeholder') || 'Жанр...'}
              value={genreInput}
              onFocus={() => setIsGenreOpen(true)}
              onChange={(e) => setGenreInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleApplyGenre();
              }}
              className="bg-transparent text-xs text-slate-200 outline-none w-24 sm:w-32 placeholder:text-slate-500 font-sans"
            />
            {genreInput ? (
              <div className="flex items-center gap-1 shrink-0 ml-1">
                <button
                  type="button"
                  onClick={() => handleApplyGenre()}
                  title={t('apply') || 'Применить'}
                  className="text-cyan-400 hover:text-cyan-300 p-0.5 cursor-pointer"
                >
                  <Check className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setGenreInput('');
                    handleApplyGenre('');
                  }}
                  title={t('reset') || 'Очистить'}
                  className="text-slate-500 hover:text-rose-400 p-0.5 cursor-pointer"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ) : null}
          </div>

          {/* Выпадающий список быстрых жанров */}
          {isGenreOpen && (
            <div className="absolute top-full left-0 mt-2 w-64 p-3 bg-[#0c1220] border border-cyan-900/60 rounded-lg shadow-2xl z-30 space-y-2 animate-fade-in">
              <div className="text-[11px] font-tech text-slate-400 uppercase tracking-wider">
                Популярные жанры:
              </div>
              <div className="flex flex-wrap gap-1.5">
                {POPULAR_GENRES.map((g) => (
                  <button
                    key={g.label}
                    type="button"
                    onClick={() => {
                      setGenreInput(g.label);
                      handleApplyGenre(g.value);
                    }}
                    className={`px-2 py-1 text-xs rounded border transition-colors cursor-pointer ${
                      filters.genre === g.value || filters.genre?.includes(g.label)
                        ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40 font-bold'
                        : 'bg-[#060910] text-slate-300 border-slate-800 hover:border-slate-700 hover:text-white'
                    }`}
                  >
                    {g.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Сортировка и направление */}
        <div className="flex items-center gap-1.5 ml-auto">
          <span className="text-xs font-tech text-slate-400 uppercase tracking-wider hidden md:inline">
            {t('filter_sort') || 'Сортировка'}:
          </span>
          <Select
            id="filter-sort-select"
            value={filters.sort || 'added'}
            onChange={(e) =>
              onChange({
                ...filters,
                sort: e.target.value as any,
              })
            }
            className="text-xs py-1.5 h-[34px]"
          >
            <option value="added">{t('sort_added') || 'По дате'}</option>
            <option value="title">{t('sort_title') || 'По названию'}</option>
            <option value="year">{t('sort_year') || 'По году'}</option>
            <option value="progress">{t('sort_progress') || 'По прогрессу'}</option>
          </Select>

          {/* Кнопка направления сортировки (ASC / DESC) */}
          <button
            type="button"
            id="filter-order-toggle-btn"
            onClick={toggleOrder}
            title={filters.order === 'asc' ? (t('order_asc') || 'По возрастанию') : (t('order_desc') || 'По убыванию')}
            aria-label={filters.order === 'asc' ? 'Сортировка по возрастанию' : 'Сортировка по убыванию'}
            className="flex items-center justify-center w-[34px] h-[34px] bg-[#090d16] border border-slate-800 rounded-md text-slate-300 hover:text-cyan-400 hover:border-slate-700 transition-colors cursor-pointer"
          >
            {filters.order === 'asc' ? (
              <ArrowUpNarrowWide className="w-4 h-4 text-cyan-400" />
            ) : (
              <ArrowDownWideNarrow className="w-4 h-4 text-cyan-400" />
            )}
          </button>
        </div>
      </div>

      {/* ── Строка активных фильтров (Active Filters Chips) ── */}
      {hasActiveFilters && (
        <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-slate-800/60 animate-fade-in">
          <span className="text-xs font-tech text-slate-400 uppercase tracking-wider">
            {t('active_filters') || 'Активные фильтры'}:
          </span>

          {/* Чип: Тип */}
          {filters.type && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-sans rounded-md bg-cyan-950/40 border border-cyan-800/60 text-cyan-300">
              <span>{filters.type === 'movie' ? (t('movies') || 'Фильмы') : (t('series') || 'Сериалы')}</span>
              <button
                type="button"
                onClick={() => onChange({ ...filters, type: undefined })}
                className="hover:text-white p-0.5 cursor-pointer"
                title="Удалить фильтр типа"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          )}

          {/* Чип: Статус */}
          {filters.status && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-sans rounded-md bg-cyan-950/40 border border-cyan-800/60 text-cyan-300">
              <span>{getStatusLabel(filters.status)}</span>
              <button
                type="button"
                onClick={() => onChange({ ...filters, status: undefined })}
                className="hover:text-white p-0.5 cursor-pointer"
                title="Удалить фильтр статуса"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          )}

          {/* Чип: Диапазон годов */}
          {isYearActive && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-sans rounded-md bg-cyan-950/40 border border-cyan-800/60 text-cyan-300">
              <span>{yearButtonLabel}</span>
              <button
                type="button"
                onClick={handleResetYear}
                className="hover:text-white p-0.5 cursor-pointer"
                title="Удалить фильтр года"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          )}

          {/* Чип: Жанр */}
          {filters.genre && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-sans rounded-md bg-cyan-950/40 border border-cyan-800/60 text-cyan-300">
              <span>
                {t('filter_genre') || 'Жанр'}: {filters.genre.split(',')[0]}
              </span>
              <button
                type="button"
                onClick={() => handleApplyGenre('')}
                className="hover:text-white p-0.5 cursor-pointer"
                title="Удалить фильтр жанра"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          )}

          {/* Кнопка сбросить всё */}
          <button
            type="button"
            onClick={onReset}
            className="flex items-center gap-1 text-xs font-tech uppercase tracking-wider text-rose-400 hover:text-rose-300 ml-auto cursor-pointer px-2 py-1 rounded hover:bg-rose-500/10 transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
            <span>{t('reset_all') || 'Сбросить всё'}</span>
          </button>
        </div>
      )}
    </div>
  );
};
