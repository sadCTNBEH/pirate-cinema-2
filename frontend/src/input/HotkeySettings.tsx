import React from 'react';
import { ACTIONS, DEFAULT_BINDINGS } from './actions';
import { useInput } from './InputProvider';
import { Button } from '../components/ui/UIComponents';
import { ChevronDown, Keyboard } from 'lucide-react';

export function HotkeySettings() {
  const { bindings, save, recording, record, error } = useInput();
  const [message, setMessage] = React.useState('');
  const [expanded, setExpanded] = React.useState(false);
  const contentId = React.useId();
  const reset = (next: typeof bindings) => save(next).then(() => setMessage('Назначения сохранены')).catch(e => setMessage(e.message));
  return <section className="ui-hotkeys">
    <h2><button type="button" className="ui-disclosure-trigger" aria-expanded={expanded} aria-controls={contentId} onClick={() => {
      if (expanded) record(null);
      setExpanded(!expanded);
    }}><Keyboard aria-hidden="true" /><span>Горячие клавиши</span><ChevronDown aria-hidden="true" className={expanded ? 'ui-chevron-expanded' : ''} /></button></h2>
    <div id={contentId} className={`ui-disclosure-content ${expanded ? 'is-expanded' : ''}`} inert={!expanded} aria-hidden={!expanded}>
    <div><div className="space-y-4 pt-4">
    <p className="text-sm text-film-muted leading-relaxed">Выберите назначение и нажмите сочетание. Поддерживаются Ctrl, Shift, Alt. Стрелки: навигация в меню, перемотка и громкость в видео. Геймпад: A / × — выбор, B / ○ — назад, X / □ — PiP, Y / △ — панель плеера и закрытие, R3 — полный экран, Start — пауза, LT / RT — перемотка.</p>
    <div>{ACTIONS.map(([id, label, scope]) => <div key={id} className="ui-hotkey-row">
      <span className="flex-1 text-sm">{label} <span className="text-xs text-film-muted">{scope === 'player' ? 'Видео' : scope === 'ui' ? 'Меню' : ''}</span></span>
      <Button variant={recording === id ? 'cyan' : 'secondary'} size="sm" onClick={() => { setMessage(''); record(recording === id ? null : id); }}>{recording === id ? 'Нажмите клавиши…' : bindings[id] || 'Не назначено'}</Button>
      <Button variant="ghost" size="sm" onClick={() => reset({ ...bindings, [id]: DEFAULT_BINDINGS[id] })}>Сброс</Button>
      <Button variant="ghost" size="sm" onClick={() => reset({ ...bindings, [id]: '' })}>Убрать</Button>
    </div>)}</div>
    {recording && <Button size="sm" onClick={() => record(null)}>Отменить назначение</Button>}
    <p role="status" className="text-sm text-amber-300">{error || message}</p>
    <Button variant="secondary" onClick={() => { record(null); reset({ ...DEFAULT_BINDINGS }); }}>Сбросить все назначения</Button>
    </div></div></div>
  </section>;
}
