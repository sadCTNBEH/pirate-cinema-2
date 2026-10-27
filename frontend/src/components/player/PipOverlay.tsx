/**
 * @file components/player/PipOverlay.tsx
 * @description Плавающий компактный оверлей для режима «Картинка в картинке» (PiP).
 * Содержит заголовок и перетаскивание. Управление над видео рисует MPV Lua/OSD.
 */

import React from 'react';
import { useApp } from '../../context/AppContext';
import { Maximize2, X } from 'lucide-react';

export const PipOverlay: React.FC = () => {
  const { togglePip, closePlayback, activePlayback } = useApp();
  const handleRestore = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await togglePip(false);
  };

  const handleClose = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await closePlayback();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col justify-between overflow-hidden select-none bg-transparent"
      onDoubleClick={handleRestore}
    >
      {/* Верхняя панель: Перетаскивание + кнопки Восстановить и Закрыть */}
      <div className="pywebview-drag-region h-[32px] w-full flex items-center justify-between px-3 bg-film-base border-b border-film-line text-film-text">
        <div className="flex items-center gap-2 truncate min-w-0 mr-2 pointer-events-none">
          <span className="w-2 h-2 rounded-full bg-film-hover shrink-0" />
          <span className="text-[11px] font-medium text-film-text truncate">
            {activePlayback?.fileName || activePlayback?.title || 'Pirate Cinema Mini'}
          </span>
        </div>

        <div className="flex items-center gap-1.5 shrink-0" onMouseDown={(e) => e.stopPropagation()}>
          {/* Восстановить размер */}
          <button
            onClick={handleRestore}
            className="p-1 rounded text-film-text hover:text-film-accent hover:bg-film-surface transition-colors cursor-pointer"
            title="Восстановить в приложение"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
          {/* Закрыть */}
          <button
            onClick={handleClose}
            className="p-1 rounded text-film-text hover:text-rose-400 hover:bg-rose-500/20 transition-colors cursor-pointer"
            title="Закрыть"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

    </div>
  );
};
