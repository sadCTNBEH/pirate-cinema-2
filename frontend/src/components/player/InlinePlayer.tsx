import React, { useEffect, useMemo, useRef } from 'react';
import { useApp, usePlayer } from '../../context/AppContext';
import { API } from '../../services/api';
import { isEditing } from '../../input/actions';
import { ExternalSubtitles } from './ExternalSubtitles';
import { PlayerControls } from './PlayerControls';
import { PlayerFileChoices } from './PlayerFileChoices';
import { PlayerStatus } from './PlayerStatus';
import { useNativePlayer } from './useNativePlayer';
import { usePlaybackSession } from './usePlaybackSession';
import { InlinePlayerProps, TimeUpdateDetail } from '../../types';

export interface PlayerKeyActions {
  togglePause: () => void;
  toggleFullscreen: () => void;
  toggleMute: () => void;
  seekBack: () => void;
  seekForward: () => void;
  volumeUp?: () => void;
  volumeDown?: () => void;
  togglePip?: () => void;
}

export function handlePlayerKey(
  e: KeyboardEvent | { code: string; preventDefault: () => void; defaultPrevented?: boolean; target?: any },
  actions: PlayerKeyActions,
  options: { isModalOpen?: boolean; isEditing?: boolean } = {}
): boolean {
  if (options.isModalOpen) return false;
  const target = (e as any).target as Element | null;
  if (options.isEditing ?? isEditing(target)) return false;

  switch (e.code) {
    case 'Space':
      e.preventDefault();
      actions.togglePause();
      return true;
    case 'KeyF':
      e.preventDefault();
      actions.toggleFullscreen();
      return true;
    case 'KeyM':
      e.preventDefault();
      actions.toggleMute();
      return true;
    case 'ArrowLeft':
      e.preventDefault();
      actions.seekBack();
      return true;
    case 'ArrowRight':
      e.preventDefault();
      actions.seekForward();
      return true;
    case 'ArrowUp':
      e.preventDefault();
      actions.volumeUp?.();
      return true;
    case 'ArrowDown':
      e.preventDefault();
      actions.volumeDown?.();
      return true;
    case 'KeyP':
      e.preventDefault();
      actions.togglePip?.();
      return true;
    default:
      return false;
  }
}

export const InlinePlayer = React.memo(function InlinePlayer(props?: InlinePlayerProps) {
  const app = useApp();
  const player = usePlayer();
  const activePlayback = props?.playback ?? player.activePlayback ?? app.activePlayback;
  const closePlayback = props?.onClose ?? player.closePlayback ?? app.closePlayback;
  const { t, isAnyModalOpen, isPip, isPipActive, debugMode } = app;

  const session = usePlaybackSession(activePlayback, closePlayback);
  const {
    resolvedHash, currentFileId, currentFileName, currentFilesList, isMpvRunning,
    isStreamReady, isEmbedded, isLoadingFiles, isStartingPlayback, isDeadTorrent, launchError,
    choice, selectedSeasonKey, playNext, selectFile,
  } = session;

  const { wrapperRef, videoSlotRef, isFullscreen } = useNativePlayer(
    session.sessionKey, session.sessionRevision, {
      requestedHash: activePlayback?.hash || resolvedHash,
      resolvedHash,
      running: isMpvRunning,
      ready: isStreamReady,
      loading: isLoadingFiles,
      starting: isStartingPlayback,
      blocked: !isEmbedded || Boolean(choice?.message || launchError || isDeadTorrent),
    }, session.backendFullscreen, isAnyModalOpen, isPipActive, isPip,
  );

  // Все входные устройства используют одни и те же действия плеера с отменой устаревших подписок
  const actionHandlersRef = useRef({ playNext, selectFile, currentFileId, currentFilesList });
  actionHandlersRef.current = { playNext, selectFile, currentFileId, currentFilesList };

  const playerKeyActionsRef = useRef<PlayerKeyActions>({
    togglePause: () => API.sendPlayerCommand(['cycle', 'pause']),
    toggleFullscreen: () => API.togglePlayerFullscreen(),
    toggleMute: () => API.sendPlayerCommand(['cycle', 'mute']),
    seekBack: () => API.sendPlayerCommand(['cinema-step', -1]),
    seekForward: () => API.sendPlayerCommand(['cinema-step', 1]),
    volumeUp: () => API.sendPlayerCommand(['add', 'volume', 5]),
    volumeDown: () => API.sendPlayerCommand(['add', 'volume', -5]),
    togglePip: () => app.togglePip(),
  });
  playerKeyActionsRef.current = {
    togglePause: () => API.sendPlayerCommand(['cycle', 'pause']),
    toggleFullscreen: () => API.togglePlayerFullscreen(),
    toggleMute: () => API.sendPlayerCommand(['cycle', 'mute']),
    seekBack: () => API.sendPlayerCommand(['cinema-step', -1]),
    seekForward: () => API.sendPlayerCommand(['cinema-step', 1]),
    volumeUp: () => API.sendPlayerCommand(['add', 'volume', 5]),
    volumeDown: () => API.sendPlayerCommand(['add', 'volume', -5]),
    togglePip: () => app.togglePip(),
  };

  useEffect(() => {
    if (!activePlayback) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      handlePlayerKey(e, playerKeyActionsRef.current, { isModalOpen: isAnyModalOpen });
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [activePlayback, isAnyModalOpen]);

  useEffect(() => {
    let cancelled = false;
    const onAction = (event: Event) => {
      if (cancelled) return;
      const action = (event as CustomEvent).detail;
      const { playNext: next, selectFile: select, currentFileId: fileId, currentFilesList: files } = actionHandlersRef.current;
      if (action === 'episodeNext') next();
      if (action === 'episodePrev' && fileId !== null) {
        const index = files.findIndex(file => file.id === fileId);
        if (index > 0) select(files[index - 1].id);
      }
    };
    window.addEventListener('cinema-player-action', onAction);
    return () => {
      cancelled = true;
      window.removeEventListener('cinema-player-action', onAction);
    };
  }, []);

  // Отмена устаревших подписок на событие обновления прогресса таймкода
  useEffect(() => {
    let cancelled = false;
    const onTimeUpdate = (event: Event) => {
      if (cancelled) return;
      const detail = (event as CustomEvent<TimeUpdateDetail>).detail;
      if (detail && player.updateProgress) {
        player.updateProgress(detail);
      }
    };
    window.addEventListener('time-update', onTimeUpdate);
    return () => {
      cancelled = true;
      window.removeEventListener('time-update', onTimeUpdate);
    };
  }, [player.updateProgress]);

  // Оптимизированный мемоизированный контент статуса видеоплеера
  const videoSlotContent = useMemo(() => {
    if (!activePlayback) return null;
    return (
      <PlayerStatus
        t={t}
        title={activePlayback.title}
        startTime={activePlayback.startTime}
        debugMode={debugMode}
        currentFileName={currentFileName}
        isLoadingFiles={isLoadingFiles}
        pollingAttempt={session.pollingAttempt}
        isStartingPlayback={isStartingPlayback}
        playbackStatusText={session.playbackStatusText}
        isDeadTorrent={isDeadTorrent}
        launchError={launchError}
        recovery={session.recovery}
        closePlayback={closePlayback}
        startSession={session.startSession}
        recoverPlayback={session.recoverPlayback}
      />
    );
  }, [
    t,
    activePlayback?.title,
    activePlayback?.startTime,
    debugMode,
    currentFileName,
    isLoadingFiles,
    session.pollingAttempt,
    isStartingPlayback,
    session.playbackStatusText,
    isDeadTorrent,
    launchError,
    session.recovery,
    closePlayback,
    session.startSession,
    session.recoverPlayback,
  ]);

  const canPlayNext = useMemo(
    () => currentFileId !== null && isMpvRunning,
    [currentFileId, isMpvRunning]
  );

  // Оптимизированный мемоизированный контент управления плеером
  const controlsContent = useMemo(
    () => (
      <PlayerControls
        t={t}
        selectedSeasonKey={selectedSeasonKey}
        seasonsList={session.seasonsList}
        hasMovies={session.hasMovies}
        currentFilesList={currentFilesList}
        currentFileId={currentFileId}
        canPlayNext={canPlayNext}
        handleSeasonChange={session.changeSeason}
        handleSelectFile={selectFile}
        handlePlayNextFile={playNext}
      />
    ),
    [
      t,
      selectedSeasonKey,
      session.seasonsList,
      session.hasMovies,
      currentFilesList,
      currentFileId,
      canPlayNext,
      session.changeSeason,
      selectFile,
      playNext,
    ]
  );

  // Оптимизированный мемоизированный контент внешних субтитров
  const subtitlesContent = useMemo(() => {
    if (!isMpvRunning || !resolvedHash || currentFileId === null) return null;
    return (
      <ExternalSubtitles
        key={`${resolvedHash}:${currentFileId}`}
        hash={resolvedHash}
        fileId={currentFileId}
        title={activePlayback?.title || ''}
        season={Number(selectedSeasonKey) || undefined}
      />
    );
  }, [isMpvRunning, resolvedHash, currentFileId, activePlayback?.title, selectedSeasonKey]);

  // Оптимизированный мемоизированный контент выбора файлов
  const fileChoicesContent = useMemo(() => {
    if (!choice?.message) return null;
    return (
      <PlayerFileChoices
        t={t}
        message={choice.message}
        candidates={choice.candidates}
        onSelect={session.confirmFile}
        onClose={closePlayback}
      />
    );
  }, [choice?.message, choice?.candidates, session.confirmFile, closePlayback, t]);

  if (!activePlayback) return null;

  if (isFullscreen) {
    return (
      <div
        ref={wrapperRef}
        id="inline-player-fullscreen-container"
        className={`fixed inset-0 z-50 bg-black overflow-hidden select-none animate-fade-in ${props?.className || ''}`}
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
      className={`ui-inline-player mb-8 space-y-3 ${props?.className || ''}`}
    >
      {/* ── Верхняя панель: Заголовок, селекторы сезона/серии и быстрые действия ── */}
      <div className="player-responsive-heading pb-2 border-b border-film-line">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-2 h-2 rounded-full bg-film-hover animate-pulse" />
          <h3 className="font-sans text-sm font-semibold text-film-text truncate">
            {activePlayback.title}
          </h3>
          {debugMode && currentFileName && currentFileName !== activePlayback.title && (
            <span className="text-xs text-film-muted font-mono truncate max-w-xs hidden md:inline">
              · {currentFileName}
            </span>
          )}
        </div>
        {controlsContent}
      </div>

      {subtitlesContent}
      {fileChoicesContent}

      {/* ── Видео-область (16:9 слот для нативного окна MPV) ── */}
      <div
        ref={videoSlotRef}
        tabIndex={0}
        aria-label="Окно видеоплеера"
        className="relative w-full aspect-video max-h-[75vh] bg-black flex items-center justify-center overflow-hidden select-none rounded border border-film-line hover:border-film-accent/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-film-accent focus-visible:ring-offset-2 focus-visible:ring-offset-[#06080d] transition-all"
      >
        {videoSlotContent}
      </div>
    </div>
  );
});
