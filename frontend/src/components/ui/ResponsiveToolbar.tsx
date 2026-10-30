import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { MoreHorizontal } from 'lucide-react';

export interface ToolbarItem {
  id: string;
  priority?: number;
  content: React.ReactNode;
}

/** Keep the highest-priority actions visible; preserve their original ordering. */
export function toolbarVisible(width: number, sizes: number[], priorities: number[]): number[] {
  const all = sizes.reduce((sum, size) => sum + size, 0) + Math.max(0, sizes.length - 1) * 8;
  if (all <= width) return sizes.map((_, index) => index);
  let remaining = Math.max(0, width - 44);
  const selected: number[] = [];
  [...sizes.keys()].sort((a, b) => priorities[b] - priorities[a] || a - b).forEach(index => {
    if (sizes[index] + 8 <= remaining) { selected.push(index); remaining -= sizes[index] + 8; }
  });
  return selected.sort((a, b) => a - b);
}

export const ResponsiveToolbar: React.FC<{ items: ToolbarItem[]; label?: string; className?: string }> =
({ items, label = 'Действия', className = '' }) => {
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null), menu = useRef<HTMLDivElement>(null);
  const current = useRef(items); current.current = items;
  const widths = useRef(new Map<string, number>());
  const [shown, setShown] = useState<string[] | null>(null);
  const [open, setOpen] = useState(false);
  const [select, setSelect] = useState<HTMLSelectElement | null>(null);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const close = useCallback((restore = true) => {
    setOpen(false);
    setSelect(null);
    if (restore) requestAnimationFrame(() => {
      const dialog = Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')).find(el => el.getClientRects().length);
      if (dialog && !dialog.contains(root.current)) return;
      (trigger.current || root.current?.querySelector<HTMLElement>('button,select'))?.focus({ preventScroll: true });
    });
  }, []);
  const key = items.map(item => `${item.id}:${item.priority || 0}`).join('|');
  useLayoutEffect(() => {
    const element = root.current;
    if (!element) return;
    const measure = () => {
      element.querySelectorAll<HTMLElement>('[data-toolbar-id]').forEach(slot => {
        if (slot.offsetWidth) widths.current.set(slot.dataset.toolbarId!, Math.max(slot.scrollWidth, slot.offsetWidth));
      });
      const list = current.current;
      const indices = toolbarVisible(element.clientWidth, list.map(item => widths.current.get(item.id) || 160), list.map(item => item.priority || 0));
      const next = indices.map(index => list[index].id);
      setShown(previous => previous?.join('|') === next.join('|') ? previous : next);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    element.querySelectorAll<HTMLElement>('[data-toolbar-id]').forEach(slot => observer.observe(slot));
    return () => observer.disconnect();
  }, [key]);
  const hidden = items.filter(item => shown !== null && !shown.includes(item.id));
  const layoutMenu = useCallback(() => {
    const rect = trigger.current?.getBoundingClientRect();
    if (!rect) return;
    const height = Math.min(menu.current?.offsetHeight || 240, window.innerHeight - 24);
    const width = Math.min(320, window.innerWidth - 24);
    setPosition({ top: Math.max(12, Math.min(window.innerHeight - height - 12, rect.bottom + 8)),
      left: Math.max(12, Math.min(window.innerWidth - width - 12, rect.right - width)) });
  }, []);
  useLayoutEffect(() => { if (open) layoutMenu(); }, [open, hidden.length, select, layoutMenu]);
  useEffect(() => {
    if (!open) return;
    if (!hidden.length) { close(); return; }
    menu.current?.querySelector<HTMLElement>('[data-menu-action] button:not(:disabled), [data-menu-action] select:not(:disabled)')?.focus();
    const pointer = (event: PointerEvent) => {
      if (!menu.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) close(false);
    };
    const keyboard = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      if (event.key === 'Escape') {
        event.preventDefault(); event.stopPropagation();
        if (select) { setSelect(null); requestAnimationFrame(() => select.focus()); } else close();
      }
      if (event.target instanceof HTMLSelectElement && event.key !== 'Tab') return;
      if (['ArrowUp', 'ArrowDown', 'Tab'].includes(event.key)) {
        const controls = Array.from(menu.current?.querySelectorAll<HTMLElement>('button:not(:disabled),select:not(:disabled)') || []).filter(el => el.getClientRects().length);
        const at = controls.indexOf(document.activeElement as HTMLElement);
        const step = event.key === 'ArrowUp' || (event.key === 'Tab' && event.shiftKey) ? -1 : 1;
        controls[(at + step + controls.length) % controls.length]?.focus();
        event.preventDefault(); event.stopPropagation();
      }
    };
    const focus = (event: FocusEvent) => {
      if (!(event.target instanceof Element)) return;
      if (event.target.closest('[role="dialog"]') && !menu.current?.contains(event.target)) close(false);
    };
    const choose = (event: Event) => {
      const element = (event as CustomEvent).detail;
      if (element instanceof HTMLSelectElement && menu.current?.contains(element)) {
        event.stopImmediatePropagation();
        setSelect(element);
      }
    };
    document.addEventListener('pointerdown', pointer);
    document.addEventListener('keydown', keyboard, true);
    document.addEventListener('focusin', focus);
    window.addEventListener('cinema-select', choose, true);
    window.addEventListener('resize', layoutMenu);
    window.addEventListener('scroll', layoutMenu, true);
    return () => {
      document.removeEventListener('pointerdown', pointer); document.removeEventListener('keydown', keyboard, true);
      document.removeEventListener('focusin', focus); window.removeEventListener('resize', layoutMenu);
      window.removeEventListener('cinema-select', choose, true);
      window.removeEventListener('scroll', layoutMenu, true);
    };
  }, [open, hidden.length, close, layoutMenu]);
  useEffect(() => {
    if (select) menu.current?.querySelector<HTMLElement>('[data-select-options] button')?.focus();
  }, [select]);
  return <div ref={root} className={`responsive-toolbar ${className}`} role="group" aria-label={label}>
    {items.map(item => <div key={item.id} data-toolbar-id={item.id} className="toolbar-slot"
      style={{ display: shown === null || shown.includes(item.id) ? undefined : 'none' }}>{shown === null || shown.includes(item.id) ? item.content : null}</div>)}
    {hidden.length > 0 && <button type="button" ref={trigger} className="cinema-icon-button toolbar-more"
      aria-label={`Ещё: ${label}`} aria-haspopup="menu" aria-expanded={open}
      onClick={() => setOpen(value => !value)}><MoreHorizontal /></button>}
    {open && hidden.length > 0 && createPortal(<div ref={menu} className="toolbar-menu cinema-theme" role="menu"
      aria-label={label} data-focus-scope style={position}>
      <button type="button" hidden data-dialog-close onClick={() => {
        if (select) { setSelect(null); requestAnimationFrame(() => select.focus()); } else close();
      }} aria-label="Закрыть меню" />
      <div style={{ display: select ? 'none' : undefined }}>
      {hidden.map(item => <div key={item.id} data-menu-action onClick={event => {
        const button = (event.target as HTMLElement).closest('button');
        if (button && !button.disabled) close();
      }}>{item.content}</div>)}
      </div>
      {select && <div data-select-options>{Array.from(select.options).map((option, index) => <button
        key={index} type="button" className="cinema-button" disabled={option.disabled} onClick={() => {
          Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')?.set?.call(select, option.value);
          select.dispatchEvent(new Event('change', { bubbles: true }));
          close();
        }} aria-pressed={option.selected} title={option.text}>{option.selected ? '✓ ' : ''}{option.text}</button>)}</div>}
    </div>, document.body)}
  </div>;
};
