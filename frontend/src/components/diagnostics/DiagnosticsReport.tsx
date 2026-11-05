/**
 * @file components/diagnostics/DiagnosticsReport.tsx
 * @description Логика генерации, обезличивания и копирования отчётов диагностики в буфер обмена.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { DiagnosticsResponse } from '../../types';
import { useApp } from '../../context/AppContext';
import { Button } from '../ui/UIComponents';
import { Check, Copy, AlertTriangle } from 'lucide-react';

/**
 * Очистка текста от чувствительных данных (токены, пароли, ключи API)
 */
export const sanitizeText = (text?: string | null): string => {
  if (!text) return '';
  return text
    .replace(/(token|api[_-]?key|password|secret|auth)=([^\s&]+)/gi, '$1=***')
    .replace(/(Bearer\s+)[^\s]+/gi, '$1***')
    .replace(/([a-zA-Z]+:\/\/[^:]+:)[^@]+@/g, '$1***@');
};

/**
 * Сборка безопасного отчёта для буфера обмена (краткий для Debug OFF, технический для Debug ON)
 */
export const buildReportText = (d: DiagnosticsResponse, isDebug: boolean): string => {
  if (!isDebug) {
    const tsStatus =
      d.torrserver.state === 'recovering'
        ? 'Восстанавливается'
        : d.torrserver.state === 'error'
        ? 'Ошибка'
        : d.torrserver.running
        ? 'Работает'
        : 'Не запущен';
    const mpvStatus =
      d.mpv.state === 'error'
        ? 'Ошибка воспроизведения'
        : d.mpv.state === 'starting'
        ? 'Запускается'
        : d.mpv.state === 'running'
        ? 'Воспроизводит'
        : d.mpv.available
        ? 'Доступен'
        : 'Не найден';

    return `Статус служб Pirate Cinema

Версия приложения: ${d.version}
Общее состояние: ${d.status === 'healthy' ? 'Работает' : d.status === 'degraded' ? 'Есть проблемы' : 'Ошибка'}
Проверено: ${d.checked_at ? new Date(d.checked_at).toLocaleTimeString() : '—'}

TorrServer:
  Состояние: ${tsStatus}
  ${d.torrserver.last_error ? `Сообщение: ${sanitizeText(d.torrserver.last_error)}` : 'Ошибок нет'}

Видеоплеер (MPV):
  Состояние: ${mpvStatus}
  ${d.mpv.last_error ? `Сообщение: ${sanitizeText(d.mpv.last_error)}` : 'Ошибок нет'}
`;
  }

  const tsRunning = d.torrserver.running ? 'Yes' : 'No';
  const mpvAvail = d.mpv.available ? 'Yes' : 'No';
  const dbOk = d.db.ok ? 'OK' : 'Error';

  const used =
    d.disk.used_mb != null
      ? d.disk.used_mb >= 1024
        ? `${(d.disk.used_mb / 1024).toFixed(1)} GB`
        : `${d.disk.used_mb.toFixed(1)} MB`
      : 'Unknown';
  const free =
    d.disk.free_mb != null
      ? d.disk.free_mb >= 1024
        ? `${(d.disk.free_mb / 1024).toFixed(1)} GB`
        : `${d.disk.free_mb.toFixed(1)} MB`
      : 'Unknown';

  let totalStr = 'Unknown';
  if (d.disk.used_mb != null && d.disk.free_mb != null) {
    const total = d.disk.used_mb + d.disk.free_mb;
    const pct = Math.round((d.disk.used_mb / (total || 1)) * 100);
    const totalGb = (total / 1024).toFixed(1);
    totalStr = `${totalGb} GB (${pct}% used)`;
  }

  const errorsList =
    d.last_errors && d.last_errors.length > 0
      ? d.last_errors
          .slice(0, 50)
          .map(
            (e) =>
              `  [${e.timestamp}] [${e.component}] [${e.error_type}]: ${sanitizeText(e.message)}`
          )
          .join('\n')
      : '  No recorded errors';

  return `System Diagnostics

Application version: ${d.version}
Status: ${d.status}
Checked at: ${d.checked_at}
Response time: ${d.response_time_ms} ms

TorrServer:
  Running: ${tsRunning}
  Port: ${d.torrserver.port ?? '—'}
  PID: ${d.torrserver.pid ?? '—'}
  Path: ${d.torrserver.path ?? '—'}
  Version: ${d.torrserver.version ?? '—'}
  Last error: ${d.torrserver.last_error ? sanitizeText(d.torrserver.last_error) : 'None'}

MPV:
  Available: ${mpvAvail}
  Version: ${d.mpv.version ?? '—'}
  Path: ${d.mpv.path ?? '—'}
  Last error: ${d.mpv.last_error ? sanitizeText(d.mpv.last_error) : 'None'}

Database (SQLite):
  Status: ${dbOk}
  Size: ${d.db.size_mb != null ? `${d.db.size_mb} MB` : '—'}

Disk:
  Data directory: ${d.disk.data_dir}
  Used: ${used}
  Free: ${free}
  Total: ${totalStr}

Recent errors:
${errorsList}
`;
};

export const copyTextToClipboard = async (text: string): Promise<boolean> => {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fallback к document.execCommand
    }
  }

  if (typeof document !== 'undefined') {
    try {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      const success = document.execCommand('copy');
      document.body.removeChild(textarea);
      return !!success;
    } catch {
      return false;
    }
  }

  return false;
};

export function useDiagnosticsReport(data: DiagnosticsResponse | null, debugMode: boolean) {
  const [copyFeedback, setCopyFeedback] = useState<'success' | 'error' | null>(null);
  const copyTimeoutRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) {
        window.clearTimeout(copyTimeoutRef.current);
      }
    };
  }, []);

  const handleCopyReport = useCallback(async () => {
    if (!data) return;
    const text = buildReportText(data, debugMode);
    const success = await copyTextToClipboard(text);
    setCopyFeedback(success ? 'success' : 'error');
    if (copyTimeoutRef.current) {
      window.clearTimeout(copyTimeoutRef.current);
    }
    copyTimeoutRef.current = window.setTimeout(() => {
      setCopyFeedback(null);
    }, 3000);
  }, [data, debugMode]);

  return {
    copyFeedback,
    handleCopyReport,
  };
}

export interface DiagnosticsReportButtonProps {
  copyFeedback: 'success' | 'error' | null;
  onCopy: () => void;
  debugMode: boolean;
}

export const DiagnosticsReportButton: React.FC<DiagnosticsReportButtonProps> = ({
  copyFeedback,
  onCopy,
  debugMode,
}) => {
  const { t } = useApp();

  return (
    <Button
      variant="secondary"
      size="sm"
      icon={
        copyFeedback === 'success' ? (
          <Check className="w-3.5 h-3.5 text-emerald-400" />
        ) : (
          <Copy className="w-3.5 h-3.5 text-film-text" />
        )
      }
      onClick={onCopy}
    >
      {copyFeedback === 'success'
        ? t('report_copied') || 'Скопировано!'
        : debugMode
        ? t('copy_report') || 'Скопировать отчёт'
        : t('copy_error_report') || 'Отчёт об ошибке'}
    </Button>
  );
};

export const DiagnosticsReportAlert: React.FC = () => {
  const { t } = useApp();
  return (
    <div className="p-3 bg-rose-950/40 border border-rose-800/60 rounded-md font-sans text-xs text-rose-300 flex items-center gap-2">
      <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
      <span>{t('report_copy_failed') || 'Не удалось скопировать отчёт в буфер обмена.'}</span>
    </div>
  );
};
