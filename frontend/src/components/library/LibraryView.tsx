/**
 * @file components/library/LibraryView.tsx
 * @description Экран управления локальной библиотекой раздач в TorrServer.
 * Поддерживает множественный выбор, массовое удаление и переход к просмотру.
 */

import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { LibraryTorrent } from '../../types';
import { Button } from '../ui/UIComponents';
import { ArrowLeft, Trash2, Film, Play, Loader2, CheckSquare, Square } from 'lucide-react';

export const LibraryView: React.FC = () => {
  const { goBack, navigate, t } = useApp();

  const [torrents, setTorrents] = useState<LibraryTorrent[]>([]);
  const [selectedHashes, setSelectedHashes] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  /**
   * Загрузка списка торрентов из TorrServer
   */
  const loadLibrary = async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const data = await API.getTorrents();
      setTorrents(data || []);
      setSelectedHashes(new Set());
    } catch (err: any) {
      setErrorMessage(err.message || 'Ошибка загрузки библиотеки');
      setTorrents([]);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadLibrary();
  }, []);

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
    if (selectedHashes.size === torrents.length) {
      setSelectedHashes(new Set());
    } else {
      setSelectedHashes(new Set(torrents.map((t) => t.hash)));
    }
  };

  /**
   * Удаление одной раздачи
   */
  const handleRemoveOne = async (hash: string) => {
    if (!window.confirm(t('confirm_delete_from_ts'))) return;
    try {
      await API.remTorrent(hash);
      setTorrents((prev) => prev.filter((t) => t.hash !== hash));
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
      alert(t('select_torrents_to_delete'));
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
      setTorrents((prev) => prev.filter((t) => !selectedHashes.has(t.hash)));
      setSelectedHashes(new Set());
    } catch (err: any) {
      alert(err.message || 'Ошибка удаления выбранных');
    }
  };

  /**
   * Удаление всех сохраненных раздач
   */
  const handleDeleteAll = async () => {
    if (torrents.length === 0) return;
    if (
      !window.confirm(
        t('confirm_delete_all_ts', { count: torrents.length }) ||
          `Удалить все раздачи (${torrents.length})?`
      )
    ) {
      return;
    }

    try {
      await API.deleteAllTorrents();
      setTorrents([]);
      setSelectedHashes(new Set());
    } catch (err: any) {
      alert(err.message || 'Ошибка очистки библиотеки');
    }
  };

  /**
   * Переход к просмотру раздачи
   */
  const handleOpenDetail = (item: LibraryTorrent) => {
    navigate('detail', {
      hash: item.hash,
      title: item.title,
      poster: item.poster_url,
    });
  };

  return (
    <div className="space-y-8 animate-fade-in pb-12">
      {/* Шапка с групповыми операциями */}
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
          <h1 className="text-2xl font-tech font-bold uppercase tracking-wider text-slate-100">
            {t('nav_library')}
          </h1>
        </div>

        {torrents.length > 0 && (
          <div className="flex items-center gap-3">
            <Button
              variant="secondary"
              size="sm"
              icon={
                selectedHashes.size === torrents.length ? (
                  <CheckSquare className="w-3.5 h-3.5 text-cyan-400" />
                ) : (
                  <Square className="w-3.5 h-3.5" />
                )
              }
              onClick={toggleSelectAll}
            >
              {selectedHashes.size === torrents.length ? 'Снять выбор' : 'Выбрать все'}
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
              className="text-rose-500 border-rose-500/50"
            >
              {t('delete_all')}
            </Button>
          </div>
        )}
      </div>

      {/* Список сохраненных торрентов */}
      <div id="lib-list" className="space-y-3">
        {isLoading ? (
          <div className="p-8 text-center bg-[#0a0e18]/60 border border-cyan-900/30 rounded-sm text-slate-400 font-tech">
            <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2 text-cyan-400" />
            {t('searching')}
          </div>
        ) : errorMessage ? (
          <div className="p-6 bg-rose-500/10 border border-rose-500/30 rounded-sm text-rose-300 text-sm">
            {t('error', { error: errorMessage }) || errorMessage}
          </div>
        ) : torrents.length === 0 ? (
          <div className="empty panel p-8 text-center bg-[#0a0e18]/60 border border-cyan-900/30 rounded-sm text-slate-400 font-tech">
            {t('library_empty')}
          </div>
        ) : (
          torrents.map((tor) => {
            const isSelected = selectedHashes.has(tor.hash);
            return (
              <div
                key={tor.hash}
                className={`result result-lib grid grid-cols-[auto_48px_minmax(0,1fr)_auto] items-center gap-4 p-3.5 rounded-sm bg-[#090d16] border transition-all duration-150 shadow-sm ${
                  isSelected
                    ? 'border-cyan-400/80 bg-cyan-950/20 shadow-[0_0_15px_rgba(0,240,255,0.15)]'
                    : 'border-cyan-900/30 hover:border-cyan-500/50 hover:bg-[#0c1220]'
                }`}
              >
                {/* Чекбокс выбора */}
                <label className="result-check flex items-center justify-center p-1 cursor-pointer">
                  <input
                    type="checkbox"
                    className="lib-checkbox w-4 h-4 accent-cyan-400 cursor-pointer"
                    checked={isSelected}
                    onChange={() => toggleSelect(tor.hash)}
                    value={tor.hash}
                  />
                </label>

                {/* Обложка торрента */}
                <div className="w-12 h-18 rounded-sm overflow-hidden bg-slate-900 border border-slate-800 flex items-center justify-center">
                  {tor.poster_url ? (
                    <img
                      src={tor.poster_url}
                      alt={tor.title}
                      className="w-full h-full object-cover"
                      loading="lazy"
                    />
                  ) : (
                    <Film className="w-5 h-5 text-slate-600" />
                  )}
                </div>

                {/* Заголовок и хеш */}
                <div className="result-main min-w-0 pr-2">
                  <h3 className="text-sm font-semibold text-slate-100 truncate mb-1">
                    {tor.title}
                  </h3>
                  <div className="result-meta font-code text-xs text-slate-500 truncate">
                    <span>{tor.hash}</span>
                  </div>
                </div>

                {/* Действия */}
                <div className="result-actions flex items-center gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    icon={<Play className="w-3.5 h-3.5 fill-current" />}
                    onClick={() => handleOpenDetail(tor)}
                  >
                    {t('watch')}
                  </Button>

                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleRemoveOne(tor.hash)}
                    title="Удалить из TorrServer"
                    className="text-slate-400 hover:text-rose-400"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
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
