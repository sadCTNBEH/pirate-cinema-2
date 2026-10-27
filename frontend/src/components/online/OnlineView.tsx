/**
 * @file components/online/OnlineView.tsx
 * @description Раздел онлайн-видео Pirate Cinema:
 * поиск видео по провайдерам (Rutube, прямые HLS потоки),
 * управление плейлистами, история просмотров и воспроизведение.
 */

import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import {
  OnlineSearchResult,
  OnlinePlaylist,
  OnlineHistoryItem,
} from '../../types';
import { formatTime } from '../../utils/torrentParser';
import {
  Search,
  Play,
  Plus,
  Trash2,
  ListPlus,
  Film,
  Loader2,
  Tv,
  Clock,
  Check,
  FolderPlus,
  Edit2,
} from 'lucide-react';
import { Progress } from '../ui/UIComponents';
import { InlinePlayer } from '../player/InlinePlayer';

export const OnlineView: React.FC = () => {
  const { t, routeParams, openPlayback, activePlayback } = useApp();

  const [activeTab, setActiveTab] = useState<'search' | 'playlists' | 'history'>('search');

  // ─── Поиск ───
  const [searchQuery, setSearchQuery] = useState<string>(routeParams.query || '');
  const [selectedProvider, setSelectedProvider] = useState<string>('rutube');
  const [selectedQuality, setSelectedQuality] = useState<string>('auto');
  const [searchResults, setSearchResults] = useState<OnlineSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  // ─── Плейлисты ───
  const [playlists, setPlaylists] = useState<OnlinePlaylist[]>([]);
  const [activePlaylistId, setActivePlaylistId] = useState<string | null>(
    routeParams.onlinePlaylistId || null
  );
  const [isLoadingPlaylists, setIsLoadingPlaylists] = useState<boolean>(false);
  const [newPlaylistTitle, setNewPlaylistTitle] = useState<string>('');
  const [isCreatingPlaylist, setIsCreatingPlaylist] = useState<boolean>(false);
  const [addToPlaylistTarget, setAddToPlaylistTarget] = useState<OnlineSearchResult | null>(null);
  const [modalNewPlaylistTitle, setModalNewPlaylistTitle] = useState<string>('');
  const [isCreatingInModal, setIsCreatingInModal] = useState<boolean>(false);

  // ─── История ───
  const [historyItems, setHistoryItems] = useState<OnlineHistoryItem[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState<boolean>(false);

  // ─── Статус воспроизведения ───
  const [playingId, setPlayingId] = useState<string | null>(null);
  const playAbortControllerRef = useRef<AbortController | null>(null);

  // Мгновенная отмена фонового запуска при закрытии плеера пользователем
  const prevActivePlaybackRef = useRef(activePlayback);
  useEffect(() => {
    if (prevActivePlaybackRef.current && !activePlayback) {
      if (playAbortControllerRef.current) {
        playAbortControllerRef.current.abort();
        playAbortControllerRef.current = null;
      }
      setPlayingId(null);
    }
    prevActivePlaybackRef.current = activePlayback;
  }, [activePlayback]);

  // Очистка при размонтировании компонента
  useEffect(() => {
    return () => {
      if (playAbortControllerRef.current) {
        playAbortControllerRef.current.abort();
        playAbortControllerRef.current = null;
      }
    };
  }, []);

  const handleCancelPlay = useCallback(() => {
    if (playAbortControllerRef.current) {
      playAbortControllerRef.current.abort();
      playAbortControllerRef.current = null;
    }
    setPlayingId(null);
  }, []);

  /**
   * Загрузка списка плейлистов
   */
  const loadPlaylists = useCallback(async () => {
    setIsLoadingPlaylists(true);
    try {
      const data = await API.getOnlinePlaylists();
      const valid = Array.isArray(data) ? data : [];
      setPlaylists(valid);
      setActivePlaylistId((prev) => {
        if (prev && valid.some((p) => p.id === prev)) return prev;
        return valid[0]?.id || null;
      });
    } catch (err: any) {
      console.warn('Ошибка загрузки плейлистов:', err);
    } finally {
      setIsLoadingPlaylists(false);
    }
  }, []);

  /**
   * Загрузка онлайн-истории
   */
  const loadHistory = useCallback(async () => {
    setIsLoadingHistory(true);
    try {
      const data = await API.getOnlineHistory();
      setHistoryItems(Array.isArray(data) ? data : []);
    } catch (err: any) {
      console.warn('Ошибка загрузки истории:', err);
    } finally {
      setIsLoadingHistory(false);
    }
  }, []);

  // Первоначальная загрузка плейлистов при монтировании
  useEffect(() => {
    loadPlaylists();
  }, [loadPlaylists]);

  useEffect(() => {
    if (activeTab === 'playlists') {
      loadPlaylists();
    } else if (activeTab === 'history') {
      loadHistory();
    }
  }, [activeTab, loadPlaylists, loadHistory]);

  // Если при переходе передан ID плейлиста, переключаемся на вкладку плейлистов
  useEffect(() => {
    if (routeParams.onlinePlaylistId) {
      setActivePlaylistId(routeParams.onlinePlaylistId);
      setActiveTab('playlists');
    }
  }, [routeParams.onlinePlaylistId]);

  /**
   * Выполнение поиска онлайн-видео
   */
  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const q = searchQuery.trim();
    if (!q) return;

    setIsSearching(true);
    setSearchError(null);
    try {
      const results = await API.searchOnline(
        q,
        selectedProvider === 'all' ? undefined : selectedProvider
      );
      setSearchResults(Array.isArray(results) ? results : []);
      if (results.length === 0) {
        setSearchError(t('nothing_found'));
      }
    } catch (err: any) {
      setSearchError(err?.message || 'Ошибка поиска онлайн-видео');
      setSearchResults([]);
    } finally {
      setIsSearching(false);
    }
  };

  /**
   * Запуск воспроизведения онлайн-видео с поддержкой отмены
   */
  const handlePlayOnline = async (
    item: OnlineSearchResult,
    playlistId?: string,
    episodeIndex?: number
  ) => {
    if (playAbortControllerRef.current) {
      playAbortControllerRef.current.abort();
    }
    const controller = new AbortController();
    playAbortControllerRef.current = controller;

    setPlayingId(item.id);
    try {
      const res = await API.playOnline(
        {
          provider: item.provider,
          id: item.id,
          quality: selectedQuality !== 'auto' ? selectedQuality : undefined,
          playlist_id: playlistId,
          episode_index: episodeIndex,
        },
        { signal: controller.signal }
      );

      if (controller.signal.aborted) {
        return;
      }

      openPlayback({
        hash: `online:${item.provider}:${item.id}`,
        title: res.title || item.title,
        poster: res.thumbnail || item.thumbnail || undefined,
        fileId: 0,
        fileName: res.title || item.title,
        startTime: res.timecode || 0,
        isOnline: true,
        onlineProvider: item.provider,
        onlineId: item.id,
        playlistId: playlistId,
        episodeIndex: episodeIndex,
      });
    } catch (err: any) {
      if (err?.name === 'AbortError' || controller.signal.aborted) {
        return;
      }
      alert(err?.message || 'Не удалось запустить онлайн-видео');
    } finally {
      if (playAbortControllerRef.current === controller) {
        playAbortControllerRef.current = null;
        setPlayingId(null);
      }
    }
  };

  /**
   * Создание нового плейлиста
   */
  const handleCreatePlaylist = async (e: React.FormEvent) => {
    e.preventDefault();
    const title = newPlaylistTitle.trim();
    if (!title) return;

    try {
      const created = await API.createOnlinePlaylist(title);
      setPlaylists((prev) => [created, ...prev]);
      setActivePlaylistId(created.id);
      setNewPlaylistTitle('');
      setIsCreatingPlaylist(false);
    } catch (err: any) {
      alert(err?.message || 'Ошибка создания плейлиста');
    }
  };

  /**
   * Удаление плейлиста
   */
  const handleDeletePlaylist = async (id: string) => {
    if (!window.confirm(t('confirm_delete_playlist') || 'Удалить этот плейлист?')) return;
    try {
      await API.deleteOnlinePlaylist(id);
      setPlaylists((prev) => {
        const next = prev.filter((p) => p.id !== id);
        if (activePlaylistId === id) {
          setActivePlaylistId(next.length > 0 ? next[0].id : null);
        }
        return next;
      });
    } catch (err: any) {
      alert(err?.message || 'Ошибка удаления плейлиста');
    }
  };

  /**
   * Переименование плейлиста
   */
  const handleRenamePlaylist = async (pl: OnlinePlaylist) => {
    const newName = window.prompt(t('playlist_title') || 'Название плейлиста', pl.title);
    if (!newName || newName.trim() === pl.title) return;

    try {
      const updated = await API.updateOnlinePlaylist(pl.id, newName.trim());
      setPlaylists((prev) => prev.map((p) => (p.id === pl.id ? updated : p)));
    } catch (err: any) {
      alert(err?.message || 'Ошибка переименования плейлиста');
    }
  };

  /**
   * Добавление элемента в плейлист
   */
  const handleAddToPlaylist = async (playlistId: string, item: OnlineSearchResult) => {
    try {
      const updated = await API.addOnlinePlaylistItem(playlistId, item);
      setPlaylists((prev) => prev.map((p) => (p.id === playlistId ? updated : p)));
      setAddToPlaylistTarget(null);
    } catch (err: any) {
      alert(err?.message || 'Ошибка добавления в плейлист');
    }
  };

  /**
   * Создание нового плейлиста из модального окна и добавление туда видео
   */
  const handleCreateAndAddToPlaylist = async (title: string, item: OnlineSearchResult) => {
    const trimmed = title.trim();
    if (!trimmed) return;
    setIsCreatingInModal(true);
    try {
      const newPl = await API.createOnlinePlaylist(trimmed);
      const updated = await API.addOnlinePlaylistItem(newPl.id, item);
      setPlaylists((prev) => [updated, ...prev.filter((p) => p.id !== newPl.id)]);
      setActivePlaylistId(newPl.id);
      setModalNewPlaylistTitle('');
      setAddToPlaylistTarget(null);
    } catch (err: any) {
      alert(err?.message || 'Ошибка создания плейлиста');
    } finally {
      setIsCreatingInModal(false);
    }
  };

  /**
   * Удаление элемента из плейлиста
   */
  const handleRemoveFromPlaylist = async (playlistId: string, itemId: string) => {
    try {
      const updated = await API.removeOnlinePlaylistItem(playlistId, itemId);
      setPlaylists((prev) => prev.map((p) => (p.id === playlistId ? updated : p)));
    } catch (err: any) {
      alert(err?.message || 'Ошибка удаления из плейлиста');
    }
  };

  /**
   * Удаление из истории онлайн-просмотров
   */
  const handleDeleteHistory = async (provider: string, itemId: string) => {
    try {
      await API.deleteOnlineHistoryItem(provider, itemId);
      setHistoryItems((prev) =>
        prev.filter((it) => !(it.provider === provider && it.item_id === itemId))
      );
    } catch (err: any) {
      alert(err?.message || 'Ошибка удаления из истории');
    }
  };

  /**
   * Очистить историю
   */
  const handleClearHistory = async () => {
    if (!window.confirm(t('confirm_clear_online_history') || 'Очистить историю онлайн-видео?')) {
      return;
    }
    try {
      await API.clearOnlineHistory();
      setHistoryItems([]);
    } catch (err: any) {
      alert(err?.message || 'Ошибка очистки истории');
    }
  };

  const currentPlaylist = playlists.find((p) => p.id === activePlaylistId);

  return (
    <div className="ui-page onlineview space-y-6 animate-fade-in">
      {/* ── Встроенный плеер MPV ── */}
      <InlinePlayer />

      {/* ── Шапка раздела и табы ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-film-line pb-4">
        <div>
          <h1 className="text-xl font-sans font-semibold text-film-text flex items-center gap-2">
            {t('online_videos') || 'Онлайн-видео'}
          </h1>
          <p className="text-xs font-sans text-film-muted mt-0.5">
            Rutube · Прямые потоки HLS · Сохранённые плейлисты
          </p>
        </div>

        <div className="flex items-center gap-1.5 bg-film-base border border-film-line p-1 rounded-md">
          <button
            type="button"
            onClick={() => setActiveTab('search')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-sm font-sans text-xs font-semibold   transition-colors cursor-pointer ${
              activeTab === 'search'
                ? 'bg-film-hover text-film-accent '
                : 'text-film-muted hover:text-film-text hover:bg-film-surface'
            }`}
          >
            <Search className="w-3.5 h-3.5" />
            {t('nav_search') || 'Поиск'}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('playlists')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-sm font-sans text-xs font-semibold   transition-colors cursor-pointer ${
              activeTab === 'playlists'
                ? 'bg-film-hover text-film-accent '
                : 'text-film-muted hover:text-film-text hover:bg-film-surface'
            }`}
          >
            <Tv className="w-3.5 h-3.5" />
            {t('online_playlists') || 'Плейлисты'}
            {playlists.length > 0 && (
              <span className="font-sans text-[10px] opacity-70">({playlists.length})</span>
            )}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('history')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-sm font-sans text-xs font-semibold   transition-colors cursor-pointer ${
              activeTab === 'history'
                ? 'bg-film-hover text-film-accent '
                : 'text-film-muted hover:text-film-text hover:bg-film-surface'
            }`}
          >
            <Clock className="w-3.5 h-3.5" />
            {t('online_history') || 'История'}
          </button>
        </div>
      </div>

      {/* ────────────────────────────────────────────────────────── */}
      {/* ВКЛАДКА: ПОИСК */}
      {/* ────────────────────────────────────────────────────────── */}
      {activeTab === 'search' && (
        <div className="space-y-6">
          <form onSubmit={handleSearch} className="flex flex-col sm:flex-row items-center gap-3">
            <div className="relative flex-1 w-full">
              <Search className="absolute left-3.5 top-1/2 /2 w-4 h-4 text-film-muted" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={
                  t('search_online_placeholder') ||
                  'Поиск видео на Rutube или прямая ссылка...'
                }
                className="w-full pl-10 pr-4 py-2.5 bg-film-base border border-film-line rounded-md text-sm text-film-text placeholder:text-film-muted focus:outline-none focus:border-film-line transition-colors font-sans"
              />
            </div>

            {/* Выбор провайдера */}
            <select
              value={selectedProvider}
              onChange={(e) => setSelectedProvider(e.target.value)}
              className="w-full sm:w-auto px-3 py-2.5 bg-film-base border border-film-line rounded-md text-xs font-sans text-film-text focus:outline-none focus:border-film-line"
            >
              <option value="rutube">Rutube</option>
              <option value="direct">Прямой поток</option>
              <option value="all">Все провайдеры</option>
            </select>

            {/* Желаемое качество */}
            <select
              value={selectedQuality}
              onChange={(e) => setSelectedQuality(e.target.value)}
              className="w-full sm:w-auto px-3 py-2.5 bg-film-base border border-film-line rounded-md text-xs font-sans text-film-text focus:outline-none focus:border-film-line"
            >
              <option value="auto">Качество: Авто</option>
              <option value="1080p">1080p</option>
              <option value="720p">720p</option>
              <option value="480p">480p</option>
              <option value="360p">360p</option>
            </select>

            <button
              type="submit"
              disabled={isSearching}
              className="w-full sm:w-auto px-6 py-2.5 bg-film-hover hover:bg-film-hover text-film-accent border border-film-line rounded-md font-sans text-xs font-semibold transition-colors flex items-center justify-center gap-2 cursor-pointer shrink-0"
            >
              {isSearching ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {t('searching') || 'Поиск...'}
                </>
              ) : (
                <>
                  <Search className="w-4 h-4" />
                  {t('search_btn') || 'Искать'}
                </>
              )}
            </button>
          </form>

          {searchError && (
            <div className="p-4 rounded-md bg-rose-950/20 border border-rose-900/40 text-rose-300 text-sm font-sans">
              {searchError}
            </div>
          )}

          {/* Результаты поиска */}
          {searchResults.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {searchResults.map((item) => {
                const isPlaying = playingId === item.id;
                return (
                  <div
                    key={item.id}
                    className="ui-online-item flex flex-col group min-w-0"
                  >
                    {/* Превью */}
                    <div className="ui-online-thumbnail relative aspect-video w-full bg-film-surface overflow-hidden">
                      {item.thumbnail ? (
                        <img
                          src={item.thumbnail}
                          alt={item.title}
                          className="w-full h-full object-cover transition-transform duration-300"
                          loading="lazy"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-slate-700">
                          <Film className="w-10 h-10" />
                        </div>
                      )}
                      {item.duration && (
                        <span className="absolute bottom-1.5 right-1.5 bg-black/80 px-1.5 py-0.5 rounded text-[11px] font-sans text-film-text">
                          {formatTime(item.duration)}
                        </span>
                      )}
                      <span className="absolute top-1.5 left-1.5 bg-film-hover border border-film-line text-film-accent px-1.5 py-0.5 rounded text-[10px] font-sans">
                        {item.provider}
                      </span>
                    </div>

                    {/* Описание и кнопки */}
                    <div className="p-3 flex-1 flex flex-col justify-between gap-3">
                      <strong className="text-sm font-sans font-semibold text-film-text line-clamp-2 leading-snug group-hover:text-film-accent transition-colors">
                        {item.title}
                      </strong>

                      <div className="flex items-center gap-2 pt-1 border-t border-film-line">
                        <button
                          type="button"
                          onClick={() => {
                            if (isPlaying) {
                              handleCancelPlay();
                            } else {
                              handlePlayOnline(item);
                            }
                          }}
                          className="flex-1 py-1.5 px-3 bg-film-hover hover:bg-film-hover border border-film-line text-film-accent rounded font-sans text-xs flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
                          title={isPlaying ? 'Отменить запуск' : (t('play') || 'Смотреть')}
                        >
                          {isPlaying ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin text-film-accent" />
                          ) : (
                            <Play className="w-3.5 h-3.5 fill-current" />
                          )}
                          {isPlaying ? 'Отмена' : (t('play') || 'Смотреть')}
                        </button>

                        <button
                          type="button"
                          onClick={() => setAddToPlaylistTarget(item)}
                          title={t('add_to_playlist') || 'В плейлист'}
                          className="p-1.5 text-film-muted hover:text-film-accent hover:bg-film-hover border border-film-line hover:border-film-line rounded transition-colors cursor-pointer"
                        >
                          <ListPlus className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ────────────────────────────────────────────────────────── */}
      {/* ВКЛАДКА: ПЛЕЙЛИСТЫ */}
      {/* ────────────────────────────────────────────────────────── */}
      {activeTab === 'playlists' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-base font-sans text-film-text">
              {t('online_playlists') || 'Сохранённые плейлисты'}
            </h2>
            <button
              type="button"
              onClick={() => setIsCreatingPlaylist(true)}
              className="px-3.5 py-1.5 bg-film-hover hover:bg-film-hover text-film-accent border border-film-line rounded font-sans text-xs font-semibold flex items-center gap-1.5 cursor-pointer transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              {t('create_playlist') || 'Создать плейлист'}
            </button>
          </div>

          {/* Форма создания нового плейлиста */}
          {isCreatingPlaylist && (
            <form
              onSubmit={handleCreatePlaylist}
              className="p-4 bg-film-base border border-film-line rounded-md flex items-center gap-3 animate-fade-in"
            >
              <input
                type="text"
                value={newPlaylistTitle}
                onChange={(e) => setNewPlaylistTitle(e.target.value)}
                placeholder={t('playlist_title') || 'Название нового плейлиста...'}
                autoFocus
                className="flex-1 px-3 py-2 bg-film-base border border-film-line rounded text-sm text-film-text font-sans focus:outline-none focus:border-film-line"
              />
              <button
                type="submit"
                className="px-4 py-2 bg-film-hover hover:bg-film-hover text-film-accent border border-film-line rounded font-sans text-xs cursor-pointer"
              >
                {t('saved') || 'Создать'}
              </button>
              <button
                type="button"
                onClick={() => setIsCreatingPlaylist(false)}
                className="px-3 py-2 text-film-muted hover:text-film-text font-sans text-xs cursor-pointer"
              >
                Отмена
              </button>
            </form>
          )}

          {/* Список плейлистов и их содержимого */}
          {isLoadingPlaylists ? (
            <div className="py-12 flex justify-center text-film-muted font-sans">
              <Loader2 className="w-6 h-6 animate-spin mr-2" />
              Загрузка плейлистов...
            </div>
          ) : playlists.length === 0 ? (
            <div className="py-16 text-center border border-dashed border-film-line rounded-md">
              <FolderPlus className="w-12 h-12 text-film-muted mx-auto mb-3" />
              <p className="text-film-muted font-sans text-sm">
                {t('playlists_empty') || 'У вас пока нет сохранённых плейлистов'}
              </p>
            </div>
          ) : (
            <div className="ui-playlist-layout">
              {/* Левая колонка: выбор плейлиста */}
              <div className="space-y-2">
                {playlists.map((pl) => (
                  <button
                    key={pl.id}
                    type="button"
                    onClick={() => setActivePlaylistId(pl.id)}
                    className={`w-full flex items-center justify-between p-3 rounded border-0 text-left font-sans cursor-pointer transition-colors ${
                      pl.id === activePlaylistId
                        ? 'bg-film-hover border-film-line text-film-accent'
                        : 'bg-film-base border-film-line text-film-text hover:border-film-line'
                    }`}
                  >
                    <div className="min-w-0 pr-2">
                      <strong className="block text-sm truncate">{pl.title}</strong>
                      <span className="text-xs text-film-muted font-sans">
                        {pl.items.length} видео
                      </span>
                    </div>
                  </button>
                ))}
              </div>

              {/* Правая колонка: элементы активного плейлиста */}
              {currentPlaylist ? (
                <div className="space-y-4 min-w-0">
                  <div className="flex items-center justify-between border-b border-film-line pb-3">
                    <div>
                      <h3 className="text-lg font-sans font-semibold text-film-text">
                        {currentPlaylist.title}
                      </h3>
                      <p className="text-xs text-film-muted font-sans">
                        Всего элементов: {currentPlaylist.items.length}
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      {currentPlaylist.items.length > 0 && (
                        <button
                          type="button"
                          onClick={() => handlePlayOnline(currentPlaylist.items[0], currentPlaylist.id, 0)}
                          className="px-3 py-1.5 bg-film-hover hover:bg-film-hover text-film-accent border border-film-line rounded font-sans text-xs flex items-center gap-1.5 cursor-pointer"
                        >
                          <Play className="w-3.5 h-3.5 fill-current" />
                          Воспроизвести всё
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => handleRenamePlaylist(currentPlaylist)}
                        title="Переименовать плейлист"
                        className="p-2 text-film-muted hover:text-film-accent hover:bg-film-surface rounded transition-colors cursor-pointer"
                      >
                        <Edit2 className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDeletePlaylist(currentPlaylist.id)}
                        title={t('delete_playlist') || 'Удалить плейлист'}
                        className="p-2 text-film-muted hover:text-rose-400 hover:bg-rose-500/10 rounded transition-colors cursor-pointer"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>

                  {currentPlaylist.items.length === 0 ? (
                    <div className="py-12 text-center text-film-muted font-sans text-sm">
                      {t('no_items_in_playlist') || 'В этом плейлисте пока нет видео'}
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {currentPlaylist.items.map((item, idx) => (
                        <div
                          key={item.id + idx}
                          className="flex items-center gap-3 p-2.5 bg-film-base border border-film-line hover:border-film-line rounded transition-colors group"
                        >
                          <span className="font-sans text-xs text-film-muted w-6 text-center">
                            {idx + 1}
                          </span>

                          <div className="w-16 h-10 rounded bg-film-surface overflow-hidden shrink-0 border border-film-line">
                            {item.thumbnail ? (
                              <img
                                src={item.thumbnail}
                                alt={item.title}
                                className="w-full h-full object-cover"
                              />
                            ) : (
                              <div className="w-full h-full flex items-center justify-center text-slate-700">
                                <Film className="w-4 h-4" />
                              </div>
                            )}
                          </div>

                          <div className="min-w-0 flex-1">
                            <strong className="block text-sm font-sans text-film-text truncate group-hover:text-film-accent">
                              {item.title}
                            </strong>
                            <small className="block text-xs font-sans text-film-muted">
                              {item.provider}
                              {item.duration ? ` · ${formatTime(item.duration)}` : ''}
                            </small>
                          </div>

                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => {
                                if (playingId === item.id) {
                                  handleCancelPlay();
                                } else {
                                  handlePlayOnline(item, currentPlaylist.id, idx);
                                }
                              }}
                              className="p-2 text-film-accent hover:bg-film-hover rounded cursor-pointer"
                              title={playingId === item.id ? 'Отменить запуск' : (t('play') || 'Смотреть')}
                            >
                              {playingId === item.id ? (
                                <Loader2 className="w-4 h-4 animate-spin text-film-accent" />
                              ) : (
                                <Play className="w-4 h-4 fill-current" />
                              )}
                            </button>
                            <button
                              type="button"
                              onClick={() => handleRemoveFromPlaylist(currentPlaylist.id, item.id)}
                              className="p-2 text-film-muted hover:text-rose-400 hover:bg-rose-500/10 rounded cursor-pointer"
                              title={t('remove_from_playlist') || 'Удалить'}
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          )}
        </div>
      )}

      {/* ────────────────────────────────────────────────────────── */}
      {/* ВКЛАДКА: ИСТОРИЯ ОНЛАЙН */}
      {/* ────────────────────────────────────────────────────────── */}
      {activeTab === 'history' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between border-b border-film-line pb-3">
            <h2 className="text-base font-sans text-film-text">
              {t('online_history') || 'История онлайн-видео'}
            </h2>
            {historyItems.length > 0 && (
              <button
                type="button"
                onClick={handleClearHistory}
                className="px-3 py-1 text-film-muted hover:text-rose-400 hover:bg-rose-500/10 border border-film-line rounded font-sans text-xs cursor-pointer"
              >
                {t('delete_all') || 'Очистить всё'}
              </button>
            )}
          </div>

          {isLoadingHistory ? (
            <div className="py-12 flex justify-center text-film-muted font-sans">
              <Loader2 className="w-6 h-6 animate-spin mr-2" />
              Загрузка истории...
            </div>
          ) : historyItems.length === 0 ? (
            <div className="py-16 text-center border border-dashed border-film-line rounded-md">
              <Clock className="w-12 h-12 text-film-muted mx-auto mb-3" />
              <p className="text-film-muted font-sans text-sm">
                {t('history_empty') || 'История просмотра пока пуста'}
              </p>
            </div>
          ) : (
            <div className="grid gap-3">
              {historyItems.map((item) => (
                <div
                  key={item.provider + item.item_id}
                  className="flex items-center gap-3 p-3 rounded bg-film-base border border-film-line hover:border-film-line transition-colors group"
                >
                  {/* Превью */}
                  <div className="w-20 h-12 rounded bg-film-surface overflow-hidden shrink-0 border border-film-line">
                    {item.thumbnail ? (
                      <img
                        src={item.thumbnail}
                        alt={item.title}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-slate-700">
                        <Film className="w-5 h-5" />
                      </div>
                    )}
                  </div>

                  {/* Название и информация */}
                  <div className="min-w-0 flex-1 pr-2">
                    <strong className="block text-sm font-sans text-film-text truncate group-hover:text-film-accent">
                      {item.title}
                    </strong>
                    <small className="block text-xs font-sans text-film-muted">
                      {item.provider} · {new Date(item.last_played_at).toLocaleDateString()}
                    </small>
                  </div>

                  {/* Прогресс */}
                  <div className="w-32 hidden sm:block">
                    <Progress
                      value={item.playback_timecode}
                      max={item.playback_duration || 1}
                    />
                  </div>

                  <span className="font-sans text-xs text-film-muted shrink-0">
                    {item.is_watched
                      ? t('watched') || 'Просмотрено'
                      : formatTime(item.playback_timecode)}
                  </span>

                  {/* Действия */}
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        if (playingId === item.item_id) {
                          handleCancelPlay();
                        } else {
                          handlePlayOnline({
                            id: item.item_id,
                            title: item.title,
                            provider: item.provider,
                            thumbnail: item.thumbnail,
                            duration: item.duration,
                            is_playlist: false,
                          });
                        }
                      }}
                      className="p-2 text-film-accent hover:bg-film-hover rounded cursor-pointer"
                      title={playingId === item.item_id ? 'Отменить запуск' : (t('play') || 'Смотреть')}
                    >
                      {playingId === item.item_id ? (
                        <Loader2 className="w-4 h-4 animate-spin text-film-accent" />
                      ) : (
                        <Play className="w-4 h-4 fill-current" />
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteHistory(item.provider, item.item_id)}
                      className="p-2 text-film-muted hover:text-rose-400 hover:bg-rose-500/10 rounded cursor-pointer"
                      title={t('remove_from_history') || 'Удалить'}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ────────────────────────────────────────────────────────── */}
      {/* МОДАЛЬНОЕ ОКНО: ДОБАВИТЬ В ПЛЕЙЛИСТ */}
      {/* ────────────────────────────────────────────────────────── */}
      {addToPlaylistTarget && (
        <div role="dialog" aria-modal="true" className="ui-dialog-overlay fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4">
          <div className="bg-film-base border border-film-line rounded-md max-w-md w-full p-6 space-y-4 animate-fade-in">
            <h3 className="text-base font-sans font-semibold text-film-text flex items-center gap-2">
              <span className="w-1.5 h-4 bg-film-hover" />
              {t('add_to_playlist') || 'Добавить в плейлист'}
            </h3>

            <p className="text-xs font-sans text-film-muted line-clamp-1">
              {addToPlaylistTarget.title}
            </p>

            {/* Быстрое создание нового плейлиста прямо в модальном окне */}
            <div className="flex items-center gap-2 pt-1 pb-2 border-b border-film-line">
              <input
                type="text"
                value={modalNewPlaylistTitle}
                onChange={(e) => setModalNewPlaylistTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleCreateAndAddToPlaylist(modalNewPlaylistTitle, addToPlaylistTarget);
                  }
                }}
                placeholder="Создать новый плейлист..."
                className="flex-1 px-3 py-2 bg-film-base border border-film-line focus:border-film-line rounded text-xs text-film-text font-sans focus:outline-none"
              />
              <button
                type="button"
                onClick={() => handleCreateAndAddToPlaylist(modalNewPlaylistTitle, addToPlaylistTarget)}
                disabled={!modalNewPlaylistTitle.trim() || isCreatingInModal}
                className="px-3.5 py-2 bg-film-hover hover:bg-film-hover text-film-accent border border-film-line rounded font-sans text-xs font-semibold flex items-center gap-1 cursor-pointer disabled:opacity-40 transition-colors shrink-0"
              >
                {isCreatingInModal ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Plus className="w-3.5 h-3.5" />
                )}
                Создать
              </button>
            </div>

            <div className="max-h-60 overflow-y-auto space-y-2">
              {playlists.length === 0 ? (
                <p className="text-xs text-film-muted font-sans py-4 text-center">
                  Нет созданных плейлистов. Введите название выше и нажмите «Создать».
                </p>
              ) : (
                playlists.map((pl) => {
                  const alreadyIn = pl.items.some((i) => i.id === addToPlaylistTarget.id);
                  return (
                    <button
                      key={pl.id}
                      type="button"
                      onClick={() => handleAddToPlaylist(pl.id, addToPlaylistTarget)}
                      className="w-full flex items-center justify-between p-3 rounded bg-film-base border border-film-line hover:border-film-line text-left font-sans cursor-pointer transition-colors"
                    >
                      <span className="text-sm text-film-text">{pl.title}</span>
                      {alreadyIn ? (
                        <span className="text-xs text-film-accent flex items-center gap-1">
                          <Check className="w-3.5 h-3.5" /> В списке
                        </span>
                      ) : (
                        <span className="text-xs text-film-muted font-sans">
                          {pl.items.length} видео
                        </span>
                      )}
                    </button>
                  );
                })
              )}
            </div>

            <div className="flex justify-end pt-2 border-t border-film-line">
              <button
                type="button"
                onClick={() => setAddToPlaylistTarget(null)}
                data-dialog-close
                className="px-4 py-2 bg-film-surface hover:bg-slate-700 text-film-text rounded font-sans text-xs cursor-pointer"
              >
                Закрыть
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
