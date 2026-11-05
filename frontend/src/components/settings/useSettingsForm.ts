/**
 * @file components/settings/useSettingsForm.ts
 * @description Хук управления состоянием настроек, их загрузкой, валидацией и сохранением.
 */

import { useState, useEffect, useCallback } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import type { SubtitleSettings } from '../../types';

export const parseCategories = (catStr: string): number[] => {
  return catStr
    .split(',')
    .map((c) => parseInt(c.trim(), 10))
    .filter((n) => !isNaN(n));
};

export function useSettingsForm() {
  const { t, reloadI18n, debugMode } = useApp();

  const [torrserverUrl, setTorrserverUrl] = useState<string>('');
  const [language, setLanguage] = useState<string>('ru');
  const [playerPath, setPlayerPath] = useState<string>('');
  const [audioLanguages, setAudioLanguages] = useState<string[]>(['auto']);
  const [subtitleLanguages, setSubtitleLanguages] = useState<string[]>(['auto']);
  const [subtitleSettings, setSubtitleSettings] = useState<SubtitleSettings>();
  const [autoSkipIntro, setAutoSkipIntro] = useState(false);
  const [seekStep, setSeekStep] = useState<5 | 10 | 15 | 30 | 60>(10);
  const [jackettUrl, setJackettUrl] = useState<string>('');
  const [jackettKey, setJackettKey] = useState<string>('');
  const [torznabEnabled, setTorznabEnabled] = useState<boolean>(false);
  const [torznabUrl, setTorznabUrl] = useState<string>('');
  const [torznabKey, setTorznabKey] = useState<string>('');
  const [torznabCategories, setTorznabCategories] = useState<string>(
    '2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060'
  );
  const [yummyanimePublicKey, setYummyanimePublicKey] = useState<string>('bz7uk_nr9bouyrn9');
  const [yummyanimePrivateKey, setYummyanimePrivateKey] = useState<string>('');
  const [minimizeToTray, setMinimizeToTray] = useState<boolean>(true);
  const [autostart, setAutostart] = useState<boolean>(false);
  const [appVersion, setAppVersion] = useState<string>(__APP_VERSION__);

  const [saveHint, setSaveHint] = useState<{ text: string; isError?: boolean } | null>(null);
  const [isSaving, setIsSaving] = useState<boolean>(false);

  const [testHint, setTestHint] = useState<{ text: string; isError?: boolean } | null>(null);
  const [isTesting, setIsTesting] = useState<boolean>(false);

  useEffect(() => {
    API.getSettings()
      .then((s) => {
        if (s.torrserver_url) setTorrserverUrl(s.torrserver_url);
        if (s.language) setLanguage(s.language);
        if (s.player_path) setPlayerPath(s.player_path);
        if (s.audio_languages?.length) setAudioLanguages(s.audio_languages);
        if (s.subtitle_languages?.length) setSubtitleLanguages(s.subtitle_languages);
        setSubtitleSettings(s.subtitle_settings);
        if (s.minimize_to_tray !== undefined) setMinimizeToTray(s.minimize_to_tray);
        if (s.autostart !== undefined) setAutostart(s.autostart);
        setAutoSkipIntro(s.auto_skip_intro === true);
        setSeekStep(s.seek_step ?? 10);
        if (s.jackett_url) setJackettUrl(s.jackett_url);
        if (s.yummyanime_public_key !== undefined) setYummyanimePublicKey(s.yummyanime_public_key || 'bz7uk_nr9bouyrn9');
        if (s.yummyanime_private_key !== undefined) setYummyanimePrivateKey(s.yummyanime_private_key || '');
        if (s.jackett_api_key) setJackettKey(s.jackett_api_key);

        if (s.torznab) {
          setTorznabEnabled(!!s.torznab.enabled);
          setTorznabUrl(s.torznab.url || s.jackett_url || '');
          setTorznabKey(s.torznab.api_key || s.jackett_api_key || '');
          if (Array.isArray(s.torznab.categories) && s.torznab.categories.length > 0) {
            setTorznabCategories(s.torznab.categories.join(', '));
          }
        } else {
          if (s.torznab_enabled !== undefined) setTorznabEnabled(!!s.torznab_enabled);
          setTorznabUrl(s.torznab_url || s.jackett_url || '');
          setTorznabKey(s.torznab_api_key || s.jackett_api_key || '');
          if (Array.isArray(s.torznab_categories) && s.torznab_categories.length > 0) {
            setTorznabCategories(s.torznab_categories.join(', '));
          }
        }
      })
      .catch((e) => console.warn('Ошибка загрузки настроек:', e));

    fetch('/version.json')
      .then((res) => {
        if (!res.ok) throw new Error('version.json not found');
        return res.json();
      })
      .then((d) => {
        if (d && d.version) setAppVersion(d.version);
      })
      .catch(() => {});
  }, []);

  const handleToggleAutostart = useCallback(async (enabled: boolean) => {
    setAutostart(enabled);
    try {
      await API.saveSettings({ autostart: enabled });
    } catch (err) {
      console.warn('Failed to update autostart:', err);
    }
  }, []);

  const handleSaveSeekStep = useCallback(async (step: 5 | 10 | 15 | 30 | 60) => {
    setIsSaving(true);
    setSaveHint(null);
    try {
      await API.saveSettings({ seek_step: step });
      setSeekStep(step);
    } catch (err) {
      setSaveHint({
        text: err instanceof Error ? err.message : 'Не удалось сохранить шаг перемотки',
        isError: true,
      });
    } finally {
      setIsSaving(false);
    }
  }, []);

  const handleSaveSettings = useCallback(async () => {
    setIsSaving(true);
    setSaveHint(null);
    try {
      const cats = parseCategories(torznabCategories);
      const effectiveUrl = (torznabUrl || jackettUrl).trim();
      const effectiveKey = (torznabKey || jackettKey).trim();

      await API.saveSettings({
        torrserver_url: torrserverUrl.trim(),
        language: language as 'ru' | 'en',
        player_path: playerPath.trim(),
        audio_languages: audioLanguages,
        subtitle_languages: subtitleLanguages,
        auto_skip_intro: autoSkipIntro,
        seek_step: seekStep,
        minimize_to_tray: minimizeToTray,
        autostart: autostart,
        debug_mode: debugMode,
        yummyanime_public_key: yummyanimePublicKey.trim(),
        yummyanime_private_key: yummyanimePrivateKey.trim(),
        jackett_url: effectiveUrl,
        jackett_api_key: effectiveKey,
        torznab_enabled: torznabEnabled,
        torznab_url: effectiveUrl,
        torznab_api_key: effectiveKey,
        torznab_categories: cats,
        torznab: {
          enabled: torznabEnabled,
          url: effectiveUrl,
          api_key: effectiveKey,
          categories: cats,
        },
      });
      await reloadI18n();
      setSaveHint({ text: t('saved') || 'Настройки сохранены' });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setSaveHint({ text: t('error', { error: msg }) || msg, isError: true });
    } finally {
      setIsSaving(false);
    }
  }, [
    torznabCategories,
    torznabUrl,
    jackettUrl,
    torznabKey,
    jackettKey,
    torrserverUrl,
    language,
    playerPath,
    audioLanguages,
    subtitleLanguages,
    autoSkipIntro,
    seekStep,
    minimizeToTray,
    autostart,
    debugMode,
    yummyanimePublicKey,
    yummyanimePrivateKey,
    torznabEnabled,
    reloadI18n,
    t,
  ]);

  const handleTestConnection = useCallback(async () => {
    setIsTesting(true);
    setTestHint({ text: t('checking') || 'Проверка...' });
    try {
      const s = await API.getServerStatus();
      if (s.active) {
        setTestHint({ text: t('ts_available') || 'TorrServer доступен' });
      } else {
        setTestHint({ text: t('ts_unavailable') || 'TorrServer недоступен', isError: true });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setTestHint({ text: t('error', { error: msg }) || msg, isError: true });
    } finally {
      setIsTesting(false);
    }
  }, [t]);

  const handleTorznabUrlChange = useCallback((url: string) => {
    setTorznabUrl(url);
    setJackettUrl(url);
  }, []);

  const handleTorznabKeyChange = useCallback((key: string) => {
    setTorznabKey(key);
    setJackettKey(key);
  }, []);

  return {
    torrserverUrl,
    setTorrserverUrl,
    language,
    setLanguage,
    playerPath,
    setPlayerPath,
    audioLanguages,
    setAudioLanguages,
    subtitleLanguages,
    setSubtitleLanguages,
    subtitleSettings,
    autoSkipIntro,
    setAutoSkipIntro,
    seekStep,
    setSeekStep,
    handleSaveSeekStep,
    jackettUrl,
    jackettKey,
    torznabEnabled,
    setTorznabEnabled,
    torznabUrl,
    handleTorznabUrlChange,
    torznabKey,
    handleTorznabKeyChange,
    torznabCategories,
    setTorznabCategories,
    yummyanimePublicKey,
    setYummyanimePublicKey,
    yummyanimePrivateKey,
    setYummyanimePrivateKey,
    minimizeToTray,
    setMinimizeToTray,
    autostart,
    handleToggleAutostart,
    appVersion,
    saveHint,
    isSaving,
    handleSaveSettings,
    testHint,
    isTesting,
    handleTestConnection,
  };
}
