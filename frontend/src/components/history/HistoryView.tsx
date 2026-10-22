import React, { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Check, Clock3, Film, Loader2, Play, Trash2, Tv } from 'lucide-react';

import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { HistoryItem } from '../../types';
import { formatTime } from '../../utils/torrentParser';
import { Button, Progress } from '../ui/UIComponents';
import { InlinePlayer } from '../player/InlinePlayer';

export const HistoryView: React.FC = () => {
  const { goBack, openPlayback, t } = useApp();
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  const loadHistory = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setItems(await API.getHistory());
    } catch (err: any) {
      setError(err?.message || 'Ошибка загрузки истории');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const itemKey = (item: HistoryItem) => `${item.torrent_hash}:${item.file_index}`;

  const continueWatching = async (item: HistoryItem) => {
    const key = itemKey(item);
    setPendingAction(key);
    try {
      if (item.torrent_hash.startsWith('online:')) {
        const parts = item.torrent_hash.split(':');
        if (parts.length >= 3) {
          const provider = parts[1];
          const id = parts.slice(2).join(':');
          const res = await API.playOnline({
            provider,
            id,
          });
          openPlayback({
            hash: item.torrent_hash,
            title: res.title || item.title || item.file_name,
            poster:
              res.thumbnail ||
              (item.poster_file
                ? `/api/library/poster/${encodeURIComponent(item.torrent_hash)}`
                : undefined),
            fileId: 0,
            fileName: res.title || item.title || item.file_name,
            startTime: item.is_watched ? 0 : (res.timecode || item.playback_timecode || 0),
            isOnline: true,
            onlineProvider: provider,
            onlineId: id,
          });
          return;
        }
      }

      openPlayback({
        hash: item.torrent_hash,
        title: item.title || item.file_name,
        poster: item.poster_file
          ? `/api/library/poster/${encodeURIComponent(item.torrent_hash)}`
          : undefined,
        fileId: item.file_index,
        fileName: item.file_name,
        startTime: item.is_watched ? 0 : item.playback_timecode || 0,
      });
    } catch (err: any) {
      setError(err?.message || 'Ошибка запуска плеера');
    } finally {
      setPendingAction(null);
    }
  };

  const markWatched = async (item: HistoryItem) => {
    const key = itemKey(item);
    setPendingAction(key);
    try {
      await API.markHistoryWatched(item.torrent_hash, item.file_index);
      setItems((current) => current.map((entry) => (
        itemKey(entry) === key
          ? {
              ...entry,
              is_watched: true,
              playback_timecode: entry.playback_duration || entry.playback_timecode,
            }
          : entry
      )));
    } catch (err: any) {
      setError(err?.message || 'Ошибка обновления истории');
    } finally {
      setPendingAction(null);
    }
  };

  const deleteEntry = async (item: HistoryItem) => {
    const key = itemKey(item);
    setPendingAction(key);
    try {
      await API.deleteHistoryEntry(item.torrent_hash, item.file_index);
      setItems((current) => current.filter((entry) => itemKey(entry) !== key));
      try {
        const raw = sessionStorage.getItem('pc_recent_items');
        if (raw) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed)) {
            const next = parsed.filter(
              (it) => !(it.torrent_hash === item.torrent_hash && it.file_index === item.file_index)
            );
            sessionStorage.setItem('pc_recent_items', JSON.stringify(next));
          }
        }
      } catch {}
    } catch (err: any) {
      setError(err?.message || 'Ошибка удаления записи');
    } finally {
      setPendingAction(null);
    }
  };

  return (
    <div className="space-y-7 animate-fade-in pb-12">
      <header className="flex items-end justify-between gap-4 border-b border-slate-800 pb-5">
        <Button
          variant="secondary"
          size="sm"
          icon={<ArrowLeft className="h-4 w-4" />}
          onClick={goBack}
        >
          {t('back')}
        </Button>
        <div>
          <p className="font-code text-xs uppercase tracking-wider text-cyan-400">Pirate Cinema</p>
          <h1 className="mt-1 font-tech text-2xl font-bold uppercase tracking-wider text-slate-100">
            {t('history')}
          </h1>
        </div>
        <Clock3 className="h-6 w-6 text-slate-500" />
      </header>

      {/* ── Встроенный видеоплеер в истории просмотров ── */}
      <InlinePlayer />

      {isLoading ? (
        <div className="py-16 text-center font-tech text-slate-400">
          <Loader2 className="mx-auto mb-3 h-7 w-7 animate-spin text-cyan-400" />
          {t('loading')}
        </div>
      ) : error ? (
        <div className="border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-300">{error}</div>
      ) : items.length === 0 ? (
        <div className="py-20 text-center text-slate-400">
          <Film className="mx-auto mb-3 h-10 w-10 text-slate-600" />
          <p className="font-tech text-sm uppercase tracking-wider">{t('history_empty')}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((item) => {
            const key = itemKey(item);
            const isPending = pendingAction === key;
            const title = item.title || item.file_name;
            const posterUrl = item.poster_file
              ? `/api/library/poster/${encodeURIComponent(item.torrent_hash)}`
              : null;
            const progress = item.playback_timecode || 0;
            const duration = item.playback_duration || 0;

            return (
              <article
                key={key}
                className="grid grid-cols-[64px_minmax(0,1fr)] gap-4 border border-slate-800/80 bg-[#090d16] p-3 sm:grid-cols-[64px_minmax(0,1fr)_minmax(180px,280px)] sm:items-center"
              >
                <div className="h-20 w-16 overflow-hidden rounded-sm bg-slate-900">
                  {posterUrl ? (
                    <img src={posterUrl} alt={title} className="h-full w-full object-cover" />
                  ) : (
                    <div className="flex h-full items-center justify-center text-slate-600">
                      {item.media_type === 'series' ? <Tv className="h-6 w-6" /> : <Film className="h-6 w-6" />}
                    </div>
                  )}
                </div>

                <div className="min-w-0">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h2 className="truncate font-tech text-sm font-semibold text-slate-100">{title}</h2>
                      <p className="mt-1 truncate font-code text-xs text-slate-400">
                        {item.season !== undefined && item.season !== null && item.episode !== undefined && item.episode !== null
                          ? `Сезон ${item.season}, эпизод ${item.episode} · ${item.file_name}`
                          : item.file_name}
                      </p>
                    </div>
                    {item.is_watched && (
                      <span className="shrink-0 rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 font-code text-[10px] uppercase text-emerald-300">
                        {t('watched')}
                      </span>
                    )}
                  </div>
                  <div className="mt-3 flex items-center gap-3">
                    <Progress value={progress} max={duration || 1} className="h-1.5 flex-1" />
                    <span className="font-code text-xs text-slate-400">
                      {duration > 0 ? `${formatTime(progress)} / ${formatTime(duration)}` : formatTime(progress)}
                    </span>
                  </div>
                </div>

                <div className="col-span-2 flex flex-wrap gap-2 sm:col-span-1 sm:justify-end">
                  <Button
                    variant="primary"
                    size="sm"
                    icon={<Play className="h-3.5 w-3.5 fill-current" />}
                    loading={isPending}
                    disabled={isPending}
                    onClick={() => continueWatching(item)}
                  >
                    {item.is_watched ? t('watch') : t('continue')}
                  </Button>
                  {!item.is_watched && (
                    <Button
                      variant="secondary"
                      size="sm"
                      icon={<Check className="h-3.5 w-3.5" />}
                      disabled={isPending}
                      onClick={() => markWatched(item)}
                      title={t('mark_watched')}
                    >
                      {t('mark_watched')}
                    </Button>
                  )}
                  <button
                    type="button"
                    title={t('delete_history_entry')}
                    disabled={isPending}
                    onClick={() => deleteEntry(item)}
                    className="flex h-8 w-8 items-center justify-center rounded border border-slate-700 text-slate-400 transition-colors hover:border-rose-500/50 hover:text-rose-400 disabled:opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
};
