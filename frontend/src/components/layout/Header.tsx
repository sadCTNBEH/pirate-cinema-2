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
    <header className="ui-page-header">
      <h1>{customTitle || t(titleKey)}</h1>
      <button type="button" id="srv-badge" className="ui-server-status" onClick={() => refreshServerStatus()} title="Проверить связь с сервером" disabled={isCheckingStatus}>
        {isCheckingStatus ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Radio className={`w-4 h-4 ${serverStatus?.active ? 'text-emerald-300' : 'text-film-muted'}`} />}
        <span>{isCheckingStatus ? t('checking') : serverStatus?.active ? t('ts_active') : t('ts_inactive')}</span>
      </button>
    </header>
  );
};
