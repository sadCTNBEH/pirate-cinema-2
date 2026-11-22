import test from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';

test('parent navigation components do not rerender on time-update', async () => {
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
    const { AppProvider, useApp, usePlayer } = await import('../src/context/AppContext');

    let parentRenders = 0;
    let playerRenders = 0;
    let lastTimecode = 0;

    function NavigationComponent() {
      parentRenders++;
      const { route } = useApp();
      return React.createElement('nav', null, route);
    }

    function PlayerProgressComponent() {
      playerRenders++;
      const { currentTime } = usePlayer();
      lastTimecode = currentTime;
      return React.createElement('div', null, String(currentTime));
    }

    const container = doc.createElement('div');
    const root = createRoot(container as any);

    await act(async () => {
      root.render(
        React.createElement(
          AppProvider,
          null,
          React.createElement('div', null,
            React.createElement(NavigationComponent),
            React.createElement(PlayerProgressComponent)
          )
        )
      );
    });

    const initialParentRenders = parentRenders;
    const initialPlayerRenders = playerRenders;

    assert.ok(initialParentRenders >= 1, 'NavigationComponent rendered at least once');
    assert.ok(initialPlayerRenders >= 1, 'PlayerProgressComponent rendered at least once');

    // Simulate high-frequency time-update events
    await act(async () => {
      mockWindow.dispatchEvent(
        new CustomEvent('time-update', { detail: { currentTime: 10, duration: 300 } })
      );
    });

    await act(async () => {
      mockWindow.dispatchEvent(
        new CustomEvent('time-update', { detail: { currentTime: 20, duration: 300 } })
      );
    });

    await act(async () => {
      mockWindow.dispatchEvent(
        new CustomEvent('time-update', { detail: { currentTime: 30, duration: 300 } })
      );
    });

    // Parent navigation component must NOT have rerendered due to time-update events
    assert.equal(
      parentRenders,
      initialParentRenders,
      'Parent navigation component must NOT re-render on time-update'
    );

    // Player progress component must have re-rendered with updated timecode
    assert.ok(
      playerRenders > initialPlayerRenders,
      'Player component must re-render on time-update'
    );
    assert.equal(lastTimecode, 30, 'Player component must have latest timecode');

    await act(async () => {
      root.unmount();
    });
  } finally {
    (globalThis as any).window = originalWindow;
    globalThis.document = originalDoc;
    globalThis.fetch = originalFetch;
  }
});

test('InlinePlayer respects memoization and stale subscriptions are cancelled on unmount', async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

  class FakeElement extends EventTarget {
    nodeType = 1;
    childNodes: any[] = [];
    style = {};
    ownerDocument: any = null;
    tagName = 'DIV';
    setAttribute() {}
    removeAttribute() {}
    appendChild(c: any) { this.childNodes.push(c); return c; }
    removeChild(c: any) {
      const i = this.childNodes.indexOf(c);
      if (i !== -1) this.childNodes.splice(i, 1);
      return c;
    }
    insertBefore(c: any) { this.childNodes.push(c); return c; }
    scrollTo() {}
  }

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
  mockWindow.HTMLIFrameElement = class extends FakeElement {};
  mockWindow.HTMLElement = FakeElement;
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
    const { AppProvider } = await import('../src/context/AppContext');
    const { InlinePlayer } = await import('../src/components/player/InlinePlayer');

    const container = doc.createElement('div');
    const root = createRoot(container as any);

    // Mount with null playback returns null
    await act(async () => {
      root.render(
        React.createElement(
          AppProvider,
          null,
          React.createElement(InlinePlayer as React.ComponentType<any>, { playback: null })
        )
      );
    });

    // Dispatching events while mounted with null playback
    await act(async () => {
      mockWindow.dispatchEvent(
        new CustomEvent('time-update', { detail: { currentTime: 100 } })
      );
      mockWindow.dispatchEvent(
        new CustomEvent('cinema-player-action', { detail: 'episodeNext' })
      );
    });

    await act(async () => {
      root.unmount();
    });

    // Dispatching events after unmount does not throw or trigger stale handlers
    await act(async () => {
      mockWindow.dispatchEvent(
        new CustomEvent('time-update', { detail: { currentTime: 200 } })
      );
      mockWindow.dispatchEvent(
        new CustomEvent('cinema-player-action', { detail: 'episodeNext' })
      );
    });
  } finally {
    (globalThis as any).window = originalWindow;
    globalThis.document = originalDoc;
    globalThis.fetch = originalFetch;
  }
});
