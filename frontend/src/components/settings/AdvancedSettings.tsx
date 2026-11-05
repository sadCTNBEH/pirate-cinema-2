/**
 * @file components/settings/AdvancedSettings.tsx
 * @description Сворачиваемый блок дополнительных настроек: URL TorrServer, проверка соединения,
 * ручной путь к MPV, категории Torznab и параметры YummyAnime API.
 */

import React, { useState } from 'react';
import { useApp } from '../../context/AppContext';
import { Button, Input } from '../ui/UIComponents';
import { Sliders, ChevronDown, ChevronUp, Radio } from 'lucide-react';
import { AnimeApiSettings } from './AnimeApiSettings';

export interface AdvancedSettingsProps {
  torrserverUrl: string;
  onTorrserverUrlChange: (url: string) => void;
  playerPath: string;
  onPlayerPathChange: (path: string) => void;
  torznabCategories: string;
  onTorznabCategoriesChange: (cats: string) => void;
  yummyanimePublicKey: string;
  onYummyanimePublicKeyChange: (key: string) => void;
  yummyanimePrivateKey: string;
  onYummyanimePrivateKeyChange: (key: string) => void;
  isTesting: boolean;
  testHint: { text: string; isError?: boolean } | null;
  onTestConnection: () => void;
}

export const AdvancedSettings: React.FC<AdvancedSettingsProps> = ({
  torrserverUrl,
  onTorrserverUrlChange,
  playerPath,
  onPlayerPathChange,
  torznabCategories,
  onTorznabCategoriesChange,
  yummyanimePublicKey,
  onYummyanimePublicKeyChange,
  yummyanimePrivateKey,
  onYummyanimePrivateKeyChange,
  isTesting,
  testHint,
  onTestConnection,
}) => {
  const { t } = useApp();
  const [isAdvancedOpen, setIsAdvancedOpen] = useState<boolean>(false);

  return (
    <div className="ui-settings-section space-y-4">
      <button
        type="button"
        onClick={() => setIsAdvancedOpen(!isAdvancedOpen)}
        className="w-full flex items-center justify-between text-left focus:outline-none group p-2 -m-2 rounded hover:bg-film-base/50 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-2">
          <Sliders className="w-5 h-5 text-film-accent" />
          <h2 className="text-lg font-sans font-semibold text-film-text">
            {t('advanced_settings') || 'Дополнительные настройки'}
          </h2>
        </div>
        <span className="p-1 rounded text-film-muted group-hover:text-film-text transition-colors">
          {isAdvancedOpen ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
        </span>
      </button>

      {isAdvancedOpen && (
        <div className="space-y-6 pt-2 border-t border-film-line animate-fade-in">
          {/* 1. URL TorrServer и Проверка соединения */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="block font-sans text-xs text-film-muted font-medium">
                {t('server_url') || 'URL сервера TorrServer'}
              </span>
              <Button
                id="test-ts"
                variant="secondary"
                size="sm"
                icon={<Radio className="w-3.5 h-3.5 text-film-accent" />}
                loading={isTesting}
                onClick={onTestConnection}
              >
                {t('test_connection') || 'Проверить соединение'}
              </Button>
            </div>
            <Input
              id="ts-url"
              type="text"
              value={torrserverUrl}
              onChange={(e) => onTorrserverUrlChange(e.target.value)}
              placeholder="http://127.0.0.1:18765"
            />
            {testHint && (
              <p
                id="ts-hint"
                className={`font-sans text-xs ${
                  testHint.isError ? 'text-rose-400' : 'text-emerald-400'
                }`}
              >
                {testHint.text}
              </p>
            )}
          </div>

          {/* 2. Ручной путь к MPV */}
          <div className="space-y-2">
            <span className="block font-sans text-xs text-film-muted font-medium">
              {t('mpv_path') || 'Ручной путь к плееру MPV'}
            </span>
            <Input
              id="player-path"
              type="text"
              value={playerPath}
              onChange={(e) => onPlayerPathChange(e.target.value)}
              placeholder="Автоопределение (mpv.exe)"
            />
            <p className="text-xs text-film-muted font-sans">
              Оставьте пустым для автоматического обнаружения (в комплекте приложения, в системе или реестре).
            </p>
          </div>

          {/* 3. Числовые категории Torznab */}
          <div className="space-y-2">
            <span className="block font-sans text-xs text-film-muted font-medium">
              {t('torznab_categories') || 'Категории Torznab (ID через запятую)'}
            </span>
            <Input
              id="torznab-categories"
              type="text"
              value={torznabCategories}
              onChange={(e) => onTorznabCategoriesChange(e.target.value)}
              placeholder="2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060"
            />
            <p className="text-[11px] text-film-muted font-sans">
              Например: 2000 (Фильмы), 5000 (Сериалы)
            </p>
          </div>

          {/* 4. YummyAnime API */}
          <AnimeApiSettings
            publicKey={yummyanimePublicKey}
            onPublicKeyChange={onYummyanimePublicKeyChange}
            privateKey={yummyanimePrivateKey}
            onPrivateKeyChange={onYummyanimePrivateKeyChange}
          />
        </div>
      )}
    </div>
  );
};
