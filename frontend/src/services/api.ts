/**
 * @file services/api.ts
 * @description Реэкспорт и тонкая обертка для обратной совместимости с доменными модулями API.
 * Доменные модули вынесены в `frontend/src/services/api/`:
 * - playbackApi: управление воспроизведением, MPV и окном плеера
 * - libraryApi: медиатека, коллекции, история, торренты
 * - searchApi: поиск раздач, метаданных и онлайн-видео
 * - settingsApi: системные настройки, статус, локализация, диагностика, обновления
 */

export * from './api/index';
export { default } from './api/index';
