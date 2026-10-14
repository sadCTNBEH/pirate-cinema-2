/**
 * @file context/AppContext.tsx
 * @description Глобальный контекст управления состоянием приложения.
 * Загружает i18n строки напрямую из FastAPI (/api/i18n) без дублирования словарей на клиенте,
 * управляет навигацией (SPA с поддержкой истории), статусом TorrServer и плеером.
 */

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { AppRoute, RouteParams, ServerStatus, ActivePlaybackState } from '../types';
import { API, DEFAULT_FALLBACK_STRINGS } from '../services/api';

interface AppContextValue {
  /** Текущий экран */
  route: AppRoute;
  /** Параметры текущего маршрута */
  routeParams: RouteParams;
  /** Переход на страницу */
  navigate: (route: AppRoute, params?: RouteParams) => void;
  /** Возврат назад по истории */
  goBack: () => void;
  /** Текущий статус демона TorrServer */
  serverStatus: ServerStatus | null;
  /** Индикатор загрузки статуса */
  isCheckingStatus: boolean;
  /** Принудительное обновление статуса сервера */
  refreshServerStatus: () => Promise<void>;
  /** Функция локализации, использующая словарь с бэкенда */
  t: (key: string, opts?: Record<string, string | number>) => string;
  /** Перезагрузка языковых строк с бэкенда */
  reloadI18n: () => Promise<void>;
  /** Текущий активный язык из бэкенда */
  lang: string;
  /** Состояние встроенного плеера */
  activePlayback: ActivePlaybackState | null;
  /** Запуск встроенного плеера на текущей странице */
  openPlayback: (payload: Omit<ActivePlaybackState, 'isPlaying'>) => void;
  /** Остановка и закрытие встроенного плеера */
  closePlayback: () => Promise<void>;
}

const AppContext = createContext<AppContextValue | null>(null);

export const AppProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [route, setRoute] = useState<AppRoute>('home');
  const [routeParams, setRouteParams] = useState<RouteParams>({});
  const [history, setHistory] = useState<Array<{ route: AppRoute; params?: RouteParams; scroll: number }>>([]);
  const [activePlayback, setActivePlayback] = useState<ActivePlaybackState | null>(null);

  // Языковые строки и язык загружаются исключительно с бэкенда FastAPI
  const [strings, setStrings] = useState<Record<string, string>>({});
  const [lang, setLang] = useState<string>('ru');

  // Состояние доступности TorrServer
  const [serverStatus, setServerStatus] = useState<ServerStatus | null>(null);
  const [isCheckingStatus, setIsCheckingStatus] = useState<boolean>(false);

  /**
   * Загрузка словаря строк из FastAPI (/api/i18n)
   */
  const reloadI18n = useCallback(async () => {
    try {
      const data = await API.getI18n();
      if (data && data.strings) {
        setStrings(data.strings);
      }
      if (data && data.lang) {
        setLang(data.lang);
      }
    } catch (err) {
      console.warn('Не удалось загрузить /api/i18n из бэкенда:', err);
    }
  }, []);

  useEffect(() => {
    reloadI18n();
  }, [reloadI18n]);

  useEffect(() => {
    let dismissed = false;
    let frontendHealthy = false;
    let disposed = false;
    const dismissSplash = () => {
      if (
        dismissed ||
        !frontendHealthy ||
        !window.pywebview?.api?.dismiss_startup_splash
      ) {
        return;
      }
      dismissed = true;
      window.pywebview.api.dismiss_startup_splash().catch(() => {});
    };

    const confirmFrontendHealth = async () => {
      try {
        const response = await fetch('/api/settings/health', { cache: 'no-store' });
        if (!disposed && response.ok) {
          frontendHealthy = true;
          dismissSplash();
        }
      } catch {
        // The splash stays visible while the desktop backend is unavailable.
      }
    };

    void confirmFrontendHealth();
    window.addEventListener('pywebviewready', confirmFrontendHealth);
    const retryId = window.setInterval(() => {
      dismissSplash();
      if (!frontendHealthy) {
        void confirmFrontendHealth();
      }
    }, 1000);
    return () => {
      disposed = true;
      window.removeEventListener('pywebviewready', confirmFrontendHealth);
      window.clearInterval(retryId);
    };
  }, []);

  /**
   * Функция подстановки строк с поддержкой шаблонов {key}
   * Точно как в оригинальном app.js
   */
  const t = useCallback(
    (key: string, opts?: Record<string, string | number>): string => {
      let res = strings[key] || DEFAULT_FALLBACK_STRINGS[key] || key;
      if (opts) {
        for (const k in opts) {
          res = res.replace(new RegExp(`\\{${k}\\}`, 'g'), String(opts[k]));
        }
      }
      return res;
    },
    [strings]
  );

  /**
   * Опрос состояния TorrServer
   */
  const refreshServerStatus = useCallback(async () => {
    setIsCheckingStatus(true);
    try {
      const s = await API.getServerStatus();
      setServerStatus(s);
    } catch {
      setServerStatus({ active: false });
    } finally {
      setIsCheckingStatus(false);
    }
  }, []);

  useEffect(() => {
    refreshServerStatus();
    // Фоновый опрос здоровья сервера раз в 45 сек
    const timer = setInterval(refreshServerStatus, 45000);
    return () => clearInterval(timer);
  }, [refreshServerStatus]);

  /**
   * Запуск встроенного плеера
   */
  const openPlayback = useCallback((payload: Omit<ActivePlaybackState, 'isPlaying'>) => {
    setActivePlayback({
      ...payload,
      isPlaying: true,
    });
  }, []);

  /**
   * Закрытие встроенного плеера и остановка MPV
   */
  const closePlayback = useCallback(async () => {
    setActivePlayback(null);
    try {
      await API.stopPlayback();
    } catch {
      // Игнорируем сбои остановки
    }
  }, []);

  /**
   * SPA-навигация с сохранением истории и скролла
   */
  const navigate = useCallback((nextRoute: AppRoute, params: RouteParams = {}) => {
    if (activePlayback) {
      setActivePlayback(null);
      API.stopPlayback().catch(() => {});
    }
    const container = document.getElementById('page-container');
    const scrollPos = container ? container.scrollTop : window.scrollY;
    setHistory((prev) => [...prev, { route, params: routeParams, scroll: scrollPos }]);
    setRoute(nextRoute);
    setRouteParams(params);
    if (container) {
      container.scrollTo({ top: 0, behavior: 'instant' });
    } else {
      window.scrollTo({ top: 0, behavior: 'instant' });
    }
  }, [route, routeParams, activePlayback]);

  /**
   * Возврат на предыдущую страницу
   */
  const goBack = useCallback(() => {
    if (activePlayback) {
      setActivePlayback(null);
      API.stopPlayback().catch(() => {});
    }
    setHistory((prev) => {
      const container = document.getElementById('page-container');
      if (prev.length === 0) {
        setRoute('home');
        setRouteParams({});
        if (container) {
          container.scrollTo({ top: 0, behavior: 'instant' });
        } else {
          window.scrollTo({ top: 0, behavior: 'instant' });
        }
        return [];
      }
      const last = prev[prev.length - 1];
      const remaining = prev.slice(0, -1);
      setRoute(last.route);
      setRouteParams(last.params || {});
      setTimeout(() => {
        const el = document.getElementById('page-container');
        if (el) {
          el.scrollTo({ top: last.scroll || 0, behavior: 'instant' });
        } else {
          window.scrollTo({ top: last.scroll || 0, behavior: 'instant' });
        }
      }, 0);
      return remaining;
    });
  }, [activePlayback]);

  return (
    <AppContext.Provider
      value={{
        route,
        routeParams,
        navigate,
        goBack,
        serverStatus,
        isCheckingStatus,
        refreshServerStatus,
        t,
        reloadI18n,
        lang,
        activePlayback,
        openPlayback,
        closePlayback,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp must be used inside AppProvider');
  return context;
};

