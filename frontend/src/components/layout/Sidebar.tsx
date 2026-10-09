/**
 * @file components/layout/Sidebar.tsx
 * @description Боковая панель навигации приложения Pirate Cinema.
 */

import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import { AppRoute } from '../../types';
import { SegaPirate } from '../ui/SegaPirate';
import {
  NavCatalogIcon,
  NavSearchIcon,
  NavLibraryIcon,
  NavSettingsIcon,
} from '../ui/NavIcons';
import { Radio } from 'lucide-react';

export const Sidebar: React.FC = () => {
  const { route, navigate, serverStatus, t } = useApp();
  const [appVersion, setAppVersion] = useState<string>('v0.0.5');

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
      renderIcon: (active) => <NavCatalogIcon active={active} />,
    },
    {
      id: 'search',
      labelKey: 'nav_search',
      renderIcon: (active) => <NavSearchIcon active={active} />,
    },
    {
      id: 'library',
      labelKey: 'nav_library',
      renderIcon: (active) => <NavLibraryIcon active={active} />,
    },
    {
      id: 'settings',
      labelKey: 'nav_settings',
      renderIcon: (active) => <NavSettingsIcon active={active} />,
    },
  ];

  return (
    <aside className="w-64 min-w-[256px] h-screen sticky top-0 bg-[#080c14]/95 border-r border-slate-800/80 flex flex-col justify-between p-4 z-40 select-none backdrop-blur-md">
      {/* ── ЛОГОТИП С SEGA ПИРАТОМ И ВЕРСИЕЙ ИЗ VERSION.JSON ── */}
      <div>
        <div
          onClick={() => navigate('home')}
          className="flex items-center gap-3.5 px-2 py-3 mb-6 rounded-md hover:bg-slate-800/30 transition-all cursor-pointer group"
        >
          {/* Портрет пирата в стиле SEGA */}
          <div className="relative shrink-0 w-12 h-12 rounded-lg bg-[#080c16] border border-cyan-500/30 flex items-center justify-center shadow-[0_0_12px_rgba(0,240,255,0.15)] group-hover:border-cyan-400 group-hover:shadow-[0_0_18px_rgba(0,240,255,0.3)] transition-all overflow-hidden p-0.5">
            <SegaPirate size={44} />
          </div>

          <div className="min-w-0">
            <h1 className="font-tech font-bold text-base tracking-wider text-slate-100 uppercase leading-tight truncate flex items-center gap-1.5">
              <span>Pirate</span>
              <span className="text-cyan-400">Cinema</span>
            </h1>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
              <span className="font-code text-[11px] text-slate-400 font-medium tracking-wide truncate">
                {appVersion}
              </span>
            </div>
          </div>
        </div>

        {/* ── НАВИГАЦИОННОЕ МЕНЮ С АНИМИРОВАННЫМИ ИКОНКАМИ ── */}
        <nav className="space-y-1.5">
          {navItems.map((item) => {
            const isActive = route === item.id;
            return (
              <button
                key={item.id}
                onClick={() => navigate(item.id)}
                data-page={item.id}
                className={`w-full flex items-center gap-3.5 px-3.5 py-3 rounded-md font-tech text-sm tracking-wide transition-all duration-200 cursor-pointer text-left relative overflow-hidden group ${
                  isActive
                    ? 'bg-gradient-to-r from-cyan-500/15 via-cyan-500/5 to-transparent text-cyan-300 border-l-2 border-cyan-400 font-semibold shadow-[inset_0_1px_0_0_rgba(255,255,255,0.05)]'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40 border-l-2 border-transparent'
                }`}
              >
                <span
                  className={`transition-colors duration-200 ${
                    isActive ? 'text-cyan-400' : 'text-slate-500 group-hover:text-slate-300'
                  }`}
                >
                  {item.renderIcon(isActive)}
                </span>
                <span className="truncate uppercase tracking-wider">{t(item.labelKey)}</span>
              </button>
            );
          })}
        </nav>
      </div>

      {/* ── СТАТУС TORRSERVER В ПОДВАЛЕ ── */}
      <div className="pt-4 border-t border-slate-800/80">
        <div className="p-3 bg-[#05080f] border border-slate-800/90 rounded-lg">
          <div className="flex items-center justify-between mb-1.5">
            <span className="font-code text-[11px] text-slate-400 flex items-center gap-1.5 uppercase tracking-wider">
              <Radio className="w-3.5 h-3.5 text-cyan-400" />
              TorrServer
            </span>
            <span
              className={`inline-block w-2 h-2 rounded-full ${
                serverStatus?.active
                  ? 'bg-emerald-400 shadow-[0_0_8px_#34d399]'
                  : 'bg-rose-500 shadow-[0_0_8px_#f43f5e]'
              }`}
            />
          </div>
          <div className="font-code text-xs font-medium text-slate-200 truncate">
            {serverStatus?.active ? t('ts_active') : t('ts_inactive')}
          </div>
        </div>
      </div>
    </aside>
  );
};
