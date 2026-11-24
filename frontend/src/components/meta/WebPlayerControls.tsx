import { Maximize2, X } from 'lucide-react';

export function WebPlayerControls({previous, next, fullscreen, close, autoNext, setAutoNext, autoSupported}: {
  previous?: () => void; next?: () => void; fullscreen?: () => void; close: () => void;
  autoNext: boolean; setAutoNext: (value: boolean) => void; autoSupported: boolean;
}) {
  return <div className="anime-player-controls" role="group" aria-label="Управление сериями">
    <div className="anime-player-navigation">
      <button type="button" className="cinema-button cinema-button--secondary" disabled={!previous} onClick={previous}>Предыдущая серия</button>
      <button type="button" className="cinema-button cinema-button--secondary" disabled={!next} onClick={next}>Следующая серия</button>
    </div>
    {autoSupported && <label className="anime-player-auto"><input type="checkbox" checked={autoNext} onChange={event => setAutoNext(event.target.checked)} />Автопереход (Beta)</label>}
    {fullscreen && <button type="button" className="cinema-button cinema-button--secondary" onClick={fullscreen}><Maximize2 aria-hidden="true" />На весь экран</button>}
    <button type="button" className="cinema-button cinema-button--quiet anime-player-close" onClick={close}><X aria-hidden="true" />Закрыть плеер</button>
  </div>;
}
