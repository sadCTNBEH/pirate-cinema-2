import { useEffect, useState } from 'react';
export type AdguardStatus = { supported: boolean; initialized: boolean; installed: boolean; enabled: boolean; active: boolean; version: string; runtime: string; error: string };

export async function prepareWebPlayer(player: string): Promise<string | null> {
  const api = window.pywebview?.api;
  if (!api?.adguard_player_scope) return null;
  const lease = crypto.randomUUID();
  const state = await api.adguard_player_scope(player, lease);
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
    if (!data || typeof data !== 'object') return false;
    if (/kodik/i.test(player)) return isKodikOrigin(origin) && data.key === 'kodik_player_video_ended';
    if (/cvh/i.test(player)) return data.key === 'player_video_ended';
    if (/alloha/i.test(player)) return origin === 'https://alloha.yani.tv' && data.type === 'pc-alloha' && data.event === 'ended';
  } catch { /* Malformed provider message. */ }
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
