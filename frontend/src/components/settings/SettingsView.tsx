/**
 * @file components/settings/SettingsView.tsx
 * @description Экран конфигурации хоста, демона TorrServer, Jackett/Prowlarr,
 * системной диагностики, проверки обновлений и резервного копирования.
 */

import React, { useEffect, useState, useRef } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { UpdateCheckResponse, UpdateStatusResponse } from '../../types';
import { Header } from '../layout/Header';
import { Button, Input, Select } from '../ui/UIComponents';
import { HotkeySettings } from '../../input/HotkeySettings';
import { TrackLanguageSettings } from './TrackLanguageSettings';
import {
  Save,
  Radio,
  RefreshCw,
  ExternalLink,
  CheckCircle2,
  AlertTriangle,
  Globe,
  Film,
  Download,
  Play,
  ShieldCheck,
  RotateCcw,
} from 'lucide-react';

interface SettingsViewProps {
  hideHeader?: boolean;
}

export const SettingsView: React.FC<SettingsViewProps> = ({ hideHeader }) => {
  const { t, reloadI18n } = useApp();

  const [torrserverUrl, setTorrserverUrl] = useState<string>('');
  const [language, setLanguage] = useState<string>('ru');
  const [playerPath, setPlayerPath] = useState<string>('');
  const [audioLanguages, setAudioLanguages] = useState<string[]>(['auto']);
  const [subtitleLanguages, setSubtitleLanguages] = useState<string[]>(['auto']);
  const [jackettUrl, setJackettUrl] = useState<string>('');
  const [jackettKey, setJackettKey] = useState<string>('');
  const [torznabEnabled, setTorznabEnabled] = useState<boolean>(false);
  const [torznabUrl, setTorznabUrl] = useState<string>('');
  const [torznabKey, setTorznabKey] = useState<string>('');
  const [torznabCategories, setTorznabCategories] = useState<string>('2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060');
  const [minimizeToTray, setMinimizeToTray] = useState<boolean>(true);
  const [autostart, setAutostart] = useState<boolean>(false);
  const [appVersion, setAppVersion] = useState<string>(__APP_VERSION__);

  const [saveHint, setSaveHint] = useState<{ text: string; isError?: boolean } | null>(null);
  const [isSaving, setIsSaving] = useState<boolean>(false);

  const [testHint, setTestHint] = useState<{ text: string; isError?: boolean } | null>(null);
  const [isTesting, setIsTesting] = useState<boolean>(false);

  const [updateCheck, setUpdateCheck] = useState<UpdateCheckResponse | null>(null);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatusResponse | null>(null);
  const [isCheckingUpdate, setIsCheckingUpdate] = useState<boolean>(false);
  const [showApplyModal, setShowApplyModal] = useState<boolean>(false);
  const [isApplying, setIsApplying] = useState<boolean>(false);
  const [applyMessage, setApplyMessage] = useState<string | null>(null);
  const pollIntervalRef = useRef<number | null>(null);

  /**
   * Загрузка настроек с бэкенда и версии из version.json
   */
  useEffect(() => {
    API.getSettings()
      .then((s) => {
        if (s.torrserver_url) setTorrserverUrl(s.torrserver_url);
        if (s.language) setLanguage(s.language);
        if (s.player_path) setPlayerPath(s.player_path);
        if (s.audio_languages?.length) setAudioLanguages(s.audio_languages);
        if (s.subtitle_languages?.length) setSubtitleLanguages(s.subtitle_languages);
        if (s.minimize_to_tray !== undefined) setMinimizeToTray(s.minimize_to_tray);
        if (s.autostart !== undefined) setAutostart(s.autostart);
        if (s.jackett_url) setJackettUrl(s.jackett_url);
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

  const handleToggleAutostart = async (enabled: boolean) => {
    setAutostart(enabled);
    try {
      await API.saveSettings({ autostart: enabled });
    } catch (err) {
      console.warn('Failed to update autostart:', err);
    }
  };

  const parseCategories = (catStr: string): number[] => {
    return catStr
      .split(',')
      .map((c) => parseInt(c.trim(), 10))
      .filter((n) => !isNaN(n));
  };

  /**
   * Сохранение настроек в FastAPI
   */
  const handleSaveSettings = async () => {
    setIsSaving(true);
    setSaveHint(null);
    try {
      const cats = parseCategories(torznabCategories);
      const effectiveUrl = (torznabUrl || jackettUrl).trim();
      const effectiveKey = (torznabKey || jackettKey).trim();

      await API.saveSettings({
        torrserver_url: torrserverUrl.trim(),
        language: language as any,
        player_path: playerPath.trim(),
        audio_languages: audioLanguages,
        subtitle_languages: subtitleLanguages,
        minimize_to_tray: minimizeToTray,
        autostart: autostart,
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
    } catch (err: any) {
      setSaveHint({ text: t('error', { error: err.message }) || err.message, isError: true });
    } finally {
      setIsSaving(false);
    }
  };

  /**
   * Проверка соединения с TorrServer
   */
  const handleTestConnection = async () => {
    setIsTesting(true);
    setTestHint({ text: t('checking') || 'Проверка...' });
    try {
      const s = await API.getServerStatus();
      if (s.active) {
        setTestHint({ text: t('ts_available') || 'TorrServer доступен' });
      } else {
        setTestHint({ text: t('ts_unavailable') || 'TorrServer недоступен', isError: true });
      }
    } catch (err: any) {
      setTestHint({ text: t('error', { error: err.message }) || err.message, isError: true });
    } finally {
      setIsTesting(false);
    }
  };

  /**
   * Восстановление состояния загрузки при монтировании
   */
  useEffect(() => {
    API.getUpdateStatus()
      .then((status) => {
        if (status) {
          setUpdateStatus(status);
        }
      })
      .catch(() => {});

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  /**
   * Опрос прогресса скачивания обновления
   */
  useEffect(() => {
    if (updateStatus && (updateStatus.state === 'downloading' || updateStatus.state === 'verifying')) {
      if (!pollIntervalRef.current) {
        pollIntervalRef.current = window.setInterval(async () => {
          try {
            const st = await API.getUpdateStatus();
            setUpdateStatus(st);
            if (st.state !== 'downloading' && st.state !== 'verifying') {
              if (pollIntervalRef.current) {
                clearInterval(pollIntervalRef.current);
                pollIntervalRef.current = null;
              }
            }
          } catch {
            // игнорируем сетевые ошибки во время polling
          }
        }, 600);
      }
    } else {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    }
  }, [updateStatus?.state]);

  /**
   * Проверка наличия обновлений через GitHub Releases (TASK-004)
   */
  const handleCheckUpdates = async () => {
    setIsCheckingUpdate(true);
    try {
      const checkRes = await API.checkUpdate();
      setUpdateCheck(checkRes);
      const st = await API.getUpdateStatus();
      setUpdateStatus(st);
    } catch (err: any) {
      setUpdateCheck({
        current_version: appVersion,
        has_update: false,
        version: '',
        release_notes: '',
        download_url: '',
        release_url: '',
        asset_name: '',
        can_auto_update: false,
        reason: err.message || 'Ошибка проверки обновлений',
      });
    } finally {
      setIsCheckingUpdate(false);
    }
  };

  /**
   * Старт скачивания обновления
   */
  const handleStartDownload = async () => {
    try {
      const st = await API.startUpdateDownload();
      setUpdateStatus(st);
    } catch (err: any) {
      setUpdateStatus({
        state: 'failed',
        downloaded_bytes: 0,
        progress_percent: 0,
        can_auto_update: false,
        error: err.message || 'Не удалось запустить скачивание обновления',
      });
    }
  };

  /**
   * Отмена активного скачивания
   */
  const handleCancelDownload = async () => {
    try {
      const st = await API.cancelUpdateDownload();
      setUpdateStatus(st);
    } catch (err: any) {
      console.warn('Cancel download error:', err);
    }
  };

  /**
   * Запуск процесса обновления с подтверждением
   */
  const handleApplyUpdate = async () => {
    setIsApplying(true);
    try {
      const actionRes = await API.applyUpdate(false);
      setApplyMessage(actionRes.message || 'Обновление запущено. Приложение перезапускается...');
      setShowApplyModal(false);
    } catch (err: any) {
      setIsApplying(false);
      setUpdateStatus((prev) => ({
        state: 'failed',
        downloaded_bytes: prev?.downloaded_bytes || 0,
        progress_percent: 100,
        can_auto_update: false,
        error: err.message || 'Не удалось применить обновление',
      }));
      setShowApplyModal(false);
    }
  };

  const formatBytes = (bytes?: number | null) => {
    if (!bytes || bytes <= 0) return '0 МБ';
    const mb = bytes / (1024 * 1024);
    return `${mb.toFixed(1)} МБ`;
  };

  return (
    <div className="ui-page settingsview space-y-8 animate-fade-in pb-16 max-w-4xl mx-auto">
      {!hideHeader && <Header titleKey="nav_settings" />}
      <HotkeySettings />

      {/* ── Блок TorrServer ── */}
      <div className="ui-settings-section space-y-4">
        <h2 className="text-lg font-sans font-semibold text-film-text flex items-center gap-2">
          <Radio className="w-5 h-5 text-film-accent" />
          TorrServer
        </h2>
        <div className="space-y-2">
          <span className="block font-sans text-xs text-film-muted font-medium">
            {t('server_url') || 'URL сервера'}
          </span>
          <Input
            id="ts-url"
            type="text"
            value={torrserverUrl}
            onChange={(e) => setTorrserverUrl(e.target.value)}
            placeholder="http://127.0.0.1:18765"
          />
        </div>
      </div>

      {/* ── Блок Плеер MPV ── */}
      <div className="ui-settings-section space-y-4">
        <h2 className="text-lg font-sans font-semibold text-film-text flex items-center gap-2">
          <Film className="w-5 h-5 text-film-accent" />
          {t('mpv_player') || 'Видеоплеер (MPV)'}
        </h2>
        <div className="space-y-2">
          <span className="block font-sans text-xs text-film-muted font-medium">
            {t('mpv_path') || 'Путь к плееру MPV'}
          </span>
          <Input
            id="player-path"
            type="text"
            value={playerPath}
            onChange={(e) => setPlayerPath(e.target.value)}
            placeholder="Автоопределение (mpv.exe)"
          />
          <p className="text-xs text-film-muted font-sans">
            Оставьте пустым для автоматического обнаружения (в комплекте приложения, в системе или реестре).
          </p>
        </div>
        <TrackLanguageSettings audio={audioLanguages} subtitles={subtitleLanguages} onAudio={setAudioLanguages} onSubtitles={setSubtitleLanguages} />
      </div>

      {/* ── Блок Общие (Язык) ── */}
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
              onChange={(e) => setLanguage(e.target.value)}
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
              onChange={(event) => setMinimizeToTray(event.target.checked)}
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
              onChange={(event) => handleToggleAutostart(event.target.checked)}
              className="peer sr-only"
            />
            <div className="h-6 w-11 rounded-full bg-film-surface peer-focus:outline-none peer-checked:bg-film-accent peer-checked:after:translate-x-full peer-checked:after:border-white after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:border after:border-film-line after:bg-slate-300 after:transition-all peer-checked:after:bg-film-surface" />
          </label>
        </div>
      </div>

      {/* ── Блок Torznab / Jackett / Prowlarr ── */}
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
              onChange={(e) => setTorznabEnabled(e.target.checked)}
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
              onChange={(e) => {
                setTorznabUrl(e.target.value);
                setJackettUrl(e.target.value);
              }}
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
              onChange={(e) => {
                setTorznabKey(e.target.value);
                setJackettKey(e.target.value);
              }}
              placeholder="••••••••••••••••••••••••••••••••"
            />
          </div>

          <div className="space-y-2">
            <span className="block font-sans text-xs text-film-muted font-medium">
              {t('torznab_categories') || 'Категории Torznab (ID через запятую)'}
            </span>
            <Input
              id="torznab-categories"
              type="text"
              value={torznabCategories}
              onChange={(e) => setTorznabCategories(e.target.value)}
              placeholder="2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060"
            />
            <p className="text-[11px] text-film-muted font-sans">
              Например: 2000 (Фильмы), 5000 (Сериалы)
            </p>
          </div>
        </div>
      </div>

      {/* ── Кнопки сохранения и проверки ── */}
      <div className="settings-actions flex flex-wrap items-center gap-4 pt-2">
        <Button
          id="save-settings"
          variant="cyan"
          icon={<Save className="w-4 h-4" />}
          loading={isSaving}
          onClick={handleSaveSettings}
        >
          {t('save_settings') || 'Сохранить настройки'}
        </Button>

        <Button
          id="test-ts"
          variant="secondary"
          icon={<Radio className="w-4 h-4 text-film-accent" />}
          loading={isTesting}
          onClick={handleTestConnection}
        >
          {t('test_connection') || 'Проверить соединение'}
        </Button>

        {saveHint && (
          <span
            id="ts-hint"
            className={`font-sans text-xs ${
              saveHint.isError ? 'text-rose-400' : 'text-emerald-400'
            }`}
          >
            {saveHint.text}
          </span>
        )}
        {testHint && (
          <span
            className={`font-sans text-xs ${
              testHint.isError ? 'text-rose-400' : 'text-emerald-400'
            }`}
          >
            {testHint.text}
          </span>
        )}
      </div>

      {/* ── Блок Обновления (TASK-004) ── */}
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
            <div className="font-sans text-sm text-film-text font-semibold">
              Pirate Cinema
            </div>
            <div className="text-xs text-film-muted mt-0.5">
              Текущая установленная версия: <span className="font-sans text-film-accent">{updateCheck?.current_version || appVersion}</span>
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
                      {applyMessage || 'Внешний процесс обновления запущен. Приложение закрывается и перезапустится через несколько секунд.'}
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
                    {t('auto_update_unsupported') || 'Автоматическое обновление недоступно для этого типа установки'}
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
          <div role="dialog" aria-modal="true" className="ui-dialog-overlay fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
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
                  data-dialog-close onClick={() => setShowApplyModal(false)}
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
    </div>
  );
};
