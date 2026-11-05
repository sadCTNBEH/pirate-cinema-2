/**
 * @file components/diagnostics/SqliteCard.tsx
 * @description Карточка диагностики базы данных SQLite: размер, статус доступности и резервное копирование/восстановление.
 */

import React from 'react';
import { Database, Download, Upload } from 'lucide-react';
import { DiagnosticsResponse } from '../../types';
import { useApp } from '../../context/AppContext';
import { Button } from '../ui/UIComponents';
import { DiagnosticCard } from './DiagnosticCard';
import { useBackupRestore } from '../../services/backupRestore';

export const formatMb = (
  mb: number | null | undefined,
  t: (key: string) => string
): string => {
  if (mb === null || mb === undefined || isNaN(mb)) return '—';
  if (mb >= 1024) {
    return (mb / 1024).toFixed(1) + ' ' + (t('gb') || 'ГБ');
  }
  return mb.toFixed(1) + ' ' + (t('mb') || 'МБ');
};

export interface SqliteCardProps {
  db: DiagnosticsResponse['db'];
}

export const SqliteCard: React.FC<SqliteCardProps> = ({ db }) => {
  const { t } = useApp();
  const {
    isDownloadingBackup,
    backupHint,
    fileInputRef,
    handleDownloadBackup,
    handleUploadBackup,
  } = useBackupRestore();

  return (
    <DiagnosticCard
      title="SQLite Database"
      icon={<Database className="w-5 h-5 text-film-accent" />}
      statusText={
        db.ok
          ? t('status_healthy') || 'Работает'
          : t('status_unhealthy') || 'Недоступна'
      }
      statusVariant={db.ok ? 'healthy' : 'unhealthy'}
      items={[
        {
          label: t('db_size_label') || 'Размер базы',
          value: formatMb(db.size_mb, t),
        },
        {
          label: t('status') || 'Статус',
          value: db.ok ? 'OK' : 'FAIL',
          alert: !db.ok,
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
  );
};
