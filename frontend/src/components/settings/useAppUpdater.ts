/**
 * @file components/settings/useAppUpdater.ts
 * @description Хук управления проверкой, скачиванием и установкой обновлений приложения.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { API } from '../../services/api';
import { UpdateCheckResponse, UpdateStatusResponse } from '../../types';

export const formatBytes = (bytes?: number | null): string => {
  if (!bytes || bytes <= 0) return '0 МБ';
  const mb = bytes / (1024 * 1024);
  return `${mb.toFixed(1)} МБ`;
};

export function useAppUpdater(appVersion: string) {
  const [updateCheck, setUpdateCheck] = useState<UpdateCheckResponse | null>(null);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatusResponse | null>(null);
  const [isCheckingUpdate, setIsCheckingUpdate] = useState<boolean>(false);
  const [showApplyModal, setShowApplyModal] = useState<boolean>(false);
  const [isApplying, setIsApplying] = useState<boolean>(false);
  const [applyMessage, setApplyMessage] = useState<string | null>(null);
  const pollIntervalRef = useRef<number | null>(null);

  useEffect(() => {
    API.getUpdateStatus()
      .then((status) => {
        if (status) {
          setUpdateStatus(status);
        }
      })
      .catch(() => {});

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (updateStatus && (updateStatus.state === 'downloading' || updateStatus.state === 'verifying')) {
      if (!pollIntervalRef.current) {
        pollIntervalRef.current = window.setInterval(async () => {
          try {
            const st = await API.getUpdateStatus();
            setUpdateStatus(st);
            if (st.state !== 'downloading' && st.state !== 'verifying') {
              if (pollIntervalRef.current) {
                clearInterval(pollIntervalRef.current);
                pollIntervalRef.current = null;
              }
            }
          } catch {
            // игнорируем сетевые ошибки во время polling
          }
        }, 600);
      }
    } else {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    }
  }, [updateStatus?.state]);

  const handleCheckUpdates = useCallback(async () => {
    setIsCheckingUpdate(true);
    try {
      const checkRes = await API.checkUpdate();
      setUpdateCheck(checkRes);
      const st = await API.getUpdateStatus();
      setUpdateStatus(st);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Ошибка проверки обновлений';
      setUpdateCheck({
        current_version: appVersion,
        has_update: false,
        version: '',
        release_notes: '',
        download_url: '',
        release_url: '',
        asset_name: '',
        can_auto_update: false,
        reason: msg,
      });
    } finally {
      setIsCheckingUpdate(false);
    }
  }, [appVersion]);

  const handleStartDownload = useCallback(async () => {
    try {
      const st = await API.startUpdateDownload();
      setUpdateStatus(st);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Не удалось запустить скачивание обновления';
      setUpdateStatus({
        state: 'failed',
        downloaded_bytes: 0,
        progress_percent: 0,
        can_auto_update: false,
        error: msg,
      });
    }
  }, []);

  const handleCancelDownload = useCallback(async () => {
    try {
      const st = await API.cancelUpdateDownload();
      setUpdateStatus(st);
    } catch (err) {
      console.warn('Cancel download error:', err);
    }
  }, []);

  const handleApplyUpdate = useCallback(async () => {
    setIsApplying(true);
    try {
      const actionRes = await API.applyUpdate(false);
      setApplyMessage(actionRes.message || 'Обновление запущено. Приложение перезапускается...');
      setShowApplyModal(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Не удалось применить обновление';
      setIsApplying(false);
      setUpdateStatus((prev) => ({
        state: 'failed',
        downloaded_bytes: prev?.downloaded_bytes || 0,
        progress_percent: 100,
        can_auto_update: false,
        error: msg,
      }));
      setShowApplyModal(false);
    }
  }, []);

  return {
    updateCheck,
    updateStatus,
    isCheckingUpdate,
    showApplyModal,
    setShowApplyModal,
    isApplying,
    applyMessage,
    handleCheckUpdates,
    handleStartDownload,
    handleCancelDownload,
    handleApplyUpdate,
    formatBytes,
  };
}
