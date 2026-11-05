import { useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import { API } from '../../services/api';
import { canShowNativePlayer } from '../../services/playerSession';

export function useNativePlayer(
  sessionKey: string | null,
  sessionRevision: number,
  policy: Parameters<typeof canShowNativePlayer>[0],
  backendFullscreen: boolean,
  isAnyModalOpen: boolean,
  isPipActive: () => boolean,
) {
  const visible = Boolean(sessionKey && canShowNativePlayer(policy));
  const isFullscreen = visible && backendFullscreen;
  const visibleRef = useRef(visible);
  visibleRef.current = visible;
  const isFullscreenRef = useRef(isFullscreen);
  isFullscreenRef.current = isFullscreen;
  const isAnyModalOpenRef = useRef(isAnyModalOpen);
  isAnyModalOpenRef.current = isAnyModalOpen;

  const wrapperRef = useRef<HTMLDivElement>(null);
  const videoSlotRef = useRef<HTMLDivElement>(null);
  const lastSentBoundsRef = useRef<{ x: number; y: number; w: number; h: number; fs: boolean } | null>(null);

  const syncPlayerBounds = useCallback(() => {
    if (!videoSlotRef.current) return;

    if (isAnyModalOpenRef.current) {
      return;
    }

    if (wrapperRef.current && wrapperRef.current.offsetParent === null && !isFullscreenRef.current) {
      return;
    }

    // Пока файлы еще грузятся или MPV буферизирует поток — нативное черное окно должно быть скрыто!
    // Иначе оно физически перекрывает HTML-лоадер в окне WebView2.
    if (!visibleRef.current) {
      lastSentBoundsRef.current = null;
      API.hidePlayerPanel();
      return;
    }

    const rect = videoSlotRef.current.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;

    const fs = isFullscreenRef.current;
    const bx = Math.round(rect.left);
    const by = Math.round(rect.top);
    const bw = Math.round(rect.width);
    const bh = Math.round(rect.height);

    const prev = lastSentBoundsRef.current;
    if (
      prev &&
      prev.x === bx &&
      prev.y === by &&
      prev.w === bw &&
      prev.h === bh &&
      prev.fs === fs
    ) {
      return;
    }

    lastSentBoundsRef.current = { x: bx, y: by, w: bw, h: bh, fs };

    if (fs) {
      API.setPlayerBounds({
        x: 0,
        y: 0,
        width: window.innerWidth,
        height: window.innerHeight,
        viewport_width: window.innerWidth,
        viewport_height: window.innerHeight,
        clip_top: 0,
        clip_left: 0,
        clip_right: window.innerWidth,
        clip_bottom: window.innerHeight,
      });
      return;
    }

    const mainEl = document.getElementById('page-container');
    const mainRect = mainEl
      ? mainEl.getBoundingClientRect()
      : {
          top: 36,
          left: 256,
          right: window.innerWidth,
          bottom: window.innerHeight,
        };

    API.setPlayerBounds({
      x: bx,
      y: by,
      width: bw,
      height: bh,
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight,
      clip_top: Math.max(36, mainRect.top),
      clip_left: Math.max(0, mainRect.left),
      clip_right: mainRect.right,
      clip_bottom: mainRect.bottom,
    });
  }, []);

  useLayoutEffect(() => () => {
    lastSentBoundsRef.current = null;
    // App unmounts the inline view while the same native panel moves into PiP.
    if (!isPipActive()) void API.hidePlayerPanel();
  }, [sessionKey, isPipActive]);

  useEffect(() => {
    lastSentBoundsRef.current = null;
    if (!visible) {
      void API.hidePlayerPanel();
      return;
    }
    const timers = (isFullscreen ? [30, 100, 250] : [50, 200, 500])
      .map(delay => setTimeout(syncPlayerBounds, delay));
    return () => timers.forEach(timer => clearTimeout(timer));
  }, [sessionKey, sessionRevision, visible, isFullscreen, syncPlayerBounds]);

  useEffect(() => {
    if (!sessionKey || isAnyModalOpen) return;
    lastSentBoundsRef.current = null;
    const timers = [50, 150].map(delay => setTimeout(syncPlayerBounds, delay));
    return () => timers.forEach(timer => clearTimeout(timer));
  }, [isAnyModalOpen, sessionKey, syncPlayerBounds]);

  useEffect(() => {
    if (!sessionKey) return;
    const timer = setTimeout(() => {
      syncPlayerBounds();
      wrapperRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 30);
    return () => clearTimeout(timer);
  }, [sessionKey, sessionRevision, syncPlayerBounds]);

  useEffect(() => {
    if (!sessionKey) return;
    return observeNativePlayerBounds(videoSlotRef.current, syncPlayerBounds);
  }, [sessionKey, isFullscreen, syncPlayerBounds]);

  return { wrapperRef, videoSlotRef, isFullscreen };
}

export function observeNativePlayerBounds(videoSlot: HTMLDivElement | null, syncPlayerBounds: () => void) {
  syncPlayerBounds();
  const timer = setTimeout(syncPlayerBounds, 80);
  let frame: number | null = null;
  const onScrollOrResize = () => {
    if (frame !== null) return;
    frame = requestAnimationFrame(() => {
      frame = null;
      syncPlayerBounds();
    });
  };

  window.addEventListener('resize', onScrollOrResize, { passive: true });
  window.addEventListener('scroll', onScrollOrResize, { passive: true });
  const mainEl = document.getElementById('page-container');
  mainEl?.addEventListener('scroll', onScrollOrResize, { passive: true });

  const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(onScrollOrResize);
  if (videoSlot) observer?.observe(videoSlot);
  if (mainEl) observer?.observe(mainEl);

  return () => {
    clearTimeout(timer);
    window.removeEventListener('resize', onScrollOrResize);
    window.removeEventListener('scroll', onScrollOrResize);
    mainEl?.removeEventListener('scroll', onScrollOrResize);
    observer?.disconnect();
    if (frame !== null) cancelAnimationFrame(frame);
  };
}

