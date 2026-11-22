/**
 * @file services/api/playbackApi.ts
 * @description Доменный модуль API для управления воспроизведением, MPV и окном плеера.
 */

import {
  BackendActivePlayerStatus,
  FileSelectionRequest,
  FileSelectionResponse,
  NextRequest,
  PlayerBounds,
  PlayOnlineRequest,
  PlayOnlineResponse,
  PlayRequest,
  RemoteInfoResponse,
} from '../../types';
import { httpClient } from './client';

let isBoundsUpdating = false;

/**
 * Запуск файла через плеер MPV
 */
export async function playFile(
  payload: PlayRequest | { hash: string; file_id: number; file_name: string; start_time?: number }
): Promise<void> {
  return httpClient.post('/api/player/play', payload, { signal: AbortSignal.timeout(30000) });
}

/**
 * Переключение на следующий файл раздачи в MPV
 */
export async function playNext(payload: NextRequest | { hash: string; file_id: number }): Promise<void> {
  return httpClient.post('/api/player/next', payload);
}

/**
 * Скрытие нативной панели встроенного плеера
 */
export async function hidePlayerPanel(): Promise<void> {
  try {
    if (window.pywebview?.api?.hide_player_panel) {
      await window.pywebview.api.hide_player_panel();
      return;
    }
    await fetch('/api/window/hide_player', { method: 'POST' });
  } catch {
    // Игнорируем в браузерном превью
  }
}

/**
 * Остановка воспроизведения в MPV
 */
export async function stopPlayback(): Promise<void> {
  await hidePlayerPanel();
  return httpClient.post('/api/player/stop', {});
}

/**
 * Получение текущего состояния активного плеера MPV
 */
export async function getActivePlayback(): Promise<BackendActivePlayerStatus> {
  try {
    return await httpClient.get<BackendActivePlayerStatus>('/api/player/active', {
      signal: AbortSignal.timeout(5000),
    });
  } catch {
    return { active: false };
  }
}

/**
 * Переключение полноэкранного режима встроенного плеера
 */
export async function togglePlayerFullscreen(fullscreen?: boolean): Promise<boolean> {
  try {
    const q = fullscreen !== undefined ? `?fullscreen=${fullscreen}` : '';
    const res = await httpClient.post<{ is_fullscreen: boolean }>(`/api/player/fullscreen${q}`, {});
    return !!res.is_fullscreen;
  } catch {
    if (window.pywebview?.api?.toggle_fullscreen) {
      return !!(await window.pywebview.api.toggle_fullscreen());
    }
    return false;
  }
}

/**
 * Переключение режима «Картинка в картинке» (PiP)
 */
export async function togglePip(pip?: boolean): Promise<boolean> {
  try {
    const res = await httpClient.post<{ is_pip: boolean }>('/api/window/pip', { pip });
    return !!res.is_pip;
  } catch {
    if (window.pywebview?.api?.toggle_pip) {
      return !!(await window.pywebview.api.toggle_pip());
    }
    return false;
  }
}

/**
 * Получение данных и QR-кода для мобильного веб-пульта
 */
export async function getRemoteInfo(): Promise<RemoteInfoResponse> {
  return httpClient.get<RemoteInfoResponse>('/api/remote/info');
}

/**
 * Отправка произвольной IPC-команды в MPV (пауза, перемотка, громкость и т.д.)
 */
export async function sendPlayerCommand(command: any[]): Promise<boolean> {
  try {
    await fetch('/api/player/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(command),
    });
    return true;
  } catch {
    return false;
  }
}

/**
 * Синхронизация координат нативной панели MPV с DOM-контейнером
 */
export async function setPlayerBounds(bounds: PlayerBounds): Promise<void> {
  try {
    if (window.pywebview?.api?.set_player_bounds) {
      await window.pywebview.api.set_player_bounds(
        bounds.x,
        bounds.y,
        bounds.width,
        bounds.height,
        bounds.viewport_width,
        bounds.viewport_height,
        bounds.clip_top,
        bounds.clip_left,
        bounds.clip_right,
        bounds.clip_bottom
      );
      return;
    }
    if (isBoundsUpdating) return;
    isBoundsUpdating = true;
    await fetch('/api/window/player_bounds', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(bounds),
    });
  } catch {
    // Игнорируем в браузерном превью
  } finally {
    isBoundsUpdating = false;
  }
}

/**
 * Временное сокрытие нативного плеера (например, при открытии модального окна) без сброса воспроизведения
 */
export async function setPlayerOccluded(occluded: boolean): Promise<boolean> {
  try {
    if (window.pywebview?.api?.set_player_occluded) {
      return !!(await window.pywebview.api.set_player_occluded(occluded));
    }
    const res = await fetch('/api/window/player_occluded', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ occluded }),
    });
    if (res.ok) {
      const data = await res.json();
      return !!data.success;
    }
    return false;
  } catch {
    return false;
  }
}

/**
 * Оповещение о фокусе текстового поля ввода для корректной работы хоткеев плеера
 */
export function setInputFocused(focused: boolean): void {
  try {
    if (window.pywebview?.api?.set_input_focused) {
      window.pywebview.api.set_input_focused(focused).catch(() => {});
      return;
    }
    fetch('/api/window/input_focus', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ focused }),
    }).catch(() => {});
  } catch {
    // ignore
  }
}

/**
 * Восстановление воспроизведения
 */
export async function recoverPlayback(): Promise<{ status: string }> {
  return httpClient.post('/api/player/recover', {});
}

/**
 * Добавление magnet-ссылки в TorrServer
 */
export async function addMagnet(
  magnet: string,
  title: string,
  options?: { signal?: AbortSignal }
): Promise<{ hash: string }> {
  return httpClient.post<{ hash: string }>(
    '/api/player/add_magnet',
    { magnet, title },
    { signal: options?.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000) }
  );
}

/**
 * Алиас: добавление торрента
 */
export async function addTorrent(
  magnet: string,
  title: string,
  options?: { signal?: AbortSignal }
): Promise<{ hash: string }> {
  return addMagnet(magnet, title, options);
}

/**
 * Подбор подходящего файла торрента для воспроизведения серии / сезона
 */
export async function selectTorrentFile(
  request: FileSelectionRequest,
  options?: { signal?: AbortSignal }
): Promise<FileSelectionResponse> {
  return httpClient.post(
    '/api/player/select-file',
    request,
    { signal: options?.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(8000)]) : AbortSignal.timeout(8000) }
  );
}

/**
 * Запуск онлайн-видео в MPV
 */
export async function playOnline(
  payload: PlayOnlineRequest,
  options?: { signal?: AbortSignal }
): Promise<PlayOnlineResponse> {
  return httpClient.post<PlayOnlineResponse>('/api/online/play', payload, options);
}

export const playbackApi = {
  get _isBoundsUpdating() {
    return isBoundsUpdating;
  },
  set _isBoundsUpdating(val: boolean) {
    isBoundsUpdating = val;
  },
  playFile,
  playNext,
  hidePlayerPanel,
  stopPlayback,
  getActivePlayback,
  togglePlayerFullscreen,
  togglePip,
  getRemoteInfo,
  sendPlayerCommand,
  setPlayerBounds,
  setPlayerOccluded,
  setInputFocused,
  recoverPlayback,
  addMagnet,
  addTorrent,
  selectTorrentFile,
  playOnline,
};
