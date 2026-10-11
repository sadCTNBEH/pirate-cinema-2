/**
 * @file App.tsx
 * @description Корневой компонент Pirate Cinema.
 * Содержит сайдбар, основной контейнер страниц и роутер.
 */

import React, { useEffect } from 'react';
import { AppProvider, useApp } from './context/AppContext';
import { Sidebar } from './components/layout/Sidebar';
import { TitleBar } from './components/layout/TitleBar';
import { HomeView } from './components/home/HomeView';
import { MetaView } from './components/meta/MetaView';
import { SearchView } from './components/search/SearchView';
import { LibraryView } from './components/library/LibraryView';
import { TorrentDetailView } from './components/detail/TorrentDetailView';
import { SettingsView } from './components/settings/SettingsView';
import { API } from './services/api';

/**
 * Внутренний контейнер с роутингом
 */
const MainContent: React.FC = () => {
  const { route, t } = useApp();

  // Начальная проверка здоровья демона при загрузке (как в оригинальном app.js)
  useEffect(() => {
    API.checkHealth()
      .then((h) => {
        if (h && h.error) {
          alert(h.error + '\n\n' + (t('ts_download_prompt') || ''));
        }
      })
      .catch(console.error);
  }, [t]);

  return (
    <div className="flex h-screen overflow-hidden bg-[#06080d] text-slate-100 overscroll-none select-none">
      {/* Киберпанк навигация */}
      <Sidebar />

      {/* Основная рабочая область с шапкой TitleBar */}
      <div className="flex-1 flex flex-col h-screen min-w-0 overflow-hidden bg-[#06080d]">
        <TitleBar />

        <main
          id="page-container"
          className="flex-1 max-w-[1600px] mx-auto p-6 md:p-10 w-full overflow-y-auto overscroll-none bg-[#06080d]"
        >
          <div className={route === 'home' ? 'block' : 'hidden'}>
            <HomeView />
          </div>
          {route === 'meta' && <MetaView />}
          {route === 'search' && <SearchView />}
          {route === 'library' && <LibraryView />}
          {route === 'detail' && <TorrentDetailView />}
          {route === 'settings' && <SettingsView />}
        </main>
      </div>
    </div>
  );
};

export default function App() {
  return (
    <AppProvider>
      <MainContent />
    </AppProvider>
  );
}
