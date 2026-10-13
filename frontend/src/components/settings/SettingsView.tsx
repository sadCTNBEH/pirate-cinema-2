/**
 * @file components/settings/SettingsView.tsx
 * @description Экран конфигурации хоста, демона TorrServer, Jackett/Prowlarr,
 * системной диагностики, проверки обновлений и резервного копирования.
 */

import React, { useEffect, useState, useRef } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { SystemDiagnostics, UpdateInfo } from '../../types';
import { formatSize } from '../../utils/torrentParser';
import { Header } from '../layout/Header';
import { Button, Input, Select } from '../ui/UIComponents';
import {
  Save,
  Radio,
  FolderOpen,
  Activity,
  Download,
  Upload,
  RefreshCw,
  ExternalLink,
  CheckCircle2,
  AlertTriangle,
  Globe,
  Film,
} from 'lucide-react';

export const SettingsView: React.FC = () => {
  const { t, reloadI18n } = useApp();

  const [torrserverUrl, setTorrserverUrl] = useState<string>('');
  const [language, setLanguage] = useState<string>('ru');
  const [playerPath, setPlayerPath] = useState<string>('');
  const [jackettUrl, setJackettUrl] = useState<string>('');
  const [jackettKey, setJackettKey] = useState<string>('');
  const [torznabEnabled, setTorznabEnabled] = useState<boolean>(false);
  const [torznabUrl, setTorznabUrl] = useState<string>('');
  const [torznabKey, setTorznabKey] = useState<string>('');
  const [torznabCategories, setTorznabCategories] = useState<string>('2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060');
  const [appVersion, setAppVersion] = useState<string>('v0.0.6');

  const [saveHint, setSaveHint] = useState<{ text: string; isError?: boolean } | null>(null);
  const [isSaving, setIsSaving] = useState<boolean>(false);

  const [testHint, setTestHint] = useState<{ text: string; isError?: boolean } | null>(null);
  const [isTesting, setIsTesting] = useState<boolean>(false);

  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [isCheckingUpdate, setIsCheckingUpdate] = useState<boolean>(false);

  const [diagnostics, setDiagnostics] = useState<SystemDiagnostics | null>(null);
  const [isLoadingDiag, setIsLoadingDiag] = useState<boolean>(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  /**
   * Загрузка настроек с бэкенда и версии из version.json
   */
  useEffect(() => {
    API.getSettings()
      .then((s) => {
        if (s.torrserver_url) setTorrserverUrl(s.torrserver_url);
        if (s.language) setLanguage(s.language);
        if (s.player_path) setPlayerPath(s.player_path);
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
   * Проверка наличия обновлений
   */
  const handleCheckUpdates = async () => {
    setIsCheckingUpdate(true);
    try {
      const info = await API.checkUpdates();
      setUpdateInfo(info);
    } catch {
      setUpdateInfo({ has_update: false, latest: '', url: '', error: t('check_error') || 'Ошибка проверки' });
    } finally {
      setIsCheckingUpdate(false);
    }
  };

  /**
   * Опрос системной диагностики
   */
  const handleLoadDiagnostics = async () => {
    setIsLoadingDiag(true);
    try {
      const d = await API.getDiagnostics();
      setDiagnostics(d);
    } catch (e: any) {
      setDiagnostics({
        torrserver_version: 'Ошибка',
        mpv_path: 'Не обнаружен',
        db_size: 0,
        last_error: e.message,
      });
    } finally {
      setIsLoadingDiag(false);
    }
  };

  /**
   * Скачивание архива бэкапа
   */
  const handleDownloadBackup = () => {
    const a = document.createElement('a');
    a.href = '/api/settings/backup';
    a.download = 'pirate_cinema_backup.zip';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  /**
   * Восстановление бэкапа из файла
   */
  const handleUploadBackup = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!window.confirm(t('confirm_restore') || 'Восстановить конфигурацию из архива?')) {
      if (fileInputRef.current) fileInputRef.current.value = '';
      return;
    }

    try {
      await API.restoreBackup(file);
      alert(t('restore_success') || 'Данные восстановлены');
      window.location.reload();
    } catch (err: any) {
      alert(t('restore_error', { error: err.message }) || err.message);
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  return (
    <div className="space-y-8 animate-fade-in pb-16 max-w-4xl">
      <Header titleKey="nav_settings" />

      {/* ── Блок TorrServer ── */}
      <div className="settings-card p-6 bg-[#0a0e18] border border-slate-800/80 rounded-lg space-y-4 shadow-sm">
        <h2 className="text-lg font-tech font-bold uppercase tracking-wider text-slate-100 flex items-center gap-2">
          <Radio className="w-5 h-5 text-cyan-400" />
          TorrServer
        </h2>
        <div className="space-y-2">
          <span className="block font-tech text-xs text-slate-400 uppercase tracking-wider font-medium">
            {t('server_url') || 'URL сервера'}
          </span>
          <Input
            id="ts-url"
            type="text"
            value={torrserverUrl}
            onChange={(e) => setTorrserverUrl(e.target.value)}
            placeholder="http://127.0.0.1:8090"
          />
        </div>
      </div>

      {/* ── Блок Плеер MPV ── */}
      <div className="settings-card p-6 bg-[#0a0e18] border border-slate-800/80 rounded-lg space-y-4 shadow-sm">
        <h2 className="text-lg font-tech font-bold uppercase tracking-wider text-slate-100 flex items-center gap-2">
          <Film className="w-5 h-5 text-cyan-400" />
          {t('mpv_player') || 'Видеоплеер (MPV)'}
        </h2>
        <div className="space-y-2">
          <span className="block font-tech text-xs text-slate-400 uppercase tracking-wider font-medium">
            {t('mpv_path') || 'Путь к плееру MPV'}
          </span>
          <Input
            id="player-path"
            type="text"
            value={playerPath}
            onChange={(e) => setPlayerPath(e.target.value)}
            placeholder="Автоопределение (mpv.exe)"
          />
          <p className="text-xs text-slate-400 font-sans">
            Оставьте пустым для автоматического обнаружения (в комплекте приложения, в системе или реестре).
          </p>
        </div>
      </div>

      {/* ── Блок Общие (Язык) ── */}
      <div className="settings-card p-6 bg-[#0a0e18] border border-slate-800/80 rounded-lg space-y-4 shadow-sm">
        <h2 className="text-lg font-tech font-bold uppercase tracking-wider text-slate-100 flex items-center gap-2">
          <Globe className="w-5 h-5 text-cyan-400" />
          {t('settings') || t('general') || 'Общие'}
        </h2>
        
        {/* Выровненный блок выбора языка с идеальным вертикальным центрированием */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-3 bg-[#060910] border border-slate-800/60 rounded-md">
          <span className="font-tech text-sm text-slate-200 uppercase tracking-wider font-semibold">
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
      </div>

      {/* ── Блок Torznab / Jackett / Prowlarr ── */}
      <div className="settings-card p-6 bg-[#0a0e18] border border-slate-800/80 rounded-lg space-y-4 shadow-sm">
        <div className="space-y-1">
          <h2 className="text-lg font-tech font-bold uppercase tracking-wider text-slate-100 flex items-center gap-2">
            <Radio className="w-5 h-5 text-cyan-400" />
            Torznab (Jackett / Prowlarr)
          </h2>
          <p className="text-xs text-slate-400 font-sans">
            {t('jackett_hint') || 'Для поиска торрентов по сторонним трекерам через Torznab API.'}
          </p>
        </div>

        {/* Переключатель активности Torznab */}
        <div className="flex items-center justify-between p-3 bg-[#060910] border border-slate-800/60 rounded-md">
          <div className="space-y-0.5">
            <span className="font-tech text-sm text-slate-200 uppercase tracking-wider font-semibold">
              {t('torznab_enabled') || 'Включить Torznab'}
            </span>
            <p className="text-xs text-slate-400 font-sans">
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
            <div className="w-11 h-6 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-300 after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-cyan-500 peer-checked:after:bg-slate-950"></div>
          </label>
        </div>

        <div className="space-y-4 pt-1">
          <div className="space-y-2">
            <span className="block font-tech text-xs text-slate-400 uppercase tracking-wider font-medium">
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
            <span className="block font-tech text-xs text-slate-400 uppercase tracking-wider font-medium">
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
            <span className="block font-tech text-xs text-slate-400 uppercase tracking-wider font-medium">
              {t('torznab_categories') || 'Категории Torznab (ID через запятую)'}
            </span>
            <Input
              id="torznab-categories"
              type="text"
              value={torznabCategories}
              onChange={(e) => setTorznabCategories(e.target.value)}
              placeholder="2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060"
            />
            <p className="text-[11px] text-slate-500 font-sans">
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
          icon={<Radio className="w-4 h-4 text-cyan-400" />}
          loading={isTesting}
          onClick={handleTestConnection}
        >
          {t('test_connection') || 'Проверить соединение'}
        </Button>

        {saveHint && (
          <span
            id="ts-hint"
            className={`font-code text-xs ${
              saveHint.isError ? 'text-rose-400' : 'text-emerald-400'
            }`}
          >
            {saveHint.text}
          </span>
        )}
        {testHint && (
          <span
            className={`font-code text-xs ${
              testHint.isError ? 'text-rose-400' : 'text-emerald-400'
            }`}
          >
            {testHint.text}
          </span>
        )}
      </div>

      {/* ── Блок Обновления ── */}
      <div className="settings-card p-6 bg-[#0a0e18] border border-slate-800/80 rounded-lg space-y-4 shadow-sm">
        <h2 className="text-lg font-tech font-bold uppercase tracking-wider text-slate-100">
          {t('updates') || 'Обновления'}
        </h2>
        <div className="flex flex-wrap items-center justify-between gap-4 p-3 bg-[#060910] border border-slate-800/60 rounded-md">
          <span className="font-tech text-sm text-slate-200 font-semibold">
            Pirate Cinema {appVersion}
          </span>

          <div className="flex items-center gap-3">
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

            {updateInfo && (
              <span id="update-status" className="font-code text-xs flex items-center gap-2">
                {updateInfo.has_update ? (
                  <span className="text-amber-400 flex items-center gap-1.5">
                    <AlertTriangle className="w-4 h-4 text-amber-400" />
                    {t('update_available', { version: updateInfo.latest }) ||
                      `Доступно: ${updateInfo.latest}`}
                    {updateInfo.url && (
                      <a
                        href={updateInfo.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-cyan-400 underline flex items-center gap-1 ml-1"
                      >
                        {t('download') || 'Скачать'}
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </span>
                ) : (
                  <span className="text-emerald-400 flex items-center gap-1.5">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    {t('latest_version_installed') || 'Установлена последняя версия'}
                  </span>
                )}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* ── Блок Диагностика ── */}
      <div className="settings-card p-6 bg-[#0a0e18] border border-slate-800/80 rounded-lg space-y-4 shadow-sm">
        <h2 className="text-lg font-tech font-bold uppercase tracking-wider text-slate-100 flex items-center gap-2">
          <Activity className="w-5 h-5 text-cyan-400" />
          {t('diagnostics') || 'Диагностика'}
        </h2>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            icon={<FolderOpen className="w-4 h-4" />}
            onClick={() => API.openFolder()}
          >
            {t('open_data_folder') || '📂 Открыть папку данных'}
          </Button>

          <Button
            variant="secondary"
            size="sm"
            icon={<Activity className="w-4 h-4 text-cyan-400" />}
            loading={isLoadingDiag}
            onClick={handleLoadDiagnostics}
          >
            {t('refresh_system') || 'Опросить систему'}
          </Button>

          <Button
            variant="secondary"
            size="sm"
            icon={<Download className="w-4 h-4 text-emerald-400" />}
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
              icon={<Upload className="w-4 h-4 text-pink-400" />}
              onClick={() => fileInputRef.current?.click()}
            >
              {t('restore_backup') || 'Восстановить бэкап'}
            </Button>
          </label>
        </div>

        {diagnostics && (
          <div
            id="diag-output"
            className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-3 border-t border-slate-800/80"
          >
            <div className="p-3 bg-[#06080e] border border-slate-800/80 rounded-md">
              <span className="font-code text-xs text-slate-500 block mb-1">
                {t('ts_version') || 'Версия TorrServer'}
              </span>
              <strong id="diag-ts" className="font-code text-sm text-cyan-300 block">
                {diagnostics.torrserver_version}
              </strong>
            </div>

            <div className="p-3 bg-[#06080e] border border-slate-800/80 rounded-md">
              <span className="font-code text-xs text-slate-500 block mb-1">
                {t('db_size') || 'Размер базы данных'}
              </span>
              <strong id="diag-db" className="font-code text-sm text-cyan-300 block">
                {formatSize(diagnostics.db_size, t)}
              </strong>
            </div>

            <div className="p-3 bg-[#06080e] border border-slate-800/80 rounded-md md:col-span-2">
              <span className="font-code text-xs text-slate-500 block mb-1">
                {t('mpv_path') || 'Путь к плееру MPV'}
              </span>
              <strong
                id="diag-mpv"
                className="font-code text-xs text-slate-300 break-all block"
              >
                {diagnostics.mpv_path}
              </strong>
            </div>

            <div className="p-3 bg-[#06080e] border border-slate-800/80 rounded-md md:col-span-2">
              <span className="font-code text-xs text-slate-500 block mb-1">
                {t('last_error') || 'Последняя ошибка'}
              </span>
              <strong
                id="diag-err"
                className="font-code text-xs text-rose-400 break-all block font-normal"
              >
                {diagnostics.last_error || t('no_errors') || 'Ошибок нет'}
              </strong>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
