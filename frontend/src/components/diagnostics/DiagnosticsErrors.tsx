/**
 * @file components/diagnostics/DiagnosticsErrors.tsx
 * @description Отображение кольцевого буфера последних ошибок системы.
 */

import React, { useState, useMemo } from 'react';
import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp } from 'lucide-react';
import { DiagnosticError } from '../../types';
import { Card, Badge } from '../ui/UIComponents';

interface DiagnosticsErrorsProps {
  errors: DiagnosticError[];
  t: (key: string) => string;
}

export const DiagnosticsErrors: React.FC<DiagnosticsErrorsProps> = ({ errors, t }) => {
  const [expandedIndices, setExpandedIndices] = useState<Record<number, boolean>>({});

  // Сортировка от новых к старым и ограничение до 50 записей
  const sortedErrors = useMemo(() => {
    if (!errors || errors.length === 0) return [];
    const list = [...errors].slice(0, 50);
    return list.sort((a, b) => {
      const tA = new Date(a.timestamp).getTime();
      const tB = new Date(b.timestamp).getTime();
      return (isNaN(tB) ? 0 : tB) - (isNaN(tA) ? 0 : tA);
    });
  }, [errors]);

  const toggleExpand = (idx: number) => {
    setExpandedIndices((prev) => ({
      ...prev,
      [idx]: !prev[idx],
    }));
  };

  const formatErrorTime = (isoString: string): string => {
    try {
      const d = new Date(isoString);
      if (isNaN(d.getTime())) return isoString;
      return d.toLocaleString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      });
    } catch {
      return isoString;
    }
  };

  return (
    <Card className="ui-diagnostic-errors">
      <div className="flex items-center justify-between pb-4 mb-4 border-b border-film-line">
        <div className="flex items-center gap-2.5">
          <AlertCircle className="w-5 h-5 text-rose-400" />
          <h2 className="font-sans font-semibold text-lg text-film-text">
            {t('recent_errors') || 'Последние ошибки'}
          </h2>
        </div>
        <Badge variant={sortedErrors.length > 0 ? 'rose' : 'slate'}>
          {sortedErrors.length} / 50
        </Badge>
      </div>

      {sortedErrors.length === 0 ? (
        <div className="flex items-center gap-3 py-6 text-film-muted">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <span className="font-sans text-sm text-film-text">
            {t('no_recent_errors') || 'Ошибок не зарегистрировано.'}
          </span>
        </div>
      ) : (
        <div className="space-y-2.5 max-h-[460px] overflow-y-auto pr-1">
          {sortedErrors.map((err, idx) => {
            const isLong = err.message && err.message.length > 140;
            const isExpanded = !!expandedIndices[idx];
            const displayMessage =
              isLong && !isExpanded
                ? err.message.slice(0, 140) + '...'
                : err.message;

            return (
              <div
                key={`${err.timestamp}-${idx}`}
                className="ui-error-entry"
              >
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2">
                    <span className="font-sans text-xs text-film-accent font-medium bg-film-hover px-2 py-0.5 rounded border border-film-line">
                      {err.component}
                    </span>
                    <span className="font-sans text-xs text-rose-300 font-medium bg-rose-950/40 px-2 py-0.5 rounded border border-rose-800/40">
                      {err.error_type}
                    </span>
                  </div>
                  <span className="font-sans text-[11px] text-film-muted">
                    {formatErrorTime(err.timestamp)}
                  </span>
                </div>

                <p className="font-sans text-xs text-film-text break-words leading-relaxed whitespace-pre-wrap select-text">
                  {displayMessage}
                </p>

                {isLong && (
                  <button
                    aria-expanded={isExpanded}
                    onClick={() => toggleExpand(idx)}
                    className="mt-2 inline-flex items-center gap-1 font-sans text-xs text-film-accent hover:text-film-accent cursor-pointer"
                  >
                    {isExpanded ? (
                      <>
                        <span>{t('collapse') || 'Свернуть'}</span>
                        <ChevronUp className="w-3.5 h-3.5" />
                      </>
                    ) : (
                      <>
                        <span>{t('expand') || 'Развернуть'}</span>
                        <ChevronDown className="w-3.5 h-3.5" />
                      </>
                    )}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
};
