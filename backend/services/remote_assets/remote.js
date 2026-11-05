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
    let phoneSession = null, phoneSequence = 0, phoneTimer = null, phoneBusy = false;
    let phoneHls = null;
    let phoneAuth = "";
    let phonePairCode = '';
    try {
      phoneAuth = localStorage.getItem('pcRemoteToken') || '';
      phonePairCode = localStorage.getItem('pcRemotePairCode') || '';
    } catch (_) {}
    if (!phoneAuth) {
      try { phoneAuth = sessionStorage.getItem('pcRemoteToken') || ''; } catch (_) {}
    }
    const phoneHeaders = () => ({"Content-Type":"application/json", ...(phoneAuth ? {"X-Remote-Token":phoneAuth} : {})});
    let phoneAttempt = 0, phoneStall = null, phoneLastFocus = null;
    const phoneVideo = document.getElementById('phoneVideo');
    const phoneMessage = document.getElementById('phoneMessage');
    let phonePairingRequest = null;
    function pairPhone(code) {
      if (phonePairingRequest) return phonePairingRequest;
      phonePairingRequest = connectPhone(code).finally(() => { phonePairingRequest = null; });
      return phonePairingRequest;
    }
    async function connectPhone(code) {
      const res = await fetch('/api/remote/pair', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({code})});
      if (!res.ok) throw new Error('Ссылка сопряжения устарела. Откройте QR-код на ПК снова.');
      const data = await res.json();
      phoneAuth = data.token;
      phonePairCode = code;
      try {
        localStorage.setItem('pcRemoteToken', phoneAuth);
        localStorage.setItem('pcRemotePairCode', code);
      } catch (_) {}
      try { sessionStorage.setItem('pcRemoteToken', phoneAuth); } catch (_) {}
    }
    let pairing = (async () => {
      const code = new URLSearchParams(location.hash.slice(1)).get('pair');
      if (!code) {
        if (!phoneAuth && phonePairCode) await pairPhone(phonePairCode);
        return;
      }
      await pairPhone(code);
      history.replaceState(null, '', location.pathname + location.search);
    })();
    pairing.catch(error => showFeedback(error.message));
    async function phoneApi(url, body) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 45000);
      try {
        const send = () => fetch(url, {method:'POST', headers:phoneHeaders(), body:JSON.stringify(body), signal:controller.signal, cache:'no-store'});
        let res = await send();
        if (res.status === 401 && phonePairCode) {
          await pairPhone(phonePairCode);
          res = await send();
        }
        const data = await res.json();
        if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось открыть видео');
        return data;
      } finally { clearTimeout(timer); }
    }
    function phonePlayUserAction() {
      phoneMessage.textContent = 'Запуск воспроизведения…';
      phoneVideo.play().then(() => {
        document.getElementById('phonePlayBtn').hidden = true;
        phoneMessage.textContent = '';
      }).catch(() => {
        phoneMessage.textContent = 'Нажмите на кнопку воспроизведения в самом плеере.';
      });
    }
    function phoneProgress(close = false) {
      if (!phoneSession) return;
      const curPos = phoneVideo.currentTime;
      if (close && (!Number.isFinite(curPos) || curPos <= 0)) {
        return fetch('/api/remote/mobile/' + phoneSession.token + '/progress', {
          method: 'POST',
          headers: phoneHeaders(),
          body: JSON.stringify({sequence: ++phoneSequence, position: 0, duration: 0, close: true}),
          keepalive: true
        }).catch(() => {});
      }
      const dur = Number.isFinite(phoneVideo.duration) && phoneVideo.duration > 0 ? phoneVideo.duration : (phoneSession?.duration || 0);
      const payload = {sequence:++phoneSequence, position:Math.max(0,curPos || 0), duration:dur, close};
      return fetch('/api/remote/mobile/' + phoneSession.token + '/progress', {method:'POST', headers:phoneHeaders(), body:JSON.stringify(payload), keepalive:close}).then(res => {
        if (!res.ok && !close) { phoneVideo.pause(); phoneMessage.textContent = 'Сессия завершена. Вернитесь к пульту и откройте видео снова.'; }
      }).catch(() => { if (!close) phoneMessage.textContent = 'Нет связи с ПК. Проверьте Wi-Fi.'; });
    }
    async function startPhone(target) {
      if (phoneBusy) return;
      phoneBusy = true;
      document.getElementById('phoneResume').hidden = true;
      document.getElementById('phoneResume').onclick = null;
      document.getElementById('phonePrevious').hidden = true;
      document.getElementById('phoneNext').hidden = true;
      const attempt = ++phoneAttempt;
      phoneLastFocus = document.activeElement;
      const closing = phoneProgress(true);
      phoneSession = null;
      clearInterval(phoneTimer); clearTimeout(phoneStall);
      if (phoneHls) { phoneHls.destroy(); phoneHls = null; }
      phoneVideo.onloadedmetadata = null;
      phoneVideo.pause(); phoneVideo.removeAttribute('src'); phoneVideo.load();
      await closing;
      document.body.classList.add('phone-open');
      Array.from(document.body.children).forEach(el => { if (el.id !== 'phonePlayer') el.inert = true; });
      document.getElementById('phonePlayer').hidden = false;
      document.getElementById('phoneBack').focus();
      document.getElementById('phoneTitle').textContent = target.file_name || target.title || 'Просмотр на телефоне';
      document.getElementById('phoneChoices').replaceChildren();
      document.getElementById('phoneResume').hidden = true;
      document.getElementById('phoneNext').hidden = true;
      document.getElementById('phonePlayBtn').hidden = true;
      phoneMessage.textContent = 'Проверяем файл и кодеки…';
      try {
        await pairing;
        const data = await phoneApi('/api/remote/mobile', target);
        if (attempt !== phoneAttempt) {
          if (data.token) fetch('/api/remote/mobile/' + data.token + '/progress', {method:'POST',headers:phoneHeaders(),body:JSON.stringify({sequence:1,close:true})});
          return;
        }
        if (data.choose_file) {
          phoneMessage.textContent = data.reason;
          data.files.forEach(file => {
            const button = document.createElement('button'); button.className = 'episode-choice';
            button.textContent = file.path || file.name;
            button.onclick = () => startPhone({...target, file_id:file.id, file_name:file.name || file.path});
            document.getElementById('phoneChoices').append(button);
          });
          return;
        }
        phoneSession = data; phoneSequence = 0;
        document.getElementById('phoneTitle').textContent = data.file_name || target.file_name || target.title || 'Просмотр на телефоне';
        if (data.mode !== 'direct' && !phoneVideo.canPlayType('application/vnd.apple.mpegurl')) {
          if (!window.Hls || !Hls.isSupported()) throw new Error('Этот браузер не поддерживает просмотр потока. Откройте пульт в Safari или Chrome.');
          phoneHls = new Hls({maxBufferLength:30, maxMaxBufferLength:36});
          phoneHls.on(Hls.Events.ERROR, (_, error) => {
            if (error.fatal) {
              phoneMessage.textContent = 'Не удалось загрузить видео. Вернитесь к пульту и повторите запуск.';
              phoneProgress(true); phoneSession = null;
              clearInterval(phoneTimer);
              phoneHls?.destroy(); phoneHls = null;
            }
          });
          phoneHls.loadSource(data.url);
          phoneHls.attachMedia(phoneVideo);
        } else {
          phoneVideo.src = data.url;
        }
        phoneMessage.textContent = '';
        document.getElementById('phonePlayBtn').hidden = false;
        const resume = document.getElementById('phoneResume');
        resume.hidden = !(data.resume > 0);
        document.getElementById('phonePlayBtn').classList.toggle('btn-play-torrent', !(data.resume > 0));
        resume.textContent = 'Продолжить с ' + formatTime(data.resume);
        resume.onclick = () => {
          const targetTime = data.resume;
          resume.hidden = true;
          document.getElementById('phonePlayBtn').hidden = true;
          if (phoneVideo.readyState >= 1) {
            phoneVideo.currentTime = targetTime;
          } else {
            phoneVideo.onloadedmetadata = () => {
              try { phoneVideo.currentTime = targetTime; } catch (_) {}
              phoneVideo.onloadedmetadata = null;
            };
          }
          phoneVideo.play().catch(() => {phoneMessage.textContent = 'Нажмите значок воспроизведения на видео.';});
        };
        const next = document.getElementById('phoneNext');
        next.hidden = !data.next;
        next.onclick = () => startPhone({hash:data.hash, title:target.title, file_id:data.next.id, file_name:data.next.name || data.next.path});
        const previous = document.getElementById('phonePrevious');
        previous.hidden = !data.previous;
        previous.onclick = () => startPhone({hash:data.hash, title:target.title, file_id:data.previous.id, file_name:data.previous.name || data.previous.path});
        phoneTimer = setInterval(() => phoneProgress(), 30000);
      } catch (error) {
        if (attempt === phoneAttempt) { phoneProgress(true); phoneSession = null; }
        if (attempt === phoneAttempt) phoneMessage.textContent = error.name === 'AbortError' ? 'Источник не ответил. Вернитесь к пульту и повторите запуск.' : error.message;
      } finally { phoneBusy = false; }
    }
    function closePhone() {
      ++phoneAttempt;
      phoneProgress(true); phoneSession = null;
      clearInterval(phoneTimer); clearTimeout(phoneStall);
      if (phoneHls) { phoneHls.destroy(); phoneHls = null; }
      phoneVideo.onloadedmetadata = null;
      phoneVideo.pause(); phoneVideo.removeAttribute('src'); phoneVideo.load();
      document.body.classList.remove('phone-open');
      Array.from(document.body.children).forEach(el => { el.inert = false; });
      document.getElementById('phonePlayer').hidden = true;
      phoneLastFocus?.focus();
    }
    function watchCurrentPhone() {
      if (activeState?.active && !activeState.is_online) startPhone({hash:activeState.hash,file_id:activeState.file_id,file_name:activeState.file_name});
    }
    phoneVideo.addEventListener('waiting', () => {
      if (!phoneSession) return;
      phoneMessage.textContent = 'Буферизация…'; clearTimeout(phoneStall);
      phoneStall = setTimeout(() => {phoneMessage.textContent = 'Буферизация видео… Проверьте раздачу и Wi-Fi связь.';}, 20000);
    });
    phoneVideo.addEventListener('playing', () => {
      clearTimeout(phoneStall);
      phoneMessage.textContent = '';
      document.getElementById('phonePlayBtn').hidden = true;
    });
    phoneVideo.addEventListener('error', () => {
      if (!phoneSession) return;
      clearTimeout(phoneStall);
      const err = phoneVideo.error;
      let msg = 'Браузер не смог воспроизвести видео.';
      if (err) {
        if (err.code === 1) msg = 'Воспроизведение отменено.';
        else if (err.code === 2) msg = 'Ошибка сети. Проверьте Wi-Fi соединение с компьютером.';
        else if (err.code === 3) msg = 'Ошибка декодирования видео.';
        else if (err.code === 4) msg = 'Формат потока не поддерживается этим устройством.';
      }
      phoneMessage.textContent = msg + ' Откройте видео повторно или вернитесь к пульту.';
      document.getElementById('phonePlayBtn').hidden = true;
      phoneProgress(true);
      phoneSession = null;
      clearInterval(phoneTimer);
    });
    ['pause','seeked','ended'].forEach(event => phoneVideo.addEventListener(event, () => phoneProgress()));
    window.addEventListener('pagehide', () => {phoneProgress(true); phoneSession = null; phoneHls?.destroy(); phoneHls = null; phoneVideo.pause(); phoneVideo.removeAttribute('src'); phoneVideo.load();});
    setInterval(() => {document.getElementById('phoneCurrent').hidden = !activeState?.active || activeState?.is_online || !activeState?.hash;},1000);
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
        const phone = document.createElement('button');
        phone.className = 'episode-choice'; phone.textContent = 'Смотреть на телефоне: ' + (file.name || file.file_name);
        phone.onclick = () => { closeSheet('episodesSheet'); startPhone({hash:activeState.hash, file_id:file.id ?? file.file_id, file_name:file.name || file.file_name}); };
        list.append(phone);
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
      return String(str).replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/"/g, '\\"');
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
          headers: phoneHeaders(),
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
          headers: phoneHeaders(),
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
                  <span>Смотреть на ПК</span>
                </button>
                <button class="btn btn-action" onclick="startPhone({hash:'${escapeJs(t.hash || '')}',magnet:'${escapeJs(t.magnet || '')}',title:'${escapeJs(t.title)}'})">Смотреть на телефоне</button>
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
          headers: phoneHeaders(),
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
          btnEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><span>Смотреть на ПК</span>';
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
                <div class="ep-item">
                  <span class="ep-name" title="${escapeHtml(ep.name)}">${escapeHtml(ep.name)}</span>
                  <button class="btn btn-action" onclick="launchTorrent('${escapeJs(hash)}', '${escapeJs(magnet || '')}', '${escapeJs(title)}', ${ep.id}, '${escapeJs(ep.name)}')">Смотреть на ПК</button>
                  <button class="btn btn-action" onclick="startPhone({hash:'${escapeJs(hash)}',magnet:'${escapeJs(magnet || '')}',title:'${escapeJs(title)}',file_id:${ep.id},file_name:'${escapeJs(ep.name)}'})">Смотреть на телефоне</button>
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
          document.getElementById('phoneCurrent').hidden = !data.active || data.is_online || !data.hash;
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
