import type { useApp } from '../../context/AppContext';
import type { TorrentFile } from '../../types';
import { formatSize } from '../../utils/torrentParser';
import { Button } from '../ui/UIComponents';

interface Props {
  t: ReturnType<typeof useApp>['t'];
  message: string;
  candidates: TorrentFile[];
  onSelect: (file: TorrentFile) => void;
  onClose: () => void;
}

export function PlayerFileChoices({ t, message, candidates, onSelect, onClose }: Props) {
  return (
    <div className="space-y-2" role="status">
      <p className="text-sm text-film-text">{message}</p>
      <div className="max-h-64 overflow-y-auto space-y-2" aria-label="Выбор видеофайла">
        {candidates.map(file => (
          <button
            type="button"
            key={file.id}
            className="w-full text-left p-3 border border-film-line rounded-sm hover:bg-film-base focus-visible:outline-2 focus-visible:outline-film-accent"
            onClick={() => onSelect(file)}
          >
            <span className="block break-words text-sm">{file.path || file.name}</span>
            <span className="text-xs text-film-muted">
              {formatSize(file.length, t)}
              {file.season != null ? ` · Сезон ${file.season}` : ''}
              {file.episode != null ? ` · Серия ${file.episode}` : ''}
            </span>
          </button>
        ))}
      </div>
      <Button variant="secondary" onClick={onClose}>Выбрать другую раздачу</Button>
    </div>
  );
}
