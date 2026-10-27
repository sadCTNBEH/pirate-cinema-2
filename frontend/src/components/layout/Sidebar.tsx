/**
 * @file components/layout/Sidebar.tsx
 * @description Боковая панель навигации приложения Pirate Cinema.
 */

import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import { AppRoute } from '../../types';
import { Activity, Clock3, Heart, History, Radio, Tv, Smartphone, Search, Library, Clapperboard, Settings } from 'lucide-react';

export const Sidebar: React.FC = () => {
  const {
    route,
    navigate,
    serverStatus,
    isRemoteOpen,
    setIsRemoteOpen,
    isSettingsOpen,
    setIsSettingsOpen,
    isDiagnosticsOpen,
    setIsDiagnosticsOpen,
    t,
  } = useApp();
  const [appVersion, setAppVersion] = useState<string>(__APP_VERSION__);

  /**
   * Загрузка актуальной версии приложения из version.json
   */
  useEffect(() => {
    fetch('/version.json')
      .then((res) => {
        if (!res.ok) throw new Error('version.json not found');
        return res.json();
      })
      .then((data) => {
        if (data && data.version) {
          setAppVersion(data.version);
        }
      })
      .catch(() => {});
  }, []);

  const navItems: Array<{
    id: AppRoute;
    labelKey: string;
    renderIcon: (active: boolean) => React.ReactNode;
  }> = [
    {
      id: 'home',
      labelKey: 'nav_catalog',
      renderIcon: () => <Clapperboard />,
    },
    {
      id: 'search',
      labelKey: 'nav_search',
      renderIcon: () => <Search />,
    },
    {
      id: 'library',
      labelKey: 'nav_library',
      renderIcon: () => <Library />,
    },
    {
      id: 'collections',
      labelKey: 'nav_collections',
      renderIcon: (active) => <Heart className={`w-5 h-5 ${active ? 'fill-current' : ''}`} />,
    },
    {
      id: 'watch_later',
      labelKey: 'nav_watch_later',
      renderIcon: () => <Clock3 className="w-5 h-5" />,
    },
    {
      id: 'history',
      labelKey: 'nav_history',
      renderIcon: () => <History className="w-5 h-5" />,
    },
    {
      id: 'online',
      labelKey: 'nav_online',
      renderIcon: () => <Tv className="w-5 h-5" />,
    },
  ];

    const icons = { home: Clapperboard, search: Search, library: Library, collections: Heart, watch_later: Clock3, history: History, online: Tv };
    return (
      <aside className="cinema-sidebar" aria-label="Навигация">
        <button type="button" className="cinema-brand" onClick={() => navigate('home')} aria-label="Pirate Cinema — главная">
          <img src="/logo.png" alt="" />
          <span>Pirate Cinema<small>{appVersion}</small></span>
        </button>
        <nav aria-label="Разделы">
          {navItems.map(item => {
            const Icon = icons[item.id as keyof typeof icons];
            const active = route === item.id || (route === 'meta' && item.id === 'home');
            return <button type="button" key={item.id} data-page={item.id} aria-current={active ? 'page' : undefined} title={t(item.labelKey)} onClick={() => navigate(item.id)}><Icon aria-hidden="true" /><span>{t(item.labelKey)}</span></button>;
          })}
        </nav>
        <div className="cinema-sidebar-tools">
          <button type="button" title={t('remote') || 'Пульт'} aria-pressed={isRemoteOpen} onClick={() => setIsRemoteOpen(!isRemoteOpen)}><Smartphone aria-hidden="true" /><span>{t('remote') || 'Пульт'}</span></button>
          <button type="button" title={t('nav_diagnostics')} aria-pressed={isDiagnosticsOpen} onClick={() => setIsDiagnosticsOpen(!isDiagnosticsOpen)}><Activity aria-hidden="true" /><span>{t('nav_diagnostics')}</span></button>
          <button type="button" title={t('nav_settings')} aria-pressed={isSettingsOpen} onClick={() => setIsSettingsOpen(!isSettingsOpen)}><Settings aria-hidden="true" /><span>{t('nav_settings')}</span></button>
          <button type="button" className="cinema-server" onClick={() => setIsDiagnosticsOpen(true)} title={serverStatus?.active ? t('ts_active') : t('ts_inactive')}><Radio aria-hidden="true" className={serverStatus?.active ? 'cinema-server--online' : ''} /><span>{serverStatus?.active ? t('ts_active') : t('ts_inactive')}</span></button>
        </div>
      </aside>
    );
};
