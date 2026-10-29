/**
 * @file components/player/RemoteModal.tsx
 * @description Модальное окно с QR-кодом и адресом локального веб-пульта
 * для управления плеером Pirate Cinema со смартфона.
 */

import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import { Smartphone, X, Copy, Check, QrCode, Wifi, Loader2, Sparkles, Globe } from 'lucide-react';

export const RemoteModal: React.FC = () => {
  const { isRemoteOpen, setIsRemoteOpen, t } = useApp();
  const [remoteInfo, setRemoteInfo] = useState<{
    url: string;
    local_url?: string;
    ip_url?: string;
    hostname?: string;
    qr_svg: string;
    ip_qr_svg?: string;
    ip: string;
    port: number;
  } | null>(null);
  const [mode, setMode] = useState<'local' | 'ip'>('ip');
  const [loading, setLoading] = useState<boolean>(true);
  const [copied, setCopied] = useState<boolean>(false);

  useEffect(() => {
    if (!isRemoteOpen) return;
    setMode('ip');
    setLoading(true);
    API.getRemoteInfo()
      .then((info) => {
        setRemoteInfo(info);
      })
      .catch((err) => {
        console.error('Failed to get remote info:', err);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [isRemoteOpen]);

  const activeUrl = mode === 'local'
    ? (remoteInfo?.local_url || remoteInfo?.url || '')
    : (remoteInfo?.ip_url || remoteInfo?.url || '');

  const activeQrSvg = mode === 'local'
    ? remoteInfo?.qr_svg
    : (remoteInfo?.ip_qr_svg || remoteInfo?.qr_svg);

  const handleCopy = () => {
    if (!activeUrl) return;
    navigator.clipboard.writeText(activeUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  if (!isRemoteOpen) return null;

  return (
    <div
      role="dialog" aria-modal="true" aria-label="Пульт для смартфона"
      className="ui-dialog-overlay fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-fade-in"
      onClick={() => setIsRemoteOpen(false)}
    >
      <div
        className="ui-dialog relative w-full max-w-md bg-film-base border border-film-line rounded-md p-6 flex flex-col items-center select-none"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Кнопка закрыть */}
        <button data-dialog-close
          onClick={() => setIsRemoteOpen(false)}
          className="absolute top-4 right-4 p-1.5 text-film-muted hover:text-white rounded-md hover:bg-film-surface transition-colors"
          title="Закрыть"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Заголовок */}
        <div className="flex items-center gap-2.5 mb-1 text-film-accent">
          <Smartphone className="w-6 h-6 stroke-[2.2]" />
          <h3 className="font-sans text-lg font-semibold text-white">
            Веб-пульт для смартфона
          </h3>
        </div>
        <p className="text-xs text-film-muted text-center mb-4">
          Управляйте фильмами и раздачами с дивана через браузер телефона
        </p>

        {/* Переключатель режима: по IP / .local (имя ПК) */}
        <div className="flex items-center gap-1.5 p-1 bg-film-base border border-film-line rounded-md mb-4 w-full max-w-xs justify-center">
          <button
            type="button"
            onClick={() => setMode('ip')}
            className={`flex-1 py-1.5 px-3 rounded-md text-xs font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
              mode === 'ip'
                ? 'bg-film-hover text-film-accent border border-film-line '
                : 'text-film-muted hover:text-film-text'
            }`}
          >
            <Globe className="w-3.5 h-3.5 text-film-muted" />
            <span>По IP-адресу</span>
          </button>
          <button
            type="button"
            onClick={() => setMode('local')}
            className={`flex-1 py-1.5 px-3 rounded-md text-xs font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
              mode === 'local'
                ? 'bg-film-hover text-film-accent border border-film-line '
                : 'text-film-muted hover:text-film-text'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5 text-film-accent" />
            <span>.local (Имя ПК)</span>
          </button>
        </div>

        {/* QR Код */}
        <div className="relative w-56 h-56 bg-white p-3 rounded-md flex items-center justify-center mb-4">
          {loading ? (
            <div className="flex flex-col items-center gap-2 text-film-muted">
              <Loader2 className="w-8 h-8 animate-spin text-film-accent" />
              <span className="text-xs font-semibold">Генерация QR...</span>
            </div>
          ) : activeQrSvg ? (
            <div
              className="w-full h-full flex items-center justify-center [&>svg]:w-full [&>svg]:h-full [&>svg]:block [&>svg_path]:fill-black"
              dangerouslySetInnerHTML={{ __html: activeQrSvg }}
            />
          ) : (
            <div className="text-xs text-rose-500 text-center p-2">
              Не удалось сгенерировать QR-код
            </div>
          )}
        </div>

        {/* Ссылка на пульт */}
        <div className="w-full bg-film-base border border-film-line rounded-md p-2.5 flex items-center justify-between gap-3 mb-2">
          <div className="flex items-center gap-2 min-w-0 pl-1">
            <Wifi className="w-4 h-4 text-emerald-400 shrink-0" />
            <span className="font-mono text-xs text-film-text truncate select-all">
              {activeUrl || (loading ? 'Загрузка адреса…' : 'Адрес недоступен')}
            </span>
          </div>
          <button
            onClick={handleCopy}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold flex items-center gap-1.5 shrink-0 transition-colors cursor-pointer ${
              copied
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                : 'bg-film-hover text-film-accent hover:bg-film-hover border border-film-line'
            }`}
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5" />
                <span>Скопировано</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                <span>Копировать</span>
              </>
            )}
          </button>
        </div>

        {/* Пояснение к выбранному режиму */}
        <p className="text-[11px] text-center mb-4 px-2 leading-tight">
          {mode === 'local' ? (
            <span className="text-film-accent font-medium">
              Постоянная ссылка через mDNS: не изменится при смене IP роутером. .local поддерживается не на всех устройствах. Если ссылка не открывается, используйте IP-адрес.
            </span>
          ) : (
            <span className="text-film-muted">
              Прямая ссылка по IP-адресу компьютера. Используйте, если ссылка .local не открывается.
            </span>
          )}
        </p>

        {/* Подсказка */}
        <div className="w-full bg-film-surface rounded-md p-3 text-[11px] text-film-muted leading-relaxed border border-film-line">
          <div className="font-semibold text-film-text mb-1 flex items-center gap-1.5">
            <QrCode className="w-3.5 h-3.5 text-film-accent" />
            Инструкция для смартфона:
          </div>
          1. Смартфон и компьютер должны быть в одной Wi-Fi сети.<br />
          2. Отсканируйте QR-код.<br />
          3. Сохраните пульт на главный экран:<br />
          <strong>iPhone:</strong> в Safari нажмите <strong>«Поделиться» → «На экран Домой»</strong>.<br />
          <strong>Android:</strong> в Chrome откройте меню <strong>⋮ → «Добавить на главный экран»</strong>.
        </div>
      </div>
    </div>
  );
};
