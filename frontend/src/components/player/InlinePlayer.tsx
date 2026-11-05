import { useEffect } from 'react';
import { useApp } from '../../context/AppContext';
import { ExternalSubtitles } from './ExternalSubtitles';
import { PlayerControls } from './PlayerControls';
import { PlayerFileChoices } from './PlayerFileChoices';
import { PlayerStatus } from './PlayerStatus';
import { useNativePlayer } from './useNativePlayer';
import { usePlaybackSession } from './usePlaybackSession';

export function InlinePlayer() {
  const { activePlayback, closePlayback, t, isAnyModalOpen, isPipActive, debugMode } = useApp();
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
    }, session.backendFullscreen, isAnyModalOpen, isPipActive,
  );

  // All input devices use the same player actions; no independent key listener.
  useEffect(() => {
    const onAction = (event: Event) => {
      const action = (event as CustomEvent).detail;
      if (action === 'episodeNext') playNext();
      if (action === 'episodePrev' && currentFileId !== null) {
        const index = currentFilesList.findIndex(file => file.id === currentFileId);
        if (index > 0) selectFile(currentFilesList[index - 1].id);
      }
    };
    window.addEventListener('cinema-player-action', onAction);
    return () => window.removeEventListener('cinema-player-action', onAction);
  });

  if (!activePlayback) return null;

  const videoSlotContent = (
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
          {debugMode && currentFileName && currentFileName !== activePlayback.title && (
            <span className="text-xs text-film-muted font-mono truncate max-w-xs hidden md:inline">
              · {currentFileName}
            </span>
          )}
        </div>
        <PlayerControls
          t={t}
          selectedSeasonKey={selectedSeasonKey}
          seasonsList={session.seasonsList}
          hasMovies={session.hasMovies}
          currentFilesList={currentFilesList}
          currentFileId={currentFileId}
          canPlayNext={currentFileId !== null && isMpvRunning}
          handleSeasonChange={session.changeSeason}
          handleSelectFile={selectFile}
          handlePlayNextFile={playNext}
        />
      </div>

      {isMpvRunning && resolvedHash && currentFileId !== null && <ExternalSubtitles
        key={`${resolvedHash}:${currentFileId}`} hash={resolvedHash} fileId={currentFileId}
        title={activePlayback.title} season={Number(selectedSeasonKey) || undefined} />}

      {choice?.message && (
        <PlayerFileChoices
          t={t}
          message={choice.message}
          candidates={choice.candidates}
          onSelect={session.confirmFile}
          onClose={closePlayback}
        />
      )}

      {/* ── Видео-область (16:9 слот для нативного окна MPV) ── */}
      <div
        ref={videoSlotRef}
        className="relative w-full aspect-video max-h-[75vh] bg-black flex items-center justify-center overflow-hidden select-none rounded border border-film-line"
      >
        {videoSlotContent}
      </div>
    </div>
  );
}
