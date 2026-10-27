/**
 * @file App.tsx
 * @description Корневой компонент Pirate Cinema.
 * Содержит сайдбар, основной контейнер страниц и роутер.
 */

import React, { useEffect, useState } from 'react';
import { AppProvider, useApp } from './context/AppContext';
import { Sidebar } from './components/layout/Sidebar';
import { TitleBar } from './components/layout/TitleBar';
import { HomeView } from './components/home/HomeView';
import { MetaView } from './components/meta/MetaView';
import { SearchView } from './components/search/SearchView';
import { LibraryView } from './components/library/LibraryView';
import { CollectionsView } from './components/collections/CollectionsView';
import { HistoryView } from './components/history/HistoryView';
import { TorrentDetailView } from './components/detail/TorrentDetailView';
import { SettingsView } from './components/settings/SettingsView';
import { OnlineView } from './components/online/OnlineView';
import { DiagnosticsView } from './components/diagnostics/DiagnosticsView';
import { RemoteModal } from './components/player/RemoteModal';
import { SettingsModal } from './components/settings/SettingsModal';
import { DiagnosticsModal } from './components/diagnostics/DiagnosticsModal';
import { PipOverlay } from './components/player/PipOverlay';
import { AutostartPromptModal } from './components/settings/AutostartPromptModal';
import { API } from './services/api';
import { InputProvider } from './input/InputProvider';
import './cinema.css';

/**
 * Внутренний контейнер с роутингом
 */
const MainContent: React.FC = () => {
  const { route, navigate, activePlayback, isPip, t } = useApp();
  const [updateBanner, setUpdateBanner] = useState<{ version: string } | null>(null);
  const [bannerDismissed, setBannerDismissed] = useState<boolean>(false);
  const [showAutostartPrompt, setShowAutostartPrompt] = useState<boolean>(false);

  // Проверка первого запуска: предложение автозапуска Windows
  useEffect(() => {
    API.getSettings()
      .then((s) => {
        if (s && s.autostart_prompted === false) {
          setShowAutostartPrompt(true);
        }
      })
      .catch(() => {});
  }, []);

  // Начальная проверка здоровья демона при загрузке (как в оригинальном app.js)
  useEffect(() => {
    API.checkHealth()
      .then((h) => {
        if (h && h.error) {
          alert(h.error);
        }
      })
      .catch(console.error);
  }, []);

  // Неблокирующая фоновая проверка обновлений при старте (TASK-004)
  useEffect(() => {
    let dismissed = false;
    try {
      dismissed = sessionStorage.getItem('update_banner_dismissed') === '1';
    } catch {
      // ignore
    }
    if (dismissed) return;

    const timer = setTimeout(() => {
      API.checkUpdate()
        .then((res) => {
          if (res && res.has_update && res.version) {
            setUpdateBanner({ version: res.version });
          }
        })
        .catch(() => {
          // Игнорируем сетевые сбои при старте
        });
    }, 2000);

    return () => clearTimeout(timer);
  }, []);

  // Отслеживание фокуса на текстовых полях ввода (для корректной работы хоткеев плеера)
  useEffect(() => {
    const onFocusIn = (e: FocusEvent) => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) {
        API.setInputFocused(true);
      }
    };
    const onFocusOut = () => {
      API.setInputFocused(false);
    };
    window.addEventListener('focusin', onFocusIn);
    window.addEventListener('focusout', onFocusOut);
    return () => {
      window.removeEventListener('focusin', onFocusIn);
      window.removeEventListener('focusout', onFocusOut);
    };
  }, []);

  if (isPip) {
    return (
      <div className="h-screen w-screen overflow-hidden bg-transparent select-none">
        <PipOverlay />
      </div>
    );
  }

  return (
    <div className={`cinema-shell flex h-screen overflow-hidden bg-[#06080d] text-slate-100 overscroll-none select-none`}>
      {/* Киберпанк навигация */}
      <Sidebar />

      {/* Основная рабочая область с шапкой TitleBar */}
      <div className="cinema-workspace flex-1 flex flex-col h-screen min-w-0 overflow-hidden bg-[#06080d]">
        <TitleBar />

        {/* Ненавязчивое уведомление о новой версии */}
        {updateBanner && !bannerDismissed && !activePlayback?.isPlaying && route !== 'settings' && (
          <div className="ui-update-banner">
            <div className="flex items-center gap-2.5">
              <span className="w-1.5 h-1.5 rounded-full bg-film-accent" />
              <span className="text-slate-200">
                Доступна новая версия Pirate Cinema —{' '}
                <span className="font-semibold text-film-text">{updateBanner.version}</span>
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  navigate('settings');
                  setBannerDismissed(true);
                }}
                className="cinema-button cinema-button--secondary"
              >
                Подробнее
              </button>
              <button
                onClick={() => {
                  setBannerDismissed(true);
                  try {
                    sessionStorage.setItem('update_banner_dismissed', '1');
                  } catch {
                    // ignore
                  }
                }}
                className="cinema-button cinema-button--quiet"
              >
                Позже
              </button>
            </div>
          </div>
        )}

        <main
          id="page-container"
          className={`flex-1 max-w-[1600px] mx-auto w-full overflow-y-auto overscroll-none bg-[#06080d] ${
            route === 'home' ? 'p-6 md:px-10 md:pb-10 md:pt-6' : 'p-6 md:p-10'
          }`}
        >
          <div className={route === 'home' ? 'block' : 'hidden'}>
            <HomeView />
          </div>
          {route === 'meta' && <MetaView />}
          {route === 'search' && <SearchView />}
          {route === 'library' && <LibraryView />}
          {route === 'collections' && <CollectionsView listName="favorites" />}
          {route === 'watch_later' && <CollectionsView listName="watch_later" />}
          {route === 'history' && <HistoryView />}
          {route === 'online' && <OnlineView />}
          {route === 'detail' && <TorrentDetailView />}
          {route === 'settings' && <SettingsView />}
          {route === 'diagnostics' && <DiagnosticsView />}
        </main>
      </div>

      {/* Модальное окно веб-пульта со смартфоном */}
      <RemoteModal />

      {/* Всплывающее модальное окно настроек */}
      <SettingsModal />

      {/* Всплывающее модальное окно диагностики */}
      <DiagnosticsModal />

      {/* Модальное окно первого запуска: предложение автозапуска Windows */}
      <AutostartPromptModal
        isOpen={showAutostartPrompt}
        onClose={() => setShowAutostartPrompt(false)}
      />
    </div>
  );
};

export default function App() {
  return (
    <AppProvider>
      <div className="cinema-theme contents"><InputProvider><MainContent /></InputProvider></div>
    </AppProvider>
  );
}
