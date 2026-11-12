import { useEffect, useState } from 'react';
type ProtectionStatus = { supported: boolean; initialized: boolean; installed: boolean; enabled: boolean; active: boolean; version: string; runtime: string; error: string };
export type AdguardStatus = ProtectionStatus & (
  { mode?: undefined } |
  { mode: 'qt'; blocked: number; updating: boolean; updatedAt: number; exceptions: string[]; exceptionError?: string }
);

export function supportsH264AacMse(): boolean {
  try {
    const type='video/mp4; codecs="avc1.42E01E, mp4a.40.2"';
    return !!document.createElement('video').canPlayType(type) &&
      typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported(type);
  } catch { return false; }
}

export type AnimePlayerPhase = 'loading' | 'page_loaded' | 'ready' | 'playing' | 'error';
export function animegoPlayerStatus(origin: string, payload: unknown): {phase: AnimePlayerPhase; message: string} | null {
  if (origin !== location.origin || !payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
  const data = payload as {type?: unknown; phase?: unknown; message?: unknown};
  if (data.type !== 'pc-anime-player-state' ||
      !['loading','page_loaded','ready','playing','error'].includes(String(data.phase))) return null;
  return {phase: data.phase as AnimePlayerPhase, message: typeof data.message === 'string' ? data.message.slice(0,180) : ''};
}

export async function prepareWebPlayer(player: string): Promise<string | null> {
  const api = window.pywebview?.api;
  if (!api?.adguard_player_scope) return null;
  const lease = crypto.randomUUID();
  const state = await api.adguard_player_scope(player, lease);
  if (state.mode === 'qt') return null;
  if (state.enabled && state.error) throw new Error(`AdGuard: ${state.error}`);
  return lease;
}

export function releaseWebPlayer(lease: string | null) {
  if (lease) void window.pywebview?.api?.adguard_release_player?.(lease).catch(() => {});
}

export function isKodikOrigin(origin: string) {
  try { const url = new URL(origin); return url.protocol === 'https:' && /(^|\.)kodik(player)?\.(com|info|biz|cc)$/.test(url.hostname); }
  catch { return false; }
}

export function preferredYummyPlayer<T extends {player: string; dubbing: string}>(items: T[], voice?: string): T | undefined {
  for (const pattern of [/cvh|chv/i, /alloha/i, /kodik/i]) {
    const candidates=items.filter(item=>pattern.test(item.player));
    if(candidates.length)return candidates.find(item=>item.dubbing===voice) || candidates[0];
  }
  return items.find(item=>item.dubbing===voice) || items[0];
}

export function playerEnded(player: string, url: string, origin: string, payload: unknown): boolean {
  try {
    if (origin !== new URL(url, location.href).origin) return false;
    const data = typeof payload === 'string' ? JSON.parse(payload) : payload;
    if (!data || typeof data !== 'object' || Array.isArray(data)) return false;
    if (/kodik/i.test(player)) return isKodikOrigin(origin) && data.key === 'kodik_player_video_ended';
    if (/cvh|chv/i.test(player)) return data.key === 'player_video_ended';
    if (/alloha/i.test(player)) return origin === 'https://alloha.yani.tv' && data.type === 'pc-alloha' && data.event === 'ended';
  } catch { /* Malformed provider message. */ }
  return false;
}

export function playerStarted(player: string, url: string, origin: string, payload: unknown): boolean {
  try {
    if (origin !== new URL(url, location.href).origin) return false;
    const data = typeof payload === 'string' ? JSON.parse(payload) : payload;
    if (!data || typeof data !== 'object' || Array.isArray(data)) return false;
    if (/kodik/i.test(player)) return isKodikOrigin(origin) && ['kodik_player_video_started','kodik_player_play'].includes(data.key);
    if (/cvh|chv/i.test(player)) return ['player_video_started','player_play'].includes(data.key) ||
      (data.key === 'player_time_update' && Number.isFinite(data.value) && data.value > 0);
    if (/alloha/i.test(player)) return origin === 'https://alloha.yani.tv' && data.type === 'pc-alloha' && data.event === 'started';
  } catch { /* Ignore malformed or unrelated provider messages. */ }
  return false;
}

export function useAllohaEvents() {
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    let disposed = false;
    const read = () => { void window.pywebview?.api?.web_player_capabilities?.().then(value => {if (!disposed) setAvailable(value.alloha_events);}).catch(() => {}); };
    read(); window.addEventListener('pywebviewready', read);
    return () => {disposed=true;window.removeEventListener('pywebviewready',read);};
  }, []);
  return available;
}

export function useWebAutoNext() {
  const read = () => {try{return localStorage.getItem('pc_web_auto_next') !== 'false';}catch{return true;}};
  const [enabled,setEnabled] = useState(read);
  useEffect(()=>{const update=()=>setEnabled(read());window.addEventListener('pc-web-auto-next',update);return()=>window.removeEventListener('pc-web-auto-next',update);},[]);
  return [enabled,(value: boolean)=>{try{localStorage.setItem('pc_web_auto_next',String(value));}catch{}setEnabled(value);window.dispatchEvent(new Event('pc-web-auto-next'));}] as const;
}
