/**
 * @file components/settings/GeneralSettings.tsx
 * @description Раздел общих настроек: выбор языка, сворачивание в трей, автозапуск и Debug Mode.
 */

import React from 'react';
import { useApp } from '../../context/AppContext';
import { Select } from '../ui/UIComponents';
import { Globe, Bug } from 'lucide-react';

export interface GeneralSettingsProps {
  language: string;
  onLanguageChange: (lang: string) => void;
  minimizeToTray: boolean;
  onMinimizeToTrayChange: (val: boolean) => void;
  autostart: boolean;
  onToggleAutostart: (enabled: boolean) => void;
}

export const GeneralSettings: React.FC<GeneralSettingsProps> = ({
  language,
  onLanguageChange,
  minimizeToTray,
  onMinimizeToTrayChange,
  autostart,
  onToggleAutostart,
}) => {
  const { t, debugMode, setDebugMode } = useApp();

  return (
    <div className="ui-settings-section space-y-4">
      <h2 className="text-lg font-sans font-semibold text-film-text flex items-center gap-2">
        <Globe className="w-5 h-5 text-film-accent" />
        {t('settings') || t('general') || 'Общие'}
      </h2>

      {/* Выровненный блок выбора языка с идеальным вертикальным центрированием */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-3 bg-film-base border border-film-line rounded-md">
        <span className="font-sans text-sm text-film-text font-semibold">
          {t('language') || 'Язык'}
        </span>

        <div className="sm:w-64 shrink-0">
          <Select
            id="lang-select"
            className="w-full"
            value={language}
            onChange={(e) => onLanguageChange(e.target.value)}
          >
            <option value="ru">{t('russian') || 'Русский'}</option>
            <option value="en">{t('english') || 'English'}</option>
          </Select>
        </div>
      </div>

      <div className="flex items-center justify-between gap-4 p-3 bg-film-base border border-film-line rounded-md">
        <div className="min-w-0">
          <span className="font-sans text-sm text-film-text font-semibold">
            {t('close_to_tray') || 'Сворачивать в трей при закрытии'}
          </span>
          <p className="mt-0.5 text-xs text-film-muted">
            {t('close_to_tray_hint') || 'Действие можно изменить в любой момент.'}
          </p>
        </div>
        <label className="relative inline-flex shrink-0 cursor-pointer items-center">
          <input
            type="checkbox"
            aria-label={t('close_to_tray')}
            checked={minimizeToTray}
            onChange={(event) => onMinimizeToTrayChange(event.target.checked)}
            className="peer sr-only"
          />
          <div className="h-6 w-11 rounded-full bg-film-surface peer-focus:outline-none peer-checked:bg-film-accent peer-checked:after:translate-x-full peer-checked:after:border-white after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:border after:border-film-line after:bg-slate-300 after:transition-all peer-checked:after:bg-film-surface" />
        </label>
      </div>

      <div className="flex items-center justify-between gap-4 p-3 bg-film-base border border-film-line rounded-md">
        <div className="min-w-0">
          <span className="font-sans text-sm text-film-text font-semibold">
            {t('autostart') || 'Автозапуск при старте Windows'}
          </span>
          <p className="mt-0.5 text-xs text-film-muted">
            {t('autostart_hint') || 'Запускать свернутым в трей при старте ПК. Всегда готов к управлению со смартфона.'}
          </p>
        </div>
        <label className="relative inline-flex shrink-0 cursor-pointer items-center">
          <input
            type="checkbox"
            aria-label={t('autostart')}
            checked={autostart}
            onChange={(event) => onToggleAutostart(event.target.checked)}
            className="peer sr-only"
          />
          <div className="h-6 w-11 rounded-full bg-film-surface peer-focus:outline-none peer-checked:bg-film-accent peer-checked:after:translate-x-full peer-checked:after:border-white after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:border after:border-film-line after:bg-slate-300 after:transition-all peer-checked:after:bg-film-surface" />
        </label>
      </div>

      {/* Переключатель Debug Mode */}
      <div className="flex items-center justify-between gap-4 p-3 bg-film-base border border-film-line rounded-md">
        <div className="min-w-0">
          <span className="font-sans text-sm text-film-text font-semibold flex items-center gap-2">
            <Bug className="w-4 h-4 text-film-accent" />
            {t('debug_mode') || 'Режим отладки (Debug Mode)'}
          </span>
          <p className="mt-0.5 text-xs text-film-muted">
            {t('debug_mode_hint') || 'Отображение технической информации, расширенной диагностики и характеристик видео.'}
          </p>
        </div>
        <label className="relative inline-flex shrink-0 cursor-pointer items-center">
          <input
            id="debug-mode-toggle"
            type="checkbox"
            aria-label={t('debug_mode') || 'Режим отладки'}
            checked={debugMode}
            onChange={(e) => setDebugMode(e.target.checked)}
            className="peer sr-only"
          />
          <div className="h-6 w-11 rounded-full bg-film-surface peer-focus:outline-none peer-checked:bg-film-accent peer-checked:after:translate-x-full peer-checked:after:border-white after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:border after:border-film-line after:bg-slate-300 after:transition-all peer-checked:after:bg-film-surface" />
        </label>
      </div>
    </div>
  );
};
