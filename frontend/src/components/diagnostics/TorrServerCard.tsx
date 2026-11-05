/**
 * @file components/diagnostics/TorrServerCard.tsx
 * @description Карточка диагностики службы TorrServer: статус, PID/порт, ошибки, перезапуск, проверка обновлений и журнал.
 */

import React from 'react';
import { Radio, RefreshCw } from 'lucide-react';
import { DiagnosticsResponse } from '../../types';
import { useApp } from '../../context/AppContext';
import { Button } from '../ui/UIComponents';
import { DiagnosticCard } from './DiagnosticCard';

export interface TorrServerCardProps {
  torrserver: DiagnosticsResponse['torrserver'];
  mpvState: DiagnosticsResponse['mpv']['state'];
  debugMode: boolean;
  serviceAction: 'restart' | 'update' | 'log' | null;
  serviceMessage: string | null;
  tsLog: string | null;
  tsUpdate: { latest_version: string; release_url: string; update_available: boolean | null } | null;
  onAction: (action: 'restart' | 'update' | 'log') => void;
  onRefresh: () => void;
}

export const TorrServerCard: React.FC<TorrServerCardProps> = ({
  torrserver,
  mpvState,
  debugMode,
  serviceAction,
  serviceMessage,
  tsLog,
  tsUpdate,
  onAction,
  onRefresh,
}) => {
  const { t } = useApp();

  return (
    <DiagnosticCard
      title="TorrServer"
      icon={<Radio className="w-5 h-5 text-film-accent" />}
      statusText={
        torrserver.state === 'recovering'
          ? 'Восстанавливается'
          : torrserver.state === 'error'
          ? 'Ошибка'
          : torrserver.running
          ? t('status_running') || 'Работает'
          : t('status_stopped') || 'Не запущен'
      }
      statusVariant={
        torrserver.state === 'error' ? 'unhealthy' : torrserver.running ? 'healthy' : 'degraded'
      }
      items={
        debugMode
          ? [
              { label: 'Версия', value: torrserver.version || '—' },
              {
                label: 'Управление',
                value: torrserver.managed ? 'Приложение' : 'Внешняя служба',
              },
              { label: 'Исполняемый файл', value: torrserver.path || '—', breakAll: true },
              {
                label: t('pid') || 'PID',
                value: torrserver.pid != null ? String(torrserver.pid) : '—',
              },
              {
                label: t('port') || 'Порт',
                value: torrserver.port != null ? String(torrserver.port) : '—',
              },
              {
                label: t('last_error') || 'Последняя ошибка',
                value: torrserver.last_error || t('no_errors') || 'Отсутствует',
                alert: !!torrserver.last_error,
                breakAll: true,
              },
            ]
          : torrserver.last_error
          ? [
              {
                label: t('last_error') || 'Сообщение',
                value: torrserver.last_error,
                alert: true,
                breakAll: true,
              },
            ]
          : []
      }
      extraContent={
        debugMode ? (
          <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={
                  !torrserver.can_restart ||
                  !!serviceAction ||
                  mpvState === 'running' ||
                  mpvState === 'starting'
                }
                loading={serviceAction === 'restart'}
                onClick={() => onAction('restart')}
              >
                Перезапустить
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={!!serviceAction}
                loading={serviceAction === 'update'}
                onClick={() => onAction('update')}
              >
                Проверить обновления
              </Button>
              {torrserver.log_path && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={!!serviceAction}
                  onClick={() => onAction('log')}
                >
                  {tsLog === null ? 'Журнал' : 'Скрыть журнал'}
                </Button>
              )}
            </div>
            {mpvState === 'running' && (
              <p className="text-xs text-film-muted">
                Для перезапуска остановите воспроизведение.
              </p>
            )}
            {serviceMessage && (
              <p role="status" className="text-xs text-film-text">
                {serviceMessage}
              </p>
            )}
            {tsUpdate && (
              <p className="text-xs text-film-muted">
                {tsUpdate.update_available === true
                  ? 'Доступна версия '
                  : tsUpdate.update_available === false
                  ? 'Установлена актуальная версия: '
                  : 'Последний выпуск: '}
                <a
                  className="text-film-accent underline"
                  href={tsUpdate.release_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {tsUpdate.latest_version}
                </a>
                {' · Установка вручную'}
              </p>
            )}
            {tsLog !== null && (
              <pre
                className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-xs text-film-muted"
                aria-label="Журнал TorrServer"
              >
                {tsLog || 'Журнал пока пуст'}
              </pre>
            )}
          </div>
        ) : !torrserver.running || torrserver.state === 'error' ? (
          <div className="pt-1">
            <Button
              size="sm"
              variant="secondary"
              icon={<RefreshCw className="w-3.5 h-3.5" />}
              onClick={onRefresh}
            >
              {t('try_again') || 'Повторить'}
            </Button>
          </div>
        ) : undefined
      }
    />
  );
};
