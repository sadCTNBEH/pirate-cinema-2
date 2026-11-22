/**
 * @file services/api/index.ts
 * @description Централизованный агрегатор модулей API платформы Pirate Cinema.
 * Предоставляет изолированные доменные модули (playbackApi, libraryApi, searchApi, settingsApi)
 * и монолитный объект API для обратной совместимости.
 */

import { DiagnosticsResponse } from '../../types';
import { httpClient } from './client';
import { libraryApi } from './libraryApi';
import { playbackApi } from './playbackApi';
import { searchApi } from './searchApi';
import { settingsApi } from './settingsApi';

export * from './client';
export * from './playbackApi';
export * from './libraryApi';
export * from './searchApi';
export * from './settingsApi';

/**
 * Единый API объект для сохранения обратной совместимости со всеми существующими компонентами.
 */
export const API = {
  ...httpClient,
  ...settingsApi,
  ...playbackApi,
  ...libraryApi,
  ...searchApi,
};

export type API = typeof API;

/**
 * Получение системной диагностики (GET /api/diagnostics)
 * Экспорт функции в соответствии со спецификацией TASK-003.1
 */
export async function getDiagnostics(signal?: AbortSignal): Promise<DiagnosticsResponse> {
  return settingsApi.getSystemDiagnostics(signal);
}

export default API;
