/**
 * @file components/diagnostics/DiagnosticsView.tsx
 * @description Главный экран комплексной диагностики системы Pirate Cinema.
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Activity,
  AlertTriangle,
  Check,
  Clock,
  Copy,
  Database,
  Download,
  Film,
  FolderOpen,
  Radio,
  RefreshCw,
  Upload,
} from 'lucide-react';
import { DiagnosticsResponse } from '../../types';
import { API } from '../../services/api';
import { useApp } from '../../context/AppContext';
import { Button, Card } from '../ui/UIComponents';
import { DiagnosticCard } from './DiagnosticCard';
import { DiagnosticsErrors } from './DiagnosticsErrors';

interface DiagnosticsViewProps {
  hideHeader?: boolean;
}

export const DiagnosticsView: React.FC<DiagnosticsViewProps> = ({ hideHeader }) => {
  const { t } = useApp();
  const [data, setData] = useState<DiagnosticsResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [staleWarning, setStaleWarning] = useState<string | null>(null);
  const [copyFeedback, setCopyFeedback] = useState<'success' | 'error' | null>(null);
  const [serviceAction, setServiceAction] = useState<string | null>(null);
  const [serviceMessage, setServiceMessage] = useState<string | null>(null);
  const [tsLog, setTsLog] = useState<string | null>(null);
  const [tsUpdate, setTsUpdate] = useState<{ latest_version: string; release_url: string; update_available: boolean | null } | null>(null);

  // Резервное копирование
  const [isDownloadingBackup, setIsDownloadingBackup] = useState<boolean>(false);
  const [backupHint, setBackupHint] = useState<{ text: string; isError?: boolean } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const abortControllerRef = useRef<AbortController | null>(null);
  const copyTimeoutRef = useRef<number | null>(null);

  /**
   * Загрузка данных диагностики
   */
  const loadDiagnostics = useCallback(
    async (isManualRefresh: boolean = false) => {
      // Защита от параллельных дублирующих запросов
      if (isManualRefresh && (isRefreshing || isLoading)) {
        return;
      }

      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      const controller = new AbortController();
      abortControllerRef.current = controller;

      if (isManualRefresh) {
        setIsRefreshing(true);
      } else {
        setIsLoading(true);
      }

      try {
        const res = await API.getSystemDiagnostics(controller.signal);
        setData(res);
        setError(null);
        setStaleWarning(null);
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          return;
        }

        const msg =
          err instanceof Error
            ? err.message
            : 'Не удалось подключиться к серверу';

        if (data) {
          // Если старые данные уже есть — сохраняем их и показываем предупреждение
          const timeStr = data.checked_at
            ? new Date(data.checked_at).toLocaleTimeString()
            : '';
          setStaleWarning(
            t('diag_stale_warning', { time: timeStr }) ||
              `Отображаются устаревшие данные от ${timeStr}. Ошибка: ${msg}`
          );
        } else {
          // Данных нет вообще — показываем экран ошибки
          setError(msg);
        }
      } finally {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    },
    [data, isLoading, isRefreshing, t]
  );
  const loadRef = useRef(loadDiagnostics);
  loadRef.current = loadDiagnostics;

  const runServiceAction = async (action: 'restart' | 'update' | 'log') => {
    if (serviceAction) return;
    setServiceAction(action); setServiceMessage(null);
    try {
      if (action === 'restart') {
        await API.restartTorrServer();
        setServiceMessage('TorrServer перезапущен');
        await loadRef.current(true);
      } else if (action === 'update') setTsUpdate(await API.checkTorrServerUpdate());
      else setTsLog(tsLog === null ? await API.getTorrServerLog() : null);
    } catch (error) {
      setServiceMessage(error instanceof Error ? error.message : 'Операция не выполнена');
    } finally { setServiceAction(null); }
  };

  useEffect(() => {
    void loadDiagnostics(false);
    const timer = window.setInterval(() => {
      if (!document.hidden) void loadRef.current(true);
    }, 10000);

    return () => {
      window.clearInterval(timer);
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (copyTimeoutRef.current) {
        window.clearTimeout(copyTimeoutRef.current);
      }
    };
  }, []);

  /**
   * Скачивание архива бэкапа
   */
  const handleDownloadBackup = async () => {
    setIsDownloadingBackup(true);
    setBackupHint(null);
    try {
      if (window.pywebview?.api?.save_backup) {
        const result = await window.pywebview.api.save_backup();
        if (result.cancelled) {
          setBackupHint({
            text: t('backup_cancelled') || 'Сохранение бэкапа отменено',
          });
          return;
        }
        if (!result.saved) {
          throw new Error(result.error || 'Не удалось сохранить бэкап');
        }
        setBackupHint({
          text:
            t('backup_saved', { path: result.path || '' }) ||
            `Бэкап сохранён: ${result.path}`,
        });
        return;
      }

      const backup = await API.downloadBackup();
      const objectUrl = URL.createObjectURL(backup);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = 'pirate_cinema_backup.zip';
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      setBackupHint({ text: t('backup_saved', { path: 'downloads' }) || 'Бэкап успешно скачан' });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Не удалось скачать бэкап';
      setBackupHint({ text: msg, isError: true });
    } finally {
      setIsDownloadingBackup(false);
    }
  };

  /**
   * Восстановление бэкапа из файла
   */
  const handleUploadBackup = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (
      !window.confirm(
        t('confirm_restore') ||
          'Восстановить конфигурацию и базу данных из архива?'
      )
    ) {
      if (fileInputRef.current) fileInputRef.current.value = '';
      return;
    }

    try {
      await API.restoreBackup(file);
      alert(t('restore_success') || 'Данные успешно восстановлены');
      window.location.reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Ошибка восстановления';
      alert(t('restore_error', { error: msg }) || msg);
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  /**
   * Форматирование размера в МБ / ГБ
   */
  const formatMb = (mb: number | null | undefined): string => {
    if (mb === null || mb === undefined || isNaN(mb)) return '—';
    if (mb >= 1024) {
      return (mb / 1024).toFixed(1) + ' ' + (t('gb') || 'ГБ');
    }
    return mb.toFixed(1) + ' ' + (t('mb') || 'МБ');
  };

  /**
   * Сборка безопасного компактного отчёта для буфера обмена
   */
  const buildReportText = (d: DiagnosticsResponse): string => {
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
                `  [${e.timestamp}] [${e.component}] [${e.error_type}]: ${e.message}`
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
  Last error: ${d.torrserver.last_error ?? 'None'}

MPV:
  Available: ${mpvAvail}
  Version: ${d.mpv.version ?? '—'}
  Path: ${d.mpv.path ?? '—'}

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

  /**
   * Копирование отчёта в буфер обмена
   */
  const handleCopyReport = async () => {
    if (!data) return;

    const text = buildReportText(data);
    let success = false;

    if (navigator?.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        success = true;
      } catch {
        success = false;
      }
    }

    if (!success) {
      // Запасной способ через скрытое текстовое поле
      try {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        success = document.execCommand('copy');
        document.body.removeChild(textarea);
      } catch {
        success = false;
      }
    }

    setCopyFeedback(success ? 'success' : 'error');
    if (copyTimeoutRef.current) {
      window.clearTimeout(copyTimeoutRef.current);
    }
    copyTimeoutRef.current = window.setTimeout(() => {
      setCopyFeedback(null);
    }, 3000);
  };

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

  // Определение общего статуса системы
  const isHealthy = data.status === 'healthy';
  const isDegraded = data.status === 'degraded';
  const statusLabel = isHealthy
    ? t('status_healthy') || 'Работает'
    : isDegraded
    ? t('status_degraded') || 'Есть проблемы'
    : t('status_unhealthy') || 'Не удалось проверить';

  const formattedCheckedAt = data.checked_at
    ? new Date(data.checked_at).toLocaleTimeString()
    : '—';

  return (
    <div className="ui-page ui-diagnostics space-y-6 max-w-6xl mx-auto py-2">
      {/* ── ШАПКА РАЗДЕЛА ── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-film-line">
        <div>
          {!hideHeader && (
            <div className="flex items-center gap-2.5 mb-1">
              <Activity className="w-6 h-6 text-film-accent" />
              <h1 className="font-sans font-semibold text-2xl text-film-text">
                {t('system_diagnostics') || 'Диагностика системы'}
              </h1>
            </div>
          )}
          <p className="font-sans text-xs text-film-muted flex items-center gap-2">
            <span>
              {t('app_version') || 'Версия'}: <strong className="text-film-accent font-semibold">{data.version}</strong>
            </span>
            <span>•</span>
            <span>
              {t('response_time') || 'Ответ'}: <strong className="text-film-text font-semibold">{data.response_time_ms} ms</strong>
            </span>
          </p>
        </div>

        {/* Кнопки управления */}
        <div className="flex flex-wrap items-center gap-2.5 shrink-0">
          <Button
            variant="secondary"
            size="sm"
            icon={<FolderOpen className="w-3.5 h-3.5 text-film-accent" />}
            onClick={() => void API.openFolder()}
          >
            {t('open_data_folder').replace(/^📂\s*/, '') || 'Папка данных'}
          </Button>

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
            onClick={handleCopyReport}
          >
            {copyFeedback === 'success'
              ? t('report_copied') || 'Скопировано!'
              : t('copy_report') || 'Скопировать отчёт'}
          </Button>

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
            {t('refresh_diagnostics') || 'Обновить'}
          </Button>
        </div>
      </div>

      {/* Уведомление об ошибке буфера обмена */}
      {copyFeedback === 'error' && (
        <div className="p-3 bg-rose-950/40 border border-rose-800/60 rounded-md font-sans text-xs text-rose-300 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
          <span>{t('report_copy_failed') || 'Не удалось скопировать отчёт в буфер обмена.'}</span>
        </div>
      )}

      {/* Предупреждение об устаревших данных */}
      {staleWarning && (
        <div className="p-3 bg-amber-950/30 border border-amber-800/60 rounded-md font-sans text-xs text-amber-300 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
          <span>{staleWarning}</span>
        </div>
      )}

      {/* ── ОБЩИЙ СТАТУС СИСТЕМЫ ── */}
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

      {/* ── СЕТКА КАРТОЧЕК КОМПОНЕНТОВ (2 КОЛОНКИ НА ДЕСКТОПЕ) ── */}
      <div className="ui-diagnostics-list">
        {/* Карточка 1: TorrServer */}
        <DiagnosticCard
          title="TorrServer"
          icon={<Radio className="w-5 h-5 text-film-accent" />}
          statusText={
            data.torrserver.state === 'recovering' ? 'Восстанавливается'
              : data.torrserver.state === 'error' ? 'Ошибка'
              : data.torrserver.running
              ? t('status_running') || 'Работает'
              : t('status_stopped') || 'Не запущен'
          }
          statusVariant={data.torrserver.state === 'error' ? 'unhealthy' : data.torrserver.running ? 'healthy' : 'degraded'}
          items={[
            { label: 'Версия', value: data.torrserver.version || '—' },
            { label: 'Управление', value: data.torrserver.managed ? 'Приложение' : 'Внешняя служба' },
            { label: 'Исполняемый файл', value: data.torrserver.path || '—', breakAll: true },
            {
              label: t('pid') || 'PID',
              value: data.torrserver.pid != null ? String(data.torrserver.pid) : '—',
            },
            {
              label: t('port') || 'Порт',
              value: data.torrserver.port != null ? String(data.torrserver.port) : '—',
            },
            {
              label: t('last_error') || 'Последняя ошибка',
              value: data.torrserver.last_error || t('no_errors') || 'Отсутствует',
              alert: !!data.torrserver.last_error,
              breakAll: true,
            },
          ]}
          extraContent={<div className="space-y-2">
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" disabled={!data.torrserver.can_restart || !!serviceAction || data.mpv.state === 'running' || data.mpv.state === 'starting'}
                loading={serviceAction === 'restart'} onClick={() => void runServiceAction('restart')}>Перезапустить</Button>
              <Button size="sm" variant="secondary" disabled={!!serviceAction} loading={serviceAction === 'update'}
                onClick={() => void runServiceAction('update')}>Проверить обновления</Button>
              {data.torrserver.log_path && <Button size="sm" variant="ghost" disabled={!!serviceAction}
                onClick={() => void runServiceAction('log')}>{tsLog === null ? 'Журнал' : 'Скрыть журнал'}</Button>}
            </div>
            {data.mpv.state === 'running' && <p className="text-xs text-film-muted">Для перезапуска остановите воспроизведение.</p>}
            {serviceMessage && <p role="status" className="text-xs text-film-text">{serviceMessage}</p>}
            {tsUpdate && <p className="text-xs text-film-muted">
              {tsUpdate.update_available === true ? 'Доступна версия ' : tsUpdate.update_available === false ? 'Установлена актуальная версия: ' : 'Последний выпуск: '}
              <a className="text-film-accent underline" href={tsUpdate.release_url} target="_blank" rel="noreferrer">{tsUpdate.latest_version}</a>
              {' · Установка вручную'}</p>}
            {tsLog !== null && <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-xs text-film-muted" aria-label="Журнал TorrServer">{tsLog || 'Журнал пока пуст'}</pre>}
          </div>}
        />

        {/* Карточка 2: MPV */}
        <DiagnosticCard
          title="MPV Player"
          icon={<Film className="w-5 h-5 text-film-accent" />}
          statusText={
            data.mpv.state === 'error' ? 'Ошибка воспроизведения'
              : data.mpv.state === 'starting' ? 'Запускается'
              : data.mpv.state === 'running' ? 'Воспроизводит'
              : data.mpv.available
              ? t('status_available') || 'Доступен'
              : t('status_not_found') || 'Не найден'
          }
          statusVariant={data.mpv.state === 'error' ? 'unhealthy' : data.mpv.available ? 'healthy' : 'degraded'}
          items={[
            { label: 'Последняя ошибка', value: data.mpv.last_error || '—', alert: !!data.mpv.last_error },
            {
              label: t('version') || 'Версия',
              value: data.mpv.version || '—',
            },
            {
              label: t('path') || 'Путь к файлу',
              value: data.mpv.path || '—',
              breakAll: true,
            },
          ]}
        />

        {/* Карточка 3: SQLite */}
        <DiagnosticCard
          title="SQLite Database"
          icon={<Database className="w-5 h-5 text-film-accent" />}
          statusText={
            data.db.ok
              ? t('status_healthy') || 'Работает'
              : t('status_unhealthy') || 'Недоступна'
          }
          statusVariant={data.db.ok ? 'healthy' : 'unhealthy'}
          items={[
            {
              label: t('db_size_label') || 'Размер базы',
              value: formatMb(data.db.size_mb),
            },
            {
              label: t('status') || 'Статус',
              value: data.db.ok ? 'OK' : 'FAIL',
              alert: !data.db.ok,
            },
          ]}
          extraContent={
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<Download className="w-3.5 h-3.5 text-emerald-400" />}
                  loading={isDownloadingBackup}
                  onClick={handleDownloadBackup}
                >
                  {t('download_backup') || 'Скачать бэкап'}
                </Button>

                <label className="inline-block cursor-pointer">
                  <input
                    type="file"
                    ref={fileInputRef}
                    accept=".zip"
                    onChange={handleUploadBackup}
                    className="hidden"
                  />
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    icon={<Upload className="w-3.5 h-3.5 text-film-accent" />}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {t('restore_backup') || 'Восстановить бэкап'}
                  </Button>
                </label>
              </div>

              {backupHint && (
                <p
                  className={`text-xs mt-1.5 ${
                    backupHint.isError ? 'text-rose-300' : 'text-emerald-300'
                  }`}
                >
                  {backupHint.text}
                </p>
              )}
            </div>
          }
        />

      </div>

      {/* ── РАЗДЕЛ ПОСЛЕДНИХ ОШИБОК ── */}
      <DiagnosticsErrors errors={data.last_errors} t={t} />
    </div>
  );
};
