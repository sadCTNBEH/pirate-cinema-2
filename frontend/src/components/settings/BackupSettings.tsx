/**
 * @file components/settings/BackupSettings.tsx
 * @description Раздел резервного копирования и восстановления данных конфигурации.
 */

import React from 'react';
import { useApp } from '../../context/AppContext';
import { Button } from '../ui/UIComponents';
import { Archive, Download, Upload } from 'lucide-react';
import { useBackupRestore, UseBackupRestoreResult } from '../../services/backupRestore';

export interface BackupSettingsProps {
  backupRestore?: UseBackupRestoreResult;
}

export const BackupSettings: React.FC<BackupSettingsProps> = ({ backupRestore }) => {
  const { t } = useApp();
  const internalBackup = useBackupRestore();
  const {
    isDownloadingBackup,
    backupHint,
    fileInputRef,
    handleDownloadBackup,
    handleUploadBackup,
  } = backupRestore || internalBackup;

  return (
    <div className="ui-settings-section space-y-4">
      <h2 className="text-lg font-sans font-semibold text-film-text flex items-center gap-2">
        <Archive className="w-5 h-5 text-film-accent" />
        {t('backup_restore') || 'Резервное копирование и восстановление'}
      </h2>
      <p className="text-xs text-film-muted font-sans">
        {t('backup_restore_hint') ||
          'Сохранение и восстановление настроек, истории просмотров и конфигурации базы данных.'}
      </p>

      <div className="flex flex-wrap items-center gap-3 p-4 bg-film-base border border-film-line rounded-md">
        <Button
          id="download-backup-btn"
          variant="secondary"
          size="sm"
          icon={<Download className="w-4 h-4 text-emerald-400" />}
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
            id="restore-backup-btn"
            type="button"
            variant="secondary"
            size="sm"
            icon={<Upload className="w-4 h-4 text-film-accent" />}
            onClick={() => fileInputRef.current?.click()}
          >
            {t('restore_backup') || 'Восстановить бэкап'}
          </Button>
        </label>

        {backupHint && (
          <span
            className={`font-sans text-xs ${
              backupHint.isError ? 'text-rose-400' : 'text-emerald-400'
            }`}
          >
            {backupHint.text}
          </span>
        )}
      </div>
    </div>
  );
};
