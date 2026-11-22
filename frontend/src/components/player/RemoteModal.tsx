/**
 * @file components/player/RemoteModal.tsx
 * @description Модальное окно с QR-кодом для смартфона и встроенным плеером мобильного стрима
 * (HLS, Direct Play, Remux) с индикацией буферизации, перемоткой и очисткой процессов FFmpeg.
 */

import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useApp } from '../../context/AppContext';
import { API } from '../../services/api';
import {
  Smartphone,
  X,
  Copy,
  Check,
  QrCode,
  Wifi,
  Loader2,
  Sparkles,
  Globe,
  Tv,
  Play,
  Pause,
  RotateCcw,
  RotateCw,
  Volume2,
  VolumeX,
  AlertCircle,
  RefreshCw,
} from 'lucide-react';

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '00:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h}:${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
  }
  return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
}

export interface RemoteModalProps {
  initialTab?: 'remote' | 'stream';
  streamUrl?: string;
}

export const RemoteModal: React.FC<RemoteModalProps> = ({
  initialTab = 'remote',
  streamUrl: initialStreamUrl,
}) => {
  const { isRemoteOpen, setIsRemoteOpen, activePlayback } = useApp();
  const [tab, setTab] = useState<'remote' | 'stream'>(initialTab);
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

  // Streaming player state
  const [streamData, setStreamData] = useState<{
    url: string;
    token: string;
    mode: string;
    duration: number;
    resume: number;
  } | null>(null);
  const [isStreamLoading, setIsStreamLoading] = useState<boolean>(false);
  const [isBuffering, setIsBuffering] = useState<boolean>(false);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [duration, setDuration] = useState<number>(0);
  const [isMuted, setIsMuted] = useState<boolean>(false);
  const [streamError, setStreamError] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const hlsRef = useRef<any>(null);
  const pairTokenRef = useRef<string | null>(null);
  const sessionTokenRef = useRef<string | null>(null);
  const sequenceRef = useRef<number>(0);
  const currentTimeRef = useRef<number>(0);
  const durationRef = useRef<number>(0);
  const lastProgressReportRef = useRef<number>(0);

  // Stop mobile stream and guarantee instant KILL of FFmpeg process
  const stopStream = useCallback(() => {
    if (hlsRef.current) {
      try {
        hlsRef.current.destroy();
      } catch {
        // ignore
      }
      hlsRef.current = null;
    }
    if (videoRef.current) {
      try {
        videoRef.current.pause();
        videoRef.current.removeAttribute('src');
        videoRef.current.load();
      } catch {
        // ignore
      }
    }
    if (sessionTokenRef.current) {
      const token = sessionTokenRef.current;
      sessionTokenRef.current = null;
      fetch(`/api/remote/mobile/${token}/progress`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sequence: sequenceRef.current++,
          position: currentTimeRef.current,
          duration: durationRef.current,
          close: true,
        }),
        keepalive: true,
      }).catch(() => {});
    }
    setIsPlaying(false);
    setIsBuffering(false);
    setStreamData(null);
  }, []);

  // Fetch remote pairing info
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

  // Cleanup stream on modal close or unmount
  useEffect(() => {
    if (!isRemoteOpen) {
      stopStream();
    }
    return () => {
      stopStream();
    };
  }, [isRemoteOpen, stopStream]);

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

  // Initialize playback in video element (HLS vs native)
  const initPlayer = useCallback((streamUrl: string) => {
    const video = videoRef.current;
    if (!video) return;

    if (hlsRef.current) {
      try {
        hlsRef.current.destroy();
      } catch {
        // ignore
      }
      hlsRef.current = null;
    }

    const isHls = streamUrl.includes('.m3u8');

    if (isHls && video.canPlayType('application/vnd.apple.mpegurl')) {
      // Safari / iOS native HLS
      video.src = streamUrl;
      video.play().catch(() => {});
    } else if (isHls) {
      const setupHls = () => {
        const HlsClass = (window as any).Hls;
        if (HlsClass && HlsClass.isSupported()) {
          const hls = new HlsClass({
            enableWorker: false,
            maxBufferLength: 30,
            maxMaxBufferLength: 60,
          });
          hls.loadSource(streamUrl);
          hls.attachMedia(video);
          hls.on(HlsClass.Events.ERROR, (_: any, data: any) => {
            if (data.fatal) {
              switch (data.type) {
                case HlsClass.ErrorTypes.NETWORK_ERROR:
                  hls.startLoad();
                  break;
                case HlsClass.ErrorTypes.MEDIA_ERROR:
                  hls.recoverMediaError();
                  break;
                default:
                  setStreamError('Ошибка воспроизведения потока HLS');
                  hls.destroy();
                  break;
              }
            }
          });
          hlsRef.current = hls;
          video.play().catch(() => {});
        } else {
          video.src = streamUrl;
          video.play().catch(() => {});
        }
      };

      if ((window as any).Hls) {
        setupHls();
      } else {
        const scriptId = 'pc-hls-script';
        let script = document.getElementById(scriptId) as HTMLScriptElement | null;
        if (!script) {
          script = document.createElement('script');
          script.id = scriptId;
          script.src = '/vendor/hls.light.min.js';
          script.onload = () => setupHls();
          script.onerror = () => {
            video.src = streamUrl;
            video.play().catch(() => {});
          };
          document.head.appendChild(script);
        } else {
          script.addEventListener('load', setupHls, { once: true });
        }
      }
    } else {
      // Direct Play or Remux MP4
      video.src = streamUrl;
      video.play().catch(() => {});
    }
  }, []);

  // Start mobile stream for active desktop playback
  const startStream = useCallback(async () => {
    setIsStreamLoading(true);
    setStreamError(null);
    try {
      if (initialStreamUrl) {
        initPlayer(initialStreamUrl);
        setIsStreamLoading(false);
        return;
      }

      const info = remoteInfo || (await API.getRemoteInfo());
      const curUrl = mode === 'local' ? (info.local_url || info.url) : (info.ip_url || info.url);
      const pairCode = curUrl.split('#pair=')[1] || '';
      let token = pairTokenRef.current;
      if (!token && pairCode) {
        const pairRes = await fetch('/api/remote/pair', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code: pairCode }),
        });
        if (pairRes.ok) {
          const pairData = await pairRes.json();
          token = pairData.token;
          pairTokenRef.current = token;
        }
      }

      if (!activePlayback?.hash) {
        setStreamError('Нет активного видео для трансляции. Запустите воспроизведение на ПК.');
        setIsStreamLoading(false);
        return;
      }

      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) {
        headers['x-remote-token'] = token;
      }

      const playRes = await fetch('/api/remote/mobile', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          hash: activePlayback.hash,
          file_id: activePlayback.fileId,
          season: activePlayback.targetSeason,
          episode: activePlayback.targetEpisode,
          absolute: activePlayback.absoluteEpisode,
          title: activePlayback.title,
          magnet: activePlayback.magnet,
        }),
      });

      if (!playRes.ok) {
        const errText = await playRes.text();
        let errMsg = 'Не удалось запустить мобильный стрим';
        try {
          const errObj = JSON.parse(errText);
          errMsg = errObj.detail || errMsg;
        } catch {
          // ignore
        }
        throw new Error(errMsg);
      }

      const playData = await playRes.json();
      sessionTokenRef.current = playData.token;
      setStreamData(playData);
      const dur = playData.duration || 0;
      setDuration(dur);
      durationRef.current = dur;
      initPlayer(playData.url);
    } catch (err: any) {
      setStreamError(err.message || 'Ошибка запуска трансляции');
    } finally {
      setIsStreamLoading(false);
    }
  }, [activePlayback, initPlayer, initialStreamUrl, mode, remoteInfo]);

  // Video event handlers
  const handleTimeUpdate = () => {
    const video = videoRef.current;
    if (!video) return;
    const cur = video.currentTime;
    setCurrentTime(cur);
    currentTimeRef.current = cur;
    if (video.duration && isFinite(video.duration) && video.duration > 0) {
      setDuration(video.duration);
      durationRef.current = video.duration;
    }
    // Independent mobile progress: never touches desktop MPV position
    const now = Date.now();
    if (sessionTokenRef.current && now - lastProgressReportRef.current > 5000) {
      lastProgressReportRef.current = now;
      fetch(`/api/remote/mobile/${sessionTokenRef.current}/progress`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sequence: sequenceRef.current++,
          position: cur,
          duration: durationRef.current,
          close: false,
        }),
      }).catch(() => {});
    }
  };

  const handleWaiting = () => setIsBuffering(true);
  const handleSeeking = () => setIsBuffering(true);
  const handlePlaying = () => {
    setIsBuffering(false);
    setIsPlaying(true);
  };
  const handlePause = () => setIsPlaying(false);
  const handleCanPlay = () => setIsBuffering(false);
  const handleSeeked = () => setIsBuffering(false);

  const togglePlayPause = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      video.play().catch(() => {});
    } else {
      video.pause();
    }
  };

  const seekBy = (seconds: number) => {
    const video = videoRef.current;
    if (!video) return;
    const target = Math.max(0, Math.min(video.currentTime + seconds, duration || video.duration || 0));
    video.currentTime = target;
    setCurrentTime(target);
    currentTimeRef.current = target;
  };

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const video = videoRef.current;
    if (!video) return;
    const val = parseFloat(e.target.value);
    video.currentTime = val;
    setCurrentTime(val);
    currentTimeRef.current = val;
  };

  const toggleMute = () => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !video.muted;
    setIsMuted(video.muted);
  };

  if (!isRemoteOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Пульт для смартфона"
      className="ui-dialog-overlay fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-fade-in"
      onClick={() => setIsRemoteOpen(false)}
    >
      <div
        className={`ui-dialog relative w-full ${tab === 'stream' ? 'max-w-2xl' : 'max-w-md'} bg-film-base border border-film-line rounded-md p-6 flex flex-col items-center select-none transition-all`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Кнопка закрыть */}
        <button
          data-dialog-close
          onClick={() => setIsRemoteOpen(false)}
          className="absolute top-4 right-4 p-1.5 text-film-muted hover:text-white rounded-md hover:bg-film-surface transition-colors cursor-pointer"
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

        {/* Табы: Пульт / Стрим */}
        <div className="flex items-center gap-2 p-1 bg-film-surface border border-film-line rounded-md mb-4 w-full max-w-xs justify-center">
          <button
            type="button"
            onClick={() => setTab('remote')}
            className={`flex-1 py-1.5 px-3 rounded-md text-xs font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
              tab === 'remote'
                ? 'bg-film-hover text-film-accent border border-film-line'
                : 'text-film-muted hover:text-film-text'
            }`}
          >
            <QrCode className="w-3.5 h-3.5" />
            <span>Пульт</span>
          </button>
          <button
            type="button"
            onClick={() => setTab('stream')}
            className={`flex-1 py-1.5 px-3 rounded-md text-xs font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
              tab === 'stream'
                ? 'bg-film-hover text-film-accent border border-film-line'
                : 'text-film-muted hover:text-film-text'
            }`}
          >
            <Tv className="w-3.5 h-3.5" />
            <span>Стрим</span>
            {activePlayback?.hash && (
              <span className="w-2 h-2 rounded-full bg-emerald-400" title="Есть активное видео" />
            )}
          </button>
        </div>

        {tab === 'remote' ? (
          <>
            {/* Переключатель режима: по IP / .local (имя ПК) */}
            <div className="flex items-center gap-1.5 p-1 bg-film-base border border-film-line rounded-md mb-4 w-full max-w-xs justify-center">
              <button
                type="button"
                onClick={() => setMode('ip')}
                className={`flex-1 py-1.5 px-3 rounded-md text-xs font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
                  mode === 'ip'
                    ? 'bg-film-hover text-film-accent border border-film-line'
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
                    ? 'bg-film-hover text-film-accent border border-film-line'
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
          </>
        ) : (
          /* Вкладка Стрима */
          <div className="w-full flex flex-col items-center">
            {streamError && (
              <div className="w-full mb-3 p-2.5 bg-rose-500/10 border border-rose-500/30 rounded-md flex items-center gap-2 text-rose-400 text-xs">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span className="flex-1">{streamError}</span>
                <button
                  onClick={startStream}
                  className="px-2 py-1 bg-rose-500/20 hover:bg-rose-500/30 rounded text-rose-300 transition-colors cursor-pointer"
                >
                  Повторить
                </button>
              </div>
            )}

            {/* Видео контейнер */}
            <div className="relative w-full aspect-video bg-black rounded-md overflow-hidden border border-film-line flex items-center justify-center mb-3">
              <video
                ref={videoRef}
                playsInline
                className="w-full h-full object-contain"
                onTimeUpdate={handleTimeUpdate}
                onWaiting={handleWaiting}
                onSeeking={handleSeeking}
                onPlaying={handlePlaying}
                onPause={handlePause}
                onCanPlay={handleCanPlay}
                onSeeked={handleSeeked}
              />

              {/* Оверлей буферизации */}
              {isBuffering && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/60 z-20 pointer-events-none">
                  <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-film-base/90 border border-film-line text-xs font-medium text-film-accent shadow-lg animate-pulse">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Буферизация...</span>
                  </div>
                </div>
              )}

              {/* Загрузка запуска стрима */}
              {isStreamLoading && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 z-20 gap-2">
                  <Loader2 className="w-8 h-8 animate-spin text-film-accent" />
                  <span className="text-xs text-film-muted">Подготовка трансляции (HLS / FFmpeg)...</span>
                </div>
              )}

              {/* Плейсхолдер перед запуском */}
              {!streamData && !isStreamLoading && !initialStreamUrl && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-film-surface/50 p-4 text-center z-10 gap-3">
                  <Tv className="w-10 h-10 text-film-muted opacity-60" />
                  <div className="text-xs text-film-muted max-w-xs">
                    {activePlayback?.title ? (
                      <span>Готово к трансляции: <strong className="text-film-text">{activePlayback.title}</strong></span>
                    ) : (
                      <span>Запустите воспроизведение фильма на ПК для просмотра стрима</span>
                    )}
                  </div>
                  <button
                    onClick={startStream}
                    disabled={!activePlayback?.hash}
                    className={`px-4 py-2 rounded-md text-xs font-semibold flex items-center gap-2 transition-all cursor-pointer ${
                      activePlayback?.hash
                        ? 'bg-film-accent text-film-base hover:opacity-90 shadow-md'
                        : 'bg-film-line text-film-muted cursor-not-allowed opacity-50'
                    }`}
                  >
                    <Play className="w-3.5 h-3.5 fill-current" />
                    <span>Запустить стрим</span>
                  </button>
                </div>
              )}
            </div>

            {/* Элементы управления стримом */}
            <div className="w-full bg-film-surface border border-film-line rounded-md p-3 flex flex-col gap-2">
              {/* Полоса перемотки */}
              <div className="flex items-center gap-2">
                <span className="font-mono text-[11px] text-film-muted w-10 text-right">
                  {formatTime(currentTime)}
                </span>
                <input
                  type="range"
                  min={0}
                  max={duration > 0 ? duration : 100}
                  step={1}
                  value={currentTime}
                  onChange={handleSliderChange}
                  className="flex-1 accent-film-accent cursor-pointer h-1.5 bg-film-line rounded-lg"
                />
                <span className="font-mono text-[11px] text-film-muted w-10">
                  {formatTime(duration)}
                </span>
              </div>

              {/* Кнопки плеера */}
              <div className="flex items-center justify-between pt-1">
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => seekBy(-10)}
                    disabled={!streamData}
                    className="p-1.5 rounded-md hover:bg-film-hover text-film-muted hover:text-film-text transition-colors cursor-pointer disabled:opacity-40"
                    title="Перемотка назад на 10 сек"
                  >
                    <RotateCcw className="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    onClick={togglePlayPause}
                    disabled={!streamData}
                    className="p-2 rounded-md bg-film-hover hover:bg-film-surface text-film-accent hover:text-white border border-film-line transition-colors cursor-pointer disabled:opacity-40"
                    title={isPlaying ? 'Пауза' : 'Воспроизведение'}
                  >
                    {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 fill-current" />}
                  </button>
                  <button
                    type="button"
                    onClick={() => seekBy(10)}
                    disabled={!streamData}
                    className="p-1.5 rounded-md hover:bg-film-hover text-film-muted hover:text-film-text transition-colors cursor-pointer disabled:opacity-40"
                    title="Перемотка вперед на 10 сек"
                  >
                    <RotateCw className="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    onClick={toggleMute}
                    disabled={!streamData}
                    className="p-1.5 rounded-md hover:bg-film-hover text-film-muted hover:text-film-text transition-colors cursor-pointer disabled:opacity-40"
                    title={isMuted ? 'Включить звук' : 'Без звука'}
                  >
                    {isMuted ? <VolumeX className="w-4 h-4 text-rose-400" /> : <Volume2 className="w-4 h-4" />}
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  {streamData && (
                    <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-film-base border border-film-line text-film-accent">
                      {streamData.mode}
                    </span>
                  )}
                  {streamData && (
                    <button
                      type="button"
                      onClick={startStream}
                      className="p-1.5 rounded-md hover:bg-film-hover text-film-muted hover:text-film-text transition-colors cursor-pointer"
                      title="Перезапустить стрим"
                    >
                      <RefreshCw className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            </div>

            <p className="text-[11px] text-film-muted text-center mt-3">
              Позиция просмотра мобильного стрима изолирована и не сбивает воспроизведение на ПК.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};
