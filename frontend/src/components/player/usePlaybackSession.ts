import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { API } from '../../services/api';
import { playbackSessionKey, seasonKeyForFile } from '../../services/playerSession';
import type { TorrentIntent } from '../../services/automaticTorrent';
import type { ActivePlaybackState, TorrentFile, TorrentFilesResponse } from '../../types';
import { createPlaybackScope, isOnlinePlayback, pollActivePlayback, preparePlayback } from './playbackSessionFlow';

const INITIAL_STATUS = 'Инициализация воспроизведения...';
const STREAM_START_TIMEOUT_MESSAGE = 'Видеопоток не запустился вовремя. Попробуйте другую раздачу.';
type FileChoice = { intent: TorrentIntent; candidates: TorrentFile[]; message: string };
type Session = ReturnType<typeof createPlaybackScope>;

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message || fallback : fallback;
}

export function usePlaybackSession(
  activePlayback: ActivePlaybackState | null,
  closePlayback: () => void,
) {
  const [resolvedHash, setResolvedHash] = useState('');
  const [filesData, setFilesData] = useState<TorrentFilesResponse | null>(null);
  const [selectedSeasonKey, setSelectedSeasonKey] = useState('1');
  const [currentFileId, setCurrentFileId] = useState<number | null>(null);
  const [currentFileName, setCurrentFileName] = useState('');
  const [isLoadingFiles, setIsLoadingFiles] = useState(false);
  const [pollingAttempt, setPollingAttempt] = useState(1);
  const [isDeadTorrent, setIsDeadTorrent] = useState(false);
  const [choice, setChoice] = useState<FileChoice | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<{ timecode: number } | null>(null);
  const [isStreamReady, setIsStreamReady] = useState(false);
  const [isEmbedded, setIsEmbedded] = useState(false);
  const [isMpvRunning, setIsMpvRunning] = useState(false);
  const [isStartingPlayback, setIsStartingPlayback] = useState(true);
  const [playbackStatusText, setPlaybackStatusText] = useState(INITIAL_STATUS);
  const [backendFullscreen, setBackendFullscreen] = useState(false);
  const [sessionRevision, setSessionRevision] = useState(0);

  // The session object identifies a request or retry. Launch and selection counters
  // also invalidate work when switching files within the same release.
  const sessionRef = useRef<Session | null>(null);
  const playbackRef = useRef(activePlayback);
  playbackRef.current = activePlayback;
  const sessionKey = playbackSessionKey(activePlayback);
  const launchGeneration = sessionRef.current?.launch ?? 0;

  const launchFile = useCallback(async (session: Session, hash: string, id: number, name: string, startTime?: number) => {
    const launch = session.nextLaunch();
    const isCurrent = () => session.isCurrent(launch);
    session.seenActive = false;
    setIsStreamReady(false);
    setIsEmbedded(false);
    setIsMpvRunning(false);
    setBackendFullscreen(false);
    setLaunchError(null);
    setCurrentFileId(id);
    setCurrentFileName(name);
    setIsStartingPlayback(true);
    setPlaybackStatusText('Запуск видеоплеера MPV и буферизация потока...');
    void API.hidePlayerPanel();

    try {
      await API.playFile({ hash, file_id: id, file_name: name, start_time: startTime });
      if (isCurrent()) setIsMpvRunning(true);
    } catch (error) {
      if (!isCurrent()) return;
      setIsStartingPlayback(false);
      setIsMpvRunning(false);
      void API.hidePlayerPanel();
      setLaunchError(errorMessage(error, 'Ошибка запуска плеера MPV'));
    }
  }, []);

  const startSession = useCallback(async () => {
    const playback = playbackRef.current;
    if (!playback) return;

    sessionRef.current?.dispose();
    const session = createPlaybackScope();
    sessionRef.current = session;
    const { signal } = session;
    setSessionRevision(revision => revision + 1);
    setResolvedHash('');
    setFilesData(null);
    setIsLoadingFiles(false);
    setIsStreamReady(false);
    setIsEmbedded(false);
    setIsMpvRunning(false);
    setBackendFullscreen(false);
    setLaunchError(null);
    setChoice(null);
    setCurrentFileId(null);
    setSelectedSeasonKey(String(playback.targetSeason ?? 1));
    setCurrentFileName('');
    setRecovery(null);
    setIsDeadTorrent(false);
    setIsStartingPlayback(true);
    setPlaybackStatusText(INITIAL_STATUS);
    setPollingAttempt(1);

    await API.hidePlayerPanel();
    if (signal.aborted) return;
    const result = await preparePlayback(API, playback, signal, {
      files: data => {
        setFilesData(data);
        setSelectedSeasonKey(seasonKeyForFile(data, playback.fileId, playback.targetSeason));
      },
      loading: (message, attempt) => {
        setPlaybackStatusText(message);
        if (attempt === undefined) setIsLoadingFiles(true);
        else setPollingAttempt(attempt);
      },
      selecting: data => {
        setFilesData(data);
        setIsLoadingFiles(false);
      },
    });
    if (signal.aborted || !result) return;
    setIsLoadingFiles(false);
    if (result.kind === 'dead') {
      setIsStartingPlayback(false);
      setIsDeadTorrent(true);
      return;
    }
    if (result.kind === 'error') {
      setIsStartingPlayback(false);
      setLaunchError(result.message);
      return;
    }

    setResolvedHash(result.hash);
    if (result.kind === 'active') {
      setCurrentFileId(result.id);
      setCurrentFileName(result.name);
      setIsMpvRunning(true);
      setIsStreamReady(result.ready);
      if (result.embedded !== undefined) setIsEmbedded(result.embedded);
      setIsStartingPlayback(!result.ready);
      if (result.onlinePending) {
        setPlaybackStatusText('Буферизация онлайн-видео...');
      }
    } else if (result.kind === 'launch') {
      if (result.seasonKey !== undefined) setSelectedSeasonKey(result.seasonKey);
      await launchFile(session, result.hash, result.id, result.name, result.startTime);
    } else {
      setSelectedSeasonKey(String(playback.targetSeason ?? 1));
      setIsStartingPlayback(false);
      setChoice({ intent: result.intent, candidates: result.selection.candidates, message: result.selection.reason });
    }
  }, [launchFile]);

  useLayoutEffect(() => {
    if (sessionKey) {
      void startSession();
    } else {
      setIsMpvRunning(false);
      setIsStreamReady(false);
      setIsEmbedded(false);
      setIsStartingPlayback(false);
      setIsLoadingFiles(false);
    }
    return () => {
      sessionRef.current?.dispose();
      sessionRef.current = null;
    };
  }, [sessionKey, startSession]);

  useEffect(() => {
    const session = sessionRef.current;
    if (!sessionKey || !session || !isMpvRunning) return;
    const isCurrent = () => session.isCurrent(launchGeneration);
    return pollActivePlayback(() => API.getActivePlayback(), status => {
      window.dispatchEvent(new CustomEvent('cinema-continuation-state', { detail: status }));
      if (!isCurrent()) return;
      if (status.active && status.hash !== resolvedHash) return;
      if (status.active) {
        session.seenActive = true;
        if (typeof status.is_embedded === 'boolean') setIsEmbedded(status.is_embedded);
        if (status.file_id !== undefined) setCurrentFileId(status.file_id);
        if (status.file_name) setCurrentFileName(status.file_name);
        const streamReady = Boolean(status.is_ready);
        setIsStreamReady(streamReady);
        if (streamReady) {
          setLaunchError(error => error === STREAM_START_TIMEOUT_MESSAGE ? null : error);
          setIsStartingPlayback(false);
          if (typeof status.is_fullscreen === 'boolean') setBackendFullscreen(status.is_fullscreen);
        } else {
          setBackendFullscreen(false);
        }
      } else if (status.failure) {
        session.seenActive = false;
        setIsMpvRunning(false);
        setIsStartingPlayback(false);
        setBackendFullscreen(false);
        setLaunchError(status.failure.message);
        setRecovery(status.failure.can_resume ? { timecode: status.failure.timecode } : null);
        void API.hidePlayerPanel();
      } else if (session.seenActive) {
        session.seenActive = false;
        setIsMpvRunning(false);
        closePlayback();
      }
    }, isCurrent);
  }, [sessionKey, sessionRevision, launchGeneration, resolvedHash, isMpvRunning, closePlayback]);

  useEffect(() => {
    if (!isMpvRunning || !isStartingPlayback || isStreamReady) return;
    const timer = setTimeout(() => {
      setIsStartingPlayback(false);
      setLaunchError(STREAM_START_TIMEOUT_MESSAGE);
    }, 45000);
    return () => clearTimeout(timer);
  }, [sessionKey, currentFileId, isMpvRunning, isStartingPlayback, isStreamReady]);

  const seasonsList = useMemo(() => {
    if (filesData?.type !== 'series' || !filesData.seasons) return [];
    return Object.keys(filesData.seasons).sort((a, b) => parseInt(a, 10) - parseInt(b, 10));
  }, [filesData]);

  const currentFilesList = useMemo((): TorrentFile[] => {
    if (!filesData) return [];
    if (filesData.type === 'series' && filesData.seasons) {
      return (selectedSeasonKey === 'movies' ? filesData.movies : filesData.seasons[selectedSeasonKey]) || [];
    }
    return filesData.flat_files || filesData.files || [];
  }, [filesData, selectedSeasonKey]);

  const selectFile = (id: number) => {
    const session = sessionRef.current;
    if (!session || !activePlayback || !resolvedHash || isOnlinePlayback(activePlayback, resolvedHash)) return;
    const file = currentFilesList.find(file => file.id === id);
    if (file) void launchFile(session, resolvedHash, file.id, file.name, file.playback_timecode || undefined);
  };

  const playNext = () => {
    const session = sessionRef.current;
    if (!session || !activePlayback) return;
    if (isOnlinePlayback(activePlayback, resolvedHash)) {
      void API.playNext({ hash: resolvedHash, file_id: 0 }).catch(() => {});
      return;
    }
    if (currentFileId === null || !resolvedHash) return;
    const launch = session.launch;
    void API.playNext({ hash: resolvedHash, file_id: currentFileId }).catch(error => {
      if (session.isCurrent(launch)) {
        setLaunchError(errorMessage(error, 'Ошибка запуска плеера MPV'));
      }
    });
  };

  const changeSeason = async (key: string) => {
    setSelectedSeasonKey(key);
    const session = sessionRef.current;
    if (!session) return;
    const selection = session.nextSelection();
    if (!filesData?.seasons?.[key] || !resolvedHash) return;
    const launch = session.launch;
    const isCurrent = () => session.isCurrent(launch, selection);
    const intent = { season: Number(key) };
    try {
      const result = await API.selectTorrentFile({ hash: resolvedHash, ...intent }, { signal: session.signal });
      if (isCurrent()) setChoice({ intent, candidates: result.candidates, message: result.reason });
    } catch (error) {
      if (isCurrent()) setLaunchError(errorMessage(error, 'Ошибка выбора видеофайла'));
    }
  };

  const confirmFile = async (file: TorrentFile) => {
    const session = sessionRef.current;
    if (!session || !activePlayback || !choice) return;
    const launch = session.launch;
    const selection = session.nextSelection();
    const isCurrent = () => session.isCurrent(launch, selection);
    try {
      const result = await API.selectTorrentFile({
        hash: resolvedHash, ...choice.intent, release_title: activePlayback.title, file_id: file.id,
      }, { signal: session.signal });
      if (!isCurrent() || !result.file) return;
      setChoice(null);
      await launchFile(session, resolvedHash, file.id, file.name, file.playback_timecode || undefined);
    } catch (error) {
      if (isCurrent()) setLaunchError(errorMessage(error, 'Ошибка выбора видеофайла'));
    }
  };

  const recoverPlayback = async () => {
    const session = sessionRef.current;
    if (!session) return;
    const launch = session.nextLaunch();
    const isCurrent = () => session.isCurrent(launch);
    setLaunchError(null);
    setIsStartingPlayback(true);
    void API.hidePlayerPanel();
    try {
      await API.recoverPlayback();
      if (!isCurrent()) return;
      setRecovery(null);
      setIsMpvRunning(true);
    } catch (error) {
      if (!isCurrent()) return;
      setIsStartingPlayback(false);
      setLaunchError(errorMessage(error, 'Не удалось восстановить просмотр'));
    }
  };

  return {
    sessionKey, sessionRevision, resolvedHash, currentFileId, currentFileName, isMpvRunning,
    isStreamReady, isEmbedded, isLoadingFiles, isStartingPlayback, choice, launchError, isDeadTorrent,
    backendFullscreen, pollingAttempt, playbackStatusText, recovery, selectedSeasonKey, seasonsList,
    currentFilesList, hasMovies: Boolean(filesData?.movies?.length),
    startSession, recoverPlayback, selectFile, playNext, changeSeason, confirmFile,
  };
}
