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
import { TorrentFilesResponse, TorrentFile } from '../../types';
import { formatSize } from '../../utils/torrentParser';
import { Button, Select, SafeHtmlText } from '../ui/UIComponents';
import {
  Play,
  SkipForward,
  Maximize2,
  X,
  RefreshCw,
  Loader2,
  Tv,
  Film,
  RotateCcw,
  PictureInPicture2,
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

/**
 * Извлекает номер серии из имени файла для точного сопоставления
 */
function extractEpisodeNumber(name: string): number | null {
  const sMatch = name.match(/S\d+[.\-\s_]*E(\d+)/i);
  if (sMatch) return parseInt(sMatch[1], 10);

  const xMatch = name.match(/\d+x(\d+)/i);
  if (xMatch) return parseInt(xMatch[1], 10);

  const epMatch = name.match(/\b(?:Episode|Ep|E)[.\-\s_]*(\d+)/i);
  if (epMatch) return parseInt(epMatch[1], 10);

  return null;
}

/**
 * Выбирает стартовый видеофайл из структуры торрента с учетом выбранного сезона и серии
 */
function selectInitialFile(
  data: TorrentFilesResponse,
  targetSeason?: string | number,
  targetEpisode?: string | number
): { file: TorrentFile | null; seasonKey: string } {
  if (data.type === 'series' && data.seasons && Object.keys(data.seasons).length > 0) {
    const seasonKeys = Object.keys(data.seasons).sort(
      (a, b) => parseInt(a, 10) - parseInt(b, 10)
    );
    const desiredSeason =
      targetSeason !== undefined &&
      targetSeason !== '' &&
      data.seasons[String(targetSeason)]
        ? String(targetSeason)
        : seasonKeys[0];

    const list = data.seasons[desiredSeason] || [];
    if (list.length === 0) {
      return { file: null, seasonKey: desiredSeason };
    }

    if (targetEpisode !== undefined && targetEpisode !== '') {
      const epNum = Number(targetEpisode);
      if (!isNaN(epNum) && epNum > 0) {
        const byRegex = list.find((f) => extractEpisodeNumber(f.name) === epNum);
        if (byRegex) return { file: byRegex, seasonKey: desiredSeason };
        if (epNum - 1 < list.length) {
          return { file: list[epNum - 1], seasonKey: desiredSeason };
        }
      }
    }

    return { file: list[0], seasonKey: desiredSeason };
  }

  const flat = data.flat_files || data.files || data.movies || [];
  if (flat.length === 0) {
    return { file: null, seasonKey: '1' };
  }

  if (targetEpisode !== undefined && targetEpisode !== '' && flat.length > 1) {
    const epNum = Number(targetEpisode);
    if (!isNaN(epNum) && epNum > 0) {
      const byRegex = flat.find((f: TorrentFile) => extractEpisodeNumber(f.name) === epNum);
      if (byRegex) return { file: byRegex, seasonKey: '1' };
      if (epNum - 1 < flat.length) {
        return { file: flat[epNum - 1], seasonKey: '1' };
      }
    }
  }

  return { file: flat[0], seasonKey: '1' };
}

export const InlinePlayer: React.FC = () => {
  const { activePlayback, closePlayback, togglePip, t } = useApp();

  const [resolvedHash, setResolvedHash] = useState<string>('');
  const [filesData, setFilesData] = useState<TorrentFilesResponse | null>(null);
  const [selectedSeasonKey, setSelectedSeasonKey] = useState<string>('1');
  const [currentFileId, setCurrentFileId] = useState<number | null>(null);
  const [currentFileName, setCurrentFileName] = useState<string>('');

  const [isLoadingFiles, setIsLoadingFiles] = useState<boolean>(false);
  const [pollingAttempt, setPollingAttempt] = useState<number>(1);
  const [isDeadTorrent, setIsDeadTorrent] = useState<boolean>(false);
  const [launchError, setLaunchError] = useState<string | null>(null);
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

  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const videoSlotRef = useRef<HTMLDivElement | null>(null);
  const pollTimerRef = useRef<any>(null);
  const isCancelledRef = useRef<boolean>(false);
  const hasSeenBackendActiveRef = useRef<boolean>(false);
  const lastSentBoundsRef = useRef<{
    x: number;
    y: number;
    w: number;
    h: number;
    fs: boolean;
  } | null>(null);

  /**
   * Вычисление и отправка точных координат видео-слота в нативное окно pywebview
   */
  const syncPlayerBounds = useCallback(() => {
    if (!videoSlotRef.current) return;

    if (wrapperRef.current && wrapperRef.current.offsetParent === null && !isFullscreenRef.current) {
      return;
    }

    // Пока файлы еще грузятся или MPV буферизирует поток — нативное черное окно должно быть скрыто!
    // Иначе оно физически перекрывает HTML-лоадер в окне WebView2.
    if (isLoadingFilesRef.current || isStartingPlaybackRef.current) {
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

  /**
   * Запуск конкретного видеофайла во встроенном MPV
   */
  const launchFileInMpv = useCallback(
    async (hashToPlay: string, fileId: number, fileName: string, startTime?: number) => {
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
        setIsMpvRunning(true);
      } catch (err: any) {
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

    isCancelledRef.current = false;
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);

    setLaunchError(null);
    setIsDeadTorrent(false);
    setIsStartingPlayback(true);
    setPlaybackStatusText('Инициализация воспроизведения...');
    setPollingAttempt(1);

    // Мгновенно синхронизируем геометрию панели под слот
    setTimeout(() => {
      syncPlayerBounds();
      wrapperRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 30);

    let activeHash = activePlayback.hash || '';

    // Проверяем, не запущено ли уже воспроизведение на бэкенде (например, запущено с веб-пульта)
    try {
      const activeStatus = await API.getActivePlayback();
      if (
        activeStatus &&
        activeStatus.active &&
        activeStatus.hash === activeHash &&
        (activePlayback.fileId === undefined || activeStatus.file_id === activePlayback.fileId)
      ) {
        setResolvedHash(activeHash);
        setCurrentFileId(activeStatus.file_id ?? 0);
        setCurrentFileName(activeStatus.file_name || activePlayback.title);
        setIsMpvRunning(true);
        setIsStartingPlayback(false);
        isStartingPlaybackRef.current = false;
        setIsLoadingFiles(false);
        isLoadingFilesRef.current = false;
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
        setFilesData(activePlayback.preloadedFiles);
      } else {
        API.getTorrentFiles(activeHash, activePlayback.title)
          .then((d) => {
            if (!isCancelledRef.current && d) setFilesData(d);
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

    if (isCancelledRef.current) return;

    if (!activeHash) {
      setIsStartingPlayback(false);
      setIsLoadingFiles(false);
      setIsDeadTorrent(true);
      return;
    }

    setResolvedHash(activeHash);

    let attempts = 0;
    const maxAttempts = 30;

    const pollFiles = async () => {
      if (isCancelledRef.current) return;
      attempts++;
      setPollingAttempt(attempts);
      setPlaybackStatusText(`Поиск метаданных в DHT (попытка ${attempts} из 30)...`);

      try {
        const data = await API.getTorrentFiles(activeHash, activePlayback.title);
        if (isCancelledRef.current) return;

        if (
          data &&
          ((data.files && data.files.length > 0) ||
            (data.flat_files && data.flat_files.length > 0))
        ) {
          setFilesData(data);
          setIsLoadingFiles(false);

          const { file, seasonKey } = selectInitialFile(
            data,
            activePlayback.targetSeason,
            activePlayback.targetEpisode
          );
          setSelectedSeasonKey(seasonKey);

          if (file) {
            setPlaybackStatusText('Выбор файла и запуск воспроизведения...');
            await launchFileInMpv(
              activeHash,
              file.id,
              file.name,
              file.playback_timecode || activePlayback.startTime || 0
            );
          }
          return;
        }

        if (attempts < maxAttempts) {
          pollTimerRef.current = setTimeout(pollFiles, 2000);
        } else {
          setIsStartingPlayback(false);
          setIsLoadingFiles(false);
          setIsDeadTorrent(true);
        }
      } catch {
        if (attempts < maxAttempts) {
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

  const activePlaybackKey = activePlayback
    ? `${activePlayback.hash || ''}:${activePlayback.fileId ?? ''}:${activePlayback.magnet || ''}`
    : null;
  const lastStartedKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (!activePlaybackKey) {
      lastStartedKeyRef.current = null;
      lastSentBoundsRef.current = null;
      hasSeenBackendActiveRef.current = false;
      setIsMpvRunning(false);
      setIsStartingPlayback(false);
      isStartingPlaybackRef.current = false;
      setIsLoadingFiles(false);
      isLoadingFilesRef.current = false;
      return;
    }
    // Если сессия с этой же раздачей и файлом уже запущена — не перезапускаем при смене fullscreen!
    if (lastStartedKeyRef.current === activePlaybackKey) {
      return;
    }
    lastStartedKeyRef.current = activePlaybackKey;
    startSession();

    return () => {
      isCancelledRef.current = true;
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, [activePlaybackKey, startSession]);

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
   * Закрытие встроенного плеера с гарантированным сбросом состояний и интервала
   */
  const handleClose = useCallback(async () => {
    hasSeenBackendActiveRef.current = false;
    setIsMpvRunning(false);
    setIsStartingPlayback(false);
    isStartingPlaybackRef.current = false;
    lastStartedKeyRef.current = null;
    lastSentBoundsRef.current = null;
    await closePlayback();
  }, [closePlayback]);

  /**
   * Опрос бэкенда (/api/player/active) для обновления шкалы прогресса, паузы, длительности и автосмены серий
   */
  useEffect(() => {
    if (!activePlayback || !isMpvRunning) return;

    const interval = setInterval(async () => {
      try {
        const status = await API.getActivePlayback();
        if (status.active) {
          hasSeenBackendActiveRef.current = true;
          if (status.file_id !== undefined && status.file_id !== currentFileId) {
            setCurrentFileId(status.file_id);
          }
          if (status.file_name && status.file_name !== currentFileName) {
            setCurrentFileName(status.file_name);
          }
          const isStreamReady =
            Boolean(status.is_ready) ||
            (typeof status.timecode === 'number' && status.timecode > 0) ||
            (!activePlayback?.isOnline && !status.is_online && typeof status.duration === 'number' && status.duration > 0);

          if (isStreamReady) {
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
          if (typeof status.is_fullscreen === 'boolean') {
            if (status.is_fullscreen !== isFullscreenRef.current) {
              lastSentBoundsRef.current = null;
              setIsFullscreen(status.is_fullscreen);
              isFullscreenRef.current = status.is_fullscreen;
              setTimeout(() => syncPlayerBounds(), 30);
              setTimeout(() => syncPlayerBounds(), 100);
              setTimeout(() => syncPlayerBounds(), 250);
            }
          }
        } else if (hasSeenBackendActiveRef.current) {
          // Пользователь закрыл плеер или воспроизведение завершилось
          hasSeenBackendActiveRef.current = false;
          setIsMpvRunning(false);
          closePlayback();
        }
      } catch {}
    }, 500);

    return () => clearInterval(interval);
  }, [activePlayback, isMpvRunning, currentFileId, currentFileName, closePlayback, syncPlayerBounds]);

  const lastFsToggleTimeRef = useRef<number>(0);

  const handleToggleFullscreen = useCallback(
    async (targetFs?: boolean) => {
      const nextVal = targetFs !== undefined ? targetFs : !isFullscreenRef.current;
      if (nextVal === isFullscreenRef.current) {
        return;
      }
      const now = Date.now();
      if (now - lastFsToggleTimeRef.current < 400) {
        return;
      }
      lastFsToggleTimeRef.current = now;
      lastSentBoundsRef.current = null;
      setIsFullscreen(nextVal);
      isFullscreenRef.current = nextVal;
      await API.togglePlayerFullscreen(nextVal);
      setTimeout(() => syncPlayerBounds(), 50);
      setTimeout(() => syncPlayerBounds(), 150);
      setTimeout(() => syncPlayerBounds(), 350);
    },
    [syncPlayerBounds]
  );

  /**
   * Глобальные горячие клавиши (Space, Esc, F, Arrows, M, Q)
   */
  useEffect(() => {
    if (!activePlayback) return;

    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(tag || '') || target?.isContentEditable) return;

      if (e.key === 'Escape') {
        e.preventDefault();
        if (isFullscreenRef.current) {
          handleToggleFullscreen(false);
        }
      } else if (e.key === ' ' || e.code === 'Space') {
        e.preventDefault();
        API.sendPlayerCommand(['cycle', 'pause']);
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        API.sendPlayerCommand(['seek', -10, 'relative']);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        API.sendPlayerCommand(['seek', 10, 'relative']);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        API.sendPlayerCommand(['add', 'volume', 5]);
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        API.sendPlayerCommand(['add', 'volume', -5]);
      } else if (['f', 'F', 'а', 'А'].includes(e.key)) {
        e.preventDefault();
        handleToggleFullscreen();
      } else if (['m', 'M', 'ь', 'Ь'].includes(e.key)) {
        e.preventDefault();
        API.sendPlayerCommand(['cycle', 'mute']);
      } else if (['q', 'Q', 'й', 'Й'].includes(e.key)) {
        e.preventDefault();
        handleClose();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [activePlayback, handleClose, handleToggleFullscreen]);

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
  const nextFile = useMemo((): TorrentFile | null => {
    if (!currentFilesList.length || currentFileId === null) return null;
    const currentIndex = currentFilesList.findIndex((f) => f.id === currentFileId);
    if (currentIndex !== -1 && currentIndex + 1 < currentFilesList.length) {
      return currentFilesList[currentIndex + 1];
    }
    return null;
  }, [currentFilesList, currentFileId]);

  /**
   * Выбор другого файла из выпадающего списка
   */
  const handleSelectFile = (fileId: number) => {
    if (activePlayback?.isOnline || resolvedHash.startsWith('online:')) return;
    const target = currentFilesList.find((f) => f.id === fileId);
    if (!target || !resolvedHash) return;
    launchFileInMpv(resolvedHash, target.id, target.name, target.playback_timecode || 0);
  };

  /**
   * Запуск следующей серии
   */
  const handlePlayNextFile = () => {
    if (activePlayback?.isOnline || resolvedHash.startsWith('online:')) {
      API.playNext({ hash: resolvedHash, file_id: 0 }).catch(() => {});
      return;
    }
    if (!nextFile || !resolvedHash) return;
    launchFileInMpv(resolvedHash, nextFile.id, nextFile.name, 0);
  };

  /**
   * Смена сезона в плеере
   */
  const handleSeasonChange = (sKey: string) => {
    setSelectedSeasonKey(sKey);
    if (!filesData || !filesData.seasons || !filesData.seasons[sKey]) return;
    const list = filesData.seasons[sKey];
    if (list.length > 0 && resolvedHash) {
      launchFileInMpv(resolvedHash, list[0].id, list[0].name, list[0].playback_timecode || 0);
    }
  };

  if (!activePlayback) {
    return null;
  }

  const videoSlotContent = (
    <>
      {isLoadingFiles && (
        <div className="p-8 text-center space-y-4 max-w-md animate-fade-in select-none">
          <div className="relative w-14 h-14 mx-auto flex items-center justify-center">
            <div className="absolute inset-0 rounded-full border-2 border-cyan-500/20 animate-ping" />
            <Loader2 className="w-8 h-8 animate-spin text-cyan-400" />
          </div>
          <div className="space-y-1.5">
            <div className="font-tech text-base text-slate-100 uppercase tracking-wider font-semibold">
              {t('loading_files_dht') || 'Подключение к раздаче (DHT)...'}
            </div>
            <div className="font-sans text-xs text-slate-400">
              Поиск пиров в сети и загрузка метаданных торрента
            </div>
            <div className="font-code text-xs text-cyan-400 mt-1">
              {t('attempt_of', { attempt: pollingAttempt, total: 30 }) ||
                `Попытка ${pollingAttempt} из 30`}
            </div>
          </div>
        </div>
      )}

      {isStartingPlayback && !isLoadingFiles && !launchError && !isDeadTorrent && (
        <div className="p-8 text-center space-y-4 max-w-md animate-fade-in select-none">
          <div className="relative w-14 h-14 mx-auto flex items-center justify-center">
            <div className="absolute inset-0 rounded-full border-2 border-cyan-500/20 animate-ping" />
            <div className="absolute inset-0 rounded-full border-2 border-t-cyan-400 border-r-cyan-400 border-b-transparent border-l-transparent animate-spin" />
            <Film className="w-6 h-6 text-cyan-400" />
          </div>
          <div className="space-y-1.5">
            <div className="font-tech text-base text-slate-100 uppercase tracking-wider font-semibold">
              {playbackStatusText || 'Буферизация видеопотока...'}
            </div>
            {currentFileName && (
              <div className="text-xs text-slate-400 font-mono truncate max-w-sm mx-auto">
                {currentFileName}
              </div>
            )}
            {activePlayback?.startTime && activePlayback.startTime > 0 ? (
              <div className="text-xs text-cyan-300 font-mono">
                Возобновление с {formatTimecode(activePlayback.startTime)}
              </div>
            ) : null}
          </div>
          <div className="flex items-center justify-center gap-2 text-xs text-slate-400 font-tech">
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse shadow-[0_0_6px_#00f0ff]" />
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
            onClick={startSession}
          >
            {t('try_again')}
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
      className="mb-8 p-4 rounded-lg bg-[#070b14] border border-cyan-500/40 shadow-[0_0_25px_rgba(0,240,255,0.12)] space-y-3 animate-fade-in"
    >
      {/* ── Верхняя панель: Заголовок, селекторы сезона/серии и быстрые действия ── */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-2 border-b border-cyan-950/60">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse shadow-[0_0_8px_#00f0ff]" />
          <h3 className="font-tech text-sm font-bold uppercase tracking-wider text-slate-100 truncate">
            {activePlayback.title}
          </h3>
          {currentFileName && currentFileName !== activePlayback.title && (
            <span className="text-xs text-slate-400 font-mono truncate max-w-xs hidden md:inline">
              · {currentFileName}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 ml-auto flex-wrap">
          {/* Выбор сезона (для сериалов) */}
          {seasonsList.length > 0 && (
            <Select
              value={selectedSeasonKey}
              onChange={(e) => handleSeasonChange(e.target.value)}
              className="text-xs py-1 px-2.5 h-8 max-w-[130px] bg-[#060911]"
            >
              {seasonsList.map((s) => (
                <option key={s} value={s}>
                  {t('season')} {s}
                </option>
              ))}
              {filesData?.movies && filesData.movies.length > 0 && (
                <option value="movies">{t('movies')}</option>
              )}
            </Select>
          )}

          {/* Выбор файла / серии внутри раздачи */}
          {currentFilesList.length > 1 && (
            <Select
              value={currentFileId !== null ? String(currentFileId) : ''}
              onChange={(e) => handleSelectFile(Number(e.target.value))}
              className="text-xs py-1 px-2.5 h-8 max-w-[260px] bg-[#060911]"
            >
              {currentFilesList.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name} {f.length ? `(${formatSize(f.length, t)})` : ''}
                </option>
              ))}
            </Select>
          )}

          {/* Следующая серия */}
          {nextFile && (
            <Button
              variant="secondary"
              size="sm"
              icon={<SkipForward className="w-3.5 h-3.5" />}
              onClick={handlePlayNextFile}
              title={nextFile.name}
            >
              {t('continue')}
            </Button>
          )}

          {/* Картинка в картинке (PiP) */}
          <Button
            variant="secondary"
            size="sm"
            icon={<PictureInPicture2 className="w-3.5 h-3.5" />}
            onClick={() => togglePip(true)}
            title="Картинка в картинке (мини-плеер)"
          >
            PiP
          </Button>

          {/* На весь экран */}
          <Button
            variant="secondary"
            size="sm"
            icon={<Maximize2 className="w-3.5 h-3.5" />}
            onClick={() => handleToggleFullscreen(true)}
            title="На весь экран (F)"
          >
            Экран
          </Button>

          {/* Закрыть плеер */}
          <Button
            variant="danger"
            size="sm"
            icon={<X className="w-3.5 h-3.5" />}
            onClick={handleClose}
            title="Закрыть плеер (Q)"
          >
            Закрыть
          </Button>
        </div>
      </div>

      {/* ── Видео-область (16:9 слот для нативного окна MPV) ── */}
      <div
        ref={videoSlotRef}
        className="relative w-full aspect-video max-h-[75vh] bg-black flex items-center justify-center overflow-hidden select-none rounded border border-slate-900"
      >
        {videoSlotContent}
      </div>
    </div>
  );
};
