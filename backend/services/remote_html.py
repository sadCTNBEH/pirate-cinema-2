"""Mobile-optimized cyberpunk web remote template for smartphone control and torrent search."""

REMOTE_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
  <title>Pirate Cinema Remote</title>
  <meta name="apple-mobile-web-app-title" content="Pirate Cinema Remote">
  <meta name="application-name" content="Pirate Cinema Remote">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="theme-color" content="#06080d">
  <link rel="icon" type="image/png" href="/logo.png">
  <link rel="apple-touch-icon" href="/logo.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/logo.png">
  <link rel="apple-touch-icon-precomposed" href="/logo.png">
  <link rel="manifest" href="/remote.webmanifest">
  <style>
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      -webkit-tap-highlight-color: transparent;
      user-select: none;
      -webkit-user-select: none;
    }
    body {
      background-color: #06080d;
      color: #e2e8f0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      padding: env(safe-area-inset-top, 12px) 16px env(safe-area-inset-bottom, 20px) 16px;
      overflow-x: hidden;
    }
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 4px 14px 4px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.1);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .brand-logo {
      width: 28px;
      height: 28px;
      border-radius: 6px;
      background: linear-gradient(135deg, #06b6d4, #0891b2);
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 900;
      font-size: 14px;
      color: #041017;
      box-shadow: 0 0 12px rgba(6, 182, 212, 0.4);
    }
    .brand-title {
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.5px;
      text-transform: uppercase;
      color: #f1f5f9;
    }
    .brand-sub {
      font-size: 10px;
      color: #06b6d4;
      font-weight: 600;
      letter-spacing: 1px;
    }
    .status-badge {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11px;
      font-weight: 500;
      padding: 4px 10px;
      border-radius: 20px;
      background: rgba(15, 23, 42, 0.8);
      border: 1px solid rgba(148, 163, 184, 0.15);
    }
    .status-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background-color: #64748b;
      transition: background-color 0.3s;
    }
    .status-dot.active {
      background-color: #10b981;
      box-shadow: 0 0 8px #10b981;
    }
    .status-dot.paused {
      background-color: #f59e0b;
      box-shadow: 0 0 8px #f59e0b;
    }
    .status-dot.offline {
      background-color: #ef4444;
    }

    /* ── Верхняя навигация по вкладкам: Пульт / Поиск ── */
    .tabs-nav {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 12px;
      background: #090e18;
      padding: 4px;
      border-radius: 12px;
      border: 1px solid rgba(148, 163, 184, 0.12);
    }
    .tab-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 9px 12px;
      border: none;
      background: transparent;
      color: #94a3b8;
      font-size: 13px;
      font-weight: 600;
      border-radius: 8px;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .tab-btn.active {
      background: #111a2d;
      color: #22d3ee;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
      border: 1px solid rgba(6, 182, 212, 0.25);
    }
    .tab-btn svg {
      width: 16px;
      height: 16px;
    }

    /* ── Вкладка: ПУЛЬТ ДУ ── */
    .media-card {
      margin-top: 14px;
      padding: 16px;
      background: #0c121e;
      border: 1px solid rgba(6, 182, 212, 0.2);
      border-radius: 14px;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
    }
    .media-title {
      font-size: 14px;
      font-weight: 600;
      line-height: 1.4;
      color: #f8fafc;
      overflow: hidden;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      min-height: 20px;
      word-break: break-word;
    }
    .media-empty {
      font-size: 13px;
      color: #64748b;
      text-align: center;
      padding: 8px 0;
    }
    .seek-container {
      margin-top: 14px;
    }
    .seek-slider {
      -webkit-appearance: none;
      appearance: none;
      width: 100%;
      height: 8px;
      border-radius: 4px;
      background: #1e293b;
      outline: none;
    }
    .seek-slider::-webkit-slider-thumb {
      -webkit-appearance: none;
      appearance: none;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: #22d3ee;
      box-shadow: 0 0 10px rgba(34, 211, 238, 0.7);
      cursor: pointer;
    }
    .time-row {
      display: flex;
      justify-content: space-between;
      margin-top: 8px;
      font-size: 12px;
      color: #94a3b8;
      font-variant-numeric: tabular-nums;
    }

    /* Кнопки воспроизведения */
    .controls-grid {
      margin-top: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .primary-row {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 16px;
    }
    .btn {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      border: none;
      outline: none;
      background: #111a2c;
      color: #f1f5f9;
      border-radius: 12px;
      border: 1px solid rgba(148, 163, 184, 0.15);
      font-weight: 600;
      transition: all 0.1s ease;
      cursor: pointer;
    }
    .btn:active {
      transform: scale(0.94);
      background: #18243d;
      border-color: #06b6d4;
    }
    .btn-step {
      width: 68px;
      height: 60px;
      font-size: 13px;
      gap: 3px;
    }
    .btn-step svg {
      width: 20px;
      height: 20px;
    }
    .btn-step span {
      font-size: 10px;
      color: #94a3b8;
    }
    .btn-play {
      width: 80px;
      height: 80px;
      border-radius: 50%;
      background: linear-gradient(135deg, #06b6d4, #0284c7);
      color: #03131e;
      border: 2px solid rgba(255, 255, 255, 0.3);
      box-shadow: 0 0 25px rgba(6, 182, 212, 0.5);
    }
    .btn-play svg {
      width: 36px;
      height: 36px;
    }
    .btn-play:active {
      transform: scale(0.92);
      box-shadow: 0 0 35px rgba(6, 182, 212, 0.8);
    }
    .action-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .btn-action {
      height: 46px;
      flex-direction: row;
      gap: 8px;
      font-size: 13px;
      background: #0f172a;
    }
    .btn-next {
      background: linear-gradient(135deg, rgba(6, 182, 212, 0.15), rgba(14, 165, 233, 0.05));
      border-color: rgba(6, 182, 212, 0.4);
      color: #38bdf8;
    }
    .btn-stop {
      color: #fb7185;
      background: rgba(244, 63, 94, 0.08);
      border-color: rgba(244, 63, 94, 0.25);
    }
    .mode-row {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 8px;
    }
    .btn-header-restore {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      background: rgba(6, 182, 212, 0.12);
      border: 1px solid rgba(6, 182, 212, 0.35);
      color: #38bdf8;
      border-radius: 8px;
      padding: 5px 9px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      font-family: inherit;
      transition: all 0.2s ease;
    }
    .btn-header-restore:active {
      transform: scale(0.94);
      background: rgba(6, 182, 212, 0.25);
    }
    .btn-mode {
      height: 42px;
      flex-direction: row;
      gap: 8px;
      font-size: 12px;
      background: #0b111e;
    }
    .btn-mode.active-mode {
      background: rgba(6, 182, 212, 0.2);
      border-color: #06b6d4;
      color: #22d3ee;
    }

    /* Громкость */
    .volume-card {
      margin-top: 14px;
      padding: 14px 16px;
      background: #0c121e;
      border: 1px solid rgba(148, 163, 184, 0.12);
      border-radius: 14px;
    }
    .volume-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 10px;
      font-size: 12px;
      color: #94a3b8;
    }
    .volume-controls {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .btn-vol-mute {
      width: 42px;
      height: 42px;
      border-radius: 10px;
      background: #131c2e;
    }
    .vol-slider {
      flex: 1;
      -webkit-appearance: none;
      appearance: none;
      height: 6px;
      border-radius: 3px;
      background: #1e293b;
      outline: none;
    }
    .vol-slider::-webkit-slider-thumb {
      -webkit-appearance: none;
      appearance: none;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: #38bdf8;
      cursor: pointer;
    }

    /* Выбор дорожек */
    .tracks-section {
      margin-top: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .track-group {
      background: #0c121e;
      border: 1px solid rgba(148, 163, 184, 0.12);
      border-radius: 12px;
      padding: 10px 14px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .track-label {
      font-size: 11px;
      font-weight: 600;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .track-select {
      width: 100%;
      background: #131c2e;
      color: #e2e8f0;
      border: 1px solid rgba(148, 163, 184, 0.2);
      border-radius: 8px;
      padding: 9px 12px;
      font-size: 13px;
      outline: none;
    }

    /* ── Вкладка: ПОИСК РАЗДАЧ ── */
    .search-panel {
      margin-top: 14px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .search-form {
      display: flex;
      gap: 8px;
    }
    .search-input-wrap {
      position: relative;
      flex: 1;
      display: flex;
      align-items: center;
    }
    .search-icon {
      position: absolute;
      left: 12px;
      color: #64748b;
      pointer-events: none;
    }
    .search-input {
      width: 100%;
      height: 46px;
      background: #0d1424;
      border: 1px solid rgba(148, 163, 184, 0.2);
      border-radius: 12px;
      padding: 0 38px 0 38px;
      color: #f1f5f9;
      font-size: 14px;
      outline: none;
      user-select: auto;
      -webkit-user-select: auto;
    }
    .search-input:focus {
      border-color: #06b6d4;
      box-shadow: 0 0 12px rgba(6, 182, 212, 0.2);
    }
    .search-clear {
      position: absolute;
      right: 12px;
      background: none;
      border: none;
      color: #94a3b8;
      font-size: 14px;
      padding: 4px;
      cursor: pointer;
    }
    .btn-search {
      height: 46px;
      padding: 0 16px;
      background: linear-gradient(135deg, #06b6d4, #0891b2);
      color: #02121e;
      font-weight: 700;
      font-size: 13px;
      border: none;
      border-radius: 12px;
      cursor: pointer;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .btn-search:active {
      transform: scale(0.96);
    }
    .search-meta-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 12px;
      color: #94a3b8;
      padding: 0 4px;
    }
    .search-results {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .search-placeholder {
      text-align: center;
      padding: 40px 16px;
      color: #64748b;
    }
    .placeholder-icon {
      font-size: 36px;
      margin-bottom: 12px;
    }
    .placeholder-title {
      font-size: 15px;
      font-weight: 600;
      color: #e2e8f0;
      margin-bottom: 6px;
    }
    .placeholder-sub {
      font-size: 12px;
      line-height: 1.5;
      max-width: 280px;
      margin: 0 auto;
    }

    /* Карточка найденного торрента */
    .torrent-card {
      background: #0d1424;
      border: 1px solid rgba(148, 163, 184, 0.15);
      border-radius: 14px;
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      transition: border-color 0.15s;
    }
    .torrent-title {
      font-size: 13px;
      font-weight: 600;
      color: #f1f5f9;
      line-height: 1.4;
      word-break: break-word;
    }
    .torrent-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .tag {
      font-size: 10px;
      font-weight: 600;
      padding: 3px 7px;
      border-radius: 6px;
      letter-spacing: 0.3px;
    }
    .tag-quality {
      background: rgba(6, 182, 212, 0.18);
      color: #22d3ee;
      border: 1px solid rgba(6, 182, 212, 0.3);
    }
    .tag-seeders {
      background: rgba(16, 185, 129, 0.15);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .tag-size {
      background: #1e293b;
      color: #cbd5e1;
    }
    .tag-source {
      background: #172033;
      color: #94a3b8;
    }

    .torrent-actions {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
    }
    .btn-play-torrent {
      height: 40px;
      background: linear-gradient(135deg, #06b6d4, #0284c7);
      color: #03131e;
      font-weight: 700;
      font-size: 13px;
      border: none;
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      cursor: pointer;
    }
    .btn-play-torrent:active {
      transform: scale(0.97);
    }
    .btn-episodes-toggle {
      height: 40px;
      padding: 0 12px;
      background: #172338;
      color: #38bdf8;
      border: 1px solid rgba(56, 189, 248, 0.3);
      border-radius: 10px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
    }

    /* Выпадающий список серий для сериалов */
    .episodes-drawer {
      margin-top: 6px;
      padding-top: 10px;
      border-top: 1px dashed rgba(148, 163, 184, 0.2);
      display: flex;
      flex-direction: column;
      gap: 6px;
      max-height: 220px;
      overflow-y: auto;
    }
    .ep-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 8px 10px;
      background: #131d2e;
      border-radius: 8px;
      font-size: 12px;
      cursor: pointer;
    }
    .ep-item:active {
      background: rgba(6, 182, 212, 0.25);
    }
    .ep-name {
      color: #f1f5f9;
      truncate;
      max-width: 220px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .ep-btn-play {
      font-size: 11px;
      font-weight: 600;
      color: #22d3ee;
      background: rgba(6, 182, 212, 0.15);
      padding: 3px 8px;
      border-radius: 6px;
      border: 1px solid rgba(6, 182, 212, 0.3);
    }

    /* Подвал */
    .footer {
      margin-top: auto;
      padding-top: 24px;
      text-align: center;
      font-size: 11px;
      color: #475569;
    }
  </style>
</head>
<body>
  <!-- Header -->
  <header class="header">
    <div class="brand">
      <div class="brand-logo">PC</div>
      <div>
        <div class="brand-title">Pirate Cinema</div>
        <div class="brand-sub">Локальный пульт</div>
      </div>
    </div>
    <div style="display:flex; align-items:center; gap:8px;">
      <button class="btn-header-restore" id="btnHeaderRestore" onclick="restoreAppWindow()" title="Развернуть окно приложения на ПК">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="3" width="20" height="14" rx="2"></rect>
          <line x1="8" y1="21" x2="16" y2="21"></line>
          <line x1="12" y1="17" x2="12" y2="21"></line>
        </svg>
        <span>Окно ПК</span>
      </button>
      <div id="statusBadge" class="status-badge">
        <div id="statusDot" class="status-dot"></div>
        <span id="statusText">Поиск...</span>
      </div>
    </div>
  </header>

  <!-- Навигация по вкладкам: Пульт / Поиск раздач -->
  <nav class="tabs-nav">
    <button class="tab-btn active" id="tabRemoteBtn" onclick="switchTab('remote')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="5" y="2" width="14" height="20" rx="3"></rect>
        <circle cx="12" cy="18" r="1.5"></circle>
        <line x1="9" y1="6" x2="15" y2="6"></line>
      </svg>
      <span>Пульт ДУ</span>
    </button>
    <button class="tab-btn" id="tabSearchBtn" onclick="switchTab('search')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="8"></circle>
        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
      </svg>
      <span>Поиск раздач</span>
    </button>
  </nav>

  <!-- ════════ ВКЛАДКА 1: ПУЛЬТ ДИСТАНЦИОННОГО УПРАВЛЕНИЯ ════════ -->
  <div id="panelRemote">
    <!-- Current Media Card -->
    <section class="media-card">
      <div id="mediaTitle" class="media-title">
        <div class="media-empty">Ничего не воспроизводится</div>
      </div>
      <div class="seek-container">
        <input type="range" id="seekSlider" class="seek-slider" min="0" max="100" value="0" step="1">
        <div class="time-row">
          <span id="curTime">00:00</span>
          <span id="durTime">00:00</span>
        </div>
      </div>
    </section>

    <!-- Controls Grid -->
    <main class="controls-grid">
      <!-- Row 1: -10s, Play/Pause, +10s -->
      <div class="primary-row">
        <button class="btn btn-step" id="btnRewind" title="Назад 10с" onclick="seekRel(-10)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="11 19 2 12 11 5 11 19"></polygon>
            <polygon points="22 19 13 12 22 5 22 19"></polygon>
          </svg>
          <span>-10 сек</span>
        </button>

        <button class="btn btn-play" id="btnPlayPause" onclick="togglePlayPause()">
          <svg id="iconPlay" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
          </svg>
          <svg id="iconPause" style="display:none;" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="4" width="4" height="16"></rect>
            <rect x="14" y="4" width="4" height="16"></rect>
          </svg>
        </button>

        <button class="btn btn-step" id="btnForward" title="Вперед 10с" onclick="seekRel(10)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="13 19 22 12 13 5 13 19"></polygon>
            <polygon points="2 19 11 12 2 5 2 19"></polygon>
          </svg>
          <span>+10 сек</span>
        </button>
      </div>

      <!-- Row 2: Next Episode & Stop -->
      <div class="action-row">
        <button class="btn btn-action btn-next" id="btnNext" onclick="nextEpisode()">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="5 4 15 12 5 20 5 4"></polygon>
            <line x1="19" y1="5" x2="19" y2="19"></line>
          </svg>
          <span>Следующая серия</span>
        </button>

        <button class="btn btn-action btn-stop" id="btnStop" onclick="stopPlayer()">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <rect x="5" y="5" width="14" height="14" rx="2"></rect>
          </svg>
          <span>Остановить</span>
        </button>
      </div>

      <!-- Row 3: Mode Toggles: Fullscreen, PiP, Restore -->
      <div class="mode-row">
        <button class="btn btn-mode" id="btnFullscreen" onclick="toggleFullscreen()" title="Полноэкранный режим на ПК">
          <svg id="iconFs" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 3 21 3 21 9"></polyline>
            <polyline points="9 21 3 21 3 15"></polyline>
            <line x1="21" y1="3" x2="14" y2="10"></line>
            <line x1="3" y1="21" x2="10" y2="14"></line>
          </svg>
          <span id="labelFs">Экран</span>
        </button>

        <button class="btn btn-mode" id="btnPip" onclick="togglePip()">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2"></rect>
            <rect x="11" y="9" width="9" height="6" rx="1" fill="currentColor" fill-opacity="0.3"></rect>
          </svg>
          <span id="labelPip">Мини (PiP)</span>
        </button>

        <button class="btn btn-mode" id="btnRestoreWin" onclick="restoreAppWindow()">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2"></rect>
            <path d="M8 21h8"></path>
            <path d="M12 17v4"></path>
          </svg>
          <span>Окно ПК</span>
        </button>
      </div>
    </main>

    <!-- Volume Card -->
    <section class="volume-card">
      <div class="volume-header">
        <span>Громкость</span>
        <span id="volLevel">100%</span>
      </div>
      <div class="volume-controls">
        <button class="btn btn-vol-mute" id="btnMute" onclick="toggleMute()">
          <svg id="iconVolHigh" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
            <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path>
          </svg>
          <svg id="iconVolMute" style="display:none;" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f43f5e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
            <line x1="23" y1="9" x2="17" y2="15"></line>
            <line x1="17" y1="9" x2="23" y2="15"></line>
          </svg>
        </button>
        <input type="range" id="volSlider" class="vol-slider" min="0" max="100" value="100" step="1" oninput="onVolSliderChange(this.value)">
      </div>
    </section>

    <!-- Tracks Section (Audio & Subs) -->
    <section class="tracks-section" id="tracksSection" style="display:none;">
      <div class="track-group">
        <label class="track-label" for="audioSelect">Аудиодорожка (озвучка)</label>
        <select id="audioSelect" class="track-select" onchange="onAudioChange(this.value)">
          <option value="">По умолчанию</option>
        </select>
      </div>

      <div class="track-group">
        <label class="track-label" for="subSelect">Субтитры</label>
        <select id="subSelect" class="track-select" onchange="onSubChange(this.value)">
          <option value="no">Выключены</option>
        </select>
      </div>
    </section>
  </div>

  <!-- ════════ ВКЛАДКА 2: ПОИСК РАЗДАЧ И ЗАПУСК НА ПК ════════ -->
  <div id="panelSearch" class="search-panel" style="display:none;">
    <form class="search-form" onsubmit="event.preventDefault(); doSearch();">
      <div class="search-input-wrap">
        <svg class="search-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"></circle>
          <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
        </svg>
        <input type="search" id="searchInput" class="search-input" placeholder="Фильм, сериал, аниме..." enterkeyhint="search" autocapitalize="none">
        <button type="button" id="searchClear" class="search-clear" onclick="clearSearch()" style="display:none;">✕</button>
      </div>
      <button type="submit" class="btn-search" id="btnSearchSubmit">Найти</button>
    </form>

    <div class="search-meta-bar" id="searchMetaBar" style="display:none;">
      <span id="searchStatusText">Найдено раздач: 0</span>
    </div>

    <div class="search-results" id="searchResults">
      <div class="search-placeholder">
        <div class="placeholder-icon">🔍</div>
        <div class="placeholder-title">Поиск торрент-раздач с ПК</div>
        <div class="placeholder-sub">Найдите фильм или сериал на телефоне и запустите просмотр на экране компьютера в один клик.</div>
      </div>
    </div>
  </div>

  <!-- Footer -->
  <footer class="footer">
    <span>Управление воспроизведением ПК по Wi-Fi</span>
  </footer>

  <script>
    let activeState = null;
    let isSeeking = false;
    let lastKnownAid = null;
    let lastKnownSid = null;
    let lastTrackListJson = "";
    let currentTab = "remote";
    let isSearching = false;

    function vibrate() {
      if (navigator.vibrate) {
        try { navigator.vibrate(25); } catch(e) {}
      }
    }

    function switchTab(tab, updateHist = true) {
      currentTab = tab;
      vibrate();
      const isRemote = tab === "remote";
      document.getElementById('panelRemote').style.display = isRemote ? "block" : "none";
      document.getElementById('panelSearch').style.display = isRemote ? "none" : "flex";
      document.getElementById('tabRemoteBtn').className = "tab-btn " + (isRemote ? "active" : "");
      document.getElementById('tabSearchBtn').className = "tab-btn " + (!isRemote ? "active" : "");
      if (!isRemote) {
        const inp = document.getElementById('searchInput');
        if (!inp.value) setTimeout(() => inp.focus(), 100);
      }
      if (updateHist) {
        pushRemoteState({ tab: tab });
      }
    }

    function formatTime(seconds) {
      if (!seconds || isNaN(seconds) || seconds < 0) return "00:00";
      const s = Math.floor(seconds);
      const m = Math.floor(s / 60);
      const h = Math.floor(m / 60);
      const remSec = s % 60;
      const remMin = m % 60;
      const pad = (n) => (n < 10 ? "0" + n : n);
      if (h > 0) return `${h}:${pad(remMin)}:${pad(remSec)}`;
      return `${pad(remMin)}:${pad(remSec)}`;
    }

    function formatSize(bytes) {
      if (!bytes || isNaN(bytes)) return "";
      const gb = bytes / (1024 * 1024 * 1024);
      if (gb >= 1) return gb.toFixed(1) + " GB";
      const mb = bytes / (1024 * 1024);
      return mb.toFixed(0) + " MB";
    }

    function escapeHtml(str) {
      if (!str) return "";
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }

    function escapeJs(str) {
      if (!str) return "";
      return String(str).replace(/\\\\/g, "\\\\\\\\").replace(/'/g, "\\\\'").replace(/"/g, '\\\\"');
    }

    async function sendCommand(cmd) {
      vibrate();
      try {
        await fetch('/api/player/command', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(cmd)
        });
      } catch (err) {
        console.error("Command error:", err);
      }
    }

    function togglePlayPause() {
      sendCommand(["cycle", "pause"]);
      if (activeState) {
        activeState.is_paused = !activeState.is_paused;
        updatePlayPauseUI();
      }
    }

    function seekRel(delta) {
      sendCommand(["seek", delta, "relative"]);
      if (activeState && typeof activeState.timecode === 'number') {
        activeState.timecode = Math.max(0, activeState.timecode + delta);
        updateProgressUI();
      }
    }

    function toggleMute() {
      sendCommand(["cycle", "mute"]);
    }

    function onVolSliderChange(val) {
      document.getElementById('volLevel').textContent = val + "%";
      sendCommand(["set_property", "volume", Number(val)]);
    }

    async function nextEpisode() {
      vibrate();
      if (!activeState || !activeState.hash) return;
      try {
        await fetch('/api/player/next', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            hash: activeState.hash,
            file_id: activeState.file_id || 0
          })
        });
      } catch (err) {
        console.error("Next episode error:", err);
      }
    }

    async function stopPlayer() {
      vibrate();
      try {
        await fetch('/api/player/stop', {method: 'POST'});
      } catch (err) {
        console.error("Stop error:", err);
      }
    }

    async function toggleFullscreen(target) {
      vibrate();
      try {
        const hasTarget = typeof target === 'boolean';
        const q = hasTarget ? `?fullscreen=${target}` : '';
        const body = hasTarget ? { fullscreen: target } : {};
        const res = await fetch('/api/player/fullscreen' + q, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(body)
        });
        if (res.ok) {
          const data = await res.json();
          updateFullscreenUI(data.is_fullscreen);
          if (data.is_fullscreen) {
            pushRemoteState({ fs: true });
          }
        }
      } catch (err) {
        console.error("FS error:", err);
      }
    }

    async function togglePip() {
      vibrate();
      try {
        const res = await fetch('/api/window/pip', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({})
        });
        if (res.ok) {
          const data = await res.json();
          updatePipUI(data.is_pip);
        }
      } catch (err) {
        console.error("PiP error:", err);
      }
    }

    async function restoreAppWindow() {
      vibrate();
      try {
        const res = await fetch('/api/window/show', { method: 'POST' });
        if (res.ok) {
          const btn = document.getElementById('btnHeaderRestore');
          if (btn) {
            const orig = btn.innerHTML;
            btn.innerHTML = '<span style="color:#10b981;">✓ Развернуто</span>';
            setTimeout(() => { btn.innerHTML = orig; }, 1500);
          }
        }
      } catch (err) {
        console.error("Restore window error:", err);
      }
    }

    function onAudioChange(aid) {
      if (!aid) return;
      sendCommand(["set_property", "aid", Number(aid)]);
    }

    function onSubChange(sid) {
      if (sid === "no") {
        sendCommand(["set_property", "sid", "no"]);
      } else {
        sendCommand(["set_property", "sid", Number(sid)]);
      }
    }

    function updatePlayPauseUI() {
      const isPaused = activeState ? !!activeState.is_paused : true;
      document.getElementById('iconPlay').style.display = isPaused ? 'block' : 'none';
      document.getElementById('iconPause').style.display = isPaused ? 'none' : 'block';
    }

    function updateFullscreenUI(isFs) {
      const btn = document.getElementById('btnFullscreen');
      const label = document.getElementById('labelFs');
      const icon = document.getElementById('iconFs');
      if (isFs) {
        btn.classList.add('active-mode');
        label.textContent = "Назад в окно";
        btn.title = "Выйти из полноэкранного режима на ПК (Назад)";
        if (icon) {
          icon.innerHTML = '<polyline points="4 14 10 14 10 20"></polyline><polyline points="20 10 14 10 14 4"></polyline><line x1="14" y1="10" x2="21" y2="3"></line><line x1="3" y1="21" x2="10" y2="14"></line>';
        }
      } else {
        btn.classList.remove('active-mode');
        label.textContent = "Экран";
        btn.title = "Полноэкранный режим на ПК";
        if (icon) {
          icon.innerHTML = '<polyline points="15 3 21 3 21 9"></polyline><polyline points="9 21 3 21 3 15"></polyline><line x1="21" y1="3" x2="14" y2="10"></line><line x1="3" y1="21" x2="10" y2="14"></line>';
        }
      }
    }

    function updatePipUI(isPip) {
      const btn = document.getElementById('btnPip');
      const label = document.getElementById('labelPip');
      if (isPip) {
        btn.classList.add('active-mode');
        label.textContent = "Выйти из PiP";
      } else {
        btn.classList.remove('active-mode');
        label.textContent = "Мини-плеер (PiP)";
      }
    }

    function updateProgressUI() {
      if (isSeeking || !activeState) return;
      const tc = activeState.timecode || 0;
      const dur = activeState.duration || 0;
      document.getElementById('curTime').textContent = formatTime(tc);
      document.getElementById('durTime').textContent = formatTime(dur);

      const slider = document.getElementById('seekSlider');
      if (dur > 0) {
        slider.max = dur;
        slider.value = tc;
      }
    }

    function updateTracksUI() {
      if (!activeState || !Array.isArray(activeState.track_list) || activeState.track_list.length === 0) {
        document.getElementById('tracksSection').style.display = 'none';
        return;
      }

      const tracks = activeState.track_list;
      const strTracks = JSON.stringify(tracks);
      const audioSelect = document.getElementById('audioSelect');
      const subSelect = document.getElementById('subSelect');

      if (strTracks !== lastTrackListJson) {
        lastTrackListJson = strTracks;

        const audios = tracks.filter(t => t.type === 'audio');
        if (audios.length > 0) {
          audioSelect.innerHTML = audios.map(a => {
            const title = a.title || a.lang || ('Дорожка ' + a.id);
            return `<option value="${a.id}">${title}</option>`;
          }).join('');
        }

        const subs = tracks.filter(t => t.type === 'sub');
        subSelect.innerHTML = `<option value="no">Выключены</option>` + subs.map(s => {
          const title = s.title || s.lang || ('Субтитры ' + s.id);
          return `<option value="${s.id}">${title}</option>`;
        }).join('');
      }

      if (activeState.audio_track !== undefined && activeState.audio_track !== lastKnownAid) {
        lastKnownAid = activeState.audio_track;
        audioSelect.value = String(activeState.audio_track);
      }
      if (activeState.subtitle_track !== undefined && activeState.subtitle_track !== lastKnownSid) {
        lastKnownSid = activeState.subtitle_track;
        subSelect.value = activeState.subtitle_track ? String(activeState.subtitle_track) : "no";
      }

      document.getElementById('tracksSection').style.display = 'flex';
    }

    // Seek slider events
    const seekSlider = document.getElementById('seekSlider');
    seekSlider.addEventListener('input', (e) => {
      isSeeking = true;
      document.getElementById('curTime').textContent = formatTime(Number(e.target.value));
    });
    seekSlider.addEventListener('change', (e) => {
      if (isSeeking && activeState && activeState.duration > 0) {
        const targetTime = Number(e.target.value);
        sendCommand(["seek", targetTime, "absolute"]);
      }
      isSeeking = false;
    });

    // ── Поиск раздач и запуск на ПК ──
    const searchInput = document.getElementById('searchInput');
    const searchClear = document.getElementById('searchClear');
    searchInput.addEventListener('input', (e) => {
      searchClear.style.display = e.target.value ? 'block' : 'none';
    });

    function clearSearch() {
      searchInput.value = '';
      searchClear.style.display = 'none';
      searchInput.focus();
    }

    async function doSearch() {
      const query = searchInput.value.trim();
      if (!query || isSearching) return;
      vibrate();
      isSearching = true;

      const submitBtn = document.getElementById('btnSearchSubmit');
      const resultsContainer = document.getElementById('searchResults');
      const metaBar = document.getElementById('searchMetaBar');
      const statusText = document.getElementById('searchStatusText');

      submitBtn.textContent = '...';
      metaBar.style.display = 'flex';
      statusText.textContent = `Поиск «${query}»...`;
      resultsContainer.innerHTML = '<div class="search-placeholder"><div class="placeholder-icon">⏳</div><div class="placeholder-title">Поиск торрентов...</div></div>';

      try {
        const res = await fetch('/api/search?q=' + encodeURIComponent(query));
        if (!res.ok) throw new Error('Search failed');
        const items = await res.json();

        if (!items || items.length === 0) {
          statusText.textContent = 'Ничего не найдено';
          resultsContainer.innerHTML = '<div class="search-placeholder"><div class="placeholder-icon">😕</div><div class="placeholder-title">Раздачи не найдены</div><div class="placeholder-sub">Попробуйте изменить поисковый запрос.</div></div>';
        } else {
          statusText.textContent = `Найдено раздач: ${items.length}`;
          resultsContainer.innerHTML = items.map((t, idx) => `
            <div class="torrent-card">
              <div class="torrent-title">${escapeHtml(t.title)}</div>
              <div class="torrent-tags">
                ${t.quality ? `<span class="tag tag-quality">${escapeHtml(t.quality)}</span>` : ''}
                <span class="tag tag-seeders">🟢 ${t.seeders !== undefined && t.seeders !== null ? t.seeders : 0}</span>
                ${t.size ? `<span class="tag tag-size">💾 ${formatSize(t.size)}</span>` : ''}
                ${t.source ? `<span class="tag tag-source">${escapeHtml(t.source)}</span>` : ''}
              </div>
              <div class="torrent-actions">
                <button class="btn-play-torrent" id="btnPlay_${idx}" onclick="launchTorrent('${escapeJs(t.hash || '')}', '${escapeJs(t.magnet || '')}', '${escapeJs(t.title)}', null, null, this)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                  <span>Включить на ПК</span>
                </button>
                <button class="btn-episodes-toggle" onclick="toggleEpisodes(this, '${escapeJs(t.hash || '')}', '${escapeJs(t.title)}', '${escapeJs(t.magnet || '')}')">
                  Серии ▼
                </button>
              </div>
              <div class="episodes-drawer" style="display:none;"></div>
            </div>
          `).join('');
        }
      } catch (err) {
        statusText.textContent = 'Ошибка поиска';
        resultsContainer.innerHTML = '<div class="search-placeholder"><div class="placeholder-icon">⚠️</div><div class="placeholder-title">Ошибка при поиске</div><div class="placeholder-sub">Проверьте работу TorrServer / Jackett.</div></div>';
      } finally {
        isSearching = false;
        submitBtn.textContent = 'Найти';
      }
    }

    async function launchTorrent(hash, magnet, title, file_id, file_name, btnEl) {
      vibrate();
      if (btnEl) {
        btnEl.disabled = true;
        btnEl.innerHTML = '<span>Запуск на ПК...</span>';
      }

      try {
        const res = await fetch('/api/remote/play', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            hash: hash || null,
            magnet: magnet || null,
            title: title || '',
            file_id: file_id !== null && file_id !== undefined ? Number(file_id) : null,
            file_name: file_name || null
          })
        });

        if (res.ok) {
          // Мгновенно переключаем телефон на вкладку пульта
          switchTab('remote');
          // Запрашиваем состояние плеера
          setTimeout(pollState, 300);
        } else {
          alert('Ошибка запуска воспроизведения');
        }
      } catch (err) {
        console.error('Launch error:', err);
        alert('Не удалось отправить команду запуска на ПК');
      } finally {
        if (btnEl) {
          btnEl.disabled = false;
          btnEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><span>Включить на ПК</span>';
        }
      }
    }

    async function toggleEpisodes(btnEl, hash, title, magnet) {
      vibrate();
      const card = btnEl.closest('.torrent-card');
      const drawer = card.querySelector('.episodes-drawer');

      if (drawer.style.display === 'flex') {
        drawer.style.display = 'none';
        btnEl.textContent = 'Серии ▼';
        return;
      }

      drawer.style.display = 'flex';
      btnEl.textContent = 'Скрыть ▲';
      if (drawer.children.length > 0 && !drawer.dataset.pending) return;

      drawer.dataset.pending = "1";
      drawer.innerHTML = '<div style="font-size:11px; color:#38bdf8; text-align:center; padding:10px;"><div class="status-dot active" style="display:inline-block; margin-right:6px;"></div>Подключение к раздаче (DHT)...</div>';

      const url = `/api/library/torrents/${encodeURIComponent(hash)}/files?title=${encodeURIComponent(title || '')}${magnet ? '&magnet=' + encodeURIComponent(magnet) : ''}`;

      for (let attempt = 1; attempt <= 4; attempt++) {
        try {
          const res = await fetch(url);
          if (res.ok) {
            const data = await res.json();
            let epList = [];
            if (data.seasons && Object.keys(data.seasons).length > 0) {
              Object.keys(data.seasons).sort((a,b) => Number(a) - Number(b)).forEach(sKey => {
                (data.seasons[sKey] || []).forEach(f => epList.push(f));
              });
            } else if (data.files && data.files.length > 0) {
              epList = data.files;
            } else if (data.movies && data.movies.length > 0) {
              epList = data.movies;
            }

            if (epList.length > 0) {
              delete drawer.dataset.pending;
              drawer.innerHTML = epList.map(ep => `
                <div class="ep-item" onclick="launchTorrent('${escapeJs(hash)}', '${escapeJs(magnet || '')}', '${escapeJs(title)}', ${ep.id}, '${escapeJs(ep.name)}')">
                  <span class="ep-name" title="${escapeHtml(ep.name)}">${escapeHtml(ep.name)}</span>
                  <span class="ep-btn-play">▶ Включить</span>
                </div>
              `).join('');
              return;
            }
          }
        } catch (err) {
          console.debug('DHT resolve attempt error:', err);
        }

        if (attempt < 4) {
          await new Promise(r => setTimeout(r, 1500));
        }
      }

      delete drawer.dataset.pending;
      drawer.innerHTML = `
        <div style="font-size:11px; color:#94a3b8; text-align:center; padding:10px; line-height:1.5;">
          Раздача еще ищет сидов в DHT.<br>
          <button style="margin-top:6px; background:#06b6d4; color:#03131e; border:none; padding:4px 10px; border-radius:6px; font-weight:600; font-size:11px; cursor:pointer;" onclick="launchTorrent('${escapeJs(hash)}', '${escapeJs(magnet || '')}', '${escapeJs(title)}', null, null)">
            ▶ Включить напрямую на ПК
          </button>
        </div>
      `;
    }

    // Main poll loop for remote tab
    async function pollState() {
      try {
        const [playerRes, winRes] = await Promise.all([
          fetch('/api/player/active'),
          fetch('/api/window/state').catch(() => null)
        ]);

        if (playerRes.ok) {
          const data = await playerRes.json();
          activeState = data;

          const dot = document.getElementById('statusDot');
          const statusText = document.getElementById('statusText');
          const titleEl = document.getElementById('mediaTitle');

          if (data && data.active) {
            dot.className = 'status-dot ' + (data.is_paused ? 'paused' : 'active');
            statusText.textContent = data.is_paused ? 'Пауза' : 'Воспроизведение';
            titleEl.textContent = data.file_name || 'Воспроизведение...';
            updatePlayPauseUI();
            updateProgressUI();
            updateTracksUI();

            if (data.volume !== undefined && document.getElementById('volSlider') !== document.activeElement) {
              document.getElementById('volSlider').value = data.volume;
              document.getElementById('volLevel').textContent = data.volume + "%";
            }
          } else {
            dot.className = 'status-dot';
            statusText.textContent = 'Ожидание';
            titleEl.innerHTML = '<div class="media-empty">Ничего не воспроизводится</div>';
            document.getElementById('tracksSection').style.display = 'none';
          }

          if (typeof data.is_fullscreen === 'boolean') {
            updateFullscreenUI(data.is_fullscreen);
          }
        }

        if (winRes && winRes.ok) {
          const winData = await winRes.json();
          if (typeof winData.is_pip === 'boolean') {
            updatePipUI(winData.is_pip);
          }
        }
      } catch (err) {
        const dot = document.getElementById('statusDot');
        const statusText = document.getElementById('statusText');
        dot.className = 'status-dot offline';
        statusText.textContent = 'Офлайн';
      }
    }

    // ── Обработка аппаратной кнопки / свайпа "Назад" на телефоне (Android/iOS) ──
    function pushRemoteState(extra) {
      try {
        window.history.pushState(Object.assign({ pc_remote: true, ts: Date.now() }, extra || {}), '');
      } catch(e) {}
    }

    function initMobileHistory() {
      try {
        window.history.replaceState({ pc_remote: true, base: true }, '');
        pushRemoteState({ base: false });
      } catch(e) {}

      window.addEventListener('popstate', async (e) => {
        // 1. Если на телефоне открыт выпадающий список серий в поиске — закрываем его
        const openDrawers = document.querySelectorAll('.episodes-drawer');
        let drawerClosed = false;
        openDrawers.forEach(d => {
          if (d.style.display !== 'none') {
            d.style.display = 'none';
            drawerClosed = true;
          }
        });
        if (drawerClosed) {
          pushRemoteState();
          return;
        }

        // 2. Если на ПК включен полный экран — выходим из него по нажатию "Назад" на телефоне!
        const btnFs = document.getElementById('btnFullscreen');
        const isFs = btnFs && btnFs.classList.contains('active-mode');
        if (isFs) {
          await toggleFullscreen(false);
          pushRemoteState();
          return;
        }

        // 3. Если открыта вкладка "Поиск раздач" — возвращаемся на пульт
        if (currentTab === 'search') {
          switchTab('remote', false);
          pushRemoteState();
          return;
        }

        // 4. Если включен PiP мини-плеер — выходим из PiP
        const btnPip = document.getElementById('btnPip');
        const isPip = btnPip && btnPip.classList.contains('active-mode');
        if (isPip) {
          await togglePip();
          pushRemoteState();
          return;
        }

        // 5. Защита от случайного закрытия веб-пульта на смартфоне
        pushRemoteState();
      });
    }

    initMobileHistory();
    setInterval(pollState, 750);
    pollState();
  </script>
</body>
</html>
"""
