import React from 'react';
import { ACTIONS, DEFAULT_BINDINGS } from './actions';
import { useInput } from './InputProvider';
import { Button } from '../components/ui/UIComponents';

export function HotkeySettings() {
  const { bindings, save, recording, record, error } = useInput();
  const [message, setMessage] = React.useState('');
  const reset = (next: typeof bindings) => save(next).then(() => setMessage('Назначения сохранены')).catch(e => setMessage(e.message));
  return <section className="settings-card p-6 bg-[#0a0e18] border border-slate-800/80 rounded-lg space-y-4">
    <h2 className="text-lg font-tech text-cyan-300">Управление и горячие клавиши</h2>
    <p className="text-xs text-slate-400">Выберите назначение и нажмите сочетание. Поддерживаются Ctrl, Shift, Alt. Стрелки: навигация в меню, перемотка и громкость в видео. Y / △ — панель плеера; LT / RT — перемотка.</p>
    <div className="space-y-2">{ACTIONS.map(([id, label, scope]) => <div key={id} className="flex items-center gap-2">
      <span className="flex-1 text-sm">{label} <span className="text-xs text-slate-500">{scope === 'player' ? 'Видео' : scope === 'ui' ? 'Меню' : ''}</span></span>
      <Button variant={recording === id ? 'cyan' : 'secondary'} size="sm" onClick={() => { setMessage(''); record(recording === id ? null : id); }}>{recording === id ? 'Нажмите клавиши…' : bindings[id] || 'Не назначено'}</Button>
      <Button variant="ghost" size="sm" onClick={() => reset({ ...bindings, [id]: DEFAULT_BINDINGS[id] })}>Сброс</Button>
      <Button variant="ghost" size="sm" onClick={() => reset({ ...bindings, [id]: '' })}>Убрать</Button>
    </div>)}</div>
    {recording && <Button size="sm" onClick={() => record(null)}>Отменить назначение</Button>}
    <p role="status" className="text-sm text-amber-300">{error || message}</p>
    <Button variant="secondary" onClick={() => { record(null); reset({ ...DEFAULT_BINDINGS }); }}>Сбросить все назначения</Button>
  </section>;
}
