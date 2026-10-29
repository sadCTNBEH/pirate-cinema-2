/**
 * @file components/player/InlinePlayer.tsx
 * @description Встроенный видеоплеер Pirate Cinema.
 * Отображается прямо на странице раздач/файлов, сдвигая список раздач вниз,
 * синхронизирует нативный контейнер MPV (--wid) с DOM-областью плеера
 * и предоставляет полнофункциональную панель управления воспроизведением.
 */

import React, { useEffect, useState, useRef, useMemo, useCallback } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { canShowNativePlayer, playbackSessionKey, seasonKeyForFile } from '../../services/playerSession';
import { TorrentFilesResponse, TorrentFile } from '../../types';
import { formatSize } from '../../utils/torrentParser';
import { ResponsiveToolbar } from '../ui/ResponsiveToolbar';
import { Button, Select, SafeHtmlText } from '../ui/UIComponents';
import {
  Play,
  SkipForward,
  X,
  RefreshCw,
  Loader2,
  Tv,
  Film,
  RotateCcw,
} from 'lucide-react';

/**
 * Форматирует секунды в строку вида HH:MM:SS или MM:SS
 */
function formatTimecode(seconds: number): string {
  if (!seconds || isNaN(seconds) || seconds < 0) return '00:00';
  const s = Math.floor(seconds);
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  const remSec = s % 60;
  const remMin = m % 60;
  if (h > 0) {
    return `${h}:${remMin < 10 ? '0' : ''}${remMin}:${remSec < 10 ? '0' : ''}${remSec}`;
  }
  return `${remMin < 10 ? '0' : ''}${remMin}:${remSec < 10 ? '0' : ''}${remSec}`;
}

export const InlinePlayer: React.FC = () => {
  const { activePlayback, closePlayback, t, isAnyModalOpen } = useApp();

  const [resolvedHash, setResolvedHash] = useState<string>('');
  const [filesData, setFilesData] = useState<TorrentFilesResponse | null>(null);
  const [selectedSeasonKey, setSelectedSeasonKey] = useState<string>('1');
  const [currentFileId, setCurrentFileId] = useState<number | null>(null);
  const [currentFileName, setCurrentFileName] = useState<string>('');

  const [isLoadingFiles, setIsLoadingFiles] = useState<boolean>(false);
  const [pollingAttempt, setPollingAttempt] = useState<number>(1);
  const [isDeadTorrent, setIsDeadTorrent] = useState<boolean>(false);
  const [choiceIntent, setChoiceIntent] = useState<{season?: number; episode?: number; absolute?: number}>({});
  const [fileChoices, setFileChoices] = useState<TorrentFile[]>([]);
  const [selectionMessage, setSelectionMessage] = useState<string | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<{ timecode: number } | null>(null);
  const [isStreamReady, setIsStreamReady] = useState(false);
  const [isMpvRunning, setIsMpvRunning] = useState<boolean>(false);
  const [isStartingPlayback, setIsStartingPlayback] = useState<boolean>(true);
  const [playbackStatusText, setPlaybackStatusText] = useState<string>('Инициализация воспроизведения...');

  // Полноэкранный режим
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);

  const isFullscreenRef = useRef<boolean>(isFullscreen);
  isFullscreenRef.current = isFullscreen;
  const isStartingPlaybackRef = useRef<boolean>(isStartingPlayback);
  isStartingPlaybackRef.current = isStartingPlayback;
  const isLoadingFilesRef = useRef<boolean>(isLoadingFiles);
  isLoadingFilesRef.current = isLoadingFiles;
  const isAnyModalOpenRef = useRef<boolean>(isAnyModalOpen);
  isAnyModalOpenRef.current = isAnyModalOpen;

  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const videoSlotRef = useRef<HTMLDivElement | null>(null);
  const pollTimerRef = useRef<any>(null);
  const isCancelledRef = useRef<boolean>(false);
  const sessionGeneration = useRef(0);
  const launchGeneration = useRef(0);
  const hasSeenBackendActiveRef = useRef<boolean>(false);
  const lastSentBoundsRef = useRef<{
    x: number;
    y: number;
    w: number;
    h: number;
    fs: boolean;
  } | null>(null);

  const nativePolicy = {requestedHash: activePlayback?.hash || resolvedHash, resolvedHash,
    running: isMpvRunning, ready: isStreamReady, loading: isLoadingFiles,
    starting: isStartingPlayback, blocked: Boolean(selectionMessage || launchError || isDeadTorrent)};
  const nativePolicyRef = useRef(nativePolicy);
  nativePolicyRef.current = nativePolicy;

  /**
   * Вычисление и отправка точных координат видео-слота в нативное окно pywebview
   */
  const syncPlayerBounds = useCallback(() => {
    if (!videoSlotRef.current) return;

    if (isAnyModalOpenRef.current) {
      return;
    }

    if (wrapperRef.current && wrapperRef.current.offsetParent === null && !isFullscreenRef.current) {
      return;
    }

    // Пока файлы еще грузятся или MPV буферизирует поток — нативное черное окно должно быть скрыто!
    // Иначе оно физически перекрывает HTML-лоадер в окне WebView2.
    if (!canShowNativePlayer(nativePolicyRef.current)) {
      lastSentBoundsRef.current = null;
      API.hidePlayerPanel();
      return;
    }

    const rect = videoSlotRef.current.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;

    const fs = isFullscreenRef.current;
    const bx = Math.round(rect.left);
    const by = Math.round(rect.top);
    const bw = Math.round(rect.width);
    const bh = Math.round(rect.height);

    const prev = lastSentBoundsRef.current;
    if (
      prev &&
      prev.x === bx &&
      prev.y === by &&
      prev.w === bw &&
      prev.h === bh &&
      prev.fs === fs
    ) {
      return;
    }

    lastSentBoundsRef.current = { x: bx, y: by, w: bw, h: bh, fs };

    if (fs) {
      API.setPlayerBounds({
        x: 0,
        y: 0,
        width: window.innerWidth,
        height: window.innerHeight,
        viewport_width: window.innerWidth,
        viewport_height: window.innerHeight,
        clip_top: 0,
        clip_left: 0,
        clip_right: window.innerWidth,
        clip_bottom: window.innerHeight,
      });
      return;
    }

    const mainEl = document.getElementById('page-container');
    const mainRect = mainEl
      ? mainEl.getBoundingClientRect()
      : {
          top: 36,
          left: 256,
          right: window.innerWidth,
          bottom: window.innerHeight,
        };

    API.setPlayerBounds({
      x: bx,
      y: by,
      width: bw,
      height: bh,
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight,
      clip_top: Math.max(36, mainRect.top),
      clip_left: Math.max(0, mainRect.left),
      clip_right: mainRect.right,
      clip_bottom: mainRect.bottom,
    });
  }, []);

  useEffect(() => {
    if (!canShowNativePlayer(nativePolicyRef.current)) {
      lastSentBoundsRef.current = null;
      API.hidePlayerPanel();
      setIsFullscreen(false);
      isFullscreenRef.current = false;
    }
  }, [activePlayback?.hash, resolvedHash, isMpvRunning, isStreamReady, isLoadingFiles,
      isStartingPlayback, selectionMessage, launchError, isDeadTorrent]);

  useEffect(() => {
    if (!isAnyModalOpen) {
      lastSentBoundsRef.current = null;
      setTimeout(() => syncPlayerBounds(), 50);
      setTimeout(() => syncPlayerBounds(), 150);
    }
  }, [isAnyModalOpen, syncPlayerBounds]);

  /**
   * Запуск конкретного видеофайла во встроенном MPV
   */
  const launchFileInMpv = useCallback(
    async (hashToPlay: string, fileId: number, fileName: string, startTime?: number) => {
      const generation = sessionGeneration.current;
      const launch = ++launchGeneration.current;
      setIsStreamReady(false);
      setIsMpvRunning(false);
      setLaunchError(null);
      setCurrentFileId(fileId);
      setCurrentFileName(fileName);
      setIsStartingPlayback(true);
      isStartingPlaybackRef.current = true;
      setPlaybackStatusText('Запуск видеоплеера MPV и буферизация потока...');
      hasSeenBackendActiveRef.current = false;

      // Скрываем нативное черное окно, пока видео буферизируется
      API.hidePlayerPanel();

      try {
        await API.playFile({
          hash: hashToPlay,
          file_id: fileId,
          file_name: fileName,
          start_time: startTime,
        });
        if (generation !== sessionGeneration.current || launch !== launchGeneration.current) return;
        setIsMpvRunning(true);
      } catch (err: any) {
        if (generation !== sessionGeneration.current || launch !== launchGeneration.current) return;
        setIsStartingPlayback(false);
        isStartingPlaybackRef.current = false;
        setIsMpvRunning(false);
        await API.hidePlayerPanel();
        setLaunchError(err?.message || 'Ошибка запуска плеера MPV');
      }
    },
    []
  );

  /**
   * Инициализация раздачи / файла при открытии или смене activePlayback
   */
  const startSession = useCallback(async () => {
    if (!activePlayback) return;
    const generation = ++sessionGeneration.current;

    isCancelledRef.current = false;
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);

    setIsStreamReady(false);
    setIsMpvRunning(false);
    setIsFullscreen(false);
    isFullscreenRef.current = false;
    isStartingPlaybackRef.current = true;
    setLaunchError(null);
    setFileChoices([]);
    setSelectionMessage(null);
    setCurrentFileId(null);
    setSelectedSeasonKey(String(activePlayback.targetSeason ?? 1));
    setCurrentFileName('');
    setRecovery(null);
    hasSeenBackendActiveRef.current = false;
    setIsDeadTorrent(false);
    setIsStartingPlayback(true);
    setPlaybackStatusText('Инициализация воспроизведения...');
    setPollingAttempt(1);

    // Мгновенно синхронизируем геометрию панели под слот
    setTimeout(() => {
      syncPlayerBounds();
      wrapperRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 30);

    await API.hidePlayerPanel();
    if (generation !== sessionGeneration.current) return;

    let activeHash = activePlayback.hash || '';
    const applyFiles = (data: TorrentFilesResponse) => {
      if (generation !== sessionGeneration.current) return;
      setFilesData(data);
      setSelectedSeasonKey(seasonKeyForFile(data, activePlayback.fileId, activePlayback.targetSeason));
    };

    // Проверяем, не запущено ли уже воспроизведение на бэкенде (например, запущено с веб-пульта)
    try {
      const activeStatus = await API.getActivePlayback();
      if (generation !== sessionGeneration.current) return;
      if (
        activeStatus &&
        activeStatus.active &&
        activeStatus.hash === activeHash &&
        (activePlayback.fileId === undefined && activePlayback.targetSeason === undefined && activePlayback.targetEpisode === undefined || activeStatus.file_id === activePlayback.fileId)
      ) {
        setResolvedHash(activeHash);
        setCurrentFileId(activeStatus.file_id ?? 0);
        setCurrentFileName(activeStatus.file_name || activePlayback.title);
        setIsMpvRunning(true);
        setIsStreamReady(Boolean(activeStatus.is_ready));
        setIsStartingPlayback(!activeStatus.is_ready);
        isStartingPlaybackRef.current = !activeStatus.is_ready;
        setIsLoadingFiles(false);
        isLoadingFilesRef.current = false;
        if (!activePlayback.isOnline && !activeHash.startsWith('online:')) {
          if (activePlayback.preloadedFiles) applyFiles(activePlayback.preloadedFiles);
          else API.getTorrentFiles(activeHash, activePlayback.title).then(data => {
            applyFiles(data);
          }).catch(() => {});
        }
        setTimeout(() => syncPlayerBounds(), 50);
        return;
      }
    } catch {}

    // 0. Если это онлайн-видео (HLS / Rutube / поток), воспроизведение уже запущено через API
    if (activePlayback.isOnline || activeHash.startsWith('online:')) {
      setResolvedHash(activeHash);
      setCurrentFileName(activePlayback.fileName || activePlayback.title);
      setCurrentFileId(0);
      setIsLoadingFiles(false);
      isLoadingFilesRef.current = false;
      setIsStartingPlayback(true);
      isStartingPlaybackRef.current = true;
      setPlaybackStatusText('Буферизация онлайн-видео...');
      setFilesData({
        type: 'movie',
        movies: [{ id: 0, name: activePlayback.fileName || activePlayback.title, length: 0 }],
        flat_files: [{ id: 0, name: activePlayback.fileName || activePlayback.title, length: 0 }],
      });
      setIsMpvRunning(true);
      return;
    }

    // 1. Если передан конкретный fileId и fileName (например, из "Продолжить просмотр" или списка файлов)
    if (
      activeHash &&
      activePlayback.fileId !== undefined &&
      activePlayback.fileName &&
      !activePlayback.magnet
    ) {
      setResolvedHash(activeHash);
      setPlaybackStatusText('Запуск видеофайла и подготовка потока...');
      if (activePlayback.preloadedFiles) {
        applyFiles(activePlayback.preloadedFiles);
      } else {
        API.getTorrentFiles(activeHash, activePlayback.title)
          .then((d) => {
            if (!isCancelledRef.current && d) applyFiles(d);
          })
          .catch(() => {});
      }
      setIsLoadingFiles(false);
      await launchFileInMpv(
        activeHash,
        activePlayback.fileId,
        activePlayback.fileName,
        activePlayback.startTime
      );
      return;
    }

    // 2. Иначе подключаемся к раздаче (DHT) и получаем список файлов
    setIsMpvRunning(false);
    await API.hidePlayerPanel();
    setIsLoadingFiles(true);
    setFilesData(null);
    setPlaybackStatusText('Подключение к торрент-сети (DHT)...');

    if (activePlayback.magnet) {
      try {
        setPlaybackStatusText('Добавление magnet-ссылки в TorrServer...');
        const added = await API.addTorrent(activePlayback.magnet, activePlayback.title);
        if (added && added.hash) {
          activeHash = added.hash;
        }
        await new Promise((r) => setTimeout(r, 1500));
      } catch (err) {
        console.warn('Ошибка добавления magnet в TorrServer:', err);
      }
    }

    if (isCancelledRef.current || generation !== sessionGeneration.current) return;

    if (!activeHash) {
      setIsStartingPlayback(false);
      setIsLoadingFiles(false);
      setIsDeadTorrent(true);
      return;
    }

    setResolvedHash(activeHash);

    let attempts = 0;
    const maxAttempts = 30;
    const deadline = Date.now() + 60000;

    const pollFiles = async () => {
      if (isCancelledRef.current || generation !== sessionGeneration.current) return;
      if (Date.now() >= deadline) {
        setIsLoadingFiles(false); setIsStartingPlayback(false);
        setIsDeadTorrent(true);
        return;
      }
      attempts++;
      setPollingAttempt(attempts);
      setPlaybackStatusText(`Поиск метаданных в DHT (попытка ${attempts} из 30)...`);

      try {
        const data = await API.getTorrentFiles(activeHash, activePlayback.title, { signal: AbortSignal.timeout(Math.max(1, Math.min(8000, deadline - Date.now()))) });
        if (isCancelledRef.current || generation !== sessionGeneration.current) return;

        if (
          data &&
          (data.metadata_ready || (data.files && data.files.length > 0) ||
            (data.flat_files && data.flat_files.length > 0))
        ) {
          setFilesData(data);
          setIsLoadingFiles(false);

          setChoiceIntent({season: activePlayback.targetSeason === undefined ? undefined : Number(activePlayback.targetSeason), episode: activePlayback.targetEpisode === undefined ? undefined : Number(activePlayback.targetEpisode), absolute: activePlayback.absoluteEpisode});
          const selection = await API.selectTorrentFile({
            hash: activeHash,
            season: activePlayback.targetSeason === undefined ? undefined : Number(activePlayback.targetSeason),
            episode: activePlayback.targetEpisode === undefined ? undefined : Number(activePlayback.targetEpisode),
            absolute: activePlayback.absoluteEpisode,
            release_title: activePlayback.title,
            media_id: activePlayback.mediaId,
          });
          if (isCancelledRef.current || generation !== sessionGeneration.current) return;
          const file = selection.file ? {...(data.flat_files || data.files || []).find((f: TorrentFile) => f.id === selection.file?.id), ...selection.file} : null;
          setSelectedSeasonKey(String(activePlayback.targetSeason ?? file?.season ?? 1));
          if (!file) {
            setIsStartingPlayback(false);
            setFileChoices(selection.candidates.map(f => ({...(data.flat_files || data.files || []).find((old: TorrentFile) => old.id === f.id), ...f})));
            setSelectionMessage(selection.reason);
          }

          if (file) {
            setPlaybackStatusText('Выбор файла и запуск воспроизведения...');
            await launchFileInMpv(
              activeHash,
              file.id,
              file.name,
              activePlayback.startTime ?? (file.playback_timecode || undefined)
            );
          }
          return;
        }

        if (attempts < maxAttempts && Date.now() < deadline) {
          pollTimerRef.current = setTimeout(pollFiles, 2000);
        } else {
          setIsStartingPlayback(false);
          setIsLoadingFiles(false);
          setIsDeadTorrent(true);
        }
      } catch {
        if (attempts < maxAttempts && Date.now() < deadline) {
          pollTimerRef.current = setTimeout(pollFiles, 2000);
        } else {
          setIsStartingPlayback(false);
          setIsLoadingFiles(false);
          setIsDeadTorrent(true);
        }
      }
    };

    pollFiles();
  }, [activePlayback, launchFileInMpv, syncPlayerBounds]);

  const activePlaybackKey = playbackSessionKey(activePlayback);
  const startSessionRef = useRef(startSession);
  startSessionRef.current = startSession;
  useEffect(() => {
    if (activePlaybackKey) {
      void startSessionRef.current();
    } else {
      setIsMpvRunning(false);
      setIsStreamReady(false);
      setIsStartingPlayback(false);
      setIsLoadingFiles(false);
      isStartingPlaybackRef.current = false;
      isLoadingFilesRef.current = false;
      API.hidePlayerPanel();
    }
    return () => {
      isCancelledRef.current = true;
      sessionGeneration.current++;
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
      API.hidePlayerPanel();
    };
  }, [activePlaybackKey]);

  /**
   * Синхронизация координат нативной панели MPV при скролле и ресайзе (с троттлингом)
   */
  useEffect(() => {
    if (!activePlayback) {
      lastSentBoundsRef.current = null;
      API.hidePlayerPanel();
      return;
    }

    syncPlayerBounds();
    const tId = setTimeout(() => syncPlayerBounds(), 80);

    let inFlight = false;
    const onScrollOrResize = () => {
      if (inFlight) return;
      inFlight = true;
      requestAnimationFrame(() => {
        inFlight = false;
        syncPlayerBounds();
      });
    };

    window.addEventListener('resize', onScrollOrResize, { passive: true });
    window.addEventListener('scroll', onScrollOrResize, { passive: true });
    const mainEl = document.getElementById('page-container');
    if (mainEl) {
      mainEl.addEventListener('scroll', onScrollOrResize, { passive: true });
    }

    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => {
        onScrollOrResize();
      });
      if (videoSlotRef.current) ro.observe(videoSlotRef.current);
      if (mainEl) ro.observe(mainEl);
    }

    return () => {
      clearTimeout(tId);
      window.removeEventListener('resize', onScrollOrResize);
      window.removeEventListener('scroll', onScrollOrResize);
      if (mainEl) {
        mainEl.removeEventListener('scroll', onScrollOrResize);
      }
      if (ro) ro.disconnect();
    };
  }, [activePlayback, syncPlayerBounds]);

  /**
   * Опрос бэкенда (/api/player/active) для обновления шкалы прогресса, паузы, длительности и автосмены серий
   */
  useEffect(() => {
    if (!activePlayback || !isMpvRunning) return;

    const generation = sessionGeneration.current;
    const launch = launchGeneration.current;
    const interval = setInterval(async () => {
      try {
        const status = await API.getActivePlayback();
        if (generation !== sessionGeneration.current || launch !== launchGeneration.current) return;
        window.dispatchEvent(new CustomEvent('cinema-continuation-state', { detail: status }));
        if (status.active && status.hash !== resolvedHash) return;
        if (status.active) {
          hasSeenBackendActiveRef.current = true;
          if (status.file_id !== undefined && status.file_id !== currentFileId) {
            setCurrentFileId(status.file_id);
          }
          if (status.file_name && status.file_name !== currentFileName) {
            setCurrentFileName(status.file_name);
          }
          const streamReady = Boolean(status.is_ready);
          setIsStreamReady(streamReady);
          if (streamReady) {
            if (isStartingPlaybackRef.current) {
              setIsStartingPlayback(false);
              isStartingPlaybackRef.current = false;
              lastSentBoundsRef.current = null;
              // Видео начало воспроизводиться! Теперь плавно показываем нативное окно поверх слота
              setTimeout(() => syncPlayerBounds(), 50);
              setTimeout(() => syncPlayerBounds(), 200);
              setTimeout(() => syncPlayerBounds(), 500);
            }
          }
          if (streamReady && typeof status.is_fullscreen === 'boolean') {
            if (status.is_fullscreen !== isFullscreenRef.current) {
              lastSentBoundsRef.current = null;
              setIsFullscreen(status.is_fullscreen);
              isFullscreenRef.current = status.is_fullscreen;
              setTimeout(() => syncPlayerBounds(), 30);
              setTimeout(() => syncPlayerBounds(), 100);
              setTimeout(() => syncPlayerBounds(), 250);
            }
          }
        } else if (status.failure) {
          hasSeenBackendActiveRef.current = false;
          setIsMpvRunning(false);
          setIsStartingPlayback(false);
          isStartingPlaybackRef.current = false;
          setIsFullscreen(false);
          isFullscreenRef.current = false;
          setLaunchError(status.failure.message);
          setRecovery(status.failure.can_resume ? { timecode: status.failure.timecode } : null);
          API.hidePlayerPanel();
        } else if (hasSeenBackendActiveRef.current) {
          // Пользователь закрыл плеер или воспроизведение завершилось
          hasSeenBackendActiveRef.current = false;
          setIsMpvRunning(false);
          closePlayback();
        }
      } catch {}
    }, 500);

    return () => clearInterval(interval);
  }, [activePlaybackKey, resolvedHash, isMpvRunning, currentFileId, currentFileName, closePlayback, syncPlayerBounds]);

  /**
   * Список сезонов (если раздача — сериал)
   */
  const seasonsList = useMemo(() => {
    if (!filesData || filesData.type !== 'series' || !filesData.seasons) return [];
    return Object.keys(filesData.seasons).sort((a, b) => parseInt(a, 10) - parseInt(b, 10));
  }, [filesData]);

  /**
   * Список файлов текущего выбранного сезона или всей раздачи
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

  /**
   * Поиск следующего файла для кнопки "Продолжить"
   */
  const nextFile = currentFileId !== null && isMpvRunning ? {name: 'Следующая серия'} : null;

  /**
   * Выбор другого файла из выпадающего списка
   */
  const handleSelectFile = (fileId: number) => {
    if (activePlayback?.isOnline || resolvedHash.startsWith('online:')) return;
    const target = currentFilesList.find((f) => f.id === fileId);
    if (!target || !resolvedHash) return;
    launchFileInMpv(resolvedHash, target.id, target.name, target.playback_timecode || undefined);
  };

  /**
   * Запуск следующей серии
   */
  const handlePlayNextFile = () => {
    if (activePlayback?.isOnline || resolvedHash.startsWith('online:')) {
      API.playNext({ hash: resolvedHash, file_id: 0 }).catch(() => {});
      return;
    }
    if (currentFileId === null || !resolvedHash) return;
    API.playNext({hash: resolvedHash, file_id: currentFileId}).catch((err) => setLaunchError(err.message));
  };

  // All input devices use the same player actions; no independent key listener.
  useEffect(() => {
    const onAction = (event: Event) => {
      const action = (event as CustomEvent).detail;
      if (action === 'episodeNext') handlePlayNextFile();
      if (action === 'episodePrev' && currentFileId !== null) {
        const index = currentFilesList.findIndex(file => file.id === currentFileId);
        if (index > 0) handleSelectFile(currentFilesList[index - 1].id);
      }
    };
    window.addEventListener('cinema-player-action', onAction);
    return () => window.removeEventListener('cinema-player-action', onAction);
  });

  /**
   * Смена сезона в плеере
   */
  const handleSeasonChange = (sKey: string) => {
    setSelectedSeasonKey(sKey);
    if (!filesData || !filesData.seasons || !filesData.seasons[sKey]) return;
    if (!resolvedHash) return;
    setChoiceIntent({season: Number(sKey)});
    API.selectTorrentFile({hash: resolvedHash, season: Number(sKey)}).then(selection => {
      setFileChoices(selection.candidates);
      setSelectionMessage(selection.reason);
    }).catch(err => setLaunchError(err.message));

  };

  if (!activePlayback) {
    return null;
  }

  const recoverPlayback = async () => {
    setLaunchError(null);
    setIsStartingPlayback(true);
    isStartingPlaybackRef.current = true;
    API.hidePlayerPanel();
    try {
      await API.recoverPlayback();
      setRecovery(null);
      setIsMpvRunning(true);
    } catch (error) {
      setIsStartingPlayback(false);
      isStartingPlaybackRef.current = false;
      setLaunchError(error instanceof Error ? error.message : 'Не удалось восстановить просмотр');
    }
  };

  const videoSlotContent = (
    <>
      {(isLoadingFiles || isStartingPlayback || launchError || isDeadTorrent) && (
        <button
          type="button"
          onClick={() => closePlayback()}
          aria-label="Закрыть плеер"
          title="Закрыть плеер"
          className="absolute top-3 right-3 z-10 rounded p-2 text-film-muted hover:bg-film-surface hover:text-film-text focus-visible:outline focus-visible:outline-film-accent"
        >
          <X className="w-4 h-4" />
        </button>
      )}
      {isLoadingFiles && (
        <div className="p-8 text-center space-y-4 max-w-md animate-fade-in select-none">
          <div className="relative w-14 h-14 mx-auto flex items-center justify-center">
            <Loader2 className="w-8 h-8 animate-spin text-film-accent" />
          </div>
          <div className="space-y-1.5">
            <div className="font-sans text-base text-film-text font-semibold">
              {t('loading_files_dht') || 'Подключение к раздаче (DHT)...'}
            </div>
            <div className="font-sans text-xs text-film-muted">
              Поиск пиров в сети и загрузка метаданных торрента
            </div>
            <div className="font-sans text-xs text-film-accent mt-1">
              {t('attempt_of', { attempt: pollingAttempt, total: 30 }) ||
                `Попытка ${pollingAttempt} из 30`}
            </div>
          </div>
        </div>
      )}

      {isStartingPlayback && !isLoadingFiles && !launchError && !isDeadTorrent && (
        <div className="p-8 text-center space-y-4 max-w-md animate-fade-in select-none">
          <div className="relative w-14 h-14 mx-auto flex items-center justify-center">
            <div className="absolute inset-0 rounded-full border-2 border-t-cyan-400 border-r-cyan-400 border-b-transparent border-l-transparent animate-spin" />
            <Film className="w-6 h-6 text-film-accent" />
          </div>
          <div className="space-y-1.5">
            <div className="font-sans text-base text-film-text font-semibold">
              {playbackStatusText || 'Буферизация видеопотока...'}
            </div>
            {currentFileName && (
              <div className="text-xs text-film-muted font-mono truncate max-w-sm mx-auto">
                {currentFileName}
              </div>
            )}
            {activePlayback?.startTime && activePlayback.startTime > 0 ? (
              <div className="text-xs text-film-accent font-mono">
                Возобновление с {formatTimecode(activePlayback.startTime)}
              </div>
            ) : null}
          </div>
          <div className="flex items-center justify-center gap-2 text-xs text-film-muted font-sans">
            <span className="w-2 h-2 rounded-full bg-film-hover animate-pulse" />
            <span>TorrServer загружает фрагменты из P2P-сети...</span>
          </div>
        </div>
      )}

      {isDeadTorrent && !isLoadingFiles && (
        <div className="p-8 text-center space-y-4 max-w-md animate-fade-in">
          <div className="text-rose-300 font-sans text-sm">
            <SafeHtmlText text={t('dead_torrent_warning')} />
          </div>
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw className="w-4 h-4" />}
            onClick={startSession}
          >
            {t('try_again')}
          </Button>
        </div>
      )}

      {launchError && !isLoadingFiles && (
        <div className="p-8 text-center space-y-4 max-w-md animate-fade-in">
          <div className="text-rose-400 font-sans text-sm">{launchError}</div>
          <Button
            variant="secondary"
            size="sm"
            icon={<Play className="w-4 h-4" />}
            onClick={recovery ? recoverPlayback : startSession}
          >
            {recovery ? `Продолжить с ${formatTimecode(recovery.timecode)}` : t('try_again')}
          </Button>
        </div>
      )}
    </>
  );

  if (isFullscreen) {
    return (
      <div
        ref={wrapperRef}
        id="inline-player-fullscreen-container"
        className="fixed inset-0 z-50 bg-black overflow-hidden select-none animate-fade-in"
      >
        {/* Видео занимает 100% экрана без полос по бокам */}
        <div
          ref={videoSlotRef}
          className="w-full h-full bg-black relative flex items-center justify-center overflow-hidden"
        >
          {videoSlotContent}
        </div>
      </div>
    );
  }

  return (
    <div
      ref={wrapperRef}
      id="inline-player-container"
      className="ui-inline-player mb-8 space-y-3"
    >
      {/* ── Верхняя панель: Заголовок, селекторы сезона/серии и быстрые действия ── */}
      <div className="player-responsive-heading pb-2 border-b border-film-line">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-2 h-2 rounded-full bg-film-hover animate-pulse" />
          <h3 className="font-sans text-sm font-semibold text-film-text truncate">
            {activePlayback.title}
          </h3>
          {currentFileName && currentFileName !== activePlayback.title && (
            <span className="text-xs text-film-muted font-mono truncate max-w-xs hidden md:inline">
              · {currentFileName}
            </span>
          )}
        </div>

        <ResponsiveToolbar className="player-toolbar-actions" label="Серии плеера" items={[
seasonsList.length > 0 ? { id: 'season', priority: 60, content: (<Select
              value={selectedSeasonKey}
              onChange={(e) => handleSeasonChange(e.target.value)}
              className="text-xs py-1 px-2.5 h-8 max-w-[130px] bg-film-base"
            >
              {seasonsList.map((s) => (
                <option key={s} value={s}>
                  {t('season')} {s}
                </option>
              ))}
              {filesData?.movies && filesData.movies.length > 0 && (
                <option value="movies">{t('movies')}</option>
              )}
            </Select>) } : null,
currentFilesList.length > 1 ? { id: 'episode', priority: 40, content: (<Select
              value={currentFileId !== null ? String(currentFileId) : ''}
              onChange={(e) => handleSelectFile(Number(e.target.value))}
              className="text-xs py-1 px-2.5 h-8 max-w-[260px] bg-film-base"
            >
              {currentFilesList.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name} {f.length ? `(${formatSize(f.length, t)})` : ''}
                </option>
              ))}
            </Select>) } : null,
nextFile ? { id: 'next', priority: 100, content: (<Button
              variant="secondary"
              size="sm"
              icon={<SkipForward className="w-3.5 h-3.5" />}
              onClick={handlePlayNextFile}
              title={nextFile.name}
            >
              {t('continue')}
            </Button>) } : null
        ].filter(item => item !== null)} />
      </div>

      {selectionMessage && <div className="space-y-2" role="status">
        <p className="text-sm text-film-text">{selectionMessage}</p>
        <div className="max-h-64 overflow-y-auto space-y-2" aria-label="Выбор видеофайла">
          {fileChoices.map(file => <button type="button" key={file.id}
            className="w-full text-left p-3 border border-film-line rounded-sm hover:bg-film-base focus-visible:outline-2 focus-visible:outline-film-accent"
            onClick={async () => {
              const generation = sessionGeneration.current;
              const launch = launchGeneration.current;
              try {
                const selection = await API.selectTorrentFile({hash: resolvedHash,
                  ...choiceIntent, release_title: activePlayback.title, file_id: file.id});
                if (generation !== sessionGeneration.current || launch !== launchGeneration.current || !selection.file) return;
                setSelectionMessage(null); setFileChoices([]);
                await launchFileInMpv(resolvedHash, file.id, file.name, file.playback_timecode || undefined);
              } catch (err: any) {
                if (generation === sessionGeneration.current && launch === launchGeneration.current) setLaunchError(err.message);
              }
            }}>
            <span className="block break-words text-sm">{file.path || file.name}</span>
            <span className="text-xs text-film-muted">{formatSize(file.length, t)}{file.season != null ? ` · Сезон ${file.season}` : ''}{file.episode != null ? ` · Серия ${file.episode}` : ''}</span>
          </button>)}
        </div>
        <Button variant="secondary" onClick={closePlayback}>Выбрать другую раздачу</Button>
      </div>}

      {/* ── Видео-область (16:9 слот для нативного окна MPV) ── */}
      <div
        ref={videoSlotRef}
        className="relative w-full aspect-video max-h-[75vh] bg-black flex items-center justify-center overflow-hidden select-none rounded border border-film-line"
      >
        {videoSlotContent}
      </div>
    </div>
  );
};
