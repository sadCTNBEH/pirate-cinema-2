/**
 * @file components/diagnostics/useDiagnostics.ts
 * @description Хук загрузки, периодического обновления и действий управления для системной диагностики.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { DiagnosticsResponse } from '../../types';
import { API } from '../../services/api';
import { useApp } from '../../context/AppContext';

export function useDiagnostics() {
  const { t } = useApp();
  const [data, setData] = useState<DiagnosticsResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [staleWarning, setStaleWarning] = useState<string | null>(null);
  const [serviceAction, setServiceAction] = useState<'restart' | 'update' | 'log' | null>(null);
  const [serviceMessage, setServiceMessage] = useState<string | null>(null);
  const [tsLog, setTsLog] = useState<string | null>(null);
  const [tsUpdate, setTsUpdate] = useState<{
    latest_version: string;
    release_url: string;
    update_available: boolean | null;
  } | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  const loadDiagnostics = useCallback(
    async (isManualRefresh: boolean = false) => {
      // Защита от параллельных дублирующих запросов
      if (isManualRefresh && (isRefreshing || isLoading)) {
        return;
      }

      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      const controller = new AbortController();
      abortControllerRef.current = controller;

      if (isManualRefresh) {
        setIsRefreshing(true);
      } else {
        setIsLoading(true);
      }

      try {
        const res = await API.getSystemDiagnostics(controller.signal);
        setData(res);
        setError(null);
        setStaleWarning(null);
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          return;
        }

        const msg =
          err instanceof Error
            ? err.message
            : 'Не удалось подключиться к серверу';

        if (data) {
          // Если старые данные уже есть — сохраняем их и показываем предупреждение
          const timeStr = data.checked_at
            ? new Date(data.checked_at).toLocaleTimeString()
            : '';
          setStaleWarning(
            t('diag_stale_warning', { time: timeStr }) ||
              `Отображаются устаревшие данные от ${timeStr}. Ошибка: ${msg}`
          );
        } else {
          // Данных нет вообще — показываем экран ошибки
          setError(msg);
        }
      } finally {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    },
    [data, isLoading, isRefreshing, t]
  );

  const loadRef = useRef(loadDiagnostics);
  loadRef.current = loadDiagnostics;

  const runServiceAction = useCallback(
    async (action: 'restart' | 'update' | 'log') => {
      if (serviceAction) return;
      setServiceAction(action);
      setServiceMessage(null);
      try {
        if (action === 'restart') {
          await API.restartTorrServer();
          setServiceMessage('TorrServer перезапущен');
          await loadRef.current(true);
        } else if (action === 'update') {
          setTsUpdate(await API.checkTorrServerUpdate());
        } else {
          setTsLog(tsLog === null ? await API.getTorrServerLog() : null);
        }
      } catch (actionErr: unknown) {
        const msg = actionErr instanceof Error ? actionErr.message : 'Операция не выполнена';
        setServiceMessage(msg);
      } finally {
        setServiceAction(null);
      }
    },
    [serviceAction, tsLog]
  );

  useEffect(() => {
    void loadDiagnostics(false);
    const timer = window.setInterval(() => {
      if (!document.hidden) void loadRef.current(true);
    }, 10000);

    return () => {
      window.clearInterval(timer);
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  return {
    data,
    isLoading,
    isRefreshing,
    error,
    staleWarning,
    serviceAction,
    serviceMessage,
    tsLog,
    tsUpdate,
    loadDiagnostics,
    runServiceAction,
  };
}
