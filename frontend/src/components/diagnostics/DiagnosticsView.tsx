/**
 * @file components/diagnostics/DiagnosticsView.tsx
 * @description Главный экран комплексной диагностики системы Pirate Cinema.
 */

import React from 'react';
import { Activity, AlertTriangle, FolderOpen, RefreshCw } from 'lucide-react';
import { API } from '../../services/api';
import { useApp } from '../../context/AppContext';
import { Button, Card } from '../ui/UIComponents';
import { DiagnosticsErrors } from './DiagnosticsErrors';
import { useDiagnostics } from './useDiagnostics';
import {
  useDiagnosticsReport,
  DiagnosticsReportButton,
  DiagnosticsReportAlert,
} from './DiagnosticsReport';
import { SystemStatusCard } from './SystemStatusCard';
import { TorrServerCard } from './TorrServerCard';
import { MpvCard } from './MpvCard';
import { SqliteCard } from './SqliteCard';

interface DiagnosticsViewProps {
  hideHeader?: boolean;
}

export const DiagnosticsView: React.FC<DiagnosticsViewProps> = ({ hideHeader }) => {
  const { t, debugMode } = useApp();
  const {
    data,
    isLoading,
    isRefreshing,
    error,
    staleWarning,
    serviceAction,
    serviceMessage,
    tsLog,
    tsUpdate,
    loadDiagnostics,
    runServiceAction,
  } = useDiagnostics();

  const { copyFeedback, handleCopyReport } = useDiagnosticsReport(data, debugMode);

  // 1. Состояние первоначальной загрузки
  if (isLoading && !data) {
    return (
      <div className="ui-page ui-diagnostics space-y-6 max-w-6xl mx-auto py-2">
        <div className="flex items-center justify-between pb-4 border-b border-film-line">
          <div className="flex items-center gap-3">
            <Activity className="w-6 h-6 text-film-accent animate-pulse" />
            <h1 className="font-sans font-semibold text-2xl text-film-text">
              {t('system_diagnostics') || 'Диагностика системы'}
            </h1>
          </div>
        </div>

        <div className="p-8 rounded-md bg-film-base border border-film-line flex flex-col items-center justify-center min-h-[320px] text-center space-y-3">
          <RefreshCw className="w-8 h-8 text-film-accent animate-spin" />
          <p className="font-sans text-sm text-film-text">
            {t('checking') || 'Сбор диагностических данных...'}
          </p>
        </div>
      </div>
    );
  }

  // 2. Экран ошибки запроса (если данных нет вообще)
  if (error && !data) {
    return (
      <div className="ui-page ui-diagnostics space-y-6 max-w-6xl mx-auto py-2">
        <div className="flex items-center gap-3 pb-4 border-b border-film-line">
          <Activity className="w-6 h-6 text-rose-400" />
          <h1 className="font-sans font-semibold text-2xl text-film-text">
            {t('system_diagnostics') || 'Диагностика системы'}
          </h1>
        </div>

        <Card className="p-8 rounded-md bg-film-base border border-rose-900/40 text-center space-y-4 max-w-xl mx-auto my-12">
          <div className="w-12 h-12 rounded-full bg-rose-500/10 border border-rose-500/30 flex items-center justify-center mx-auto text-rose-400">
            <AlertTriangle className="w-6 h-6" />
          </div>
          <div className="space-y-1.5">
            <h2 className="font-sans font-semibold text-lg text-film-text">
              {t('diag_load_error') || 'Не удалось получить данные диагностики'}
            </h2>
            <p className="font-sans text-xs text-film-muted">
              {t('diag_load_error_hint') ||
                'Проверьте подключение к приложению и попробуйте обновить данные.'}
            </p>
            <p className="font-sans text-xs text-rose-400/90 pt-1 break-all">
              {error}
            </p>
          </div>
          <Button
            variant="cyan"
            size="md"
            icon={<RefreshCw className="w-4 h-4" />}
            onClick={() => void loadDiagnostics(true)}
          >
            {t('try_again') || 'Повторить попытку'}
          </Button>
        </Card>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="ui-page ui-diagnostics space-y-6 max-w-6xl mx-auto py-2">
      {/* ── ШАПКА РАЗДЕЛА ── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-film-line">
        <div>
          {!hideHeader && (
            <div className="flex items-center gap-2.5 mb-1">
              <Activity className="w-6 h-6 text-film-accent" />
              <h1 className="font-sans font-semibold text-2xl text-film-text">
                {debugMode
                  ? t('system_diagnostics') || 'Диагностика системы'
                  : t('service_status') || 'Статус служб'}
              </h1>
            </div>
          )}
          <p className="font-sans text-xs text-film-muted flex items-center gap-2">
            <span>
              {t('app_version') || 'Версия'}:{' '}
              <strong className="text-film-accent font-semibold">{data.version}</strong>
            </span>
            {debugMode && (
              <>
                <span>•</span>
                <span>
                  {t('response_time') || 'Ответ'}:{' '}
                  <strong className="text-film-text font-semibold">
                    {data.response_time_ms} ms
                  </strong>
                </span>
              </>
            )}
          </p>
        </div>

        {/* Кнопки управления */}
        <div className="flex flex-wrap items-center gap-2.5 shrink-0">
          {debugMode && (
            <Button
              variant="secondary"
              size="sm"
              icon={<FolderOpen className="w-3.5 h-3.5 text-film-accent" />}
              onClick={() => void API.openFolder()}
            >
              {t('open_data_folder').replace(/^📂\s*/, '') || 'Папка данных'}
            </Button>
          )}

          <DiagnosticsReportButton
            copyFeedback={copyFeedback}
            onCopy={handleCopyReport}
            debugMode={debugMode}
          />

          <Button
            variant="cyan"
            size="sm"
            loading={isRefreshing}
            icon={
              <RefreshCw
                className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`}
              />
            }
            onClick={() => void loadDiagnostics(true)}
          >
            {debugMode
              ? t('refresh_diagnostics') || 'Обновить'
              : t('try_again') || 'Повторить'}
          </Button>
        </div>
      </div>

      {/* Уведомление об ошибке буфера обмена */}
      {copyFeedback === 'error' && <DiagnosticsReportAlert />}

      {/* Предупреждение об устаревших данных */}
      {staleWarning && (
        <div className="p-3 bg-amber-950/30 border border-amber-800/60 rounded-md font-sans text-xs text-amber-300 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
          <span>{staleWarning}</span>
        </div>
      )}

      {/* ── ОБЩИЙ СТАТУС СИСТЕМЫ ── */}
      <SystemStatusCard status={data.status} checkedAt={data.checked_at} />

      {/* ── СЕТКА КАРТОЧЕК КОМПОНЕНТОВ (2 КОЛОНКИ НА ДЕСКТОПЕ) ── */}
      <div className="ui-diagnostics-list">
        <TorrServerCard
          torrserver={data.torrserver}
          mpvState={data.mpv.state}
          debugMode={debugMode}
          serviceAction={serviceAction}
          serviceMessage={serviceMessage}
          tsLog={tsLog}
          tsUpdate={tsUpdate}
          onAction={runServiceAction}
          onRefresh={() => void loadDiagnostics(true)}
        />

        <MpvCard
          mpv={data.mpv}
          debugMode={debugMode}
          onRefresh={() => void loadDiagnostics(true)}
        />

        {debugMode && <SqliteCard db={data.db} />}
      </div>

      {/* ── РАЗДЕЛ ПОСЛЕДНИХ ОШИБОК ── */}
      {debugMode && <DiagnosticsErrors errors={data.last_errors} t={t} />}
    </div>
  );
};
