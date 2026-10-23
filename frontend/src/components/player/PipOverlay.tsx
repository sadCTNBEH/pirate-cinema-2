/**
 * @file components/player/PipOverlay.tsx
 * @description Плавающий компактный оверлей для режима «Картинка в картинке» (PiP).
 * Отображается поверх нативного MPV в компактном окне (~420x236 px),
 * предоставляет плавающие элементы управления при наведении и перетаскивание.
 */

import React, { useState, useEffect } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { Maximize2, X, Play, Pause, RotateCcw, RotateCw } from 'lucide-react';

export const PipOverlay: React.FC = () => {
  const { togglePip, closePlayback, activePlayback } = useApp();
  const [isPaused, setIsPaused] = useState<boolean>(false);
  const [timecode, setTimecode] = useState<number>(0);
  const [duration, setDuration] = useState<number>(0);

  // Опрос состояния активного плеера во время PiP
  useEffect(() => {
    const poll = async () => {
      try {
        const state = await API.getActivePlayback();
        if (state) {
          setIsPaused(!!state.is_paused);
          if (typeof state.timecode === 'number') setTimecode(state.timecode);
          if (typeof state.duration === 'number') setDuration(state.duration);
        }
      } catch {}
    };
    poll();
    const interval = setInterval(poll, 700);
    return () => clearInterval(interval);
  }, []);

  const handlePlayPause = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsPaused((p) => !p);
    await API.sendPlayerCommand(['cycle', 'pause']);
  };

  const handleSeek = async (e: React.MouseEvent, delta: number) => {
    e.stopPropagation();
    await API.sendPlayerCommand(['seek', delta, 'relative']);
  };

  const handleRestore = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await togglePip(false);
  };

  const handleClose = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await closePlayback();
  };

  const formatTime = (sec: number) => {
    if (!sec || isNaN(sec)) return '00:00';
    const s = Math.floor(sec);
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return `${m < 10 ? '0' : ''}${m}:${rem < 10 ? '0' : ''}${rem}`;
  };

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col justify-between overflow-hidden select-none bg-transparent group"
      onDoubleClick={handleRestore}
    >
      {/* Верхняя панель: Перетаскивание + кнопки Восстановить и Закрыть */}
      <div className="pywebview-drag-region h-10 w-full flex items-center justify-between px-3 bg-gradient-to-b from-black/85 via-black/40 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-200">
        <div className="flex items-center gap-2 truncate min-w-0 mr-2 pointer-events-none">
          <span className="w-2 h-2 rounded-full bg-cyan-400 shrink-0 shadow-sm shadow-cyan-400" />
          <span className="text-[11px] font-medium text-slate-200 truncate">
            {activePlayback?.fileName || activePlayback?.title || 'Pirate Cinema Mini'}
          </span>
        </div>

        <div className="flex items-center gap-1 shrink-0" onMouseDown={(e) => e.stopPropagation()}>
          {/* Восстановить размер */}
          <button
            onClick={handleRestore}
            className="p-1.5 rounded text-slate-300 hover:text-cyan-300 hover:bg-slate-800/80 transition-colors"
            title="Восстановить окно (двойной клик)"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
          {/* Закрыть */}
          <button
            onClick={handleClose}
            className="p-1.5 rounded text-slate-300 hover:text-rose-400 hover:bg-rose-500/20 transition-colors"
            title="Закрыть плеер"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Центр: Быстрое управление воспроизведением (появляется при наведении) */}
      <div
        className="flex items-center justify-center gap-4 opacity-0 group-hover:opacity-100 transition-opacity duration-200"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <button
          onClick={(e) => handleSeek(e, -10)}
          className="p-2 rounded-full bg-black/60 hover:bg-black/80 text-slate-200 hover:text-cyan-300 border border-white/10 hover:border-cyan-400/40 transition-colors"
          title="-10 сек"
        >
          <RotateCcw className="w-4 h-4" />
        </button>

        <button
          onClick={handlePlayPause}
          className="p-3 rounded-full bg-cyan-500/90 hover:bg-cyan-400 text-slate-950 font-bold shadow-lg shadow-cyan-500/30 transition-transform active:scale-95"
          title={isPaused ? 'Воспроизвести' : 'Пауза'}
        >
          {isPaused ? <Play className="w-5 h-5 fill-current" /> : <Pause className="w-5 h-5 fill-current" />}
        </button>

        <button
          onClick={(e) => handleSeek(e, 10)}
          className="p-2 rounded-full bg-black/60 hover:bg-black/80 text-slate-200 hover:text-cyan-300 border border-white/10 hover:border-cyan-400/40 transition-colors"
          title="+10 сек"
        >
          <RotateCw className="w-4 h-4" />
        </button>
      </div>

      {/* Нижняя панель: Таймкод и прогресс */}
      <div className="h-8 w-full flex items-center justify-between px-3 bg-gradient-to-t from-black/85 via-black/40 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none">
        <span className="font-mono text-[10px] text-slate-300">
          {formatTime(timecode)} / {formatTime(duration)}
        </span>
        <span className="text-[10px] text-cyan-400 font-semibold tracking-wider uppercase">
          PiP
        </span>
      </div>
    </div>
  );
};
