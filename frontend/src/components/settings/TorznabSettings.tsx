/**
 * @file components/settings/TorznabSettings.tsx
 * @description Раздел настроек Torznab: интеграция с Jackett / Prowlarr, URL и API-ключ.
 */

import React from 'react';
import { useApp } from '../../context/AppContext';
import { Input } from '../ui/UIComponents';
import { Radio } from 'lucide-react';

export interface TorznabSettingsProps {
  torznabEnabled: boolean;
  onTorznabEnabledChange: (val: boolean) => void;
  torznabUrl: string;
  onTorznabUrlChange: (val: string) => void;
  torznabKey: string;
  onTorznabKeyChange: (val: string) => void;
}

export const TorznabSettings: React.FC<TorznabSettingsProps> = ({
  torznabEnabled,
  onTorznabEnabledChange,
  torznabUrl,
  onTorznabUrlChange,
  torznabKey,
  onTorznabKeyChange,
}) => {
  const { t } = useApp();

  return (
    <div className="ui-settings-section space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-sans font-semibold text-film-text flex items-center gap-2">
          <Radio className="w-5 h-5 text-film-accent" />
          Torznab (Jackett / Prowlarr)
        </h2>
        <p className="text-xs text-film-muted font-sans">
          {t('jackett_hint') || 'Для поиска торрентов по сторонним трекерам через Torznab API.'}
        </p>
      </div>

      {/* Переключатель активности Torznab */}
      <div className="flex items-center justify-between p-3 bg-film-base border border-film-line rounded-md">
        <div className="space-y-0.5">
          <span className="font-sans text-sm text-film-text font-semibold">
            {t('torznab_enabled') || 'Включить Torznab'}
          </span>
          <p className="text-xs text-film-muted font-sans">
            Поиск по трекерам через совместимые сервисы (Jackett / Prowlarr)
          </p>
        </div>
        <label className="relative inline-flex items-center cursor-pointer">
          <input
            id="torznab-enabled"
            type="checkbox"
            checked={torznabEnabled}
            onChange={(e) => onTorznabEnabledChange(e.target.checked)}
            className="sr-only peer"
          />
          <div className="w-11 h-6 bg-film-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-300 after:border-film-line after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-film-accent peer-checked:after:bg-film-surface"></div>
        </label>
      </div>

      <div className="space-y-4 pt-1">
        <div className="space-y-2">
          <span className="block font-sans text-xs text-film-muted font-medium">
            {t('torznab_url') || 'URL Torznab API'}
          </span>
          <Input
            id="torznab-url"
            type="text"
            value={torznabUrl}
            onChange={(e) => onTorznabUrlChange(e.target.value)}
            placeholder="http://127.0.0.1:9117/api/v2.0/indexers/all/results/torznab/"
          />
        </div>

        <div className="space-y-2">
          <span className="block font-sans text-xs text-film-muted font-medium">
            {t('torznab_key') || t('api_key') || 'Ключ API'}
          </span>
          <Input
            id="torznab-key"
            type="password"
            value={torznabKey}
            onChange={(e) => onTorznabKeyChange(e.target.value)}
            placeholder="••••••••••••••••••••••••••••••••"
          />
        </div>
      </div>
    </div>
  );
};
