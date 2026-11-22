import React, { useEffect, useState } from 'react';
import type { AdguardStatus } from '../../services/webPlayer';

export const AdguardSettings: React.FC = () => {
  const [state, setState] = useState<AdguardStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [site, setSite] = useState('');
  const [actionError, setActionError] = useState('');
  useEffect(() => {
    if (busy) return;
    let disposed = false;
    const refresh = () => {
      void window.pywebview?.api?.adguard_status?.()
        .then(status => { if (!disposed) setState(status); }).catch(() => {});
    };
    refresh(); window.addEventListener('pywebviewready', refresh);
    const timer = state?.mode === 'qt' ? window.setInterval(refresh, 1500) : undefined;
    return () => {
      disposed = true;
      window.clearInterval(timer);
      window.removeEventListener('pywebviewready', refresh);
    };
  }, [busy, state?.mode]);
  const change = async (enabled: boolean) => {
    if (!window.pywebview?.api?.adguard_set_enabled) return;
    setBusy(true);
    setActionError('');
    try { setState(await window.pywebview.api.adguard_set_enabled(enabled)); }
    catch { setActionError('Не удалось изменить настройку блокировки.'); }
    finally { setBusy(false); }
  };
  const changeException = async (value: string, add: boolean) => {
    const update = window.pywebview?.api?.adguard_set_exception;
    if (!update) return;
    setBusy(true);
    setActionError('');
    try {
      const status = await update(value, add);
      setState(status);
      if (status.mode === 'qt' && status.exceptionError) setActionError(status.exceptionError);
      else if (add) setSite('');
    } catch {
      setActionError('Не удалось сохранить исключение.');
    } finally {
      setBusy(false);
    }
  };
  if (state?.mode === 'qt') return <section className="space-y-3" aria-label="Блокировка рекламы во встроенном браузере">
    <h3>Блокировка рекламы во встроенном браузере</h3>
    <label className="flex items-center gap-3">
      <input type="checkbox" checked={state.enabled} disabled={busy} onChange={event => void change(event.target.checked)} />
      Блокировать рекламу и трекеры
    </label>
    <p className="cinema-secondary">Сетевые правила AdGuard Base Filter и Tracking Protection. Фильтры обновляются автоматически.</p>
    <p role="status">{state.active ? 'Защита работает.' : state.enabled ? 'Ожидание загрузки фильтров.' : 'Защита выключена.'}{state.updating && ' Обновляем фильтры…'}</p>
    <p className="cinema-secondary">Заблокировано за сеанс: {state.blocked.toLocaleString()}{state.updatedAt > 0 && ` · Фильтры обновлены: ${new Date(state.updatedAt * 1000).toLocaleString()}`}</p>
    {state.enabled && state.error && <p role="alert">{state.error}</p>}
    <form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); void changeException(site, true); }}>
      <label className="flex flex-col gap-1">Исключения для сайтов
        <input className="rounded border border-film-line bg-film-base p-2" value={site} maxLength={2048} placeholder="example.com" onChange={event => setSite(event.target.value)} />
      </label>
      <button type="submit" className="cinema-button cinema-button--secondary" disabled={busy || !site.trim()}>Добавить</button>
    </form>
    {state.exceptions.length > 0 && <ul className="space-y-2">
      {state.exceptions.map(domain => <li key={domain} className="flex flex-wrap items-center gap-2">
        <span>{domain}</span>
        <button type="button" aria-label={`Удалить исключение ${domain}`} className="cinema-button cinema-button--secondary" disabled={busy} onClick={() => void changeException(domain, false)}>Удалить</button>
      </li>)}
    </ul>}
    {actionError && <p role="alert">{actionError}</p>}
  </section>;
  if (!state?.supported) return <p className="cinema-secondary">AdGuard Антибаннер доступен во встроенном браузере приложения в поддерживаемых системах. {state?.error}</p>;
  return <section className="space-y-3" aria-label="Блокировка рекламы в веб-плеерах">
    <h3>Блокировка рекламы в веб-плеерах</h3>
    {state.installed && !state.error ? <label className="flex items-center gap-3"><input type="checkbox" checked={state.enabled} disabled={busy} onChange={event => change(event.target.checked)} />AdGuard Антибаннер</label> : <button type="button" className="cinema-button cinema-button--secondary" disabled={busy} onClick={() => change(true)}>{busy ? 'Устанавливаем официальное расширение…' : 'Установить и включить AdGuard'}</button>}
    <p className="cinema-secondary">Настоящее расширение AdGuard {state.version} (Manifest V3). Для Kodik, CVH и Alloha. После включения заново откройте плеер.</p>
    {state.installed && <p role="status">{state.enabled ? 'AdGuard включён для поддерживаемых плееров.' : 'AdGuard выключен. Настройки расширения сохранены.'}</p>}
    {state.error && <p role="alert">AdGuard не активирован: {state.error}</p>}
    {actionError && <p role="alert">{actionError}</p>}
  </section>;
};
