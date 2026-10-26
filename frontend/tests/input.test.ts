import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ACTIONS, DEFAULT_BINDINGS, PLAYER_COMMANDS, conflicts, isEditing, keyChord, keyboardAction, matchAction, mergedBindings, reservedKey } from '../src/input/actions';
import { GamepadInput } from '../src/input/gamepad';
import { focusScope, moveFocus, nearestIndex } from '../src/input/focus';
import { editText, isTextField, LAYOUTS } from '../src/input/text';

const key = (code: string, modifiers = {}) => ({ code, ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, ...modifiers });
const pad = (buttons: number[] = [], axes = [0, 0]) => ({ connected: true, mapping: 'standard', axes,
  buttons: Array.from({ length: 16 }, (_, index) => ({ pressed: buttons.includes(index), value: buttons.includes(index) ? 1 : 0 })) }) as unknown as Gamepad;
const rect = (left: number, top: number, width = 100, height = 150) => ({ left, top, width, height, right: left + width, bottom: top + height });

test('spatial navigation follows rows, columns and irregular controls rather than DOM order', () => {
  const grid = [rect(120, 170), rect(0, 170), rect(120, 0), rect(0, 0)];
  assert.equal(nearestIndex(grid[3], grid, 'right'), 2);
  assert.equal(nearestIndex(grid[3], grid, 'down'), 1);
  assert.equal(nearestIndex(grid[0], grid, 'left'), 1);
  assert.equal(nearestIndex(grid[3], grid, 'up'), -1);
  assert.equal(nearestIndex(rect(0, 0, 40, 40), [rect(0, 60, 300, 40), rect(200, 0, 40, 40)], 'down'), 0);
});
test('focus stays inside modal boundaries and scrolls the selected off-screen card into view', () => {
  const previousDocument = globalThis.document, previousStyle = globalThis.getComputedStyle;
  const document = { activeElement: null as any, body: {} as any, querySelectorAll: () => [modal] };
  const make = (r: ReturnType<typeof rect>) => ({
    isConnected: true, tabIndex: 0, scrolled: false,
    getClientRects: () => [r], getBoundingClientRect: () => r,
    closest: () => null, matches: () => false,
    focus() { document.activeElement = this; }, scrollIntoView() { this.scrolled = true; },
  });
  const inside = [make(rect(0, 0)), make(rect(0, 600))];
  const modal = { ...make(rect(0, 0)), querySelectorAll: () => inside };
  (globalThis as any).document = document;
  (globalThis as any).getComputedStyle = () => ({ visibility: 'visible' });
  try {
    document.activeElement = inside[0];
    assert.equal(focusScope(), modal);
    moveFocus('down');
    assert.equal(document.activeElement, inside[1]);
    assert.equal(inside[1].scrolled, true);
    moveFocus('down');
    assert.equal(document.activeElement, inside[1]); // does not escape modal
  } finally { (globalThis as any).document = previousDocument; globalThis.getComputedStyle = previousStyle; }
});
test('pad A confirms once, B goes back; simultaneous stick and D-pad never double fire', () => {
  const reader = new GamepadInput();
  assert.deepEqual(reader.sample([pad([0])], 0, true), ['confirm']);
  assert.deepEqual(reader.sample([pad([0])], 1000, true), []);
  assert.deepEqual(reader.sample([pad([1])], 1010, true), ['back']);
  assert.deepEqual(reader.sample([pad([15], [1, 0])], 1020, true), ['right']);
});
test('pad hold repeats after delay, deadzone ignores noise, disconnect clears held state', () => {
  const reader = new GamepadInput();
  assert.deepEqual(reader.sample([pad([], [0.3, -0.3])], 0, true), []);
  assert.deepEqual(reader.sample([pad([13])], 1, true), ['down']);
  assert.deepEqual(reader.sample([pad([13])], 300, true), []);
  assert.deepEqual(reader.sample([pad([13])], 381, true), ['down']);
  assert.deepEqual(reader.sample([pad([13])], 400, true), []);
  assert.deepEqual(reader.sample([pad([13])], 491, true), ['down']);
  assert.deepEqual(reader.sample([null], 500, true), []);
  assert.deepEqual(reader.sample([pad([13])], 510, true), ['down']);
  assert.deepEqual(reader.sample([pad([0])], 520, false), []);
  assert.deepEqual(reader.sample([pad([0])], 600, true), []); // held while app was inactive
  reader.sample([pad()], 620, true);
  assert.deepEqual(reader.sample([pad([0])], 640, true), ['confirm']);
});
test('pad player buttons and multiple pads map to shared UI/player actions', () => {
  const reader = new GamepadInput();
  assert.deepEqual(reader.sample([pad([3, 4, 6, 9]), pad([9])], 0, true), ['controls', 'sectionPrev', 'seekBack', 'pause']);
  assert.deepEqual(reader.sample([{ ...pad([0]), mapping: 'unknown' } as unknown as Gamepad], 10, true), []);
});
test('hotkey registry retains old MPV defaults and has no conflicting default contexts', () => {
  assert.deepEqual(conflicts(DEFAULT_BINDINGS), []);
  assert.equal(matchAction(key('ArrowLeft'), DEFAULT_BINDINGS, 'player'), 'seekBack');
  assert.equal(matchAction(key('ArrowLeft'), DEFAULT_BINDINGS, 'ui'), 'left');
  assert.equal(matchAction(key('Space'), DEFAULT_BINDINGS, 'player'), 'pause');
  assert.equal(matchAction(key('KeyQ'), DEFAULT_BINDINGS, 'player'), 'stop');
  assert.equal(matchAction(key('Tab'), DEFAULT_BINDINGS, 'ui'), undefined); // preserve native Tab navigation
  assert.deepEqual(PLAYER_COMMANDS.pause, ['cycle', 'pause']);
  assert.deepEqual(PLAYER_COMMANDS.seekForward, ['seek', 10, 'relative']);
  assert.deepEqual(PLAYER_COMMANDS.volumeDown, ['add', 'volume', -5]);
  assert.equal(new Set(ACTIONS.map(a => a[0])).size, ACTIONS.length);
});
test('code-based chords ignore keyboard layout, support modifiers and report conflicts', () => {
  const event = key('KeyK', { ctrlKey: true, altKey: true, shiftKey: true });
  assert.equal(keyChord(event), 'Ctrl+Alt+Shift+KeyK');
  const bindings = mergedBindings({ pause: keyChord(event) });
  assert.equal(matchAction(event, bindings, 'player'), 'pause');
  assert.deepEqual(conflicts({ ...bindings, mute: bindings.pause }), ['pause', 'mute']);
  assert.deepEqual(conflicts({ ...bindings, pause: bindings.confirm }), []); // distinct UI/player modes
  assert.deepEqual(conflicts({ ...bindings, stop: bindings.back }), ['back', 'stop']);
  assert.equal(mergedBindings({ pause: '' }).pause, '');
  assert.equal(matchAction(key('ControlLeft'), mergedBindings({ pause: '' }), 'player'), undefined);
  assert.equal(mergedBindings(JSON.parse(JSON.stringify(bindings))).pause, bindings.pause);
});
test('system shortcuts are left alone and editing targets are detected', () => {
  for (const event of [key('KeyW', { ctrlKey: true }), key('F4', { altKey: true }), key('KeyK', { metaKey: true })]) {
    assert.equal(reservedKey(event), true);
    assert.equal(matchAction(event, { ...DEFAULT_BINDINGS, pause: keyChord(event) }, 'player'), undefined);
  }
  for (const selector of ['input', 'textarea', 'select', '[contenteditable]']) {
    const input = { closest: () => ({ tagName: selector }) } as any;
    assert.equal(isEditing(input), true);
    for (const code of ['Space', 'KeyQ', 'KeyF', 'ArrowLeft', 'ArrowUp']) {
      assert.equal(keyboardAction(key(code), DEFAULT_BINDINGS, 'player', input), undefined);
    }
    assert.equal(keyboardAction(key('Escape'), DEFAULT_BINDINGS, 'ui', input, true), 'back');
  }
  assert.equal(isEditing(null), false);
  assert.equal(isEditing({ closest: () => null } as any), false);
});
test('gamepad text-field confirmation opens one reusable keyboard only for editable inputs', () => {
  for (const tagName of ['INPUT', 'TEXTAREA']) {
    assert.equal(isTextField({ tagName, type: 'text' } as any), true);
    assert.equal(isTextField({ tagName, type: 'text', readOnly: true } as any), false);
    assert.equal(isTextField({ tagName, type: 'text', disabled: true } as any), false);
  }
  for (const type of ['checkbox', 'radio', 'file', 'range', 'date', 'submit']) assert.equal(isTextField({ tagName: 'INPUT', type } as any), false);
  assert.equal(isTextField(null), false);
});
test('reusable text input supports Russian/English, caret, selection, clear and React input events', () => {
  class MockField {
    tagName = 'INPUT'; maxLength = -1; selectionStart = 0; selectionEnd = 0;
    private text = ''; events: string[] = [];
    get value() { return this.text; } set value(value) { this.text = value; }
    dispatchEvent(event: Event) { this.events.push(event.type); return true; }
    setSelectionRange(start: number, end: number) { this.selectionStart = start; this.selectionEnd = end; }
  }
  const previous = (globalThis as any).HTMLInputElement;
  (globalThis as any).HTMLInputElement = MockField;
  try {
    const input = new MockField();
    const field = input as unknown as HTMLInputElement;
    assert.equal(LAYOUTS.ru.join('').includes('я'), true);
    for (const letter of 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя') assert.equal(LAYOUTS.ru.join('').includes(letter), true);
    assert.equal(LAYOUTS.en.join('').includes('q'), true);
    editText(field, 'Привет'); editText(field, ' world');
    assert.equal(input.value, 'Привет world');
    editText(field, '', 'backspace');
    assert.equal(input.value, 'Привет worl');
    input.setSelectionRange(0, 6); editText(field, 'Hello');
    assert.equal(input.value, 'Hello worl');
    editText(field, '', 'clear'); assert.equal(input.value, '');
    editText(field, '😀'); editText(field, '', 'backspace'); assert.equal(input.value, '');
    editText(field, 'abc'); input.maxLength = 3; input.setSelectionRange(1, 1);
    editText(field, 'x'); assert.equal(input.value, 'abc');
    assert.equal(input.events.every(type => type === 'input'), true);
  } finally { (globalThis as any).HTMLInputElement = previous; }
});
