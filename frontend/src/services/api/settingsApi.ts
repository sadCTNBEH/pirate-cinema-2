/**
 * @file services/api/settingsApi.ts
 * @description Доменный модуль API для настроек, системного статуса, локализации, диагностики и обновлений.
 */

import {
  DiagnosticsResponse,
  ServerStatus,
  SettingsUpdate,
  SystemDiagnostics,
  SystemSettings,
  TorrServerDiagnostics,
  UpdateActionResponse,
  UpdateCheckResponse,
  UpdateInfo,
  UpdateStatusResponse,
} from '../../types';
import { DEFAULT_FALLBACK_STRINGS, httpClient } from './client';

/**
 * Загрузка словаря локализации и текущего языка из FastAPI
 */
export async function getI18n(): Promise<{ strings: Record<string, string>; lang: string }> {
  try {
    const data = await httpClient.get<{ strings: Record<string, string>; lang: string }>('/api/i18n');
    if (data && data.strings) return data;
    return { strings: DEFAULT_FALLBACK_STRINGS, lang: 'ru' };
  } catch {
    return { strings: DEFAULT_FALLBACK_STRINGS, lang: 'ru' };
  }
}

/**
 * Получение состояния демона TorrServer
 */
export async function getServerStatus(): Promise<ServerStatus> {
  try {
    return await httpClient.get<ServerStatus>('/api/settings/status');
  } catch {
    return { active: false, message: 'Офлайн' };
  }
}

/**
 * Получение текущих настроек приложения
 */
export async function getSettings(): Promise<SystemSettings> {
  try {
    return await httpClient.get<SystemSettings>('/api/settings');
  } catch {
    return {
      torrserver_url: 'http://127.0.0.1:18765',
      language: 'ru',
      jackett_url: 'http://127.0.0.1:9117/api/v2.0/indexers/all/results/torznab',
      jackett_api_key: '',
      yummyanime_public_key: 'bz7uk_nr9bouyrn9',
      yummyanime_private_key: '',
    };
  }
}

/**
 * Обновление настроек приложения
 */
export async function updateSettings(settings: SettingsUpdate): Promise<any> {
  try {
    return await httpClient.post('/api/settings', settings);
  } catch (e) {
    console.warn('updateSettings warn:', e);
    return { success: true };
  }
}

/**
 * Сохранение настроек (псевдоним updateSettings)
 */
export async function saveSettings(settings: SettingsUpdate): Promise<any> {
  return updateSettings(settings);
}

/**
 * Проверка наличия обновлений приложения (legacy settings)
 */
export async function checkUpdates(): Promise<UpdateInfo> {
  try {
    return await httpClient.get<UpdateInfo>('/api/settings/updates');
  } catch {
    return {
      has_update: false,
      latest: 'v2.0.0',
      url: '',
    };
  }
}

/**
 * Получение базовой системной диагностики (legacy)
 */
export async function getDiagnostics(): Promise<SystemDiagnostics> {
  try {
    return await httpClient.get<SystemDiagnostics>('/api/settings/diagnostics');
  } catch {
    return {
      torrserver_version: 'Офлайн',
      mpv_path: 'Офлайн',
      db_size: 0,
      last_error: null,
    };
  }
}

/**
 * Получение полной системной диагностики (GET /api/diagnostics)
 */
export async function getSystemDiagnostics(signal?: AbortSignal): Promise<DiagnosticsResponse> {
  return httpClient.get<DiagnosticsResponse>('/api/diagnostics', { signal });
}

/**
 * Перезапуск TorrServer
 */
export async function restartTorrServer(): Promise<TorrServerDiagnostics> {
  return httpClient.post<TorrServerDiagnostics>('/api/diagnostics/torrserver/restart', {});
}

/**
 * Проверка обновлений TorrServer
 */
export async function checkTorrServerUpdate(): Promise<{
  latest_version: string;
  release_url: string;
  update_available: boolean | null;
}> {
  return httpClient.post('/api/diagnostics/torrserver/check-update', {});
}

/**
 * Получение лога TorrServer
 */
export async function getTorrServerLog(): Promise<string> {
  const response = await fetch('/api/diagnostics/torrserver/log');
  const text = await response.text();
  if (!response.ok) {
    let message = text;
    try {
      message = JSON.parse(text).detail || text;
    } catch {}
    throw new Error(message);
  }
  return text;
}

/**
 * Проверка здоровья сервисов
 */
export async function checkHealth(): Promise<{ error?: string }> {
  try {
    return await httpClient.get<{ error?: string }>('/api/settings/health');
  } catch {
    return {};
  }
}

/**
 * Запрос к бэкенду на открытие папки с данными в проводнике
 */
export async function openFolder(): Promise<void> {
  try {
    await fetch('/api/settings/open_folder', { method: 'POST' });
  } catch {
    // Игнорируем в автономном режиме
  }
}

/**
 * Скачивание резервной копии конфигурации в ZIP-архиве
 */
export async function downloadBackup(): Promise<Blob> {
  return httpClient.downloadBackup();
}

/**
 * Загрузка резервной копии конфигурации
 */
export async function restoreBackup(file: File): Promise<void> {
  const res = await fetch('/api/settings/restore', {
    method: 'POST',
    body: file,
    headers: { 'Content-Type': 'application/zip' },
  });
  if (!res.ok) {
    throw new Error(await res.text());
  }
}

// ─── In-App Updater API (TASK-004) ───

export async function checkUpdate(signal?: AbortSignal): Promise<UpdateCheckResponse> {
  return httpClient.get<UpdateCheckResponse>('/api/updater/check', { signal });
}

export async function getUpdateStatus(signal?: AbortSignal): Promise<UpdateStatusResponse> {
  return httpClient.get<UpdateStatusResponse>('/api/updater/status', { signal });
}

export async function startUpdateDownload(): Promise<UpdateStatusResponse> {
  return httpClient.post<UpdateStatusResponse>('/api/updater/download');
}

export async function applyUpdate(dryRun: boolean = false): Promise<UpdateActionResponse> {
  return httpClient.post<UpdateActionResponse>('/api/updater/apply', { dry_run: dryRun });
}

export async function cancelUpdateDownload(): Promise<UpdateStatusResponse> {
  return httpClient.post<UpdateStatusResponse>('/api/updater/cancel');
}

export const settingsApi = {
  getI18n,
  getServerStatus,
  getSettings,
  updateSettings,
  saveSettings,
  checkUpdates,
  getDiagnostics,
  getSystemDiagnostics,
  restartTorrServer,
  checkTorrServerUpdate,
  getTorrServerLog,
  checkHealth,
  openFolder,
  downloadBackup,
  restoreBackup,
  checkUpdate,
  getUpdateStatus,
  startUpdateDownload,
  applyUpdate,
  cancelUpdateDownload,
};
