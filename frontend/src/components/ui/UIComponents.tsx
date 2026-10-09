/**
 * @file components/ui/UIComponents.tsx
 * @description Базовые интерфейсные компоненты (Button, Input, Select, Progress, Badge, Card).
 */

import React, { ButtonHTMLAttributes, InputHTMLAttributes, SelectHTMLAttributes, ReactNode } from 'react';
import { Loader2 } from 'lucide-react';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost' | 'cyan';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  icon?: ReactNode;
  children: ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  children,
  className = '',
  disabled,
  ...props
}) => {
  const sizeClasses = {
    sm: 'px-3 py-1.5 text-xs gap-1.5 min-h-[34px]',
    md: 'px-4 py-2 text-sm gap-2 min-h-[40px]',
    lg: 'px-6 py-2.5 text-base gap-2.5 min-h-[46px]',
  }[size];

  const variantClasses = {
    primary:
      'bg-cyan-500/15 text-cyan-300 border border-cyan-500/40 hover:bg-cyan-500/25 hover:border-cyan-400 hover:text-white active:scale-[0.98] shadow-[0_0_12px_rgba(0,240,255,0.12)]',
    cyan:
      'bg-cyan-500 text-slate-950 font-bold border border-cyan-400 hover:bg-cyan-400 active:scale-[0.98] shadow-[0_0_14px_rgba(0,240,255,0.35)]',
    secondary:
      'bg-slate-900/80 text-slate-300 border border-slate-800 hover:bg-slate-800 hover:text-white hover:border-slate-700 active:scale-[0.98]',
    danger:
      'bg-rose-500/15 text-rose-300 border border-rose-500/40 hover:bg-rose-500/25 hover:border-rose-400 hover:text-white active:scale-[0.98]',
    ghost:
      'bg-transparent text-slate-400 hover:text-cyan-400 hover:bg-slate-800/40 border border-transparent',
  }[variant];

  return (
    <button
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center font-tech uppercase tracking-wider transition-all duration-150 rounded-md cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed select-none ${sizeClasses} ${variantClasses} ${className}`}
      {...props}
    >
      {loading ? <Loader2 className="w-4 h-4 animate-spin text-current" /> : icon}
      <span>{children}</span>
    </button>
  );
};

export const Badge: React.FC<{
  variant?: 'cyan' | 'green' | 'rose' | 'amber' | 'slate';
  pulse?: boolean;
  children: ReactNode;
  className?: string;
}> = ({ variant = 'cyan', pulse = false, children, className = '' }) => {
  const styles = {
    cyan: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30',
    green: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    rose: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
    amber: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
    slate: 'bg-slate-800/60 text-slate-400 border-slate-700/50',
  }[variant];

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 text-xs font-code font-medium border rounded-md ${styles} ${className}`}
    >
      {pulse && (
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 bg-current" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-current" />
        </span>
      )}
      {children}
    </span>
  );
};

export const Card: React.FC<{
  children: ReactNode;
  className?: string;
  glow?: boolean;
  onClick?: () => void;
}> = ({ children, className = '', glow = false, onClick }) => {
  return (
    <div
      onClick={onClick}
      className={`relative bg-[#0c101a]/90 border border-slate-800/80 rounded-lg backdrop-blur-sm transition-all duration-200 ${
        glow ? 'hover:border-cyan-500/50 hover:shadow-[0_0_16px_rgba(0,240,255,0.1)]' : ''
      } ${onClick ? 'cursor-pointer' : ''} ${className}`}
    >
      {children}
    </div>
  );
};

export const Input: React.FC<InputHTMLAttributes<HTMLInputElement> & { icon?: ReactNode }> = ({
  icon,
  className = '',
  ...props
}) => {
  return (
    <div className="relative flex items-center w-full">
      {icon && (
        <div className="absolute left-3.5 text-slate-500 pointer-events-none flex items-center justify-center">
          {icon}
        </div>
      )}
      <input
        className={`w-full bg-[#090d16] border border-slate-800 focus:border-cyan-400/80 focus:shadow-[0_0_10px_rgba(0,240,255,0.18)] text-slate-100 placeholder:text-slate-500 rounded-md py-2 text-sm font-sans transition-all duration-150 outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:m-0 [&::-webkit-inner-spin-button]:m-0 ${
          icon ? 'pl-10 pr-3' : 'px-3.5'
        } ${className}`}
        {...props}
      />
    </div>
  );
};

export const Select: React.FC<SelectHTMLAttributes<HTMLSelectElement>> = ({
  className = '',
  children,
  ...props
}) => {
  return (
    <select
      className={`bg-[#090d16] border border-slate-800 focus:border-cyan-400/80 focus:shadow-[0_0_10px_rgba(0,240,255,0.18)] text-slate-200 rounded-md py-2 px-3 text-sm font-sans transition-all duration-150 outline-none cursor-pointer ${className}`}
      {...props}
    >
      {children}
    </select>
  );
};

export const Progress: React.FC<{
  value: number;
  max: number;
  className?: string;
}> = ({ value, max, className = '' }) => {
  const percentage = Math.min(100, Math.max(0, (value / (max || 1)) * 100));

  return (
    <div className={`w-full bg-slate-900/90 h-2 rounded-full overflow-hidden border border-slate-800 p-[1px] ${className}`}>
      <div
        className="h-full bg-gradient-to-r from-cyan-600 to-cyan-400 rounded-full shadow-[0_0_6px_rgba(0,240,255,0.5)] transition-all duration-300"
        style={{ width: `${percentage}%` }}
      />
    </div>
  );
};

/**
 * Безопасный рендеринг текста с HTML тегами <br>, чтобы они не выводились в виде сырого текста
 */
export const SafeHtmlText: React.FC<{ text: string; className?: string }> = ({
  text,
  className = '',
}) => {
  if (!text) return null;
  let cleaned = text;
  if (
    cleaned.includes('Invalid JSON received for torrent video files') ||
    cleaned.includes('Expecting value: line 1 column 1')
  ) {
    cleaned = 'Не удалось получить список файлов с торрент-трекера. <br> Возможно торрент “мертв“ или в данный момент недоступен.';
  }

  const parts = cleaned.split(/<br\s*\/?>/i);
  if (parts.length === 1) {
    return <span className={className}>{cleaned}</span>;
  }
  return (
    <span className={className}>
      {parts.map((part, index) => (
        <React.Fragment key={index}>
          {index > 0 && <br />}
          {part}
        </React.Fragment>
      ))}
    </span>
  );
};

