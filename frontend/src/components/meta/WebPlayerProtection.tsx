import { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import type { AdguardStatus } from '../../services/webPlayer';

export function WebPlayerProtection({player}: {player: string}) {
  const {navigate} = useApp();
  const [state,setState] = useState<AdguardStatus | null>(null);
  useEffect(()=>{
    let disposed=false;
    const refresh=()=>{void window.pywebview?.api?.adguard_status?.().then(value=>{if(!disposed)setState(value);}).catch(()=>{});};
    refresh();
    const timer=window.setInterval(refresh,3000);
    window.addEventListener('pywebviewready',refresh);
    return()=>{disposed=true;clearInterval(timer);window.removeEventListener('pywebviewready',refresh);};
  },[player]);
  if (!state) return null;
  const supported=/kodik|cvh|alloha/i.test(player) || player.toLowerCase()==='animego online';
  const message=!supported ? 'Для этого плеера блокировка рекламы пока не подключена.' :
    state.error ? `AdGuard: ${state.error}` : !state.installed ? 'AdGuard не установлен в профиле приложения.' :
    !state.enabled ? 'Блокировка рекламы выключена.' : !state.active ? 'AdGuard сейчас не активен в плеере.' : '';
  if(!message)return null;
  return <div role="status" className="flex flex-wrap items-center gap-3 cinema-secondary">
    <span>{message}</span>
    {supported && <button type="button" className="cinema-button cinema-button--secondary" onClick={()=>navigate('settings')}>Настроить AdGuard</button>}
  </div>;
}
