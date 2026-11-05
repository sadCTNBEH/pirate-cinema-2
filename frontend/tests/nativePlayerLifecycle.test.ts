import test from 'node:test';
import assert from 'node:assert/strict';
import { observeNativePlayerBounds } from '../src/components/player/useNativePlayer';

test('native bounds observer coalesces events and releases timers, listeners and observer on unmount', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const windowTarget = new EventTarget();
  const page = new EventTarget();
  const removeWindowListener = t.mock.method(windowTarget, 'removeEventListener');
  const removePageListener = t.mock.method(page, 'removeEventListener');
  const slot = {} as HTMLDivElement;
  const observed: unknown[] = [];
  const cancelled: number[] = [];
  let queued = 0;
  let disconnected = false;
  const globals = {
    window: windowTarget,
    document: { getElementById: () => page },
    requestAnimationFrame: () => ++queued,
    cancelAnimationFrame: (id: number) => cancelled.push(id),
    ResizeObserver: class {
      observe(target: unknown) { observed.push(target); }
      disconnect() { disconnected = true; }
    },
  };
  for (const [key, value] of Object.entries(globals)) {
    const original = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { value, configurable: true });
    t.after(() => {
      if (original) Object.defineProperty(globalThis, key, original);
      else Reflect.deleteProperty(globalThis, key);
    });
  }

  let syncs = 0;
  const cleanup = observeNativePlayerBounds(slot, () => syncs++);
  assert.deepEqual(observed, [slot, page]);
  windowTarget.dispatchEvent(new Event('resize'));
  windowTarget.dispatchEvent(new Event('scroll'));
  page.dispatchEvent(new Event('scroll'));
  assert.equal(queued, 1);

  cleanup();
  assert.equal(disconnected, true);
  assert.deepEqual(cancelled, [1]);
  assert.deepEqual(removeWindowListener.mock.calls.map(call => call.arguments[0]), ['resize', 'scroll']);
  assert.deepEqual(removePageListener.mock.calls.map(call => call.arguments[0]), ['scroll']);
  t.mock.timers.tick(100);
  windowTarget.dispatchEvent(new Event('resize'));
  windowTarget.dispatchEvent(new Event('scroll'));
  page.dispatchEvent(new Event('scroll'));
  assert.equal(queued, 1);
  assert.equal(syncs, 1);
});
