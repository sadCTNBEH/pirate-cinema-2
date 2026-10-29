import { useCallback, useEffect, useReducer } from 'react';
import { API } from './api';

type Entry = { data: unknown; updated: number };
type Flight = { controller: AbortController; promise: Promise<void> };
const STORAGE = 'pc_catalog_swr_v1';
const entries = new Map<string, Entry>();
const listeners = new Map<string, Set<() => void>>();
const flights = new Map<string, Flight>();
const retryAfter = new Map<string, number>();
const DAY = 86400000;
let restored = false;

function persist() {
  const now = Date.now();
  for (const [key, entry] of entries) if (now - entry.updated > 30 * DAY) entries.delete(key);
  while (entries.size > 64 || JSON.stringify([...entries]).length > 1024 * 1024) entries.delete(entries.keys().next().value!);
  try { sessionStorage.setItem(STORAGE, JSON.stringify([...entries])); } catch { /* memory cache still works */ }
}
function restore() {
  if (restored) return;
  restored = true;
  try {
    const raw = sessionStorage.getItem(STORAGE);
    if (!raw || raw.length > 1024 * 1024) return;
    for (const [key, value] of JSON.parse(raw)) {
      if (typeof key === 'string' && value && Number.isFinite(value.updated) && value.updated <= Date.now() && Date.now() - value.updated < 30 * DAY) entries.set(key, value);
    }
    persist();
  } catch { /* empty or unavailable storage */ }
}

export function readCatalog<T>(key: string, maxAge = 7 * DAY): T | undefined {
  restore();
  const entry = entries.get(key);
  return entry && Date.now() - entry.updated <= maxAge ? entry.data as T : undefined;
}

/** Replace the old Home session cache with one bounded, parameter-aware SWR path. */
export function refreshCatalog(key: string, freshFor: number, force = false): Promise<void> {
  restore();
  const entry = entries.get(key);
  if (!force && entry && Date.now() - entry.updated < freshFor) return Promise.resolve();
  const existing = flights.get(key);
  if (existing) return existing.promise;
  if (!force && Date.now() < (retryAfter.get(key) || 0)) return Promise.resolve();
  const controller = new AbortController();
  const save = (data: unknown, stale: boolean, age: number) => {
    if (controller.signal.aborted) return;
    const old = entries.get(key);
    if (Array.isArray(data) && Array.isArray(old?.data)) {
      const previous = new Map(old.data.map(item => [item.id, item]));
      data = data.map(item => JSON.stringify(previous.get(item.id)) === JSON.stringify(item) ? previous.get(item.id) : item);
    }
    const unchanged = old && JSON.stringify(old.data) === JSON.stringify(data);
    entries.delete(key);
    entries.set(key, { data: unchanged ? old.data : data, updated: Date.now() - Math.max(age * 1000, stale ? freshFor + 1 : 0) });
    retryAfter.delete(key);
    persist();
    if (!unchanged) listeners.get(key)?.forEach(notify => notify());
  };
  const request = async (wait: boolean) => {
    let stale = false, age = 0;
    const data = await API.get<unknown>(`${key}&refresh=${wait}`, {
      signal: controller.signal, cache: 'no-store',
      onResponse: response => {
        stale = response.headers.get('X-Catalog-Stale') === '1';
        const seconds = Number(response.headers.get('X-Catalog-Age'));
        age = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
      },
    });
    save(data, stale, age);
    if (stale && wait) retryAfter.set(key, Date.now() + 60000);
    return stale;
  };
  const promise = (async () => {
    // With no browser cache, get persisted server data before waiting on a provider.
    const waiting = Boolean(entry);
    const stale = await request(waiting);
    if (stale && !waiting && !controller.signal.aborted) await request(true);
  })()
    .catch(error => {
      if (error?.name !== 'AbortError') {
        if (retryAfter.size >= 64) retryAfter.delete(retryAfter.keys().next().value!);
        retryAfter.set(key, Date.now() + 60000);
      }
    })
    .finally(() => {
      if (flights.get(key)?.controller !== controller) return;
      flights.delete(key);
      listeners.get(key)?.forEach(notify => notify());
    });
  flights.set(key, { controller, promise });
  return promise;
}

export function useCatalog<T>(key: string | null, freshFor = DAY, maxAge = 7 * DAY) {
  const [, update] = useReducer(value => value + 1, 0);
  useEffect(() => {
    if (!key) return;
    const notify = () => update();
    const set = listeners.get(key) || new Set<() => void>();
    set.add(notify); listeners.set(key, set);
    void refreshCatalog(key, freshFor).then(notify);
    const online = () => { void refreshCatalog(key, freshFor).then(notify); };
    window.addEventListener('online', online);
    return () => {
      set.delete(notify);
      if (!set.size) listeners.delete(key);
      window.removeEventListener('online', online);
      // React StrictMode may immediately subscribe again to the same shared request.
      queueMicrotask(() => {
        if (!listeners.has(key)) {
          const flight = flights.get(key);
          flights.delete(key);
          flight?.controller.abort();
        }
      });
    };
  }, [key, freshFor]);
  const reload = useCallback(() => {
    if (!key) return Promise.resolve();
    retryAfter.delete(key);
    const pending = refreshCatalog(key, freshFor, true);
    update();
    return pending.then(() => update());
  }, [key, freshFor]);
  const data = key ? readCatalog<T>(key, maxAge) : undefined;
  return { data, loading: Boolean(key && data === undefined && !retryAfter.has(key)), reload };
}
