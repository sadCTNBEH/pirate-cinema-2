/**
 * @file components/diagnostics/DiagnosticsModal.tsx
 * @description Всплывающее модальное окно системной диагностики Pirate Cinema
 * Открывается поверх плеера или каталога без прерывания фильма.
 */

import React from 'react';
import { useApp } from '../../context/AppContext';
import { DiagnosticsView } from './DiagnosticsView';
import { Activity, X } from 'lucide-react';

export const DiagnosticsModal: React.FC = () => {
  const { isDiagnosticsOpen, setIsDiagnosticsOpen, t } = useApp();

  if (!isDiagnosticsOpen) return null;

  return (
    <div
      role="dialog" aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-3 md:p-6 bg-black/80 backdrop-blur-md animate-fade-in"
      onClick={() => setIsDiagnosticsOpen(false)}
    >
      <div
        className="relative w-full max-w-5xl max-h-[92vh] bg-[#070b14] border border-cyan-500/40 rounded-2xl shadow-2xl shadow-cyan-950/60 flex flex-col overflow-hidden select-none"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Шапка модального окна */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-cyan-950/80 bg-[#060911]/90 shrink-0">
          <div className="flex items-center gap-2.5 text-cyan-400">
            <Activity className="w-5 h-5 stroke-[2.2]" />
            <h2 className="font-tech text-base md:text-lg font-bold uppercase tracking-wider text-white">
              {t('system_diagnostics') || 'Диагностика системы'}
            </h2>
          </div>
          <button data-dialog-close
            onClick={() => setIsDiagnosticsOpen(false)}
            className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800/80 transition-colors cursor-pointer"
            title={t('close') || 'Закрыть'}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Прокручиваемое содержимое диагностики */}
        <div className="flex-1 overflow-y-auto p-4 md:p-8 overscroll-contain select-auto">
          <DiagnosticsView hideHeader={true} />
        </div>
      </div>
    </div>
  );
};
