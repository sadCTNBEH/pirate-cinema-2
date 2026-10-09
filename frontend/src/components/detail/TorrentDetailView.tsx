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
import { formatSize } from '../../utils/torrentParser';
import { Button, Select, SafeHtmlText } from '../ui/UIComponents';
import { ArrowLeft, Play, SkipForward, RefreshCw, FileVideo, Loader2 } from 'lucide-react';

export const TorrentDetailView: React.FC = () => {
  const { routeParams, goBack, t } = useApp();
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
   * Воспроизведение конкретного файла
   */
  const handlePlayFile = async (file: TorrentFile) => {
    if (!currentHash) return;
    setPlayingFileId(file.id);

    try {
      await API.playFile({
        hash: currentHash,
        file_id: file.id,
        file_name: file.name,
      });
    } catch (err: any) {
      alert(err.message || 'Ошибка запуска плеера MPV');
    } finally {
      setTimeout(() => setPlayingFileId(null), 1500);
    }
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
                      <strong className="block text-sm font-medium text-slate-100 truncate mb-1">
                        {f.name}
                      </strong>
                      <small className="block font-code text-xs text-slate-400">
                        {formatSize(f.length, t)}
                      </small>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
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
