/**
 * @file components/detail/TorrentDetailView.tsx
 * @description Экран детального просмотра файлов торрента в TorrServer.
 * Выполняет подключение к DHT-рою, опрос файлов с циклическим поллингом (до 30 попыток),
 * группировку по сезонам и отправку команд запуска в плеер MPV.
 */

import React, { useEffect, useState, useRef, useMemo } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { TorrentFilesResponse, TorrentFile } from '../../types';
import { formatSize, formatTime } from '../../utils/torrentParser';
import { Button, Select, SafeHtmlText } from '../ui/UIComponents';
import { ArrowLeft, Play, SkipForward, RefreshCw, Loader2, Check } from 'lucide-react';
import { InlinePlayer } from '../player/InlinePlayer';

export const TorrentDetailView: React.FC = () => {
  const { routeParams, goBack, openPlayback, t } = useApp();
  const {
    hash: initialHash = '',
    title = '',
    magnet = null,
    targetSeason,
  } = routeParams;

  const [currentHash, setCurrentHash] = useState<string>(initialHash);
  const [filesData, setFilesData] = useState<TorrentFilesResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isDeadTorrent, setIsDeadTorrent] = useState<boolean>(false);
  const [pollingAttempt, setPollingAttempt] = useState<number>(1);
  const [selectedSeasonKey, setSelectedSeasonKey] = useState<string>('1');
  const [overview, setOverview] = useState<string>('');
  const [playingFileId, setPlayingFileId] = useState<number | null>(null);

  const pollTimerRef = useRef<any>(null);
  const isCancelledRef = useRef<boolean>(false);

  /**
   * Запуск процесса получения файлов раздачи
   */
  const startFileFetchProcess = async () => {
    setIsLoading(true);
    setIsDeadTorrent(false);
    setPollingAttempt(1);
    setFilesData(null);

    let activeHash = currentHash;

    // Добавление magnet-ссылки в TorrServer (как в оригинальном app.js)
    if (magnet) {
      try {
        const added = await API.addTorrent(magnet, title);
        if (added && added.hash) {
          activeHash = added.hash;
          setCurrentHash(activeHash);
        }
        // Даем TorrServer 2 секунды на подключение к DHT и парсинг торрента
        await new Promise((r) => setTimeout(r, 2000));
      } catch (err: any) {
        console.warn('Ошибка добавления торрента:', err);
      }
    }

    if (!activeHash) {
      setIsLoading(false);
      return;
    }

    let attempts = 0;
    const maxAttempts = 30;

    const pollFiles = async () => {
      if (isCancelledRef.current) return;
      attempts++;
      setPollingAttempt(attempts);

      try {
        const data = await API.getTorrentFiles(activeHash, title);

        if (data && ((data.files && data.files.length > 0) || (data.flat_files && data.flat_files.length > 0))) {
          setFilesData(data);
          setIsLoading(false);

          if (data.type === 'series' && data.seasons) {
            const seasonKeys = Object.keys(data.seasons).sort(
              (a, b) => parseInt(a, 10) - parseInt(b, 10)
            );

            if (targetSeason && seasonKeys.includes(String(targetSeason))) {
              setSelectedSeasonKey(String(targetSeason));
            } else if (seasonKeys.length > 0) {
              setSelectedSeasonKey(seasonKeys[0]);
            }
          }
          return;
        }

        if (attempts < maxAttempts) {
          pollTimerRef.current = setTimeout(pollFiles, 2000);
        } else {
          setIsLoading(false);
          setIsDeadTorrent(true);
        }
      } catch {
        if (attempts < maxAttempts) {
          pollTimerRef.current = setTimeout(pollFiles, 2000);
        } else {
          setIsLoading(false);
          setIsDeadTorrent(true);
        }
      }
    };

    pollFiles();
  };

  useEffect(() => {
    isCancelledRef.current = false;
    startFileFetchProcess();

    return () => {
      isCancelledRef.current = true;
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, [currentHash, magnet]);

  /**
   * Подгрузка синопсиса фильма/сериала
   */
  useEffect(() => {
    if (title) {
      API.searchMedia(title)
        .then((res: any[]) => {
          if (res?.length && res[0].overview) {
            setOverview(res[0].overview);
          }
        })
        .catch(() => {});
    }
  }, [title]);

  /**
   * Воспроизведение конкретного файла во встроенном плеере над списком файлов
   */
  const handlePlayFile = async (file: TorrentFile) => {
    if (!currentHash) return;
    setPlayingFileId(file.id);

    openPlayback({
      hash: currentHash,
      title: title || file.name,
      fileId: file.id,
      fileName: file.name,
      startTime: file.playback_timecode || 0,
      preloadedFiles: filesData,
    });

    setTimeout(() => setPlayingFileId(null), 800);
  };

  /**
   * Воспроизведение следующей серии
   */
  const handlePlayNext = async (currentFile: TorrentFile) => {
    if (!currentHash || !filesData) return;

    const list = filesData.flat_files || filesData.files || [];
    const currentIndex = list.findIndex((f: TorrentFile) => f.id === currentFile.id);

    if (currentIndex >= 0 && currentIndex < list.length - 1) {
      const nextFile = list[currentIndex + 1];
      await handlePlayFile(nextFile);
    }
  };

  const [markingFileId, setMarkingFileId] = useState<number | null>(null);

  const handleToggleWatched = async (file: TorrentFile) => {
    if (!currentHash) return;
    setMarkingFileId(file.id);
    const targetWatched = !file.is_watched;
    try {
      await API.markWatched({
        torrent_hash: currentHash,
        file_index: file.id,
        watched: targetWatched,
      });

      setFilesData((prev) => {
        if (!prev) return prev;
        const updateFile = (f: TorrentFile) =>
          f.id === file.id
            ? {
                ...f,
                is_watched: targetWatched,
                playback_timecode: targetWatched ? 0 : f.playback_timecode,
              }
            : f;

        return {
          ...prev,
          flat_files: prev.flat_files?.map(updateFile),
          files: prev.files?.map(updateFile),
          movies: prev.movies?.map(updateFile),
          seasons: prev.seasons
            ? Object.fromEntries(
                Object.entries(prev.seasons).map(([k, list]) => [
                  k,
                  list.map(updateFile),
                ])
              )
            : undefined,
        };
      });
    } catch (err: any) {
      alert(err?.message || 'Ошибка обновления статуса просмотра');
    } finally {
      setMarkingFileId(null);
    }
  };

  /**
   * Список файлов для отображения
   */
  const currentFilesList = useMemo((): TorrentFile[] => {
    if (!filesData) return [];

    if (filesData.type === 'series' && filesData.seasons) {
      if (selectedSeasonKey === 'movies') {
        return filesData.movies || [];
      }
      return filesData.seasons[selectedSeasonKey] || [];
    }

    return filesData.flat_files || filesData.files || [];
  }, [filesData, selectedSeasonKey]);

  const seasonsList = useMemo(() => {
    if (!filesData || filesData.type !== 'series' || !filesData.seasons) return [];
    return Object.keys(filesData.seasons).sort((a, b) => parseInt(a, 10) - parseInt(b, 10));
  }, [filesData]);

  return (
    <div className="space-y-8 animate-fade-in pb-12">
      {/* Кнопка "Назад" */}
      <div>
        <Button
          id="back-btn"
          variant="secondary"
          size="sm"
          icon={<ArrowLeft className="w-4 h-4" />}
          onClick={goBack}
        >
          {t('back')}
        </Button>
      </div>

      {/* Заголовок раздачи и синопсис */}
      <div className="bg-[#0a0e18] border border-cyan-900/30 p-6 rounded-sm">
        <h1 id="detail-title" className="text-2xl font-tech font-bold uppercase tracking-wider text-slate-100 mb-3">
          {title}
        </h1>
        {overview && (
          <p id="detail-overview" className="overview text-slate-300 text-sm leading-relaxed font-sans max-w-4xl">
            {overview}
          </p>
        )}
      </div>

      {/* Встроенный плеер появляется над списком файлов, сдвигая файлы вниз */}
      <InlinePlayer />

      {/* Секция файлов */}
      <div className="space-y-4">
        {/* Индикатор ожидания DHT */}
        {isLoading && (
          <div className="p-8 text-center bg-[#0a0e18]/80 border border-cyan-500/30 rounded-sm">
            <Loader2 className="w-8 h-8 animate-spin mx-auto mb-3 text-cyan-400" />
            <div className="font-tech text-base text-slate-200 uppercase tracking-wider">
              {t('loading_files_dht')}
            </div>
            <div className="font-code text-xs text-slate-400 mt-2">
              {t('attempt_of', { attempt: pollingAttempt, total: 30 }) ||
                `Попытка ${pollingAttempt} из 30`}
            </div>
          </div>
        )}

        {/* Предупреждение об оффлайн торренте */}
        {isDeadTorrent && !isLoading && (
          <div className="p-8 text-center bg-rose-950/20 border border-rose-500/40 rounded-sm space-y-4">
            <div className="text-rose-300 font-sans text-sm">
              <SafeHtmlText text={t('dead_torrent_warning')} />
            </div>
            <Button
              id="reload-files-btn"
              variant="secondary"
              icon={<RefreshCw className="w-4 h-4" />}
              onClick={startFileFetchProcess}
            >
              {t('try_again')}
            </Button>
          </div>
        )}

        {/* Отображение файлов и селектор сезона */}
        {filesData && !isLoading && (
          <div>
            {/* Селектор сезонов */}
            {seasonsList.length > 0 && (
              <div className="mb-4">
                <Select
                  id="season-selector"
                  value={selectedSeasonKey}
                  onChange={(e) => setSelectedSeasonKey(e.target.value)}
                >
                  {seasonsList.map((s) => (
                    <option key={s} value={s}>
                      {t('season_prefix')} {s}
                    </option>
                  ))}
                  {filesData.movies && filesData.movies.length > 0 && (
                    <option value="movies">{t('movies_outside_seasons')}</option>
                  )}
                </Select>
              </div>
            )}

            {/* Список файлов */}
            <div id="detail-files" className="space-y-2.5">
              {currentFilesList.map((f, i) => {
                let hasNext = false;
                if (filesData.flat_files && filesData.flat_files.length > 1) {
                  const idx = filesData.flat_files.findIndex((x) => x.id === f.id);
                  hasNext = idx >= 0 && idx < filesData.flat_files.length - 1;
                } else {
                  hasNext = currentFilesList.length > 1 && i < currentFilesList.length - 1;
                }

                const isThisPlaying = playingFileId === f.id;

                return (
                  <div
                    key={f.id}
                    className="file flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3.5 rounded-sm bg-[#090d16] border border-cyan-900/30 hover:border-cyan-500/50 hover:bg-[#0c1220] transition-all duration-150"
                  >
                    <div className="min-w-0 flex-1 pr-2">
                      <div className="flex items-center gap-2 mb-1">
                        <strong className="block text-sm font-medium text-slate-100 truncate">
                          {f.name}
                        </strong>
                        {f.is_watched && (
                          <span className="shrink-0 rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 font-code text-[10px] uppercase text-emerald-300">
                            {t('watched')}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 font-code text-xs text-slate-400">
                        <span>{formatSize(f.length, t)}</span>
                        {Boolean(f.playback_timecode && !f.is_watched) && (
                          <span className="text-cyan-400">
                            Продолжить с {formatTime(f.playback_timecode || 0)}
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        type="button"
                        disabled={markingFileId === f.id}
                        onClick={() => handleToggleWatched(f)}
                        title={f.is_watched ? 'Отметить как непросмотренное' : t('mark_watched')}
                        className={`flex h-8 w-8 items-center justify-center rounded border transition-colors cursor-pointer ${
                          f.is_watched
                            ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20'
                            : 'border-slate-700 text-slate-400 hover:border-cyan-500/50 hover:text-cyan-300'
                        }`}
                      >
                        {markingFileId === f.id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Check className="w-3.5 h-3.5" />
                        )}
                      </button>

                      {hasNext && (
                        <Button
                          variant="secondary"
                          size="sm"
                          icon={<SkipForward className="w-3.5 h-3.5" />}
                          onClick={() => handlePlayNext(f)}
                        >
                          {t('continue')}
                        </Button>
                      )}

                      <Button
                        variant="primary"
                        size="sm"
                        disabled={isThisPlaying}
                        icon={
                          isThisPlaying ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Play className="w-3.5 h-3.5 fill-current" />
                          )
                        }
                        onClick={() => handlePlayFile(f)}
                      >
                        {isThisPlaying ? '…' : t('play')}
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
