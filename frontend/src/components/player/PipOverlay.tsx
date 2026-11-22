/**
 * @file components/player/PipOverlay.tsx
 * @description Плавающий компактный оверлей для режима «Картинка в картинке» (PiP).
 * Обеспечивает отображение органов управления при наведении и корректный выход из PiP режима.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useApp, usePlayer } from '../../context/AppContext';
import { API } from '../../services/api';
import { Maximize2, X, Play, Pause, RotateCcw, RotateCw, Volume2, VolumeX } from 'lucide-react';

export const PipOverlay: React.FC = () => {
  const { togglePip, closePlayback, activePlayback } = useApp();
  const player = usePlayer();
  const [isHovered, setIsHovered] = useState(false);
  const [controlsVisible, setControlsVisible] = useState(true);
  const [isMuted, setIsMuted] = useState(false);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleRestore = useCallback(async (e?: React.MouseEvent) => {
    e?.stopPropagation();
    await togglePip(false);
  }, [togglePip]);

  const handleClose = useCallback(async (e?: React.MouseEvent) => {
    e?.stopPropagation();
    await closePlayback();
  }, [closePlayback]);

  const showControls = useCallback(() => {
    setControlsVisible(true);
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    hideTimerRef.current = setTimeout(() => {
      setControlsVisible(false);
    }, 2500);
  }, []);

  useEffect(() => {
    showControls();
    return () => {
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    };
  }, [showControls]);

  // Хоткеи внутри PiP-окна
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      switch (e.code) {
        case 'Escape':
        case 'KeyP':
          e.preventDefault();
          handleRestore();
          break;
        case 'Space':
          e.preventDefault();
          API.sendPlayerCommand(['cycle', 'pause']);
          break;
        case 'KeyF':
          e.preventDefault();
          API.togglePlayerFullscreen();
          break;
        case 'KeyM':
          e.preventDefault();
          setIsMuted(prev => !prev);
          API.sendPlayerCommand(['cycle', 'mute']);
          break;
        case 'ArrowLeft':
          e.preventDefault();
          API.sendPlayerCommand(['cinema-step', -1]);
          break;
        case 'ArrowRight':
          e.preventDefault();
          API.sendPlayerCommand(['cinema-step', 1]);
          break;
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleRestore]);

  const isPaused = player.isPaused;
  const isControlsActive = isHovered || controlsVisible;

  return (
    <div
      className="group fixed inset-0 z-50 flex flex-col justify-between overflow-hidden select-none bg-transparent"
      onMouseEnter={() => { setIsHovered(true); showControls(); }}
      onMouseMove={showControls}
      onMouseLeave={() => { setIsHovered(false); setControlsVisible(false); }}
      onDoubleClick={handleRestore}
    >
      {/* Верхняя панель: Перетаскивание + заголовок + кнопки Восстановить и Закрыть */}
      <div
        className={`pywebview-drag-region h-[36px] w-full flex items-center justify-between px-3 bg-black/80 backdrop-blur-sm border-b border-film-line/60 text-film-text transition-opacity duration-200 ${
          isControlsActive ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
      >
        <div className="flex items-center gap-2 truncate min-w-0 mr-2 pointer-events-none">
          <span className="w-2 h-2 rounded-full bg-film-accent shrink-0 animate-pulse" />
          <span className="text-xs font-medium text-film-text truncate">
            {activePlayback?.fileName || activePlayback?.title || 'Pirate Cinema Mini'}
          </span>
        </div>

        <div className="flex items-center gap-1.5 shrink-0" onMouseDown={(e) => e.stopPropagation()}>
          <button
            type="button"
            onClick={handleRestore}
            className="p-1.5 rounded text-film-text hover:text-film-accent hover:bg-film-surface focus:outline-none focus-visible:ring-2 focus-visible:ring-film-accent focus-visible:ring-offset-1 focus-visible:ring-offset-black transition-colors cursor-pointer"
            title="Восстановить в приложение (P или Esc)"
            aria-label="Восстановить в приложение"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={handleClose}
            className="p-1.5 rounded text-film-text hover:text-rose-400 hover:bg-rose-500/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500 focus-visible:ring-offset-1 focus-visible:ring-offset-black transition-colors cursor-pointer"
            title="Закрыть"
            aria-label="Закрыть"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Центральная / нижняя панель управления воспроизведением */}
      <div
        className={`w-full flex items-center justify-center gap-3 py-2 px-4 bg-gradient-to-t from-black/85 via-black/50 to-transparent transition-opacity duration-200 ${
          isControlsActive ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Перемотка назад */}
        <button
          type="button"
          onClick={() => API.sendPlayerCommand(['cinema-step', -1])}
          className="p-2 rounded-full bg-film-surface/70 hover:bg-film-hover text-white/90 hover:text-film-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-film-accent focus-visible:ring-offset-1 focus-visible:ring-offset-black active:scale-95 transition-all cursor-pointer"
          title="Назад (ArrowLeft)"
          aria-label="Перемотать назад"
        >
          <RotateCcw className="w-4 h-4" />
        </button>

        {/* Пауза / Воспроизведение */}
        <button
          type="button"
          onClick={() => API.sendPlayerCommand(['cycle', 'pause'])}
          className="p-2.5 rounded-full bg-film-accent/20 hover:bg-film-accent/30 text-film-accent border border-film-accent/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-film-accent focus-visible:ring-offset-1 focus-visible:ring-offset-black active:scale-95 transition-all cursor-pointer"
          title="Пауза / Воспроизведение (Space)"
          aria-label={isPaused ? 'Воспроизвести' : 'Пауза'}
        >
          {isPaused ? <Play className="w-4 h-4 fill-current" /> : <Pause className="w-4 h-4 fill-current" />}
        </button>

        {/* Перемотка вперёд */}
        <button
          type="button"
          onClick={() => API.sendPlayerCommand(['cinema-step', 1])}
          className="p-2 rounded-full bg-film-surface/70 hover:bg-film-hover text-white/90 hover:text-film-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-film-accent focus-visible:ring-offset-1 focus-visible:ring-offset-black active:scale-95 transition-all cursor-pointer"
          title="Вперёд (ArrowRight)"
          aria-label="Перемотать вперёд"
        >
          <RotateCw className="w-4 h-4" />
        </button>

        {/* Звук */}
        <button
          type="button"
          onClick={() => {
            setIsMuted(prev => !prev);
            API.sendPlayerCommand(['cycle', 'mute']);
          }}
          className="p-2 rounded-full bg-film-surface/70 hover:bg-film-hover text-white/90 hover:text-film-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-film-accent focus-visible:ring-offset-1 focus-visible:ring-offset-black active:scale-95 transition-all cursor-pointer"
          title="Включить/выключить звук (M)"
          aria-label="Звук"
        >
          {isMuted ? <VolumeX className="w-4 h-4 text-rose-400" /> : <Volume2 className="w-4 h-4" />}
        </button>

        {/* Развернуть обратно в полноразмерный плеер */}
        <button
          type="button"
          onClick={handleRestore}
          className="p-2 rounded-full bg-film-surface/70 hover:bg-film-hover text-white/90 hover:text-film-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-film-accent focus-visible:ring-offset-1 focus-visible:ring-offset-black active:scale-95 transition-all cursor-pointer"
          title="Восстановить в приложение (P)"
          aria-label="Восстановить в приложение"
        >
          <Maximize2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};
