/**
 * @file components/settings/SettingsView.tsx
 * @description Экран конфигурации хоста, демона TorrServer, Jackett/Prowlarr,
 * системной диагностики, проверки обновлений и резервного копирования.
 */

import React from 'react';
import { useApp } from '../../context/AppContext';
import { Header } from '../layout/Header';
import { Button } from '../ui/UIComponents';
import { HotkeySettings } from '../../input/HotkeySettings';
import { Save } from 'lucide-react';

import { useSettingsForm } from './useSettingsForm';
import { GeneralSettings } from './GeneralSettings';
import { PlayerSettings } from './PlayerSettings';
import { TorznabSettings } from './TorznabSettings';
import { BackupSettings } from './BackupSettings';
import { AdvancedSettings } from './AdvancedSettings';
import { UpdatesSettings } from './UpdatesSettings';

interface SettingsViewProps {
  hideHeader?: boolean;
}

export const SettingsView: React.FC<SettingsViewProps> = ({ hideHeader }) => {
  const { t } = useApp();
  const form = useSettingsForm();

  return (
    <div className="ui-page settingsview space-y-8 animate-fade-in pb-16 max-w-4xl mx-auto">
      {!hideHeader && <Header titleKey="nav_settings" />}
      <HotkeySettings />

      <GeneralSettings
        language={form.language}
        onLanguageChange={form.setLanguage}
        minimizeToTray={form.minimizeToTray}
        onMinimizeToTrayChange={form.setMinimizeToTray}
        autostart={form.autostart}
        onToggleAutostart={form.handleToggleAutostart}
      />

      <PlayerSettings
        seekStep={form.seekStep}
        onSeekStepChange={form.handleSaveSeekStep}
        isSaving={form.isSaving}
        audioLanguages={form.audioLanguages}
        onAudioLanguagesChange={form.setAudioLanguages}
        subtitleLanguages={form.subtitleLanguages}
        onSubtitleLanguagesChange={form.setSubtitleLanguages}
        autoSkipIntro={form.autoSkipIntro}
        onAutoSkipIntroChange={form.setAutoSkipIntro}
      />

      <TorznabSettings
        torznabEnabled={form.torznabEnabled}
        onTorznabEnabledChange={form.setTorznabEnabled}
        torznabUrl={form.torznabUrl}
        onTorznabUrlChange={form.handleTorznabUrlChange}
        torznabKey={form.torznabKey}
        onTorznabKeyChange={form.handleTorznabKeyChange}
      />

      <BackupSettings />

      <AdvancedSettings
        torrserverUrl={form.torrserverUrl}
        onTorrserverUrlChange={form.setTorrserverUrl}
        playerPath={form.playerPath}
        onPlayerPathChange={form.setPlayerPath}
        torznabCategories={form.torznabCategories}
        onTorznabCategoriesChange={form.setTorznabCategories}
        yummyanimePublicKey={form.yummyanimePublicKey}
        onYummyanimePublicKeyChange={form.setYummyanimePublicKey}
        yummyanimePrivateKey={form.yummyanimePrivateKey}
        onYummyanimePrivateKeyChange={form.setYummyanimePrivateKey}
        isTesting={form.isTesting}
        testHint={form.testHint}
        onTestConnection={form.handleTestConnection}
      />

      {/* ── Кнопка сохранения настроек ── */}
      <div className="settings-actions flex flex-wrap items-center gap-4 pt-2">
        <Button
          id="save-settings"
          variant="cyan"
          icon={<Save className="w-4 h-4" />}
          loading={form.isSaving}
          onClick={form.handleSaveSettings}
        >
          {t('save_settings') || 'Сохранить настройки'}
        </Button>

        {form.saveHint && (
          <span
            id="ts-hint"
            className={`font-sans text-xs ${
              form.saveHint.isError ? 'text-rose-400' : 'text-emerald-400'
            }`}
          >
            {form.saveHint.text}
          </span>
        )}
      </div>

      <UpdatesSettings appVersion={form.appVersion} />
    </div>
  );
};
