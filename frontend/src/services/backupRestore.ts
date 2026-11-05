/**
 * @file services/backupRestore.ts
 * @description Единый сервис и хук для резервного копирования и восстановления данных.
 * Поддерживает нативный pywebview диалог сохранения, браузерное скачивание архива,
 * диалог подтверждения восстановления и обработку отмены и ошибок.
 */

import React, { useState, useRef, useCallback } from 'react';
import { useApp } from '../context/AppContext';
import { API, DEFAULT_FALLBACK_STRINGS } from './api';

export interface BackupHint {
  text: string;
  isError?: boolean;
}

export type TranslateFn = (key: string, opts?: Record<string, string | number>) => string;

export interface PywebviewBackupResult {
  saved: boolean;
  cancelled?: boolean;
  path?: string;
  error?: string;
}

export interface BackupRestoreDeps {
  api?: {
    downloadBackup: () => Promise<Blob>;
    restoreBackup: (file: File) => Promise<void>;
  };
  window?: {
    pywebview?: {
      api?: {
        save_backup?: () => Promise<PywebviewBackupResult>;
      };
    };
    confirm?: (message?: string) => boolean;
    alert?: (message?: string) => void;
    location?: {
      reload: () => void;
    };
    setTimeout?: (handler: () => void, timeout?: number) => number;
  };
  document?: {
    createElement: (tagName: string) => {
      href: string;
      download: string;
      click: () => void;
      remove?: () => void;
      parentNode?: {
        removeChild: (child: unknown) => unknown;
      } | null;
    };
    body: {
      appendChild: (node: unknown) => unknown;
    };
  };
  url?: {
    createObjectURL: (blob: Blob) => string;
    revokeObjectURL: (url: string) => void;
  };
}

export const defaultTranslate: TranslateFn = (key, opts) => {
  const fallback = DEFAULT_FALLBACK_STRINGS[key] || key;
  if (opts) {
    let res = fallback;
    for (const k in opts) {
      res = res.replace(new RegExp(`\\{${k}\\}`, 'g'), String(opts[k]));
    }
    return res;
  }
  return fallback;
};

/**
 * Скачивание архива бэкапа:
 * 1. Через нативный диалог pywebview (если запущен десктопный шелл).
 * 2. Через браузерную ссылку (fallback для веб-режима).
 */
export async function downloadBackup(
  t: TranslateFn = defaultTranslate,
  deps: BackupRestoreDeps = {}
): Promise<BackupHint> {
  const win = deps.window ?? (typeof window !== 'undefined' ? (window as unknown as BackupRestoreDeps['window']) : undefined);
  const doc = deps.document ?? (typeof document !== 'undefined' ? (document as unknown as BackupRestoreDeps['document']) : undefined);
  const api = deps.api ?? API;

  try {
    if (win?.pywebview?.api?.save_backup) {
      const result = await win.pywebview.api.save_backup();
      if (result.cancelled) {
        return {
          text: t('backup_cancelled') || 'Сохранение бэкапа отменено',
        };
      }
      if (!result.saved) {
        throw new Error(result.error || 'Не удалось сохранить бэкап');
      }
      return {
        text:
          t('backup_saved', { path: result.path || '' }) ||
          `Бэкап сохранён: ${result.path}`,
      };
    }

    const backup = await api.downloadBackup();
    const urlObj = deps.url ?? (typeof URL !== 'undefined' ? URL : undefined);
    if (!urlObj || !doc) {
      throw new Error('Не удалось скачать бэкап');
    }
    const objectUrl = urlObj.createObjectURL(backup);
    const link = doc.createElement('a');
    link.href = objectUrl;
    link.download = 'pirate_cinema_backup.zip';
    doc.body.appendChild(link);
    link.click();
    if (typeof link.remove === 'function') {
      link.remove();
    } else if (link.parentNode?.removeChild) {
      link.parentNode.removeChild(link);
    }
    const scheduleRevoke = win?.setTimeout ?? (typeof setTimeout !== 'undefined' ? setTimeout : undefined);
    if (scheduleRevoke) {
      scheduleRevoke(() => urlObj.revokeObjectURL(objectUrl), 1000);
    } else {
      urlObj.revokeObjectURL(objectUrl);
    }
    const savedMsg = t('backup_saved', { path: 'downloads' });
    return {
      text: savedMsg && savedMsg !== 'backup_saved' ? savedMsg : 'Бэкап успешно скачан',
    };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : 'Не удалось скачать бэкап';
    return { text: msg, isError: true };
  }
}

/**
 * Восстановление бэкапа из переданного файла с подтверждением пользователя.
 */
export async function restoreBackup(
  file: File | undefined | null,
  t: TranslateFn = defaultTranslate,
  deps: BackupRestoreDeps = {}
): Promise<{ success: boolean; cancelled?: boolean; error?: string }> {
  if (!file) {
    return { success: false, cancelled: true };
  }

  const win = deps.window ?? (typeof window !== 'undefined' ? (window as unknown as BackupRestoreDeps['window']) : undefined);
  const api = deps.api ?? API;

  const confirmText =
    t('confirm_restore') ||
    'Восстановить конфигурацию и базу данных из архива?';
  const confirmed = typeof win?.confirm === 'function' ? win.confirm(confirmText) : true;
  if (!confirmed) {
    return { success: false, cancelled: true };
  }

  try {
    await api.restoreBackup(file);
    const successMsg = t('restore_success') || 'Данные успешно восстановлены';
    if (typeof win?.alert === 'function') {
      win.alert(successMsg);
    }
    if (typeof win?.location?.reload === 'function') {
      win.location.reload();
    }
    return { success: true };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : 'Ошибка восстановления';
    const translated = t('restore_error', { error: msg });
    const errorMsg = translated && translated !== 'restore_error' ? translated : msg;
    if (typeof win?.alert === 'function') {
      win.alert(errorMsg);
    }
    return { success: false, error: msg };
  }
}

export interface UseBackupRestoreOptions {
  t?: TranslateFn;
  deps?: BackupRestoreDeps;
}

export interface UseBackupRestoreResult {
  isDownloadingBackup: boolean;
  backupHint: BackupHint | null;
  setBackupHint: React.Dispatch<React.SetStateAction<BackupHint | null>>;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  handleDownloadBackup: () => Promise<void>;
  handleUploadBackup: (e: React.ChangeEvent<HTMLInputElement>) => Promise<void>;
}

/**
 * React-хук для управления резервным копированием и восстановлением в UI.
 */
export function useBackupRestore(options?: UseBackupRestoreOptions): UseBackupRestoreResult {
  const { t: appTranslate } = useApp();
  const t = options?.t ?? appTranslate ?? defaultTranslate;

  const [isDownloadingBackup, setIsDownloadingBackup] = useState<boolean>(false);
  const [backupHint, setBackupHint] = useState<BackupHint | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDownloadBackup = useCallback(async () => {
    setIsDownloadingBackup(true);
    setBackupHint(null);
    try {
      const hint = await downloadBackup(t, options?.deps);
      setBackupHint(hint);
    } finally {
      setIsDownloadingBackup(false);
    }
  }, [t, options?.deps]);

  const handleUploadBackup = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

      try {
        await restoreBackup(file, t, options?.deps);
      } finally {
        if (fileInputRef.current) {
          fileInputRef.current.value = '';
        }
      }
    },
    [t, options?.deps]
  );

  return {
    isDownloadingBackup,
    backupHint,
    setBackupHint,
    fileInputRef,
    handleDownloadBackup,
    handleUploadBackup,
  };
}
