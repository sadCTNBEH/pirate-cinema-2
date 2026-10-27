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
    <div className="ui-filter-bar space-y-3">
      {/* ── Основная строка фильтров и сортировки ── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Тип медиа: Все | Фильмы | Сериалы */}
        <div className="flex items-center gap-1 bg-film-base border border-film-line rounded-md p-1">
          <button
            type="button"
            id="filter-type-all-btn"
            onClick={() => onChange({ ...filters, type: undefined })}
            className={`px-3 py-1.5 text-xs font-sans   rounded transition-all cursor-pointer ${
              !filters.type
                ? 'bg-film-hover text-film-accent font-semibold border border-film-line '
                : 'text-film-muted hover:text-film-text'
            }`}
          >
            {t('all') || 'Все'}
          </button>
          <button
            type="button"
            id="filter-type-movie-btn"
            onClick={() => onChange({ ...filters, type: 'movie' })}
            className={`px-3 py-1.5 text-xs font-sans   rounded transition-all cursor-pointer ${
              filters.type === 'movie'
                ? 'bg-film-hover text-film-accent font-semibold border border-film-line '
                : 'text-film-muted hover:text-film-text'
            }`}
          >
            {t('movies') || 'Фильмы'}
          </button>
          <button
            type="button"
            id="filter-type-series-btn"
            onClick={() => onChange({ ...filters, type: 'series' })}
            className={`px-3 py-1.5 text-xs font-sans   rounded transition-all cursor-pointer ${
              filters.type === 'series'
                ? 'bg-film-hover text-film-accent font-semibold border border-film-line '
                : 'text-film-muted hover:text-film-text'
            }`}
          >
            {t('series') || 'Сериалы'}
          </button>
        </div>

        {/* Фильтр статуса */}
        <div className="flex items-center gap-2">
          <span className="text-xs font-sans text-film-muted hidden sm:inline">
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
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-sans rounded-md border transition-all h-[34px] cursor-pointer ${
              isYearActive
                ? 'bg-film-hover border-film-line text-film-accent font-semibold '
                : 'bg-film-base border-film-line text-film-text hover:border-film-line hover:text-white'
            }`}
            title={t('filter_year') || 'Диапазон годов'}
          >
            <Calendar className="w-3.5 h-3.5 text-film-accent" />
            <span>{yearButtonLabel}</span>
            <ChevronDown className="w-3 h-3 opacity-60" />
          </button>

          {isYearOpen && (
            <div className="absolute top-full left-0 mt-2 w-64 p-3.5 bg-film-base border border-film-line rounded-md z-30 space-y-3 animate-fade-in">
              <div className="text-xs font-sans font-semibold text-film-text">
                {t('filter_year') || 'Год выпуска'}
              </div>

              <div className="flex items-center gap-2">
                <div className="flex-1 space-y-1">
                  <span className="text-[10px] text-film-muted font-sans">
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
                    className="w-full bg-film-base border border-film-line focus:border-film-line text-film-text rounded px-2 py-1 text-xs outline-none"
                  />
                </div>
                <div className="flex-1 space-y-1">
                  <span className="text-[10px] text-film-muted font-sans">
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
                    className="w-full bg-film-base border border-film-line focus:border-film-line text-film-text rounded px-2 py-1 text-xs outline-none"
                  />
                </div>
              </div>

              {yearError && (
                <div className="text-[11px] text-rose-400 leading-tight">{yearError}</div>
              )}

              <div className="flex items-center justify-between gap-2 pt-1 border-t border-film-line">
                <button
                  type="button"
                  onClick={handleResetYear}
                  className="text-xs text-film-muted hover:text-film-text cursor-pointer font-sans"
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
          <div className="flex items-center bg-film-base border border-film-line rounded-md h-[34px] px-2.5 focus-within:border-film-line transition-all">
            <Tag className="w-3.5 h-3.5 text-film-muted shrink-0 mr-1.5" />
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
              className="bg-transparent text-xs text-film-text outline-none w-24 sm:w-32 placeholder:text-film-muted font-sans"
            />
            {genreInput ? (
              <div className="flex items-center gap-1 shrink-0 ml-1">
                <button
                  type="button"
                  onClick={() => handleApplyGenre()}
                  title={t('apply') || 'Применить'}
                  className="text-film-accent hover:text-film-accent p-0.5 cursor-pointer"
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
                  className="text-film-muted hover:text-rose-400 p-0.5 cursor-pointer"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ) : null}
          </div>

          {/* Выпадающий список быстрых жанров */}
          {isGenreOpen && (
            <div className="absolute top-full left-0 mt-2 w-64 p-3 bg-film-base border border-film-line rounded-md z-30 space-y-2 animate-fade-in">
              <div className="text-[11px] font-sans text-film-muted">
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
                        ? 'bg-film-hover text-film-accent border-film-line font-semibold'
                        : 'bg-film-base text-film-text border-film-line hover:border-film-line hover:text-white'
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
          <span className="text-xs font-sans text-film-muted hidden md:inline">
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
            className="flex items-center justify-center w-[34px] h-[34px] bg-film-base border border-film-line rounded-md text-film-text hover:text-film-accent hover:border-film-line transition-colors cursor-pointer"
          >
            {filters.order === 'asc' ? (
              <ArrowUpNarrowWide className="w-4 h-4 text-film-accent" />
            ) : (
              <ArrowDownWideNarrow className="w-4 h-4 text-film-accent" />
            )}
          </button>
        </div>
      </div>

      {/* ── Строка активных фильтров (Active Filters Chips) ── */}
      {hasActiveFilters && (
        <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-film-line animate-fade-in">
          <span className="text-xs font-sans text-film-muted">
            {t('active_filters') || 'Активные фильтры'}:
          </span>

          {/* Чип: Тип */}
          {filters.type && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-sans rounded-md bg-film-hover border border-film-line text-film-accent">
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
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-sans rounded-md bg-film-hover border border-film-line text-film-accent">
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
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-sans rounded-md bg-film-hover border border-film-line text-film-accent">
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
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-sans rounded-md bg-film-hover border border-film-line text-film-accent">
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
            className="flex items-center gap-1 text-xs font-sans text-rose-400 hover:text-rose-300 ml-auto cursor-pointer px-2 py-1 rounded hover:bg-rose-500/10 transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
            <span>{t('reset_all') || 'Сбросить всё'}</span>
          </button>
        </div>
      )}
    </div>
  );
};
