/**
 * @file components/diagnostics/SystemStatusCard.tsx
 * @description Карточка общего состояния системы (индикатор, статус и время последней проверки).
 */

import React from 'react';
import { Clock } from 'lucide-react';
import { Card } from '../ui/UIComponents';
import { useApp } from '../../context/AppContext';

export interface SystemStatusCardProps {
  status: string;
  checkedAt?: string | null;
}

export const SystemStatusCard: React.FC<SystemStatusCardProps> = ({
  status,
  checkedAt,
}) => {
  const { t } = useApp();

  const isHealthy = status === 'healthy';
  const isDegraded = status === 'degraded';
  const statusLabel = isHealthy
    ? t('status_healthy') || 'Работает'
    : isDegraded
    ? t('status_degraded') || 'Есть проблемы'
    : t('status_unhealthy') || 'Не удалось проверить';

  const formattedCheckedAt = checkedAt
    ? new Date(checkedAt).toLocaleTimeString()
    : '—';

  return (
    <Card className="ui-system-status flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div className="flex items-center gap-3.5">
        <div
          className={`w-3.5 h-3.5 rounded-full ${
            isHealthy
              ? 'bg-emerald-400 '
              : isDegraded
              ? 'bg-amber-400 '
              : 'bg-rose-500 '
          }`}
        />
        <div>
          <div className="flex items-center gap-2">
            <span className="font-sans text-sm text-film-muted">
              {t('overall_status') || 'Общее состояние'}:
            </span>
            <strong className="font-sans text-base text-film-text">
              {statusLabel}
            </strong>
          </div>
          <p className="font-sans text-xs text-film-muted flex items-center gap-1.5 mt-0.5">
            <Clock className="w-3.5 h-3.5 text-film-muted" />
            <span>
              {t('last_checked') || 'Последняя проверка'}: {formattedCheckedAt}
            </span>
          </p>
        </div>
      </div>
    </Card>
  );
};
