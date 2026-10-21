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
  HardDrive,
  Radio,
  RefreshCw,
  Upload,
} from 'lucide-react';
import { DiagnosticsResponse } from '../../types';
import { API } from '../../services/api';
import { useApp } from '../../context/AppContext';
import { Button, Card, Badge } from '../ui/UIComponents';
import { DiagnosticCard } from './DiagnosticCard';
import { DiagnosticsErrors } from './DiagnosticsErrors';

export const DiagnosticsView: React.FC = () => {
  const { t } = useApp();
  const [data, setData] = useState<DiagnosticsResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [staleWarning, setStaleWarning] = useState<string | null>(null);
  const [copyFeedback, setCopyFeedback] = useState<'success' | 'error' | null>(null);

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

  useEffect(() => {
    void loadDiagnostics(false);

    return () => {
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

  /**
   * Вычисление процента заполненности диска
   */
  const diskUsage = (() => {
    if (!data || data.disk.used_mb == null || data.disk.free_mb == null) {
      return null;
    }
    const total = data.disk.used_mb + data.disk.free_mb;
    if (total <= 0) return null;
    const percent = Math.min(100, Math.max(0, Math.round((data.disk.used_mb / total) * 100)));
    return {
      percent,
      total,
      isWarning: percent >= 80 && percent < 95,
      isCritical: percent >= 95,
    };
  })();

  // 1. Состояние первоначальной загрузки
  if (isLoading && !data) {
    return (
      <div className="space-y-6 max-w-6xl mx-auto py-2">
        <div className="flex items-center justify-between pb-4 border-b border-slate-800/80">
          <div className="flex items-center gap-3">
            <Activity className="w-6 h-6 text-cyan-400 animate-pulse" />
            <h1 className="font-tech font-bold text-2xl uppercase tracking-wider text-slate-100">
              {t('system_diagnostics') || 'Диагностика системы'}
            </h1>
          </div>
        </div>

        <div className="p-8 rounded-lg bg-[#0a0e18] border border-slate-800/80 flex flex-col items-center justify-center min-h-[320px] text-center space-y-3">
          <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin" />
          <p className="font-tech uppercase tracking-wider text-sm text-slate-300">
            {t('checking') || 'Сбор диагностических данных...'}
          </p>
        </div>
      </div>
    );
  }

  // 2. Экран ошибки запроса (если данных нет вообще)
  if (error && !data) {
    return (
      <div className="space-y-6 max-w-6xl mx-auto py-2">
        <div className="flex items-center gap-3 pb-4 border-b border-slate-800/80">
          <Activity className="w-6 h-6 text-rose-400" />
          <h1 className="font-tech font-bold text-2xl uppercase tracking-wider text-slate-100">
            {t('system_diagnostics') || 'Диагностика системы'}
          </h1>
        </div>

        <Card className="p-8 rounded-lg bg-[#0a0e18] border border-rose-900/40 text-center space-y-4 max-w-xl mx-auto my-12">
          <div className="w-12 h-12 rounded-full bg-rose-500/10 border border-rose-500/30 flex items-center justify-center mx-auto text-rose-400">
            <AlertTriangle className="w-6 h-6" />
          </div>
          <div className="space-y-1.5">
            <h2 className="font-tech font-bold text-lg uppercase tracking-wider text-slate-100">
              {t('diag_load_error') || 'Не удалось получить данные диагностики'}
            </h2>
            <p className="font-sans text-xs text-slate-400">
              {t('diag_load_error_hint') ||
                'Проверьте подключение к приложению и попробуйте обновить данные.'}
            </p>
            <p className="font-code text-xs text-rose-400/90 pt-1 break-all">
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
  const statusBadgeVariant = isHealthy
    ? 'green'
    : isDegraded
    ? 'amber'
    : 'rose';

  const statusLabel = isHealthy
    ? t('status_healthy') || 'Работает'
    : isDegraded
    ? t('status_degraded') || 'Есть проблемы'
    : t('status_unhealthy') || 'Не удалось проверить';

  const formattedCheckedAt = data.checked_at
    ? new Date(data.checked_at).toLocaleTimeString()
    : '—';

  return (
    <div className="space-y-6 max-w-6xl mx-auto py-2">
      {/* ── ШАПКА РАЗДЕЛА ── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-slate-800/80">
        <div>
          <div className="flex items-center gap-2.5">
            <Activity className="w-6 h-6 text-cyan-400" />
            <h1 className="font-tech font-bold text-2xl uppercase tracking-wider text-slate-100">
              {t('system_diagnostics') || 'Диагностика системы'}
            </h1>
          </div>
          <p className="font-code text-xs text-slate-400 mt-1 flex items-center gap-2">
            <span>
              {t('app_version') || 'Версия'}: <strong className="text-cyan-300 font-semibold">{data.version}</strong>
            </span>
            <span>•</span>
            <span>
              {t('response_time') || 'Ответ'}: <strong className="text-slate-300 font-semibold">{data.response_time_ms} ms</strong>
            </span>
          </p>
        </div>

        {/* Кнопки управления */}
        <div className="flex flex-wrap items-center gap-2.5 shrink-0">
          <Button
            variant="secondary"
            size="sm"
            icon={<FolderOpen className="w-3.5 h-3.5 text-cyan-400" />}
            onClick={() => void API.openFolder()}
          >
            {t('open_data_folder') || 'Папка данных'}
          </Button>

          <Button
            variant="secondary"
            size="sm"
            icon={
              copyFeedback === 'success' ? (
                <Check className="w-3.5 h-3.5 text-emerald-400" />
              ) : (
                <Copy className="w-3.5 h-3.5 text-slate-300" />
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
      <Card className="p-5 bg-[#0a0e18] border border-slate-800/80 rounded-lg shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div
            className={`w-3.5 h-3.5 rounded-full ${
              isHealthy
                ? 'bg-emerald-400 shadow-[0_0_12px_#34d399]'
                : isDegraded
                ? 'bg-amber-400 shadow-[0_0_12px_#fbbf24]'
                : 'bg-rose-500 shadow-[0_0_12px_#f43f5e]'
            }`}
          />
          <div>
            <div className="flex items-center gap-2">
              <span className="font-tech text-sm uppercase tracking-wider text-slate-400">
                {t('overall_status') || 'Общее состояние'}:
              </span>
              <strong className="font-tech text-base uppercase tracking-wider text-slate-100">
                {statusLabel}
              </strong>
            </div>
            <p className="font-code text-xs text-slate-500 flex items-center gap-1.5 mt-0.5">
              <Clock className="w-3.5 h-3.5 text-slate-500" />
              <span>
                {t('last_checked') || 'Последняя проверка'}: {formattedCheckedAt}
              </span>
            </p>
          </div>
        </div>

        <Badge variant={statusBadgeVariant} pulse={isHealthy}>
          {data.status.toUpperCase()}
        </Badge>
      </Card>

      {/* ── СЕТКА КАРТОЧЕК КОМПОНЕНТОВ (2 КОЛОНКИ НА ДЕСКТОПЕ) ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Карточка 1: TorrServer */}
        <DiagnosticCard
          title="TorrServer"
          icon={<Radio className="w-5 h-5 text-cyan-400" />}
          statusText={
            data.torrserver.running
              ? t('status_running') || 'Работает'
              : t('status_stopped') || 'Не запущен'
          }
          statusVariant={data.torrserver.running ? 'healthy' : 'degraded'}
          items={[
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
        />

        {/* Карточка 2: MPV */}
        <DiagnosticCard
          title="MPV Player"
          icon={<Film className="w-5 h-5 text-cyan-400" />}
          statusText={
            data.mpv.available
              ? t('status_available') || 'Доступен'
              : t('status_not_found') || 'Не найден'
          }
          statusVariant={data.mpv.available ? 'healthy' : 'degraded'}
          items={[
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
          icon={<Database className="w-5 h-5 text-cyan-400" />}
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
              label: t('status') || 'Состояние',
              value: data.db.ok ? 'OK (SELECT 1)' : 'FAIL',
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
                    icon={<Upload className="w-3.5 h-3.5 text-pink-400" />}
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

        {/* Карточка 4: Дисковое пространство */}
        <DiagnosticCard
          title={t('disk_status') || 'Дисковое пространство'}
          icon={<HardDrive className="w-5 h-5 text-cyan-400" />}
          statusText={
            diskUsage?.isCritical
              ? 'Критично'
              : diskUsage?.isWarning
              ? 'Мало места'
              : 'В норме'
          }
          statusVariant={
            diskUsage?.isCritical
              ? 'unhealthy'
              : diskUsage?.isWarning
              ? 'degraded'
              : 'healthy'
          }
          items={[
            {
              label: t('data_dir') || 'Каталог данных',
              value: (
                <span className="flex items-center gap-1.5 justify-end">
                  <span className="break-all">{data.disk.data_dir}</span>
                  <button
                    type="button"
                    onClick={() => void API.openFolder()}
                    title={t('open_data_folder') || 'Открыть папку данных'}
                    className="p-1 text-slate-400 hover:text-cyan-300 hover:bg-slate-800/70 rounded shrink-0 transition-colors cursor-pointer"
                  >
                    <FolderOpen className="w-3.5 h-3.5 text-cyan-400" />
                  </button>
                </span>
              ),
              breakAll: true,
            },
            {
              label: t('used_space') || 'Занято',
              value: formatMb(data.disk.used_mb),
            },
            {
              label: t('free_space') || 'Свободно',
              value: formatMb(data.disk.free_mb),
            },
            ...(diskUsage
              ? [
                  {
                    label: t('total_space') || 'Всего',
                    value: `${formatMb(diskUsage.total)} (${diskUsage.percent}%)`,
                  },
                ]
              : []),
          ]}
          extraContent={
            diskUsage ? (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between font-code text-xs text-slate-400">
                  <span>{t('used_space') || 'Заполнение диска'}</span>
                  <span
                    className={`font-semibold ${
                      diskUsage.isCritical
                        ? 'text-rose-400'
                        : diskUsage.isWarning
                        ? 'text-amber-400'
                        : 'text-cyan-400'
                    }`}
                  >
                    {diskUsage.percent}%
                  </span>
                </div>
                {/* Кастомная полоса заполненности диска */}
                <div className="w-full bg-slate-900/90 h-2.5 rounded-full overflow-hidden border border-slate-800 p-[1px]">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      diskUsage.isCritical
                        ? 'bg-rose-500 shadow-[0_0_8px_#f43f5e]'
                        : diskUsage.isWarning
                        ? 'bg-amber-400 shadow-[0_0_8px_#fbbf24]'
                        : 'bg-cyan-400 shadow-[0_0_8px_#22d3ee]'
                    }`}
                    style={{ width: `${diskUsage.percent}%` }}
                  />
                </div>
              </div>
            ) : null
          }
        />
      </div>

      {/* ── РАЗДЕЛ ПОСЛЕДНИХ ОШИБОК ── */}
      <DiagnosticsErrors errors={data.last_errors} t={t} />
    </div>
  );
};
