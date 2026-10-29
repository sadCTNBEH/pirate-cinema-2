"""Mobile cinematic web remote template for smartphone control and torrent search."""

REMOTE_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>Pirate Cinema Remote</title>
  <meta name="apple-mobile-web-app-title" content="Pirate Cinema Remote">
  <meta name="application-name" content="Pirate Cinema Remote">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="theme-color" content="#090b10">
  <link rel="icon" type="image/png" href="/logo.png">
  <link rel="apple-touch-icon" href="/logo.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/logo.png">
  <link rel="apple-touch-icon-precomposed" href="/logo.png">
  <link rel="manifest" href="/remote.webmanifest">
  <style>

    :root { color-scheme:dark; --film-bg:#090b10; --film-surface:#141820; --film-hover:#202630; --film-text:#f3f4f6; --film-muted:#a7adb8; --film-accent:#8dd9e8; --film-line:#292e38; }
    * { box-sizing:border-box; margin:0; padding:0; -webkit-tap-highlight-color:transparent; }
    body { background:var(--film-bg); color:var(--film-text); font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; min-height:100svh; max-width:560px; margin:auto; display:flex; flex-direction:column; padding:calc(16px + env(safe-area-inset-top)) 24px calc(24px + env(safe-area-inset-bottom)); }
    ::selection { background:var(--film-accent); color:var(--film-bg); }
    button,input,select { font:inherit; }
    button { cursor:pointer; touch-action:manipulation; }
    button:disabled,input:disabled,select:disabled { opacity:.4; cursor:default; }
    button:focus-visible,input:focus-visible,select:focus-visible { outline:2px solid var(--film-accent); outline-offset:4px; }
    button:active { opacity:.8; }
    [hidden] { display:none !important; }
    .header,.brand,.status-badge { display:flex; align-items:center; }
    .header { justify-content:space-between; gap:12px; padding:0 0 24px; }
    .brand { gap:10px; min-width:0; }
    .brand-logo { width:32px; height:32px; object-fit:contain; border-radius:6px; }
    .brand-title { font-size:14px; font-weight:600; letter-spacing:-.02em; white-space:nowrap; }
    .brand-sub { font-size:11px; color:var(--film-muted); margin-top:3px; }
    .btn-header-restore { display:none; }
    .status-badge { gap:6px; font-size:11px; color:var(--film-muted); white-space:nowrap; }
    .status-dot { width:6px; height:6px; flex-shrink:0; background:var(--film-muted); border-radius:50%; }
    .status-dot.active { background:#99c8ae; }
    .status-dot.paused { background:#e4c28c; }
    .status-dot.offline { background:#f1a4a9; }
    .tabs-nav { display:grid; grid-template-columns:1fr 1fr; border-bottom:1px solid var(--film-line); }
    .tab-btn { display:flex; align-items:center; justify-content:center; gap:8px; min-height:48px; border:0; border-bottom:2px solid transparent; background:transparent; color:var(--film-muted); font-size:14px; }
    .tab-btn.active { color:var(--film-text); border-bottom-color:var(--film-text); }
    .tab-btn svg { width:17px; height:17px; }
    #panelRemote { display:flex; flex-direction:column; min-height:calc(100svh - 148px - env(safe-area-inset-top) - env(safe-area-inset-bottom)); }
    .media-card { padding:32px 0 12px; }
    .media-title { min-height:64px; font-size:24px; font-weight:600; line-height:1.3; letter-spacing:-.025em; overflow-wrap:anywhere; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
    .media-empty { color:var(--film-muted); font-size:18px; line-height:1.5; font-weight:400; }
    .seek-container { margin-top:20px; }
    input[type=range] { appearance:none; -webkit-appearance:none; width:100%; min-width:0; height:44px; background:transparent; touch-action:pan-y; cursor:pointer; accent-color:var(--film-text); }
    input[type=range]::-webkit-slider-runnable-track { height:4px; border-radius:2px; background:var(--film-line); }
    input[type=range]::-webkit-slider-thumb { appearance:none; -webkit-appearance:none; width:18px; height:18px; margin-top:-7px; background:var(--film-text); border:0; border-radius:50%; }
    input[type=range]::-moz-range-track { height:4px; background:var(--film-line); border-radius:2px; }
    input[type=range]::-moz-range-thumb { width:18px; height:18px; background:var(--film-text); border:0; border-radius:50%; }
    .time-row { display:flex; justify-content:space-between; color:var(--film-muted); font-size:12px; font-variant-numeric:tabular-nums; }
    #seekPreview { height:20px; text-align:center; font-size:12px; color:var(--film-accent); font-variant-numeric:tabular-nums; }
    .controls-grid { order:3; display:flex; flex-direction:column; gap:24px; margin-top:auto; padding:28px 0 24px; }
    .primary-row { display:flex; align-items:center; justify-content:center; gap:28px; }
    .btn { display:flex; align-items:center; justify-content:center; flex-direction:column; gap:6px; border:0; border-radius:6px; color:var(--film-text); background:var(--film-surface); min-height:48px; font-size:13px; }
    .btn:hover { background:var(--film-hover); }
    .btn svg { width:20px; height:20px; flex-shrink:0; }
    .btn-step { width:64px; height:64px; background:transparent; color:var(--film-muted); }
    .btn-step span { font-size:11px; }
    .btn-play { width:88px; height:88px; flex-shrink:0; border-radius:50%; background:var(--film-text); color:var(--film-bg); }
    .btn-play svg { width:32px; height:32px; }
    .btn-play:hover { background:#d9edf1; }
    .action-row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .btn-action,.btn-mode { flex-direction:row; gap:8px; padding:12px; }
    .btn-next { color:var(--film-accent); }
    .btn-stop { width:100%; color:#f1a4a9; background:#25191e; }
    .mode-row { display:flex; flex-direction:column; gap:8px; }
    .active-mode,.sheet button[aria-pressed=true] { background:var(--film-hover); color:var(--film-accent); }
    .volume-card { order:4; padding:20px 0 0; border-top:1px solid var(--film-line); }
    .volume-header { display:flex; justify-content:space-between; color:var(--film-muted); font-size:12px; margin-bottom:8px; font-variant-numeric:tabular-nums; }
    .volume-controls { display:flex; align-items:center; gap:6px; }
    .btn-vol-mute,.volume-step { width:44px; min-height:44px; flex-shrink:0; background:transparent; font-size:20px; }
    .tracks-section { order:2; display:flex; flex-direction:column; gap:14px; margin:12px 0; }
    .track-group { display:flex; flex-direction:column; gap:8px; }
    .track-label { font-size:12px; color:var(--film-muted); }
    .track-select { min-height:48px; width:100%; padding:10px 12px; color:var(--film-text); background:var(--film-surface); border:1px solid var(--film-line); border-radius:6px; font-size:13px; }
    .sheet { background:var(--film-surface); color:var(--film-text); border:0; border-top:1px solid var(--film-line); border-radius:16px 16px 0 0; width:min(100%,560px); max-height:85svh; padding:24px 24px calc(24px + env(safe-area-inset-bottom)); margin:auto auto 0; }
    .sheet::backdrop { background:#0009; }
    .sheet-heading { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:20px; }
    .sheet-heading h2 { font-size:20px; font-weight:600; letter-spacing:-.02em; }
    .sheet-close { width:44px; min-height:44px; font-size:24px; background:transparent; }
    .episode-list { display:flex; flex-direction:column; gap:8px; }
    .episode-list h3 { font-size:13px; color:var(--film-muted); padding:12px 0 4px; }
    .episode-choice { min-height:52px; width:100%; text-align:left; padding:12px; color:inherit; border:1px solid var(--film-line); border-radius:6px; background:transparent; overflow-wrap:anywhere; }
    .episode-choice[aria-current=true] { border-color:var(--film-accent); }
    .episode-choice small { display:block; color:var(--film-accent); margin-top:6px; }
    .search-panel { flex-direction:column; gap:20px; padding-top:24px; flex:1; }
    .search-form { display:flex; gap:8px; }
    .search-input-wrap { display:flex; align-items:center; position:relative; flex:1; min-width:0; }
    .search-icon { position:absolute; left:12px; color:var(--film-muted); pointer-events:none; }
    .search-input { min-height:48px; width:100%; min-width:0; background:var(--film-surface); border:1px solid var(--film-line); border-radius:6px; padding:12px 38px; color:var(--film-text); font-size:14px; caret-color:var(--film-accent); }
    .search-input::placeholder { color:var(--film-muted); }
    .search-clear { position:absolute; right:0; min-width:44px; min-height:44px; border:0; background:transparent; color:var(--film-muted); }
    .btn-search,.btn-play-torrent { min-height:48px; padding:12px 16px; border:0; border-radius:6px; background:var(--film-text); color:var(--film-bg); font-size:13px; font-weight:600; }
    .search-meta-bar { display:flex; justify-content:space-between; color:var(--film-muted); font-size:12px; }
    .search-results { display:flex; flex-direction:column; gap:0; }
    .search-placeholder { text-align:center; padding:48px 8px; color:var(--film-muted); }
    .placeholder-icon { margin:0 auto 20px; width:36px; height:36px; color:var(--film-muted); }
    .placeholder-icon svg { width:100%; height:100%; }
    .placeholder-title { font-size:18px; font-weight:500; color:var(--film-text); margin-bottom:10px; line-height:1.4; }
    .placeholder-sub { font-size:13px; line-height:1.7; max-width:280px; margin:auto; }
    .torrent-card { display:flex; flex-direction:column; gap:14px; padding:20px 0; border-bottom:1px solid var(--film-line); }
    .torrent-title { font-size:15px; line-height:1.5; overflow-wrap:anywhere; font-weight:500; }
    .torrent-tags { display:flex; flex-wrap:wrap; gap:8px 12px; }
    .tag { color:var(--film-muted); font-size:11px; }
    .tag-quality { color:var(--film-accent); }
    .tag-seeders { color:#99c8ae; }
    .torrent-actions { display:grid; grid-template-columns:1fr auto; gap:8px; }
    .btn-play-torrent { display:flex; justify-content:center; align-items:center; gap:8px; }
    .btn-episodes-toggle { min-height:48px; padding:12px; background:var(--film-surface); color:var(--film-text); border:0; border-radius:6px; font-size:13px; }
    .episodes-drawer { display:flex; flex-direction:column; gap:8px; max-height:260px; overflow-y:auto; }
    .ep-item { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px; background:var(--film-surface); border-radius:6px; min-height:48px; font-size:12px; }
    .ep-name { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .ep-btn-play { color:var(--film-accent); white-space:nowrap; }
    .mini-player { position:sticky; bottom:env(safe-area-inset-bottom,0px); background:var(--film-surface); border:1px solid var(--film-line); border-radius:12px; display:flex; align-items:center; gap:12px; padding:8px; margin-top:20px; z-index:10; }
    .mini-title { flex:1; min-width:0; text-align:left; background:transparent; color:inherit; border:0; padding:8px; min-height:48px; }
    .mini-title span { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:13px; }
    .mini-title small { display:block; color:var(--film-muted); margin-top:4px; }
    .mini-player .btn { width:48px; height:48px; background:var(--film-hover); }
    #feedback { position:fixed; bottom:calc(20px + env(safe-area-inset-bottom)); left:16px; right:16px; max-width:528px; margin:auto; background:#25191e; border:1px solid #56323b; color:#f8c9cd; padding:16px; border-radius:12px; z-index:30; font-size:13px; line-height:1.5; }
    .footer { display:none; }
    @media(max-width:360px) { body { padding-inline:16px; } .brand-title { font-size:13px; } .status-badge { font-size:10px; } .primary-row { gap:20px; } }
    @media(max-height:640px) { #panelRemote { min-height:0; } .media-card { padding-top:24px; } .controls-grid { padding-top:24px; } }
  </style>
</head>
<body>
  <!-- Header -->
  <header class="header">
    <div class="brand">
      <img class="brand-logo" src="/logo.png" alt="">
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
        <span id="statusText" role="status">Подключение…</span>
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
        <input type="range" id="seekSlider" class="seek-slider" min="0" max="100" value="0" step="1" aria-label="Позиция воспроизведения">
        <div id="seekPreview" aria-live="off"></div>
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

        <button class="btn btn-play" id="btnPlayPause" aria-label="Воспроизвести" onclick="togglePlayPause()">
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

        <button class="btn btn-action" id="btnEpisodes" onclick="openEpisodes()" hidden>
          <span id="episodeLabel">Серии</span>
        </button>
      </div>

      <!-- Row 3: Mode Toggles: Fullscreen, PiP, Restore -->
      <div class="mode-row">
        <button class="btn btn-mode" onclick="openSheet('screenSheet')">Экран</button>
        <button class="btn btn-mode" onclick="openSheet('moreSheet')">Ещё</button>
      </div>
    </main>

    <dialog class="sheet" id="screenSheet" aria-labelledby="screenTitle">
      <div class="sheet-heading"><h2 id="screenTitle">Экран компьютера</h2><button class="btn sheet-close" aria-label="Закрыть" onclick="closeSheet('screenSheet')">×</button></div>
      <div class="mode-row">
        <button class="btn btn-mode" id="btnNormal" onclick="setScreenMode('normal')">Обычное окно</button>
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
    </dialog>

    <dialog class="sheet" id="moreSheet" aria-labelledby="moreTitle">
      <div class="sheet-heading"><h2 id="moreTitle">Дополнительно</h2><button class="btn sheet-close" aria-label="Закрыть" onclick="closeSheet('moreSheet')">×</button></div>
      <button class="btn btn-stop" id="btnStop" onclick="stopPlayer()">Остановить просмотр</button>
    </dialog>
    <dialog class="sheet" id="episodesSheet" aria-labelledby="episodesTitle">
      <div class="sheet-heading"><h2 id="episodesTitle">Серии</h2><button class="btn sheet-close" aria-label="Закрыть" onclick="closeSheet('episodesSheet')">×</button></div>
      <div id="episodeList" class="episode-list"></div>
    </dialog>

    <section class="volume-card" id="continuationPanel" hidden aria-live="polite">
      <div id="continuationTitle" class="volume-header"></div>
      <div id="continuationActions" class="episode-list"></div>
    </section>

    <!-- Volume Card -->
    <section class="volume-card">
      <div class="volume-header">
        <span>Громкость</span>
        <span id="volLevel">100%</span>
      </div>
      <div class="volume-controls">
        <button class="btn btn-vol-mute" id="btnMute" aria-label="Выключить звук" onclick="toggleMute()">
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
        <button class="btn volume-step" aria-label="Тише на 5 процентов" onclick="stepVolume(-5)">−</button>
        <input type="range" id="volSlider" class="vol-slider" aria-label="Громкость" min="0" max="100" value="100" step="1" oninput="onVolSliderChange(this.value)">
        <button class="btn volume-step" aria-label="Громче на 5 процентов" onclick="stepVolume(5)">+</button>
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
        <div class="placeholder-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg></div>
        <div class="placeholder-title">Поиск торрент-раздач с ПК</div>
        <div class="placeholder-sub">Найдите фильм или сериал на телефоне и запустите просмотр на экране компьютера в один клик.</div>
      </div>
    </div>
  </div>

  <!-- Footer -->
  <div class="mini-player" id="miniPlayer" hidden>
    <button class="mini-title" onclick="switchTab('remote')"><span id="miniTitle"></span><small id="miniStatus">Вернуться к пульту</small></button>
    <button class="btn" id="miniPause" aria-label="Пауза" onclick="togglePlayPause()">Ⅱ</button>
  </div>
  <div id="feedback" role="alert" hidden></div>
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
    let connected = false;
    let polling = false;
    let windowState = {};
    let episodeHash = null;
    let episodeFiles = [];
    let episodeLoading = false;
    let seekOrigin = 0;
    let feedbackTimer;
    let volumeTimer;
    let screenChanging = false;
    let episodeRetryAfter = 0;

    function showFeedback(message) {
      const box = document.getElementById('feedback');
      box.textContent = message;
      box.hidden = false;
      clearTimeout(feedbackTimer);
      feedbackTimer = setTimeout(() => { box.hidden = true; }, 5000);
    }

    async function request(url, options = {}) {
      const abort = new AbortController();
      const timer = setTimeout(() => abort.abort(), 8000);
      try {
        const response = await fetch(url, { ...options, signal: abort.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response;
      } finally { clearTimeout(timer); }
    }

    function openSheet(id) {
      document.getElementById(id).showModal();
    }
    function closeSheet(id) { document.getElementById(id).close(); }
    document.querySelectorAll('dialog').forEach(dialog => {
      dialog.addEventListener('click', event => {
        if (event.target === dialog) {
          const bounds = dialog.getBoundingClientRect();
          if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
        }
      });
    });

    function updateAvailability() {
      const playing = connected && !!activeState?.active;
      ['btnPlayPause', 'btnRewind', 'btnForward', 'btnMute', 'volSlider', 'audioSelect', 'subSelect', 'miniPause', 'btnStop'].forEach(id => {
        document.getElementById(id).disabled = !playing;
      });
      document.getElementById('seekSlider').disabled = !playing || !(activeState.duration > 0);
      document.querySelectorAll('.volume-step').forEach(button => { button.disabled = !playing; });
      document.querySelectorAll('#screenSheet .btn-mode').forEach(button => { button.disabled = !connected || screenChanging; });
      document.getElementById('btnSearchSubmit').disabled = !connected || isSearching;
      const currentIndex = episodeFiles.findIndex(file => String(file.id ?? file.file_id) === String(activeState?.file_id));
      document.getElementById('btnNext').hidden = !playing || !episodeFiles.length;
      document.getElementById('btnNext').disabled = currentIndex < 0 || currentIndex >= episodeFiles.length - 1;
      document.getElementById('btnEpisodes').hidden = !playing || !episodeFiles.length;
      document.getElementById('miniPlayer').hidden = currentTab !== 'search' || !activeState?.active;
      document.getElementById('miniTitle').textContent = activeState?.file_name || '';
      document.getElementById('miniStatus').textContent = connected ? (activeState?.is_buffering ? 'Буферизация…' : activeState?.is_paused ? 'На паузе' : 'Воспроизведение') : 'Нет связи · переподключение…';
      document.getElementById('miniPause').textContent = activeState?.is_paused ? '▶' : 'Ⅱ';
      document.getElementById('miniPause').setAttribute('aria-label', activeState?.is_paused ? 'Воспроизвести' : 'Пауза');
      const current = episodeFiles[currentIndex];
      document.getElementById('episodeLabel').textContent = current ? 'Сезон ' + current.season + ' · Серия ' + (currentIndex - episodeFiles.findIndex(file => file.season === current.season) + 1) : 'Серии';
    }

    async function loadEpisodes() {
      const hash = activeState?.hash;
      if (!hash || activeState.is_online || episodeLoading || episodeHash === hash || Date.now() < episodeRetryAfter) return;
      episodeLoading = true;
      try {
        const response = await request('/api/library/torrents/' + encodeURIComponent(hash) + '/files');
        const data = await response.json();
        if (activeState?.hash !== hash) return;
        episodeFiles = Object.keys(data.seasons || {}).sort((a,b) => Number(a) - Number(b))
          .flatMap(season => (data.seasons[season] || []).map(file => ({ ...file, season })));
        episodeHash = hash;
        updateAvailability();
      } catch (error) {
        episodeRetryAfter = Date.now() + 10000;
        console.debug('Episode list unavailable:', error);
      } finally { episodeLoading = false; }
    }

    async function openEpisodes() {
      openSheet('episodesSheet');
      const list = document.getElementById('episodeList');
      list.replaceChildren();
      let previousSeason;
      episodeFiles.forEach(file => {
        if (previousSeason !== file.season) {
          const heading = document.createElement('h3');
          heading.textContent = 'Сезон ' + file.season;
          list.append(heading);
          previousSeason = file.season;
        }
        const button = document.createElement('button');
        button.className = 'episode-choice';
        const current = String(file.id ?? file.file_id) === String(activeState?.file_id);
        button.setAttribute('aria-current', String(current));
        button.textContent = file.name || file.file_name || 'Серия';
        const status = document.createElement('small');
        status.textContent = current ? 'Сейчас на экране' : file.is_watched ? 'Просмотрено' : file.playback_timecode > 0 ? 'Продолжить с ' + formatTime(file.playback_timecode) : 'Не просмотрено';
        button.append(status);
        button.onclick = async () => {
          if (!connected || !activeState?.active) return;
          button.disabled = true;
          try {
            await request('/api/player/play', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ hash:activeState.hash, file_id:file.id ?? file.file_id, file_name:file.name || file.file_name }) });
            closeSheet('episodesSheet');
            void pollState();
          } catch { showFeedback('Не удалось включить серию. Попробуйте ещё раз.'); }
          finally { button.disabled = false; }
        };
        list.append(button);
      });
    }

    async function setScreenMode(mode) {
      if (!connected || screenChanging) return;
      screenChanging = true;
      updateAvailability();
      try {
        await request('/api/window/pip', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({pip:false}) });
        await request('/api/player/fullscreen', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({fullscreen:mode === 'fullscreen'}) });
        if (mode === 'pip') await request('/api/window/pip', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({pip:true}) });
        closeSheet('screenSheet');
        void pollState();
      } catch { showFeedback('Не удалось переключить режим экрана.'); }
      finally { screenChanging = false; updateAvailability(); }
    }

    function vibrate() {
      if (navigator.vibrate) {
        try { navigator.vibrate(25); } catch(e) {}
      }
    }

    function switchTab(tab, updateHist = true) {
      currentTab = tab;
      vibrate();
      const isRemote = tab === "remote";
      document.getElementById('panelRemote').style.display = isRemote ? "flex" : "none";
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
      updateAvailability();
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

    let continuationJson = '';
    function updateContinuation() {
      const offer = activeState?.continuation;
      const panel = document.getElementById('continuationPanel');
      panel.hidden = !offer?.status;
      if (!offer?.status) { continuationJson = ''; return; }
      const label = document.getElementById('continuationTitle');
      label.textContent = offer.label + (offer.remaining ? ' · ' + offer.remaining + ' с' : '');
      const token = activeState.continuation_token;
      const signature = JSON.stringify([token, offer.status, offer.results, offer.files]);
      if (signature === continuationJson) return;
      continuationJson = signature;
      const actions = document.getElementById('continuationActions');
      actions.replaceChildren();
      function add(text, action, index) {
        const button = document.createElement('button');
        button.className = 'btn'; button.textContent = text;
        button.onclick = () => sendCommand(['continuation', action, token, index]);
        actions.append(button);
      }
      if (offer.status === 'offer') add(offer.external ? 'Найти раздачу' : 'Смотреть', 'watch');
      if (offer.status === 'empty') add('Повторить поиск', 'retry');
      if (offer.status === 'results') offer.results.forEach((r, index) => {
        const size = r.size ? (r.size / 1073741824).toFixed(1) + ' ГБ' : 'Размер неизвестен';
        add(r.title + ' · ' + (r.quality || 'Качество неизвестно') + ' · ' + size + ' · Сиды: ' + (r.seeders ?? '?'), 'choose', index);
      });
      if (offer.status === 'files') offer.files.forEach((f, index) => add(f.path || f.name, 'file', index));
      add('Отмена', 'cancel');
    }

    async function sendCommand(cmd) {
      if (!connected || !activeState?.active) return false;
      vibrate();
      try {
        await request('/api/player/command', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(cmd)
        });
        return true;
      } catch (err) {
        showFeedback('Команда не отправлена. Проверьте связь с компьютером.');
        return false;
      }
    }

    async function togglePlayPause() {
      if (await sendCommand(["cycle", "pause"])) {
        activeState.is_paused = !activeState.is_paused;
        updatePlayPauseUI();
        updateAvailability();
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
      clearTimeout(volumeTimer);
      volumeTimer = setTimeout(() => sendCommand(["set_property", "volume", Number(val)]), 100);
    }

    function stepVolume(delta) {
      if (!connected || !activeState?.active) return;
      const slider = document.getElementById('volSlider');
      slider.value = Math.max(0, Math.min(100, Number(slider.value) + delta));
      onVolSliderChange(slider.value);
    }

    async function nextEpisode() {
      if (!connected || !activeState?.active) return;
      vibrate();
      if (!activeState || !activeState.hash) return;
      try {
        await request('/api/player/next', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            hash: activeState.hash,
            file_id: activeState.file_id || 0
          })
        });
      } catch (err) {
        showFeedback('Не удалось включить следующую серию.');
      }
    }

    async function stopPlayer() {
      if (!connected || !activeState?.active) return;
      vibrate();
      try {
        await request('/api/player/stop', {method: 'POST'});
        closeSheet('moreSheet');
        void pollState();
      } catch (err) {
        showFeedback('Не удалось остановить просмотр.');
      }
    }

    async function toggleFullscreen(target) {
      return setScreenMode(typeof target === 'boolean' ? (target ? 'fullscreen' : 'normal') : (windowState.is_fullscreen ? 'normal' : 'fullscreen'));
    }

    async function togglePip() {
      return setScreenMode(windowState.is_pip ? 'normal' : 'pip');
    }

    async function restoreAppWindow() {
      if (!connected) return;
      vibrate();
      try {
        const res = await request('/api/window/show', { method: 'POST' });
        if (res.ok) {
          const btn = document.getElementById('btnHeaderRestore');
          if (btn) {
            const orig = btn.innerHTML;
            btn.innerHTML = '<span style="color:#10b981;">✓ Развернуто</span>';
            setTimeout(() => { btn.innerHTML = orig; }, 1500);
          }
        }
      } catch (err) {
        showFeedback('Не удалось показать окно компьютера.');
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
      document.getElementById('btnPlayPause').setAttribute('aria-label', isPaused ? 'Воспроизвести' : 'Пауза');
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
            return `<option value="${escapeHtml(String(a.id))}">${escapeHtml(title)}</option>`;
          }).join('');
        }

        const subs = tracks.filter(t => t.type === 'sub');
        subSelect.innerHTML = `<option value="no">Выключены</option>` + subs.map(s => {
          const title = s.title || s.lang || ('Субтитры ' + s.id);
          return `<option value="${escapeHtml(String(s.id))}">${escapeHtml(title)}</option>`;
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
      if (!isSeeking) seekOrigin = activeState?.timecode || 0;
      isSeeking = true;
      const selected = Number(e.target.value);
      const delta = Math.round(selected - seekOrigin);
      document.getElementById('curTime').textContent = formatTime(selected);
      document.getElementById('seekPreview').textContent = formatTime(selected) + ' · ' + (delta >= 0 ? '+' : '−') + formatTime(Math.abs(delta));
    });
    seekSlider.addEventListener('change', (e) => {
      if (isSeeking && activeState && activeState.duration > 0) {
        const targetTime = Number(e.target.value);
        sendCommand(["seek", targetTime, "absolute+exact"]);
      }
      isSeeking = false;
      document.getElementById('seekPreview').textContent = '';
    });
    seekSlider.addEventListener('pointercancel', () => {
      isSeeking = false;
      document.getElementById('seekPreview').textContent = '';
      updateProgressUI();
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
      if (!connected || !query || isSearching) return;
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
                <span class="tag tag-seeders">Сиды: ${t.seeders !== undefined && t.seeders !== null ? t.seeders : 0}</span>
                ${t.size ? `<span class="tag tag-size">${formatSize(t.size)}</span>` : ''}
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
      if (!connected) { showFeedback('Нет связи с компьютером. Переподключение…'); return; }
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
      if (polling) return;
      polling = true;
      try {
        const [playerRes, winRes] = await Promise.all([
          request('/api/player/active'),
          request('/api/window/state')
        ]);

        if (playerRes.ok) {
          const data = await playerRes.json();
          connected = true;
          if (activeState?.hash !== data.hash) { episodeHash = null; episodeFiles = []; }
          activeState = data;
          updateContinuation();

          const dot = document.getElementById('statusDot');
          const statusText = document.getElementById('statusText');
          const titleEl = document.getElementById('mediaTitle');

          if (data && data.active) {
            dot.className = 'status-dot ' + (data.is_paused ? 'paused' : 'active');
            statusText.textContent = data.is_buffering || !data.is_ready ? 'Буферизация…' : data.is_paused ? 'На паузе' : 'Воспроизведение';
            titleEl.textContent = data.file_name || 'Воспроизведение...';
            updatePlayPauseUI();
            updateProgressUI();
            updateTracksUI();
            void loadEpisodes();
            document.getElementById('iconVolHigh').style.display = data.is_muted ? 'none' : 'block';
            document.getElementById('iconVolMute').style.display = data.is_muted ? 'block' : 'none';
            document.getElementById('btnMute').setAttribute('aria-pressed', String(!!data.is_muted));
            document.getElementById('btnMute').setAttribute('aria-label', data.is_muted ? 'Включить звук' : 'Выключить звук');

            if (data.volume !== undefined && document.getElementById('volSlider') !== document.activeElement) {
              document.getElementById('volSlider').value = data.volume;
              document.getElementById('volLevel').textContent = data.volume + "%";
            }
          } else {
            dot.className = 'status-dot';
            statusText.textContent = 'Ожидание';
            titleEl.innerHTML = '<div class="media-empty">Ничего не воспроизводится</div>';
            document.getElementById('tracksSection').style.display = 'none';
            lastTrackListJson = '';
            lastKnownAid = null;
            lastKnownSid = null;
            document.getElementById('curTime').textContent = '00:00';
            document.getElementById('durTime').textContent = '00:00';
            document.getElementById('seekSlider').value = 0;
          }

          if (typeof data.is_fullscreen === 'boolean') {
            updateFullscreenUI(data.is_fullscreen);
          }
        }

        if (winRes && winRes.ok) {
          const winData = await winRes.json();
          windowState = winData;
          document.getElementById('btnNormal').setAttribute('aria-pressed', String(!winData.is_pip && !winData.is_fullscreen));
          document.getElementById('btnFullscreen').setAttribute('aria-pressed', String(!!winData.is_fullscreen));
          document.getElementById('btnPip').setAttribute('aria-pressed', String(!!winData.is_pip));
          if (typeof winData.is_pip === 'boolean') {
            updatePipUI(winData.is_pip);
          }
        }
      } catch (err) {
        connected = false;
        const dot = document.getElementById('statusDot');
        const statusText = document.getElementById('statusText');
        dot.className = 'status-dot offline';
        statusText.textContent = 'Нет связи · повтор…';
      } finally {
        polling = false;
        updateAvailability();
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
        const sheet = document.querySelector('dialog[open]');
        if (sheet) { sheet.close(); pushRemoteState(); return; }
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
    updateAvailability();
    async function pollLoop() {
      await pollState();
      setTimeout(pollLoop, connected ? 1000 : 2500);
    }
    window.addEventListener('online', () => { void pollState(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void pollState(); });
    pollLoop();
  </script>
</body>
</html>
"""
