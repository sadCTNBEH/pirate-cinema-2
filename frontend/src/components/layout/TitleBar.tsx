/**
 * @file components/layout/TitleBar.tsx
 * @description Бесшовная шапка окна (frameless titlebar) с областью drag-region
 * и кастомными кнопками управления: свернуть / развернуть (восстановить) / закрыть.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Minus, Square, X } from 'lucide-react';

declare global {
  interface Window {
    pywebview?: {
      api?: {
        minimize?: () => Promise<boolean>;
        maximize?: () => Promise<boolean>;
        restore?: () => Promise<boolean>;
        toggle_maximize?: () => Promise<boolean>;
        is_maximized?: () => Promise<boolean>;
        close?: () => Promise<boolean>;
        save_backup?: () => Promise<{
          saved: boolean;
          cancelled?: boolean;
          path?: string;
          error?: string;
        }>;
      };
    };
  }
}

export const TitleBar: React.FC = () => {
  const [isMaximized, setIsMaximized] = useState<boolean>(false);

  /**
   * Проверка состояния окна (развернуто или нормальное)
   */
  const checkMaximized = useCallback(async () => {
    try {
      if (window.pywebview?.api?.is_maximized) {
        const state = await window.pywebview.api.is_maximized();
        setIsMaximized(!!state);
        return;
      }
      const res = await fetch('/api/window/state');
      if (res.ok) {
        const data = await res.json();
        if (typeof data.is_maximized === 'boolean') {
          setIsMaximized(data.is_maximized);
        }
      }
    } catch {
      // Игнорируем сетевые сбои при инициализации
    }
  }, []);

  useEffect(() => {
    checkMaximized();

    const onResize = () => {
      checkMaximized();
    };

    window.addEventListener('resize', onResize);
    window.addEventListener('pywebviewready', checkMaximized);

    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('pywebviewready', checkMaximized);
    };
  }, [checkMaximized]);

  /**
   * Свернуть окно
   */
  const handleMinimize = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      if (window.pywebview?.api?.minimize) {
        await window.pywebview.api.minimize();
        return;
      }
      await fetch('/api/window/minimize', { method: 'POST' });
    } catch (err) {
      console.error('Failed to minimize window', err);
    }
  };

  /**
   * Развернуть / восстановить окно
   */
  const handleToggleMaximize = async (e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    try {
      if (window.pywebview?.api?.toggle_maximize) {
        const nextState = await window.pywebview.api.toggle_maximize();
        setIsMaximized(!!nextState);
        return;
      }
      const res = await fetch('/api/window/toggle_maximize', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setIsMaximized(!!data.is_maximized);
      }
    } catch (err) {
      console.error('Failed to toggle maximize window', err);
    }
  };

  /**
   * Закрыть окно
   */
  const handleClose = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      if (window.pywebview?.api?.close) {
        await window.pywebview.api.close();
        return;
      }
      await fetch('/api/window/close', { method: 'POST' });
    } catch (err) {
      console.error('Failed to close window', err);
    }
  };

  return (
    <header className="h-9 w-full bg-[#06080d] border-b border-slate-800/60 flex items-center justify-between select-none z-30 shrink-0">
      {/* ── ОБЛАСТЬ ПЕРЕТАСКИВАНИЯ (DRAG REGION) ── */}
      <div
        className="pywebview-drag-region flex-1 h-full flex items-center px-4 cursor-default"
        onDoubleClick={() => handleToggleMaximize()}
      >
        <div className="flex items-center gap-2 pointer-events-none opacity-60 hover:opacity-100 transition-opacity">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
          <span className="font-tech text-[11px] tracking-widest text-slate-400 uppercase font-semibold">
            Pirate Cinema
          </span>
        </div>
      </div>

      {/* ── КНОПКИ УПРАВЛЕНИЯ ОКНОМ (MINIMIZE / MAXIMIZE / CLOSE) ── */}
      <div
        className="flex items-center h-full shrink-0"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Свернуть */}
        <button
          type="button"
          onClick={handleMinimize}
          title="Свернуть"
          aria-label="Свернуть"
          className="h-full px-3.5 flex items-center justify-center text-slate-400 hover:text-cyan-300 hover:bg-slate-800/60 active:bg-cyan-500/20 transition-colors cursor-pointer"
        >
          <Minus className="w-3.5 h-3.5 stroke-[2]" />
        </button>

        {/* Развернуть / Восстановить */}
        <button
          type="button"
          onClick={(e) => handleToggleMaximize(e)}
          title={isMaximized ? 'Восстановить' : 'Развернуть'}
          aria-label={isMaximized ? 'Восстановить' : 'Развернуть'}
          className="h-full px-3.5 flex items-center justify-center text-slate-400 hover:text-cyan-300 hover:bg-slate-800/60 active:bg-cyan-500/20 transition-colors cursor-pointer"
        >
          {isMaximized ? (
            <svg
              className="w-3.5 h-3.5"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
            >
              <rect x="4.5" y="1.5" width="9" height="9" rx="0.5" />
              <path d="M2.5 5.5H2a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h7a1 1 0 0 0 1-1v-.5" />
            </svg>
          ) : (
            <Square className="w-3.5 h-3.5 stroke-[2]" />
          )}
        </button>

        {/* Закрыть */}
        <button
          type="button"
          onClick={handleClose}
          title="Закрыть"
          aria-label="Закрыть"
          className="h-full px-4 flex items-center justify-center text-slate-400 hover:text-white hover:bg-rose-600 active:bg-rose-700 transition-colors cursor-pointer"
        >
          <X className="w-4 h-4 stroke-[2]" />
        </button>
      </div>
    </header>
  );
};
