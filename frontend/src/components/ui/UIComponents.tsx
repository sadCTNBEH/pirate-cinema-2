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
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={`ui-button ui-button--${variant} ui-button--${size} ${className}`}
      {...props}
    >
      {loading ? <Loader2 className="w-4 h-4 animate-spin text-current" /> : icon}
      <span className="min-w-0">{children}</span>
    </button>
  );
};

export const Badge: React.FC<{
  variant?: 'cyan' | 'green' | 'rose' | 'amber' | 'slate';
  pulse?: boolean;
  children: ReactNode;
  className?: string;
}> = ({ variant = 'cyan', pulse = false, children, className = '' }) => {
  return (
    <span
      className={`ui-badge ui-badge--${variant} ${className}`}
    >
      {pulse && (
        <span className="relative flex h-1.5 w-1.5">
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-current" />
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
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      className={`ui-section ${onClick ? 'cursor-pointer' : ''} ${glow ? 'ui-section--interactive' : ''} ${className}`}
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
        <div className="absolute left-3.5 text-film-muted pointer-events-none flex items-center justify-center">
          {icon}
        </div>
      )}
      <input
        className={`ui-input ${icon ? 'pl-10 pr-3.5' : 'px-3.5'} ${className}`}
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
      className={`ui-select ${className}`}
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
    <div className={`ui-progress ${className}`} role="progressbar" aria-label="Просмотрено" aria-valuenow={Math.round(percentage)} aria-valuemin={0} aria-valuemax={100}>
      <div
        className="ui-progress-fill"
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

