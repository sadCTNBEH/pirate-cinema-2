/**
 * @file components/diagnostics/DiagnosticCard.tsx
 * @description Информационная карточка компонента системы (TorrServer, MPV, SQLite, Диск).
 */

import React, { ReactNode } from 'react';
import { Badge, Card } from '../ui/UIComponents';

export interface DiagnosticItemRow {
  label: string;
  value: ReactNode;
  alert?: boolean;
  breakAll?: boolean;
}

interface DiagnosticCardProps {
  title: string;
  icon: ReactNode;
  statusText: string;
  statusVariant: 'healthy' | 'degraded' | 'unhealthy' | 'neutral';
  items: DiagnosticItemRow[];
  extraContent?: ReactNode;
  className?: string;
}

export const DiagnosticCard: React.FC<DiagnosticCardProps> = ({
  title,
  icon,
  statusText,
  statusVariant,
  items,
  extraContent,
  className = '',
}) => {
  const badgeVariant =
    statusVariant === 'healthy'
      ? 'green'
      : statusVariant === 'degraded'
      ? 'amber'
      : statusVariant === 'unhealthy'
      ? 'rose'
      : 'slate';

  return (
    <Card
      className={`p-5 flex flex-col justify-between border-slate-800/80 bg-[#0a0e18] shadow-sm ${className}`}
    >
      <div>
        {/* Шапка карточки */}
        <div className="flex items-center justify-between pb-3.5 mb-3.5 border-b border-slate-800/70">
          <div className="flex items-center gap-2.5">
            <span className="text-cyan-400 shrink-0">{icon}</span>
            <h3 className="font-tech font-bold text-base uppercase tracking-wider text-slate-100 truncate">
              {title}
            </h3>
          </div>
          <Badge variant={badgeVariant} pulse={statusVariant === 'healthy'}>
            {statusText}
          </Badge>
        </div>

        {/* Список характеристик */}
        <div className="space-y-2 font-code text-xs">
          {items.map((it, idx) => (
            <div
              key={idx}
              className="flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-1 py-1 border-b border-slate-800/40 last:border-0"
            >
              <span className="text-slate-400 shrink-0 font-medium">
                {it.label}:
              </span>
              <span
                className={`font-medium ${
                  it.alert ? 'text-rose-400' : 'text-slate-200'
                } ${it.breakAll ? 'break-all sm:text-right' : 'sm:text-right truncate sm:max-w-[70%]'}`}
              >
                {it.value}
              </span>
            </div>
          ))}
        </div>
      </div>

      {extraContent && (
        <div className="mt-4 pt-3.5 border-t border-slate-800/60">
          {extraContent}
        </div>
      )}
    </Card>
  );
};
