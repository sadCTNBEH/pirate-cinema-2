import React, { useEffect, useState } from 'react';
import type { AdguardStatus } from '../../services/webPlayer';

export const AdguardSettings: React.FC = () => {
  const [state, setState] = useState<AdguardStatus | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const refresh = () => { void window.pywebview?.api?.adguard_status?.().then(setState); };
    refresh(); window.addEventListener('pywebviewready', refresh);
    return () => window.removeEventListener('pywebviewready', refresh);
  }, []);
  const change = async (enabled: boolean) => {
    if (!window.pywebview?.api?.adguard_set_enabled) return;
    setBusy(true);
    try { setState(await window.pywebview.api.adguard_set_enabled(enabled)); }
    catch (error: any) { setState(previous => previous ? {...previous, error: error.message} : null); }
    finally { setBusy(false); }
  };
  if (!state?.supported) return <p className="cinema-secondary">AdGuard Антибаннер доступен во встроенном Windows WebView2. {state?.error}</p>;
  return <section className="space-y-3" aria-label="Блокировка рекламы в веб-плеерах">
    <h3>Блокировка рекламы в веб-плеерах</h3>
    {state.installed && !state.error ? <label className="flex items-center gap-3"><input type="checkbox" checked={state.enabled} disabled={busy} onChange={event => change(event.target.checked)} />AdGuard Антибаннер</label> : <button type="button" className="cinema-button cinema-button--secondary" disabled={busy} onClick={() => change(true)}>{busy ? 'Устанавливаем официальное расширение…' : 'Установить и включить AdGuard'}</button>}
    <p className="cinema-secondary">Настоящее расширение AdGuard {state.version} (Manifest V3). Для Kodik, CVH и Alloha. После включения заново откройте плеер.</p>
    {state.installed && <p role="status">{state.enabled ? 'AdGuard включён для поддерживаемых плееров.' : 'AdGuard выключен. Настройки расширения сохранены.'}</p>}
    {state.error && <p role="alert">AdGuard не активирован: {state.error}</p>}
  </section>;
};
