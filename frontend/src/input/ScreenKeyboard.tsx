import React, { useState, useRef, useEffect } from 'react';
import { Button } from '../components/ui/UIComponents';
import { Action } from './actions';
import { nearestIndex } from './focus';
import { editText, LAYOUTS, TextField } from './text';

export function ScreenKeyboard({ field, onClose, handler }: {
  field: TextField; onClose: () => void;
  handler: React.MutableRefObject<((action: Action) => void) | null>;
}) {
  const [layout, setLayout] = useState<'ru' | 'en'>('ru');
  const [upper, setUpper] = useState(false);
  const [selected, setSelected] = useState(0);
  const [value, setValue] = useState(field.value);
  const root = useRef<HTMLDivElement>(null);
  const activate = (key: string) => {
    if (key === 'RU / EN') { setLayout(layout === 'ru' ? 'en' : 'ru'); setSelected(0); }
    else if (key === '⇧') setUpper(!upper);
    else if (key === 'Закрыть') onClose();
    else if (key === 'Enter') {
      if (field.tagName === 'TEXTAREA') editText(field, '\n');
      else {
        onClose();
        if (field.form) field.form.requestSubmit();
        else field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
      }
    } else editText(field, key === 'Пробел' ? ' ' : key === '⌫' || key === 'Очистить' ? '' : key,
      key === '⌫' ? 'backspace' : key === 'Очистить' ? 'clear' : 'insert');
    setValue(field.value);
  };
  useEffect(() => {
    const update = () => setValue(field.value);
    field.addEventListener('input', update);
    return () => field.removeEventListener('input', update);
  }, [field]);
  useEffect(() => {
    handler.current = action => {
      const buttons = Array.from(root.current?.querySelectorAll<HTMLButtonElement>('button') || []);
      if (action === 'back') onClose();
      else if (action === 'confirm') buttons[selected]?.click();
      else if (['left', 'right', 'up', 'down'].includes(action)) {
        const index = nearestIndex(buttons[selected]?.getBoundingClientRect() || buttons[0].getBoundingClientRect(),
          buttons.map(b => b.getBoundingClientRect()), action as 'left');
        if (index >= 0) setSelected(index);
      }
    };
    return () => { handler.current = null; };
  });
  let index = 0;
  return <div ref={root} role="dialog" aria-modal="true" aria-label="Экранная клавиатура"
    className="ui-screen-keyboard fixed inset-x-4 bottom-4 z-[100] mx-auto max-w-4xl rounded-md border border-film-line bg-film-base p-4 space-y-2"
    onMouseDown={e => e.preventDefault()}>
    <div className="font-sans p-2 text-film-accent truncate" aria-live="polite">{field.type === 'password' ? '•'.repeat(value.length) : value || 'Введите текст'}</div>
    {['1234567890-_.:/@', ...LAYOUTS[layout], '?=&+#,!()[]%', ['RU / EN', '⇧', 'Пробел', '⌫', 'Очистить', 'Enter', 'Закрыть']].map((row, r) =>
      <div key={r} className="flex justify-center gap-1">{(typeof row === 'string' ? Array.from(upper ? row.toUpperCase() : row) : row).map(key => {
        const current = index++;
        return <Button key={key} size="sm" variant="secondary" data-pad-focus={current === selected || undefined}
          className={key === 'Пробел' ? 'flex-1' : 'min-w-9'} onClick={() => activate(key)}>{key}</Button>;
      })}</div>)}
    <p className="text-xs text-film-muted">A / Cross — ввод · B / Circle — закрыть · Физическая клавиатура работает как обычно</p>
  </div>;
}
