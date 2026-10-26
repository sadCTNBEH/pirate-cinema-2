/**
 * @file components/settings/SettingsModal.tsx
 * @description Всплывающее модальное окно настроек Pirate Cinema
 * Открывается поверх плеера или каталога без прерывания фильма.
 */

import React from 'react';
import { useApp } from '../../context/AppContext';
import { SettingsView } from './SettingsView';
import { Settings, X } from 'lucide-react';

export const SettingsModal: React.FC = () => {
  const { isSettingsOpen, setIsSettingsOpen, t } = useApp();

  if (!isSettingsOpen) return null;

  return (
    <div
      role="dialog" aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-3 md:p-6 bg-black/80 backdrop-blur-md animate-fade-in"
      onClick={() => setIsSettingsOpen(false)}
    >
      <div
        className="relative w-full max-w-4xl max-h-[92vh] bg-[#070b14] border border-cyan-500/40 rounded-2xl shadow-2xl shadow-cyan-950/60 flex flex-col overflow-hidden select-none"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Шапка модального окна */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-cyan-950/80 bg-[#060911]/90 shrink-0">
          <div className="flex items-center gap-2.5 text-cyan-400">
            <Settings className="w-5 h-5 stroke-[2.2]" />
            <h2 className="font-tech text-base md:text-lg font-bold uppercase tracking-wider text-white">
              {t('nav_settings') || 'Настройки'}
            </h2>
          </div>
          <button data-dialog-close
            onClick={() => setIsSettingsOpen(false)}
            className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800/80 transition-colors cursor-pointer"
            title={t('close') || 'Закрыть'}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Прокручиваемое содержимое настроек */}
        <div className="flex-1 overflow-y-auto p-4 md:p-8 overscroll-contain select-auto">
          <SettingsView hideHeader={true} />
        </div>
      </div>
    </div>
  );
};
