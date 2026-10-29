import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/** DOM listbox stays within the WebView viewport, unlike a native select popup. */
export const EpisodePicker: React.FC<{value: string; options: {value: string; label: string}[]; onChange: (value: string) => void; disabled?: boolean}> = ({value, options, onChange, disabled}) => {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [box, setBox] = useState({top:0,left:0,width:160,height:280});
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const id = useId();
  const selected = options.find(item => item.value === value);
  useLayoutEffect(() => {
    if (!open || !button.current) return;
    const rect = button.current.getBoundingClientRect();
    const height = Math.min(288, window.innerHeight - 20, options.length * 40 + 8);
    const width = Math.min(Math.max(rect.width,160),window.innerWidth-16);
    setBox({width,height,left:Math.max(8,Math.min(rect.left,window.innerWidth-width-8)),top:rect.bottom+height+4<window.innerHeight ? rect.bottom+4 : Math.max(8,rect.top-height-4)});
    setHighlight(Math.max(0,options.findIndex(item => item.value === value)));
    menu.current?.focus();
  }, [open, options.length, value]);
  useEffect(() => {
    if (open) menu.current?.querySelector(`[data-index="${highlight}"]`)?.scrollIntoView({block:'nearest'});
  }, [highlight,open]);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => { if (!menu.current?.contains(event.target as Node) && !button.current?.contains(event.target as Node)) setOpen(false); };
    const resize = () => setOpen(false);
    document.addEventListener('pointerdown',outside); window.addEventListener('resize',resize);
    return () => {document.removeEventListener('pointerdown',outside);window.removeEventListener('resize',resize);};
  }, [open]);
  const choose = (next: string) => {onChange(next);setOpen(false);button.current?.focus();};
  return <div className="flex min-w-0 flex-col gap-2"><span>Серия</span>
    <button ref={button} type="button" role="combobox" aria-label="Серия" aria-haspopup="listbox" aria-controls={id} aria-expanded={open} disabled={disabled || !options.length} className="cinema-button cinema-button--secondary min-w-36 justify-between" onClick={() => setOpen(previous => !previous)} onKeyDown={event => {if (['ArrowDown','ArrowUp','Enter',' '].includes(event.key)){event.preventDefault();setOpen(true);}}}>{selected?.label || 'Выберите серию'}<span aria-hidden="true">▾</span></button>
    {open && createPortal(<div ref={menu} id={id} role="listbox" aria-label="Серии" tabIndex={-1} aria-activedescendant={`${id}-${highlight}`} style={{position:'fixed',top:box.top,left:box.left,width:box.width,maxHeight:box.height,zIndex:200,background:'#11161e',borderColor:'#303744',color:'#f2f4f6',overflowY:'auto',overscrollBehavior:'contain'}} className="rounded-lg border border-film-line bg-film-base p-1 shadow-xl" onKeyDown={event => {
      if (event.key==='Escape'){setOpen(false);button.current?.focus();}
      else if(event.key==='ArrowDown'){event.preventDefault();setHighlight(current=>Math.min(options.length-1,current+1));}
      else if(event.key==='ArrowUp'){event.preventDefault();setHighlight(current=>Math.max(0,current-1));}
      else if(event.key==='Home'){event.preventDefault();setHighlight(0);}
      else if(event.key==='End'){event.preventDefault();setHighlight(options.length-1);}
      else if(event.key==='Enter' || event.key===' '){event.preventDefault();if(options[highlight])choose(options[highlight].value);}
      else if(event.key==='Tab')setOpen(false);
    }}>{options.map((item,index)=><button type="button" role="option" id={`${id}-${index}`} data-index={index} key={item.value} aria-selected={item.value===value} tabIndex={-1} style={{background:index===highlight?'#29313d':'transparent'}} onMouseEnter={()=>setHighlight(index)} onClick={()=>choose(item.value)} className={`block min-h-10 w-full rounded px-3 py-2 text-left ${index===highlight ? 'bg-film-surface text-film-text' : 'text-film-muted'}`}>{item.label}</button>)}</div>,document.body)}
  </div>;
};
