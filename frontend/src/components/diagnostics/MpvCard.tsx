/**
 * @file components/diagnostics/MpvCard.tsx
 * @description Карточка диагностики видеоплеера MPV: доступность, версия, путь к исполняемому файлу и ошибки.
 */

import React from 'react';
import { Film, RefreshCw } from 'lucide-react';
import { DiagnosticsResponse } from '../../types';
import { useApp } from '../../context/AppContext';
import { Button } from '../ui/UIComponents';
import { DiagnosticCard } from './DiagnosticCard';

export interface MpvCardProps {
  mpv: DiagnosticsResponse['mpv'];
  debugMode: boolean;
  onRefresh: () => void;
}

export const MpvCard: React.FC<MpvCardProps> = ({ mpv, debugMode, onRefresh }) => {
  const { t } = useApp();

  return (
    <DiagnosticCard
      title={debugMode ? 'MPV Player' : (t('video_player') || 'Видеоплеер')}
      icon={<Film className="w-5 h-5 text-film-accent" />}
      statusText={
        mpv.state === 'error'
          ? 'Ошибка воспроизведения'
          : mpv.state === 'starting'
          ? 'Запускается'
          : mpv.state === 'running'
          ? 'Воспроизводит'
          : mpv.available
          ? t('status_available') || 'Доступен'
          : t('status_not_found') || 'Не найден'
      }
      statusVariant={mpv.state === 'error' ? 'unhealthy' : mpv.available ? 'healthy' : 'degraded'}
      items={
        debugMode
          ? [
              { label: 'Последняя ошибка', value: mpv.last_error || '—', alert: !!mpv.last_error },
              {
                label: t('version') || 'Версия',
                value: mpv.version || '—',
              },
              {
                label: t('path') || 'Путь к файлу',
                value: mpv.path || '—',
                breakAll: true,
              },
            ]
          : mpv.last_error
          ? [
              {
                label: t('last_error') || 'Сообщение',
                value: mpv.last_error,
                alert: true,
                breakAll: true,
              },
            ]
          : []
      }
      extraContent={
        !debugMode && !mpv.available ? (
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
