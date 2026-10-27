/**
 * @file components/diagnostics/DiagnosticCard.tsx
 * @description Информационная карточка компонента системы (TorrServer, MPV, SQLite, Диск).
 */

import React, { ReactNode } from 'react';
import { Badge } from '../ui/UIComponents';

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
    <section className={`ui-diagnostic ${className}`} aria-label={title}>
      <div className="ui-diagnostic-heading">
        <h3>{icon}{title}</h3>
        <Badge variant={badgeVariant}>{statusText}</Badge>
      </div>
      <dl>
        {items.map((item, index) => (
          <div key={index}>
            <dt>{item.label}</dt>
            <dd className={item.alert ? 'text-rose-300' : undefined}>{item.value}</dd>
          </div>
        ))}
      </dl>
      {extraContent && <div className="ui-diagnostic-extra">{extraContent}</div>}
    </section>
  );
};
