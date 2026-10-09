/**
 * @file components/layout/Header.tsx
 * @description Верхняя панель (Topbar) с заголовком активного раздела
 * и киберпанк индикатором состояния подключения TorrServer.
 */

import React from 'react';
import { useApp } from '../../context/AppContext';
import { Radio, RefreshCw } from 'lucide-react';

interface HeaderProps {
  titleKey?: string;
  customTitle?: string;
}

export const Header: React.FC<HeaderProps> = ({ titleKey = 'nav_catalog', customTitle }) => {
  const { t, serverStatus, isCheckingStatus, refreshServerStatus } = useApp();

  return (
    <div className="flex items-center justify-between gap-4 mb-8 pb-4 border-b border-cyan-900/20">
      <div className="flex items-center gap-3">
        <div className="w-1.5 h-6 bg-cyan-400 shadow-[0_0_8px_#00f0ff]" />
        <h1 className="text-2xl font-tech font-bold uppercase tracking-wider text-white">
          {customTitle || t(titleKey)}
        </h1>
      </div>

      <div className="flex items-center gap-3">
        {/* Индикатор TorrServer с сохранением ID для обратной совместимости */}
        <div
          id="srv-badge"
          onClick={() => refreshServerStatus()}
          title="Нажмите для проверки связи с сервером"
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-sm border font-code text-xs font-semibold cursor-pointer select-none transition-all duration-150 ${
            serverStatus?.active
              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/40 shadow-[0_0_10px_rgba(52,211,153,0.15)] hover:bg-emerald-500/20'
              : 'bg-rose-500/10 text-rose-400 border-rose-500/40 shadow-[0_0_10px_rgba(244,63,94,0.15)] hover:bg-rose-500/20'
          }`}
        >
          {isCheckingStatus ? (
            <RefreshCw className="w-3.5 h-3.5 animate-spin text-current" />
          ) : (
            <Radio className="w-3.5 h-3.5 text-current" />
          )}
          <span>
            {isCheckingStatus
              ? t('checking')
              : serverStatus?.active
              ? t('ts_active')
              : t('ts_inactive')}
          </span>
        </div>
      </div>
    </div>
  );
};
