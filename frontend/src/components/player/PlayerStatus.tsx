import { Film, Loader2, Play, RefreshCw, X } from 'lucide-react';
import { Button, SafeHtmlText } from '../ui/UIComponents';
import type { useApp } from '../../context/AppContext';

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

interface Props {
  t: ReturnType<typeof useApp>['t'];
  title: string;
  startTime?: number;
  debugMode: boolean;
  currentFileName: string;
  isLoadingFiles: boolean;
  pollingAttempt: number;
  isStartingPlayback: boolean;
  playbackStatusText: string;
  isDeadTorrent: boolean;
  launchError: string | null;
  recovery: { timecode: number } | null;
  closePlayback: () => void;
  startSession: () => void;
  recoverPlayback: () => void;
}

function statusLabel(text: string, debugMode: boolean) {
  if (debugMode) return text || 'Буферизация видеопотока...';
  const lower = text.toLowerCase();
  if (lower.includes('dht') || lower.includes('метадан') || lower.includes('поиск')) return 'Поиск раздачи...';
  if (lower.includes('подключен') || lower.includes('добавлен') || lower.includes('торрент-сет')) return 'Подключение...';
  return 'Буферизация...';
}

export function PlayerStatus({
  t, title, startTime, debugMode, currentFileName, isLoadingFiles, pollingAttempt,
  isStartingPlayback, playbackStatusText, isDeadTorrent, launchError, recovery,
  closePlayback, startSession, recoverPlayback,
}: Props) {
  const displayStatus = statusLabel(playbackStatusText, debugMode);
  return (
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
              {displayStatus}
            </div>
            {(debugMode || !title) && currentFileName ? (
              <div className="text-xs text-film-muted font-mono truncate max-w-sm mx-auto">
                {currentFileName}
              </div>
            ) : null}
            {startTime && startTime > 0 ? (
              <div className="text-xs text-film-accent font-mono">
                Возобновление с {formatTimecode(startTime)}
              </div>
            ) : null}
          </div>
          <div className="flex items-center justify-center gap-2 text-xs text-film-muted font-sans">
            <span className="w-2 h-2 rounded-full bg-film-hover animate-pulse" />
            <span>{debugMode ? 'TorrServer загружает фрагменты из P2P-сети...' : 'Загрузка видео...'}</span>
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
}
