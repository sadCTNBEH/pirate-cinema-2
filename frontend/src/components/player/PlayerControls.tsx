import { SkipForward } from 'lucide-react';
import type { useApp } from '../../context/AppContext';
import type { TorrentFile } from '../../types';
import { formatSize } from '../../utils/torrentParser';
import { ResponsiveToolbar } from '../ui/ResponsiveToolbar';
import { Button, Select } from '../ui/UIComponents';

interface Props {
  t: ReturnType<typeof useApp>['t'];
  selectedSeasonKey: string;
  seasonsList: string[];
  hasMovies: boolean;
  currentFilesList: TorrentFile[];
  currentFileId: number | null;
  canPlayNext: boolean;
  handleSeasonChange: (key: string) => void;
  handleSelectFile: (id: number) => void;
  handlePlayNextFile: () => void;
}

export function PlayerControls({
  t, selectedSeasonKey, seasonsList, hasMovies, currentFilesList, currentFileId,
  canPlayNext, handleSeasonChange, handleSelectFile, handlePlayNextFile,
}: Props) {
  return (
    <ResponsiveToolbar className="player-toolbar-actions" label="Серии плеера" items={[
      seasonsList.length > 0 ? { id: 'season', priority: 60, content: (<Select
          value={selectedSeasonKey}
          onChange={(e) => handleSeasonChange(e.target.value)}
          aria-label={t('season')}
          className="player-season-select bg-film-base"
        >
          {seasonsList.map((s) => (
            <option key={s} value={s}>
              {t('season')} {s}
            </option>
          ))}
          {hasMovies && (
            <option value="movies">{t('movies')}</option>
          )}
        </Select>) } : null,
      currentFilesList.length > 1 ? { id: 'episode', priority: 40, content: (<Select
          value={currentFileId !== null ? String(currentFileId) : ''}
          onChange={(e) => handleSelectFile(Number(e.target.value))}
          aria-label="Серия"
          className="player-episode-select bg-film-base"
        >
          {currentFilesList.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name} {f.length ? `(${formatSize(f.length, t)})` : ''}
            </option>
          ))}
        </Select>) } : null,
      canPlayNext ? { id: 'next', priority: 100, content: (<Button
          variant="secondary"
          size="sm"
          icon={<SkipForward className="w-3.5 h-3.5" />}
          onClick={handlePlayNextFile}
          title="Следующая серия"
        >
          {t('continue')}
        </Button>) } : null
    ].filter(item => item !== null)} />
  );
}
