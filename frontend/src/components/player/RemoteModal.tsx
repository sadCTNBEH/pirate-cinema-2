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
  const [mode, setMode] = useState<'local' | 'ip'>('local');
  const [loading, setLoading] = useState<boolean>(true);
  const [copied, setCopied] = useState<boolean>(false);

  useEffect(() => {
    if (!isRemoteOpen) return;
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
      role="dialog" aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-fade-in"
      onClick={() => setIsRemoteOpen(false)}
    >
      <div
        className="relative w-full max-w-md bg-[#0a0f1d] border border-cyan-500/40 rounded-2xl p-6 shadow-2xl shadow-cyan-950/50 flex flex-col items-center select-none"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Кнопка закрыть */}
        <button data-dialog-close
          onClick={() => setIsRemoteOpen(false)}
          className="absolute top-4 right-4 p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800/80 transition-colors"
          title="Закрыть"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Заголовок */}
        <div className="flex items-center gap-2.5 mb-1 text-cyan-400">
          <Smartphone className="w-6 h-6 stroke-[2.2]" />
          <h3 className="font-tech text-lg font-bold uppercase tracking-wider text-white">
            Веб-пульт для смартфона
          </h3>
        </div>
        <p className="text-xs text-slate-400 text-center mb-4">
          Управляйте фильмами и раздачами с дивана через браузер телефона
        </p>

        {/* Переключатель режима: .local (постоянный) / по IP */}
        <div className="flex items-center gap-1.5 p-1 bg-[#06080d] border border-slate-800 rounded-xl mb-4 w-full max-w-xs justify-center">
          <button
            type="button"
            onClick={() => setMode('local')}
            className={`flex-1 py-1.5 px-3 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
              mode === 'local'
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
            <span>.local (Имя ПК)</span>
          </button>
          <button
            type="button"
            onClick={() => setMode('ip')}
            className={`flex-1 py-1.5 px-3 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
              mode === 'ip'
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Globe className="w-3.5 h-3.5 text-slate-400" />
            <span>По IP-адресу</span>
          </button>
        </div>

        {/* QR Код */}
        <div className="relative w-56 h-56 bg-white p-3 rounded-xl shadow-lg shadow-black/40 flex items-center justify-center mb-4">
          {loading ? (
            <div className="flex flex-col items-center gap-2 text-slate-600">
              <Loader2 className="w-8 h-8 animate-spin text-cyan-600" />
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
        <div className="w-full bg-[#06080d] border border-slate-800 rounded-xl p-2.5 flex items-center justify-between gap-3 mb-2">
          <div className="flex items-center gap-2 min-w-0 pl-1">
            <Wifi className="w-4 h-4 text-emerald-400 shrink-0" />
            <span className="font-mono text-xs text-slate-200 truncate select-all">
              {activeUrl || 'http://desktop.local:8001/remote'}
            </span>
          </div>
          <button
            onClick={handleCopy}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 shrink-0 transition-colors cursor-pointer ${
              copied
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                : 'bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30 border border-cyan-500/30'
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
            <span className="text-cyan-300/90 font-medium">
              Постоянная ссылка через mDNS: не изменится при смене IP роутером. Идеально для iPhone.
            </span>
          ) : (
            <span className="text-slate-400">
              Прямой IP-адрес: резервный вариант, если устройство не поддерживает .local.
            </span>
          )}
        </p>

        {/* Подсказка */}
        <div className="w-full bg-slate-900/60 rounded-lg p-3 text-[11px] text-slate-400 leading-relaxed border border-slate-800/80">
          <div className="font-semibold text-slate-300 mb-1 flex items-center gap-1.5">
            <QrCode className="w-3.5 h-3.5 text-cyan-400" />
            Инструкция для смартфона:
          </div>
          1. Смартфон и компьютер должны быть в одной Wi-Fi сети.<br />
          2. Наведите камеру iPhone на QR-код и откройте ссылку в Safari.<br />
          3. В Safari нажмите <strong>«Поделиться» → «На экран Домой»</strong>, чтобы сохранить пульт с иконкой на рабочий стол.
        </div>
      </div>
    </div>
  );
};
