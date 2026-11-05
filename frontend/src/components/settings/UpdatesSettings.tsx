/**
 * @file components/settings/UpdatesSettings.tsx
 * @description Раздел проверки, скачивания и установки обновлений Pirate Cinema.
 */

import React from 'react';
import { useApp } from '../../context/AppContext';
import { Button } from '../ui/UIComponents';
import {
  RefreshCw,
  ExternalLink,
  CheckCircle2,
  AlertTriangle,
  Download,
  Play,
  ShieldCheck,
  RotateCcw,
} from 'lucide-react';
import { useAppUpdater, formatBytes } from './useAppUpdater';

export interface UpdatesSettingsProps {
  appVersion: string;
}

export const UpdatesSettings: React.FC<UpdatesSettingsProps> = ({ appVersion }) => {
  const { t } = useApp();
  const {
    updateCheck,
    updateStatus,
    isCheckingUpdate,
    showApplyModal,
    setShowApplyModal,
    isApplying,
    applyMessage,
    handleCheckUpdates,
    handleStartDownload,
    handleCancelDownload,
    handleApplyUpdate,
  } = useAppUpdater(appVersion);

  return (
    <div className="ui-settings-section space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-sans font-semibold text-film-text flex items-center gap-2">
          <RefreshCw className="w-5 h-5 text-film-accent" />
          {t('updates') || 'Обновления'}
        </h2>
        <span className="font-sans text-xs px-2.5 py-1 rounded bg-film-surface text-film-accent font-semibold border border-film-line">
          {appVersion}
        </span>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4 p-4 bg-film-base border border-film-line rounded-md">
        <div>
          <div className="font-sans text-sm text-film-text font-semibold">Pirate Cinema</div>
          <div className="text-xs text-film-muted mt-0.5">
            Текущая установленная версия:{' '}
            <span className="font-sans text-film-accent">
              {updateCheck?.current_version || appVersion}
            </span>
          </div>
        </div>

        <Button
          id="check-updates-btn"
          variant="secondary"
          size="sm"
          icon={<RefreshCw className={`w-3.5 h-3.5 ${isCheckingUpdate ? 'animate-spin' : ''}`} />}
          loading={isCheckingUpdate}
          onClick={handleCheckUpdates}
        >
          {t('check_updates') || 'Проверить обновления'}
        </Button>
      </div>

      {/* Результат проверки: актуальная версия */}
      {updateCheck && !updateCheck.has_update && (
        <div className="flex items-center gap-2.5 p-3.5 bg-emerald-950/20 border border-emerald-500/30 rounded-md text-emerald-400 font-sans text-xs">
          <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
          <span>{t('latest_version_installed') || 'У вас установлена последняя версия'}</span>
          {updateCheck.reason && updateCheck.reason !== 'up_to_date' && (
            <span className="text-film-muted">({updateCheck.reason})</span>
          )}
        </div>
      )}

      {/* Доступно обновление */}
      {updateCheck && updateCheck.has_update && (
        <div className="p-4 bg-film-surface border border-film-line rounded-md space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-film-line pb-3">
            <div>
              <span className="text-xs text-film-muted font-sans">Доступна новая версия</span>
              <div className="text-base font-semibold font-sans text-film-accent flex items-center gap-2">
                <span>{updateCheck.version}</span>
                {updateCheck.size_bytes && (
                  <span className="text-xs font-normal text-film-muted">
                    ({formatBytes(updateCheck.size_bytes)})
                  </span>
                )}
              </div>
            </div>

            {updateCheck.release_url && (
              <a
                href={updateCheck.release_url}
                target="_blank"
                rel="noreferrer"
                className="text-xs font-sans text-film-accent hover:text-film-accent underline flex items-center gap-1.5"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                {t('open_github_release') || 'Открыть релиз на GitHub'}
              </a>
            )}
          </div>

          {/* Release notes */}
          {updateCheck.release_notes && (
            <div className="space-y-1.5">
              <span className="text-xs font-sans font-semibold text-film-text">
                {t('whats_new') || 'Что нового:'}
              </span>
              <div className="p-3 bg-film-base border border-film-line rounded text-xs text-film-text max-h-48 overflow-y-auto whitespace-pre-wrap font-sans leading-relaxed select-text">
                {updateCheck.release_notes}
              </div>
            </div>
          )}

          {/* Блок скачивания и применения */}
          {updateCheck.can_auto_update ? (
            <div className="space-y-3 pt-2">
              {/* Состояние: Idle / Available */}
              {(!updateStatus || updateStatus.state === 'idle' || updateStatus.state === 'available') && (
                <Button
                  variant="cyan"
                  icon={<Download className="w-4 h-4" />}
                  onClick={handleStartDownload}
                >
                  {t('download_update') || 'Скачать обновление'}
                </Button>
              )}

              {/* Состояние: Downloading */}
              {updateStatus?.state === 'downloading' && (
                <div className="space-y-2 p-3 bg-film-base border border-film-line rounded-md">
                  <div className="flex items-center justify-between text-xs font-sans">
                    <span className="text-film-accent flex items-center gap-2">
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      {t('downloading_update') || 'Скачивание обновления...'}
                    </span>
                    <span className="text-film-text font-semibold">{updateStatus.progress_percent}%</span>
                  </div>

                  {/* Progress bar */}
                  <div className="w-full bg-film-surface h-2 rounded-full overflow-hidden">
                    <div
                      className="bg-film-hover h-full rounded-full transition-all duration-300"
                      style={{ width: `${Math.min(100, updateStatus.progress_percent)}%` }}
                    />
                  </div>

                  <div className="flex items-center justify-between text-[11px] font-sans text-film-muted pt-1">
                    <span>
                      Загружено: {formatBytes(updateStatus.downloaded_bytes)}
                      {updateStatus.total_bytes ? ` / ${formatBytes(updateStatus.total_bytes)}` : ''}
                    </span>
                    <button
                      onClick={handleCancelDownload}
                      className="text-rose-400 hover:text-rose-300 underline"
                    >
                      {t('cancel') || 'Отмена'}
                    </button>
                  </div>
                </div>
              )}

              {/* Состояние: Verifying */}
              {updateStatus?.state === 'verifying' && (
                <div className="p-3 bg-film-base border border-film-line rounded-md flex items-center gap-2 text-xs font-sans text-film-accent">
                  <RefreshCw className="w-4 h-4 animate-spin text-film-accent" />
                  <span>{t('verifying_update') || 'Проверка целостности файла (SHA-256)...'}</span>
                </div>
              )}

              {/* Состояние: Ready */}
              {updateStatus?.state === 'ready' && (
                <div className="space-y-3">
                  <div className="p-3 bg-emerald-950/20 border border-emerald-500/30 rounded-md flex items-center gap-2 text-xs font-sans text-emerald-400">
                    <ShieldCheck className="w-4 h-4 text-emerald-400" />
                    <span>{t('update_ready') || 'Обновление загружено и проверено.'}</span>
                  </div>

                  <Button
                    variant="cyan"
                    icon={<Play className="w-4 h-4" />}
                    onClick={() => setShowApplyModal(true)}
                  >
                    {t('install_and_restart') || 'Установить и перезапустить'}
                  </Button>
                </div>
              )}

              {/* Состояние: Applying */}
              {(updateStatus?.state === 'applying' || isApplying) && (
                <div className="p-4 bg-film-hover border border-film-line rounded-md space-y-2 text-xs font-sans text-film-accent">
                  <div className="flex items-center gap-2 font-semibold">
                    <RefreshCw className="w-4 h-4 animate-spin text-film-accent" />
                    <span>Установка обновления...</span>
                  </div>
                  <p className="text-film-text">
                    {applyMessage ||
                      'Внешний процесс обновления запущен. Приложение закрывается и перезапустится через несколько секунд.'}
                  </p>
                </div>
              )}

              {/* Состояние: Failed */}
              {updateStatus?.state === 'failed' && (
                <div className="p-3 bg-rose-950/30 border border-rose-500/40 rounded-md space-y-2">
                  <div className="flex items-center gap-2 text-xs font-sans text-rose-400 font-semibold">
                    <AlertTriangle className="w-4 h-4 shrink-0" />
                    <span>Ошибка обновления</span>
                  </div>
                  {updateStatus.error && (
                    <p className="text-xs text-rose-300 font-sans">{updateStatus.error}</p>
                  )}
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<RotateCcw className="w-3.5 h-3.5" />}
                    onClick={handleStartDownload}
                  >
                    {t('retry') || 'Повторить'}
                  </Button>
                </div>
              )}
            </div>
          ) : (
            /* Автоматическое обновление не поддерживается */
            <div className="p-3.5 bg-amber-950/20 border border-amber-500/30 rounded-md space-y-2">
              <div className="flex items-center gap-2 text-xs font-sans text-amber-400">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>
                  {t('auto_update_unsupported') ||
                    'Автоматическое обновление недоступно для этого типа установки'}
                </span>
              </div>
              {updateCheck.reason && (
                <div className="text-[11px] font-sans text-film-muted">
                  Причина: {updateCheck.reason}
                </div>
              )}
              <div className="pt-1">
                <a
                  href={updateCheck.release_url || updateCheck.download_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-film-hover hover:bg-film-hover text-film-text font-sans font-semibold text-xs rounded transition-colors"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  {t('open_github_release') || 'Открыть релиз на GitHub для ручного обновления'}
                </a>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Модальное окно подтверждения перезапуска */}
      {showApplyModal && (
        <div
          role="dialog"
          aria-modal="true"
          className="ui-dialog-overlay fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
        >
          <div className="ui-dialog bg-film-base border border-film-line rounded-md max-w-md w-full p-6 space-y-5">
            <div className="flex items-center gap-3">
              <AlertTriangle className="w-6 h-6 text-amber-400 shrink-0" />
              <h3 className="text-base font-sans font-semibold text-film-text">
                {t('update_confirm_title') || 'Установка обновления'}
              </h3>
            </div>

            <p className="text-xs text-film-text leading-relaxed font-sans">
              {t('update_confirm_text') ||
                'Для установки обновления приложение будет закрыто и перезапущено. Сохраните незавершённую работу.'}
            </p>

            <div className="flex items-center justify-end gap-3 pt-2">
              <Button
                variant="secondary"
                size="sm"
                data-dialog-close
                onClick={() => setShowApplyModal(false)}
              >
                {t('cancel') || 'Отмена'}
              </Button>
              <Button
                variant="cyan"
                size="sm"
                icon={<Play className="w-4 h-4" />}
                loading={isApplying}
                onClick={handleApplyUpdate}
              >
                {t('install_and_restart') || 'Установить и перезапустить'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
