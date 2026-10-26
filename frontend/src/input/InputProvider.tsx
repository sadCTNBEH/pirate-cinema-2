import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { useApp } from '../context/AppContext';
import { API } from '../services/api';
import { ACTIONS, Action, Bindings, DEFAULT_BINDINGS, conflicts, isEditing, keyChord, keyboardAction, mergedBindings, PLAYER_COMMANDS, reservedKey } from './actions';
import { candidates, focusElement, focusScope, moveFocus, visible } from './focus';
import { GamepadInput } from './gamepad';
import { ScreenKeyboard } from './ScreenKeyboard';
import { isTextField, type TextField } from './text';

type InputContext = { bindings: Bindings; save: (bindings: Bindings) => Promise<void>; recording: Action | null; record: (action: Action | null) => void; error: string };
const Context = createContext<InputContext | null>(null);
export const useInput = () => useContext(Context)!;

export function InputProvider({ children }: { children: React.ReactNode }) {
  const app = useApp();
  const [bindings, setBindings] = useState<Bindings>({ ...DEFAULT_BINDINGS });
  const [recording, record] = useState<Action | null>(null);
  const [error, setError] = useState('');
  const [field, setField] = useState<TextField | null>(null);
  const [controls, setControls] = useState(false);
  const [padName, setPadName] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const keyboardHandler = useRef<((action: Action) => void) | null>(null);
  const nativeActive = useRef(false);
  const routeFocus = useRef(new Map<string, { element: HTMLElement; text: string }>());
  const current = useRef<(action: Action, gamepad?: boolean) => void>(() => {});
  const latest = useRef({ bindings, recording, field, controls, app });
  latest.current = { bindings, recording, field, controls, app };
  const save = async (next: Bindings) => {
    if (conflicts(next).length) throw new Error('Сочетание уже используется в этом режиме');
    // Do not use the legacy helper which reports success on failed requests.
    await API.post('/api/settings', { hotkeys: next });
    setBindings(next); setError('');
  };
  useEffect(() => { let cancelled = false; API.getSettings().then(s => { if (!cancelled) setBindings(mergedBindings(s.hotkeys)); }); return () => { cancelled = true; }; }, []);
  const closeKeyboard = () => { setField(null); if (field?.isConnected) field.focus({ preventScroll: true }); };
  const run = (action: Action, gamepad = false) => {
    if (gamepad) document.documentElement.dataset.inputMode = 'gamepad';
    if (recording) { if (action === 'back') record(null); return; }
    if (field && gamepad) { keyboardHandler.current?.(action); return; }
    const scope = focusScope();
    if (action === 'back') {
      if (field) { closeKeyboard(); return; }
      const close = scope !== document.body ? scope.querySelector<HTMLElement>('[data-dialog-close]') : null;
      if (close) { close.click(); return; }
      if (controls) { setControls(false); return; }
      if (app.activePlayback) {
        API.getActivePlayback().then(status => {
          if (status.is_fullscreen) API.togglePlayerFullscreen(false);
          else if (app.isPip) app.togglePip(false);
          else if (gamepad) app.goBack();
        });
        return;
      }
      app.goBack(); return;
    }
    if (gamepad && app.activePlayback && !controls && scope === document.body
        && ['left', 'right', 'up', 'down', 'confirm'].includes(action)) { setControls(true); return; }
    if (['left', 'right', 'up', 'down'].includes(action)) { moveFocus(action as 'left'); return; }
    if (action === 'confirm') {
      let active = document.activeElement as HTMLElement;
      if (!candidates().includes(active)) { active = candidates()[0]; focusElement(active); }
      if (!active) return;
      if (gamepad && isTextField(active)) {
        setField(active); return;
      }
      if (gamepad && active instanceof HTMLSelectElement) {
        // Render native select options in the same focus/navigation system.
        window.dispatchEvent(new CustomEvent('cinema-select', { detail: active })); return;
      }
      active.click(); return;
    }
    if (action === 'sectionNext' || action === 'sectionPrev') {
      if (app.activePlayback && scope === document.body) {
        window.dispatchEvent(new CustomEvent('cinema-player-action', { detail: action === 'sectionNext' ? 'episodeNext' : 'episodePrev' }));
        return;
      }
      const tablist = document.activeElement?.closest('[role="tablist"]') || Array.from(scope.querySelectorAll<HTMLElement>('[role="tablist"]')).find(visible);
      const tabs = tablist ? tablist.querySelectorAll<HTMLElement>('[role="tab"]') : scope.querySelectorAll<HTMLElement>('[data-page]');
      if (tabs.length) {
        const array = Array.from(tabs).filter(visible);
        if (!array.length) return;
        const at = array.findIndex(e => e === document.activeElement || e.getAttribute('data-page') === app.route || e.getAttribute('aria-selected') === 'true');
        const next = array[(Math.max(at, 0) + (action === 'sectionNext' ? 1 : array.length - 1)) % array.length];
        focusElement(next); next.click();
      } else moveFocus(action === 'sectionNext' ? 'right' : 'left');
      return;
    }
    if (!app.activePlayback) return;
    if (action === 'controls') { setControls(!controls); return; }
    if (action === 'stop') { setControls(false); app.closePlayback(); return; }
    if (action === 'fullscreen') { API.togglePlayerFullscreen(); return; }
    if (PLAYER_COMMANDS[action]) { API.sendPlayerCommand(PLAYER_COMMANDS[action]!); return; }
    window.dispatchEvent(new CustomEvent('cinema-player-action', { detail: action }));
  };
  current.current = run;
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      const state = latest.current;
      if (e.defaultPrevented || e.isComposing || reservedKey(e)) return;
      document.documentElement.dataset.inputMode = 'keyboard';
      if (state.recording) {
        e.preventDefault(); e.stopImmediatePropagation();
        const chord = keyChord(e);
        if (!chord || e.repeat) return;
        const next = { ...state.bindings, [state.recording]: chord };
        if (conflicts(next).length) { setError('Конфликт: сочетание уже используется'); return; }
        save(next).then(() => record(null)).catch(err => setError(String(err.message)));
        return;
      }
      if (state.field) {
        if (e.code === 'Escape') { e.preventDefault(); setField(null); }
        return; // The real field retains DOM focus while the pad uses a visual key cursor.
      }
      const scope = focusScope();
      if (e.code === 'Tab' && !e.ctrlKey && !e.altKey && scope !== document.body
          && !keyboardAction(e, state.bindings, 'ui', null)) {
        const elements = candidates(scope);
        const index = elements.indexOf(document.activeElement as HTMLElement);
        e.preventDefault(); e.stopImmediatePropagation();
        focusElement(elements[(index + (e.shiftKey ? elements.length - 1 : 1)) % elements.length]);
        return;
      }
      const context = state.app.activePlayback && !state.controls && focusScope() === document.body ? 'player' : 'ui';
      const target = isEditing(document.activeElement) ? document.activeElement : e.target as Element;
      const action = keyboardAction(e, state.bindings, context, target, focusScope() !== document.body);
      if (!action || (e.repeat && !['left', 'right', 'up', 'down', 'seekBack', 'seekForward', 'volumeUp', 'volumeDown'].includes(action))) return;
      e.preventDefault(); e.stopImmediatePropagation(); current.current(action);
    };
    const nativeKey = (event: Event) => handleKey(new KeyboardEvent('keydown', { ...(event as CustomEvent).detail }));
    const nativeFocus = (event: Event) => { nativeActive.current = !!(event as CustomEvent).detail; };
    const mouseMode = () => { document.documentElement.dataset.inputMode = 'mouse'; };
    const focusChanged = (event: FocusEvent) => {
      if (latest.current.field && event.target !== latest.current.field) setField(null);
      const element = event.target as HTMLElement;
      if (element.closest?.('#page-container')) {
        routeFocus.current.set(latest.current.app.route, { element, text: element.textContent || '' });
      }
    };
    window.addEventListener('keydown', handleKey, true);
    window.addEventListener('cinema-native-key', nativeKey);
    window.addEventListener('cinema-native-focus', nativeFocus);
    window.addEventListener('focusin', focusChanged);
    window.addEventListener('pointerdown', mouseMode);
    return () => { window.removeEventListener('keydown', handleKey, true); window.removeEventListener('cinema-native-key', nativeKey); window.removeEventListener('cinema-native-focus', nativeFocus); window.removeEventListener('focusin', focusChanged); window.removeEventListener('pointerdown', mouseMode); };
  }, []);
  useEffect(() => {
    if (document.documentElement.dataset.inputMode !== 'gamepad') return;
    const frame = requestAnimationFrame(() => {
      if (focusScope() !== document.body) return;
      const main = document.getElementById('page-container');
      if (!main) return;
      const saved = routeFocus.current.get(app.route);
      const elements = candidates(main);
      const restored = saved && (visible(saved.element) ? saved.element : elements.find(element => element.tagName === saved.element.tagName && element.textContent === saved.text));
      focusElement(restored || elements[0]);
    });
    return () => cancelAnimationFrame(frame);
  }, [app.route, app.routeParams]);
  useEffect(() => {
    if (!navigator.getGamepads) return;
    const reader = new GamepadInput();
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    let lastPad = '';
    const tick = () => {
      if (stopped) return;
      const pads = Array.from(navigator.getGamepads());
      const pad = pads.find(p => p?.connected && (!p.mapping || p.mapping === 'standard'));
      if (lastPad !== (pad?.id || '')) { lastPad = pad?.id || ''; setPadName(lastPad); }
      const active = !document.hidden && (document.hasFocus() || nativeActive.current);
      for (const action of reader.sample(pads, performance.now(), active)) current.current(action, true);
      timer = setTimeout(tick, pad && active ? 32 : 1000);
    };
    const wake = () => { clearTimeout(timer); reader.reset(true); tick(); };
    tick();
    window.addEventListener('gamepadconnected', wake); window.addEventListener('gamepaddisconnected', wake);
    window.addEventListener('focus', wake); document.addEventListener('visibilitychange', wake);
    return () => { stopped = true; clearTimeout(timer); reader.reset(); window.removeEventListener('gamepadconnected', wake); window.removeEventListener('gamepaddisconnected', wake); window.removeEventListener('focus', wake); document.removeEventListener('visibilitychange', wake); };
  }, []);
  // Restore focus when routes/dialogs replace the active element; confine focus to top modal.
  useEffect(() => {
    let previousScope = focusScope();
    const stack: { scope: HTMLElement; focused: HTMLElement }[] = [];
    const observer = new MutationObserver(() => {
      const scope = focusScope();
      setDialogOpen(scope !== document.body);
      if (latest.current.field) { if (!latest.current.field.isConnected) setField(null); return; }
      if (scope !== previousScope) {
        const restoreIndex = stack.findIndex(entry => entry.scope === scope);
        if (restoreIndex >= 0) {
          const [restore] = stack.splice(restoreIndex);
          if (restore.focused && visible(restore.focused)) focusElement(restore.focused);
        } else if (scope !== document.body) stack.push({ scope: previousScope, focused: document.activeElement as HTMLElement });
        previousScope = scope;
        if (scope !== document.body && !scope.contains(document.activeElement)) focusElement(candidates(scope)[0]);
      }
      if (document.documentElement.dataset.inputMode === 'gamepad' && (!scope.contains(document.activeElement) || document.activeElement === document.body)) focusElement(candidates(scope)[0]);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);
  return <Context.Provider value={{ bindings, save, recording, record, error }}>
    {children}
    {padName && <div className="fixed bottom-1 left-2 z-40 text-[10px] text-slate-400 pointer-events-none">Геймпад · A выбор · B назад · Y панель · Start пауза</div>}
    {controls && app.activePlayback && <div role="dialog" aria-modal="true" aria-label="Управление плеером" className="fixed inset-0 z-[90] flex items-center justify-center bg-black/90 p-6">
      <div className="max-w-xl max-h-[90vh] overflow-y-auto rounded-xl border border-cyan-500/50 bg-[#070b14] p-6 space-y-4">
        <h2 className="font-tech text-cyan-300">Управление плеером</h2>
        <div className="grid grid-cols-2 gap-3">{ACTIONS.filter(([id, , scope]) => scope === 'player' || id === 'controls').map(([id, label]) =>
          <button key={id} className="rounded border border-cyan-500/40 p-3 hover:bg-cyan-900/40" data-dialog-close={id === 'controls' || undefined} onClick={() => run(id)}>{id === 'controls' ? 'Вернуться к видео' : label}</button>)}</div>
      </div>
    </div>}
    <SelectDialog />
    {field && <ScreenKeyboard field={field} onClose={closeKeyboard} handler={keyboardHandler} />}
    <NativeOcclusion extra={!!field || controls || dialogOpen} />
  </Context.Provider>;
}

function NativeOcclusion({ extra }: { extra: boolean }) {
  const { isAnyModalOpen } = useApp();
  useEffect(() => { API.setPlayerOccluded(extra || isAnyModalOpen); }, [extra, isAnyModalOpen]);
  return null;
}

function SelectDialog() {
  const [select, setSelect] = useState<HTMLSelectElement | null>(null);
  useEffect(() => { const open = (e: Event) => setSelect((e as CustomEvent).detail); window.addEventListener('cinema-select', open); return () => window.removeEventListener('cinema-select', open); }, []);
  if (!select) return null;
  const close = () => { setSelect(null); focusElement(select); };
  return <div role="dialog" aria-modal="true" aria-label="Выбор значения" className="fixed inset-0 z-[95] flex items-center justify-center bg-black/90 p-6">
    <div className="max-h-[80vh] overflow-y-auto min-w-64 rounded-xl border border-cyan-500/50 bg-[#070b14] p-4 space-y-2">
      {Array.from(select.options).map((option, index) => <button key={index} disabled={option.disabled} className="block w-full rounded border border-slate-700 p-3 text-left" onClick={() => {
        Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')?.set?.call(select, option.value);
        select.dispatchEvent(new Event('change', { bubbles: true })); close();
      }}>{option.selected ? '✓ ' : ''}{option.text}</button>)}
      <button data-dialog-close className="block w-full p-3" onClick={close}>Закрыть</button>
    </div>
  </div>;
}
