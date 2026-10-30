export const ACTIONS = [
  ['up', 'Вверх', 'ui', 'ArrowUp'], ['down', 'Вниз', 'ui', 'ArrowDown'],
  ['left', 'Влево', 'ui', 'ArrowLeft'], ['right', 'Вправо', 'ui', 'ArrowRight'],
  ['confirm', 'Выбрать', 'ui', 'Enter'], ['back', 'Назад / закрыть', 'all', 'Escape'],
  ['sectionPrev', 'Предыдущий раздел', 'ui', 'BracketLeft'],
  ['sectionNext', 'Следующий раздел', 'ui', 'BracketRight'],
  ['pause', 'Пауза / продолжить', 'player', 'Space'],
  ['seekBack', 'Назад на шаг перемотки', 'player', 'ArrowLeft'],
  ['seekForward', 'Вперёд на шаг перемотки', 'player', 'ArrowRight'],
  ['volumeUp', 'Громче', 'player', 'ArrowUp'], ['volumeDown', 'Тише', 'player', 'ArrowDown'],
  ['mute', 'Выключить звук', 'player', 'KeyM'], ['fullscreen', 'Полный экран', 'player', 'KeyF'],
  ['pip', 'Картинка в картинке', 'player', 'KeyP'],
  ['stop', 'Закрыть плеер', 'player', 'KeyQ'],
  ['episodePrev', 'Предыдущая серия', 'player', 'PageUp'],
  ['episodeNext', 'Следующая серия', 'player', 'PageDown'],
  ['controls', 'Панель управления плеером', 'all', 'KeyC'],
] as const;
export type Action = typeof ACTIONS[number][0];
export type Bindings = Record<Action, string>;
export const DEFAULT_BINDINGS = Object.fromEntries(ACTIONS.map(([id, , , key]) => [id, key])) as Bindings;
export const PLAYER_COMMANDS: Partial<Record<Action, unknown[]>> = {
  pause: ['cycle', 'pause'], mute: ['cycle', 'mute'],
  seekBack: ['cinema-step', -1], seekForward: ['cinema-step', 1],
  volumeUp: ['add', 'volume', 5], volumeDown: ['add', 'volume', -5],
};
export type KeyInput = Pick<KeyboardEvent, 'code' | 'ctrlKey' | 'altKey' | 'shiftKey' | 'metaKey'>;
export function keyChord(e: KeyInput): string {
  if (/^(Control|Shift|Alt|Meta)/.test(e.code)) return '';
  return [e.ctrlKey && 'Ctrl', e.altKey && 'Alt', e.shiftKey && 'Shift', e.code].filter(Boolean).join('+');
}
export function reservedKey(e: KeyInput): boolean {
  return e.metaKey || ['F1', 'F5', 'F6', 'F10', 'F11', 'F12', 'PrintScreen'].includes(e.code)
    || (e.altKey && ['Tab', 'F4', 'Space', 'Escape', 'ArrowLeft', 'ArrowRight', 'Home'].includes(e.code))
    || (e.ctrlKey && ['KeyW', 'KeyT', 'KeyN', 'KeyL', 'KeyR', 'KeyP', 'KeyS', 'KeyO', 'KeyF', 'KeyI', 'KeyJ', 'KeyU', 'Tab', 'Escape', 'Delete'].includes(e.code));
}
export function mergedBindings(value?: Record<string, string>): Bindings {
  return Object.fromEntries(ACTIONS.map(([id]) => [id, typeof value?.[id] === 'string' ? value[id] : DEFAULT_BINDINGS[id]])) as Bindings;
}
export function conflicts(bindings: Bindings): Action[] {
  return ACTIONS.filter(([id, , scope]) => bindings[id] && ACTIONS.some(([other, , otherScope]) =>
    other !== id && bindings[other] === bindings[id] && (scope === otherScope || scope === 'all' || otherScope === 'all')
  )).map(([id]) => id);
}
export function matchAction(e: KeyInput, bindings: Bindings, context: 'ui' | 'player'): Action | undefined {
  if (reservedKey(e)) return;
  const chord = keyChord(e);
  if (!chord) return;
  return ACTIONS.find(([id, , scope]) => (scope === context || scope === 'all') && bindings[id] === chord)?.[0];
}
export function isEditing(element: Element | null): boolean {
  return !!element?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])');
}
export function keyboardAction(e: KeyInput, bindings: Bindings, context: 'ui' | 'player', target: Element | null, dialog = false): Action | undefined {
  const action = matchAction(e, bindings, context);
  return isEditing(target) && !(dialog && action === 'back') ? undefined : action;
}
