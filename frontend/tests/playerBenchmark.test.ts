import test from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';

test('benchmark: player component time-to-first-render and high-frequency time-update throughput', async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

  class FakeElement extends EventTarget {
    nodeType = 1;
    childNodes: any[] = [];
    style = {};
    ownerDocument: any = null;
    tagName = 'DIV';

    setAttribute() {}
    removeAttribute() {}
    appendChild(c: any) {
      this.childNodes.push(c);
      return c;
    }
    removeChild(c: any) {
      const i = this.childNodes.indexOf(c);
      if (i !== -1) this.childNodes.splice(i, 1);
      return c;
    }
    insertBefore(c: any) {
      this.childNodes.push(c);
      return c;
    }
    scrollTo() {}
  }

  globalThis.HTMLElement = FakeElement as any;
  (globalThis as any).HTMLIFrameElement = class extends FakeElement {};
  (globalThis as any).HTMLInputElement = class extends FakeElement {};

  const doc = new FakeElement() as any;
  doc.nodeType = 9;
  doc.createElement = (tag: string) => {
    const el = new FakeElement();
    el.tagName = tag.toUpperCase();
    el.ownerDocument = doc;
    return el;
  };
  doc.createTextNode = (text: string) => ({ nodeType: 3, nodeValue: text, ownerDocument: doc });
  doc.documentElement = doc.createElement('html');
  doc.body = doc.createElement('body');
  globalThis.document = doc;

  const mockWindow = new EventTarget() as any;
  mockWindow.document = doc;
  mockWindow.HTMLIFrameElement = (globalThis as any).HTMLIFrameElement;
  mockWindow.HTMLElement = globalThis.HTMLElement;
  mockWindow.addEventListener = mockWindow.addEventListener.bind(mockWindow);
  mockWindow.removeEventListener = mockWindow.removeEventListener.bind(mockWindow);
  mockWindow.dispatchEvent = mockWindow.dispatchEvent.bind(mockWindow);
  mockWindow.setInterval = globalThis.setInterval.bind(globalThis);
  mockWindow.clearInterval = globalThis.clearInterval.bind(globalThis);
  mockWindow.setTimeout = globalThis.setTimeout.bind(globalThis);
  mockWindow.clearTimeout = globalThis.clearTimeout.bind(globalThis);
  mockWindow.scrollTo = () => {};

  const originalWindow = globalThis.window;
  const originalDoc = globalThis.document;
  const originalFetch = globalThis.fetch;

  (globalThis as any).window = mockWindow;
  globalThis.fetch = (async () => ({
    ok: true,
    text: async () => JSON.stringify({ strings: {}, lang: 'ru' }),
    json: async () => ({ strings: {}, lang: 'ru' }),
  })) as any;

  try {
    const { AppProvider, usePlayer } = await import('../src/context/AppContext');

    let renderCount = 0;
    let lastRenderedTime = 0;

    function BenchmarkPlayerTracker() {
      renderCount++;
      const { currentTime, duration } = usePlayer();
      lastRenderedTime = currentTime;
      return React.createElement(
        'div',
        { 'data-testid': 'player-timecode' },
        `${currentTime}/${duration}`
      );
    }

    const container = doc.createElement('div');
    const root = createRoot(container as any);

    // 1. Measure Time to First Render (TTFR)
    const tStart = performance.now();
    await act(async () => {
      root.render(
        React.createElement(
          AppProvider,
          null,
          React.createElement(BenchmarkPlayerTracker)
        )
      );
    });
    const ttfrMs = performance.now() - tStart;

    assert.ok(renderCount >= 1, 'Player tracker must render initially');
    assert.ok(ttfrMs < 50, `Time to first render (${ttfrMs.toFixed(2)}ms) must be under 50ms`);

    // 2. Measure high-frequency (60fps simulation) timeline update throughput
    const iterations = 60;
    const tUpdatesStart = performance.now();

    for (let i = 1; i <= iterations; i++) {
      await act(async () => {
        mockWindow.dispatchEvent(
          new CustomEvent('time-update', {
            detail: { currentTime: i * 0.5, duration: 300 },
          })
        );
      });
    }

    const tUpdatesDuration = performance.now() - tUpdatesStart;
    const avgPerUpdateMs = tUpdatesDuration / iterations;
    const effectiveFps = iterations / (tUpdatesDuration / 1000);

    assert.equal(lastRenderedTime, iterations * 0.5, 'Tracker must record latest timecode');
    assert.ok(effectiveFps > 0, 'Effective update rate must be positive');
    assert.ok(
      avgPerUpdateMs < 10,
      `Average timecode update latency (${avgPerUpdateMs.toFixed(2)}ms) must be < 10ms`
    );

    // Cleanup
    await act(async () => {
      root.unmount();
    });
  } finally {
    (globalThis as any).window = originalWindow;
    globalThis.document = originalDoc;
    globalThis.fetch = originalFetch;
  }
});
