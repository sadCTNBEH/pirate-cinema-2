/* ── Pirate Cinema v2 ── app.js ── */
'use strict';

let STRINGS = {}; let LANG = 'ru';
async function loadI18n(){ const d = await API.get('/api/i18n'); STRINGS=d.strings; LANG=d.lang; }
function t(k, opts){ 
    let res = STRINGS[k] || k;
    if (opts) {
        for (let key in opts) {
            res = res.replace('{'+key+'}', opts[key]);
        }
    }
    return res;
}


const API = {
    async get(path) {
        const r = await fetch(path);
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
    },
    async post(path, body) {
        const r = await fetch(path, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        });
        if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
        return r.json();
    },
    async del(path) {
        const r = await fetch(path, {method: 'DELETE'});
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
    }
};

// ── State ──────────────────────────────────────────────────────────────────
const state = {
    page: 'home',
    prevPage: 'home',
    detail: null,  // {hash, title, magnet}
    searchQuery: '',
    searchHTML: ''
};

// ── Router ──────────────────────────────────────────────────────────────────
function parseTrans(titleStr) {
    if (!titleStr) return t('unknown');
    const p = titleStr.split('|');
    if (p.length < 2) return t('unknown');
    const l = p[p.length - 1].trim();
    if (l.length > 20) return t('unknown');
    const res = [];
    for(let c of l.split(/[,+]/)) {
        c = c.trim().toUpperCase();
        if (c==='D'||c==='Д') res.push(t('dubbing'));
        else if (c.startsWith('P')||c.startsWith('П')||c==='M') res.push(t('prof'));
        else if (c.startsWith('A')||c.startsWith('Л')||c.startsWith('L')) res.push(t('amateur'));
        else if (c==='O'||c==='О') res.push(t('original'));
        else if (c.startsWith('S')||c.startsWith('С')) res.push(t('subtitles'));
        else res.push(c);
    }
    return [...new Set(res)].join(', ') || t('unknown');
}

const container = document.getElementById('page-container');

function cloneTemplate(id) {
    return document.getElementById(id).content.cloneNode(true);
}

async function navigate(page, data = null, push = true, restoreScroll = 0) {
    if (push && state.page && state.page !== page) {
        state.history = state.history || [];
        state.history.push({page: state.page, data: state.data, scroll: window.scrollY});
    }
    state.page = page;
    state.data = data;
    document.querySelectorAll('.nav button[data-page]').forEach(b => {
        if (b.dataset.page === page) b.classList.add('active');
        else b.classList.remove('active');
    });
    container.innerHTML = '';
    const frag = cloneTemplate(`tmpl-${page}`);
    container.appendChild(frag);

    if (PAGES[page]) await PAGES[page](data);
    document.querySelectorAll('[data-i18n]').forEach(el => el.textContent = t(el.dataset.i18n));
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => el.placeholder = t(el.dataset.i18nPlaceholder));

    if (restoreScroll > 0) {
        setTimeout(() => window.scrollTo(0, restoreScroll), 0);
    } else {
        window.scrollTo(0, 0);
    }
}
function goBack() {
    state.history = state.history || [];
    if (state.history.length > 0) {
        const prev = state.history.pop();
        navigate(prev.page, prev.data, false, prev.scroll || 0);
    } else {
        navigate('home');
    }
}


// ── Pages ────────────────────────────────────────────────────────────────────
const PAGES = {

    async home() {
        // Server status
        const badge = document.getElementById('srv-badge');
        API.get('/api/settings/status').then(s => {
            badge.textContent = s.active ? t('ts_active') : t('ts_inactive');
            badge.className = 'status ' + (s.active ? 'active' : 'error');
        }).catch(() => {
            badge.textContent = t('ts_check_error');
            badge.className = 'status error';
        });

        // Continue watching
        loadContinue();

        // Popular movies
        loadPopular('movies', '/api/library/popular', t('popular_movies'));
        loadPopular('series', '/api/library/popular/series', t('popular_series'));
    },

    async meta({imdb, title, type, poster}) {
        document.getElementById('meta-back-btn').onclick = goBack;
        document.getElementById('meta-title').textContent = title;
        const posterEl = document.getElementById('meta-poster');
        if (poster) posterEl.src = poster;
        
        const resultsEl = document.getElementById('meta-search-results');
        const seasonSel = document.getElementById('meta-season-sel');
        const episodeSel = document.getElementById('meta-episode-sel');
        const controls = document.getElementById('meta-series-controls');
        
        let currentSeason = 1;
        let currentEpisode = 1;
        let metaVideos = [];
        let isSeries = type === 'series';
        


        let searchData = [];
        function renderSearchResults() {
            if (!searchData.length) {
                resultsEl.innerHTML = `<div class="empty panel">${t('nothing_found')}</div>`;
                return;
            }
            
            let baseData = searchData;
            if (isSeries) {
                const sStr = currentSeason.toString();
                const s0 = sStr.padStart(2, '0');
                baseData = baseData.filter(r => {
                    const title = r.title.toLowerCase();
                    if (new RegExp(`\\b(s${s0}|s${sStr}|сезон ${sStr}|${sStr} сезон)\\b`, 'i').test(t)) return true;
                    if (/(сезоны|seasons|s0?1-)/i.test(t)) return true;
                    if (!/(s\d+|сезон)/i.test(t)) return true;
                    return false;
                });
            }
            
            if (!baseData.length) {
                resultsEl.innerHTML = `<div class="empty panel">${t('season_not_found')}</div>`;
                return;
            }

            const filter = document.getElementById('meta-trans-sel')?.value || 'all';
            const filtered = filter === 'all' ? baseData : baseData.filter(r => parseTrans(r.title) === filter);
            
            const transList = [...new Set(baseData.map(r => parseTrans(r.title)))].sort();
            const filterHTML = transList.length > 1 ? `
                <div style="margin-bottom: 16px;">
                    <select id="meta-trans-sel" class="filters" style="min-height:36px; border-radius:6px;" onchange="window.renderMetaSearch()">
                        <option value="all">${t('all_voiceovers')}</option>
                        ${transList.map(t => `<option value="${t}" ${t===filter?'selected':''}>${t}</option>`).join('')}
                    </select>
                </div>
            ` : '';

            resultsEl.innerHTML = filterHTML + (filtered.length ? filtered.map(r => `
                <div class="result">
                    <div class="result-main">
                        <h3>${esc(r.title)}</h3>
                        <div class="result-meta">
                            <span>${esc(r.source || 'TorrServer')}</span>
                            ${r.seeders ? `<small>🌱 ${r.seeders} ${t('seeders')}</small>` : ''}
                            <small style="color:var(--accent);">🎤 ${parseTrans(r.title)}</small>
                        </div>
                    </div>
                    <div class="result-actions">
                        <button class="primary" data-magnet="${esc(r.magnet)}" data-hash="${esc(r.hash)}" data-title="${esc(r.title)}" data-season="${isSeries ? currentSeason : ''}" data-episode="${isSeries ? currentEpisode : ''}" onclick="openDetail(this)">
                            ${t('play')}
                        </button>
                    </div>
                </div>`).join('') : `<div class="empty panel">${t('nothing_found')}</div>`);
        }
        window.renderMetaSearch = renderSearchResults;

        function doSearchQuery(q) {
            if (!resultsEl) return;
            resultsEl.innerHTML = `<div class="notice">${t('searching_torrents')}</div>`;
            API.get(`/api/search?q=${encodeURIComponent(q)}`).then(data => {
                searchData = data;
                renderSearchResults();
            }).catch(e => {
                resultsEl.innerHTML = `<div class="empty panel">${t('search_error', {error: esc(e.message)})}</div>`;
            });
        }
        
        function triggerSearch() {
            renderSearchResults();
        }
        
        function updateEpisodes() {
            const eps = metaVideos.filter(v => v.season == currentSeason).sort((a,b) => a.episode - b.episode);
            if (!eps.length) {
                episodeSel.style.display = 'none';
                return;
            }
            episodeSel.style.display = 'inline-block';
            episodeSel.innerHTML = eps.map(e => `<option value="${e.episode}">${t('episode')} ${e.episode} ${e.name ? `(${esc(e.name)})` : ''}</option>`).join('');
            currentEpisode = eps[0].episode;
        }

        if (seasonSel) {
            seasonSel.onchange = () => { currentSeason = seasonSel.value; updateEpisodes(); triggerSearch(); };
            episodeSel.onchange = () => { currentEpisode = episodeSel.value; triggerSearch(); };
        }

        // Fetch torrents once for the title
        doSearchQuery(title);

        try {
            const meta = await API.get(`/api/library/meta/${imdb}?type=${type || (isSeries ? 'series' : 'movie')}`);
            if (meta.overview) document.getElementById('meta-overview').textContent = meta.overview;
            if (meta.rating) document.getElementById('meta-rating').textContent = `★ ${meta.rating.toFixed(1)}`;
            if (meta.poster_url && !poster) posterEl.src = meta.poster_url;
            
            if (meta.type === 'series' || isSeries) {
                isSeries = true;
                metaVideos = meta.videos || [];
                if (metaVideos.length > 0) {
                    controls.style.display = 'flex';
                    const seasons = [...new Set(metaVideos.map(v => v.season))].sort((a,b) => a - b);
                    seasonSel.innerHTML = seasons.map(s => `<option value="${s}">${t('season_prefix')} ${s}</option>`).join('');
                    currentSeason = seasons[0];
                    updateEpisodes();
                    triggerSearch();
                } else {
                    triggerSearch(); // fallback
                }
            }
        } catch(e) {
            console.error(e);
            if (isSeries && metaVideos.length === 0) triggerSearch();
        }
    },

    async search(data) {
        document.getElementById('search-back-btn').onclick = goBack;
        const input = document.getElementById('q');
        const btn = document.getElementById('do-search');
        const results = document.getElementById('results');

        if (data?.query) {
            input.value = data.query;
        } else if (state.searchQuery) {
            input.value = state.searchQuery;
            results.innerHTML = state.searchHTML;
        }

        window._searchData = [];
        function renderManualSearch() {
            if (!window._searchData.length) {
                results.innerHTML = `<div class="empty panel">${t('nothing_found_try_another')}</div>`;
                return;
            }
            
            const seasonVal = document.getElementById('search-season')?.value;
            const episodeVal = document.getElementById('search-episode')?.value;
            let baseData = window._searchData;
            
            if (seasonVal) {
                const sStr = seasonVal.toString();
                const s0 = sStr.padStart(2, '0');
                baseData = baseData.filter(r => {
                    const title = r.title.toLowerCase();
                    if (new RegExp(`\\b(s${s0}|s${sStr}|сезон ${sStr}|${sStr} сезон)\\b`, 'i').test(t)) return true;
                    if (/(сезоны|seasons|s0?1-)/i.test(t)) return true;
                    if (!/(s\d+|сезон)/i.test(t)) return true;
                    return false;
                });
            }
            
            if (!baseData.length) {
                results.innerHTML = `<div class="empty panel">${t('season_not_found')}</div>`;
                return;
            }

            const filter = document.getElementById('manual-trans-sel')?.value || 'all';
            const filtered = filter === 'all' ? baseData : baseData.filter(r => parseTrans(r.title) === filter);
            
            const transList = [...new Set(baseData.map(r => parseTrans(r.title)))].sort();
            const filterHTML = transList.length > 1 ? `
                <div style="margin-bottom: 16px;">
                    <select id="manual-trans-sel" class="filters" style="min-height:36px; border-radius:6px;" onchange="window.renderManualSearch()">
                        <option value="all">${t('all_voiceovers')}</option>
                        ${transList.map(t => `<option value="${t}" ${t===filter?'selected':''}>${t}</option>`).join('')}
                    </select>
                </div>
            ` : '';

            results.innerHTML = filterHTML + (filtered.length ? filtered.map(r => `
                <div class="result">
                    <div class="result-main">
                        <h3>${esc(r.title)}</h3>
                        <div class="result-meta">
                            <span>${esc(r.source || 'TorrServer')}</span>
                            ${r.seeders ? `<small>🟢 ${r.seeders} ${t('seeders')}</small>` : ''}
                            <small style="color:var(--accent);">🎤 ${parseTrans(r.title)}</small>
                        </div>
                    </div>
                    <div class="result-actions">
                        <button class="primary" data-magnet="${esc(r.magnet)}" data-hash="${esc(r.hash)}" data-title="${esc(r.title)}" data-season="${seasonVal || ''}" data-episode="${episodeVal || ''}" onclick="openDetail(this)">
                            ${t('watch')}
                        </button>
                    </div>
                </div>`).join('') : `<div class="empty panel">${t('nothing_found')}</div>`);
                
            state.searchQuery = input.value.trim();
            state.searchHTML = results.innerHTML;
        }
        window.renderManualSearch = renderManualSearch;

        async function doSearch() {
            const q = input.value.trim();
            if (!q) return;
            results.innerHTML = `<div class="notice">${t('searching')}...</div>`;
            btn.disabled = true;
            try {
                window._searchData = await API.get(`/api/search?q=${encodeURIComponent(q)}`);
                renderManualSearch();
            } catch (e) {
                results.innerHTML = `<div class="empty panel">${t('error', {error: esc(e.message)})}</div>`;
            } finally {
                btn.disabled = false;
            }
        }

        btn.onclick = doSearch;
        input.onkeydown = e => { if (e.key === 'Enter') doSearch(); };
        input.focus();
        if (data?.query) doSearch();
    },

    async library() {
        document.getElementById('lib-back-btn').onclick = goBack;
        const list = document.getElementById('lib-list');
        try {
            const data = await API.get('/api/library/torrents');
            const torrents = data.torrents || [];
            if (!torrents.length) {
                list.innerHTML = `<div class="empty panel">${t('library_empty')}</div>`;
                return;
            }
            list.innerHTML = torrents.map(tor => `
                <div class="result result-lib" style="display: grid; grid-template-columns: auto 48px minmax(0, 1fr) auto; align-items: center; gap: 16px;">
                    <label class="result-check">
                        <input type="checkbox" class="lib-checkbox" value="${esc(tor.hash)}">
                    </label>
                    <div style="width: 48px; height: 72px; border-radius: 4px; overflow: hidden; background: rgba(255,255,255,0.05); display: flex; align-items: center; justify-content: center;">
                        ${tor.poster_url ? `<img src="${tor.poster_url}" style="width:100%;height:100%;object-fit:cover;">` : `<span style="opacity:0.3;font-size:20px;">🎬</span>`}
                    </div>
                    <div class="result-main">
                        <h3>${esc(tor.title)}</h3>
                        <div class="result-meta"><small>${esc(tor.hash)}</small></div>
                    </div>
                    <div class="result-actions">
                        <button class="primary" data-hash="${esc(tor.hash)}" data-title="${esc(tor.title)}" onclick="openDetailByHash(this)">${t('watch')}</button>
                        <button class="secondary" data-hash="${esc(tor.hash)}" onclick="removeTorrent(this)">🗑</button>
                    </div>
                </div>
            `).join('');
        } catch (e) {
            list.innerHTML = `<div class="empty panel">${t('error', {error: esc(e.message)})}</div>`;
        }
    },

    async settings() {
        const urlInput = document.getElementById('ts-url');
        const langSelect = document.getElementById('lang-select');
        const jackettUrl = document.getElementById('jackett-url');
        const jackettKey = document.getElementById('jackett-key');
        const hint = document.getElementById('ts-hint');
        try {
            const s = await API.get('/api/settings');
            if (s.torrserver_url) urlInput.value = s.torrserver_url;
            if (s.language && langSelect) langSelect.value = s.language;
            if (s.jackett_url && jackettUrl) jackettUrl.value = s.jackett_url;
            if (s.jackett_api_key && jackettKey) jackettKey.value = s.jackett_api_key;
        } catch {}

        document.getElementById('save-settings').addEventListener('click', async () => {
            const prevLang = LANG;
            try {
                await API.post('/api/settings', {
                    torrserver_url: urlInput.value.trim(),
                    language: langSelect ? langSelect.value : 'ru',
                    jackett_url: jackettUrl ? jackettUrl.value.trim() : '',
                    jackett_api_key: jackettKey ? jackettKey.value.trim() : ''
                });
                if (langSelect && prevLang !== langSelect.value) {
                    await loadI18n();
                    navigate(state.page, state.data, false);
                }
                hint.textContent = t('saved');
                hint.style.color = '#4ade80';
            } catch (e) {
                hint.textContent = t('error', {error: e.message});
                hint.style.color = '#f87171';
            }
        });

        document.getElementById('test-ts').addEventListener('click', async () => {
            hint.textContent = t('checking');
            hint.style.color = '';
            try {
                const s = await API.get('/api/settings/status');
                hint.textContent = s.active ? t('ts_available') : t('ts_unavailable');
                hint.style.color = s.active ? '#4ade80' : '#f87171';
            } catch (e) {
                hint.textContent = t('error', {error: e.message});
                hint.style.color = '#f87171';
            }
        });

        const checkUpdatesBtn = document.getElementById('check-updates-btn');
        if (checkUpdatesBtn) {
            checkUpdatesBtn.addEventListener('click', async function() {
                this.disabled = true;
                this.textContent = t('checking');
                const stat = document.getElementById('update-status');
                stat.className = 'status';
                stat.textContent = '';
                try {
                    const res = await API.get('/api/settings/updates');
                    if (res.error) throw new Error(res.error);
                    if (res.has_update) {
                        stat.className = 'status active';
                        stat.innerHTML = `${t('update_available', {version: res.latest})} <a href="${res.url}" target="_blank" style="text-decoration:underline;margin-left:8px;color:inherit;">${t('download')}</a>`;
                    } else {
                        stat.textContent = t('latest_version_installed');
                    }
                } catch(e) {
                    stat.className = 'status error';
                    stat.textContent = t('check_error');
                } finally {
                    this.disabled = false;
                    this.textContent = t('check_updates');
                }
            });
        }
    },

    async detail({hash, title, magnet, targetSeason, targetEpisode}) {
        document.getElementById('back-btn').onclick = goBack;
        document.getElementById('detail-title').textContent = title;

        const filesDiv = document.getElementById('detail-files');

        // Fire off metadata request in background
        API.get(`/api/library/meta/search?q=${encodeURIComponent(title)}`).then(results => {
            if (results && results.length > 0) {
                const meta = results[0];
                if (meta.overview) {
                    document.getElementById('detail-overview').textContent = meta.overview;
                }
            }
        }).catch(e => console.error("Meta search failed:", e));



        // Add magnet if provided (new search result)
        if (magnet) {
            try {
                filesDiv.innerHTML = `<div class="notice">${t('searching_torrents')}...</div>`;
                const resp = await API.post('/api/player/add_magnet', {magnet, title});
                if (resp && resp.hash) { hash = resp.hash; }
                // Give TorrServer ~2s to parse the torrent
                await sleep(2000);
            } catch (e) {
                filesDiv.innerHTML = `<div class="notice">${t('error', {error: ''})} ${esc(e.message)}</div>
                <button id="reload-files-btn" class="secondary" data-hash="${esc(hash)}" data-title="${esc(title)}">${t('retry')}</button>`;
                const btn = document.getElementById('reload-files-btn');
                if(btn) btn.onclick = e => reloadFiles(e.currentTarget.dataset.hash, e.currentTarget.dataset.title);
                return;
            }
        }

        let attempts = 0;
        let foundFiles = false;

        while (attempts < 30 && !foundFiles && state.page === 'detail') {
            filesDiv.innerHTML = `<div class="notice">
                ${t('loading_files_dht')}
                <div style="margin-top:8px; font-size:13px; color:var(--text-muted)">
                    ${t('attempt_of', {attempt: attempts + 1, total: 30})}
                </div>
            </div>`;
            const btn = document.getElementById('reload-files-btn');
            if(btn) btn.addEventListener('click', e => reloadFiles(e.currentTarget.dataset.hash, e.currentTarget.dataset.title));
            
            try {
                const files = await API.get(`/api/library/torrents/${hash}/files?title=${encodeURIComponent(title || '')}`);
                if (files && ((files.flat_files && files.flat_files.length > 0) || files.length > 0)) {
                    const isGrouped = files.type === 'series';
                    const seasonsObj = files.seasons || {};
                    const movies = files.movies || files;
                    
                    let seasonsHTML = '';
                    if (isGrouped && (Object.keys(seasonsObj).length > 0 || movies.length > 0)) {
                        const seasonsKeys = Object.keys(seasonsObj).sort((a,b) => parseInt(a) - parseInt(b));
                        const options = seasonsKeys.map(s => `<option value="${s}">${t('season_prefix')} ${s}</option>`).join('');
                        const extraOption = movies.length > 0 ? `<option value="movies">${t('movies_outside_seasons')}</option>` : '';
                        seasonsHTML = `
                            <select id="season-selector" class="season-select" onchange="renderSeason(this.value, '${esc(hash)}')">
                                ${options}
                                ${extraOption}
                            </select>
                        `;
                    }
                    
                    window._currentTorrentData = files;
                    filesDiv.innerHTML = seasonsHTML + `<div id="season-files"></div>`;
                    
                    if (isGrouped && Object.keys(seasonsObj).length > 0) {
                        let seasonToRender = Object.keys(seasonsObj).sort((a,b) => parseInt(a) - parseInt(b))[0];
                        if (targetSeason && seasonsObj[targetSeason]) {
                            seasonToRender = targetSeason;
                            const sel = document.getElementById('season-selector');
                            if (sel) sel.value = targetSeason;
                        }
                        window.renderSeason(seasonToRender, hash);
                    } else {
                        window.renderSeason('movies', hash);
                    }

                    foundFiles = true;
                    break;
                }
            } catch (e) {
                // Ignore errors during polling, it will retry
            }
            
            attempts++;
            if (!foundFiles && state.page === 'detail') {
                await sleep(2000);
            }
        }

        if (!foundFiles && state.page === 'detail') {
            filesDiv.innerHTML = `
                <div class="notice">
                    ${t('dead_torrent_warning')}
                    <button class="secondary" style="margin-top:12px" id="reload-files-btn" data-hash="${esc(hash)}" data-title="${esc(title)}">
                        🔄 ${t('try_again')}
                    </button>
                </div>`;
            const btn = document.getElementById('reload-files-btn');
            if(btn) btn.addEventListener('click', e => reloadFiles(e.currentTarget.dataset.hash, e.currentTarget.dataset.title));
        }
    },
};

// ── Loaders ──────────────────────────────────────────────────────────────────
async function loadContinue() {
    const sec = document.getElementById('continue-section');
    try {
        const recent = await API.get('/api/library/recent');
        if (!recent.length) return;
        sec.innerHTML = `
            <div class="section-heading"><h2>${t('continue_watching')}</h2></div>
            <div class="continue-list">
                ${recent.map(r => {
                    const pct = r.playback_duration ? r.playback_timecode / r.playback_duration : 0;
                    return `
                    <div class="continue-item-wrapper" style="display: flex; gap: 8px; margin-bottom: 8px;">
                        <button class="continue-item" style="flex: 1"
                            data-hash="${esc(r.torrent_hash)}"
                            data-file-id="${r.file_index}"
                            data-file-name="${esc(r.file_name)}"
                            data-title="${esc(r.title || r.file_name)}"
                            data-start-time="${r.playback_timecode || 0}"
                            onclick="playFile(this)">
                            <div style="width: 48px; height: 72px; border-radius: 4px; overflow: hidden; background: rgba(255,255,255,0.05); display: flex; align-items: center; justify-content: center;">
                                ${r.poster_url ? `<img src="${r.poster_url}" style="width:100%;height:100%;object-fit:cover;">` : `<span style="opacity:0.3;font-size:20px;">🎬</span>`}
                            </div>
                            <div>
                                <strong>${esc(r.title || r.file_name)}</strong>
                                <small>${esc(r.file_name)}</small>
                            </div>
                            <progress value="${r.playback_timecode || 0}" max="${r.playback_duration || 1}"></progress>
                            <span>${r.is_watched ? t('watched') : formatTime(r.playback_timecode || 0)}</span>
                        </button>
                        <button class="secondary" style="align-self: center; padding: 12px; color: #f87171"
                            data-hash="${esc(r.torrent_hash)}"
                            title="${t('remove_from_history')}"
                            onclick="event.stopPropagation(); removeHistory(this)">
                            ❌
                        </button>
                    </div>`;
                }).join('')}
            </div>`;
    } catch {}
}

const POPULAR_CACHE = {};
async function loadPopular(id, url, heading) {
    const sec = document.getElementById(`popular-${id}`);
    if (!sec) return;
    try {
        if (!POPULAR_CACHE[id]) {
            sec.innerHTML = `<div class="section-heading"><h2>${heading}</h2></div><div class="notice">Загрузка...</div>`;
            POPULAR_CACHE[id] = await API.get(url);
        }
        const movies = POPULAR_CACHE[id];
        if (!movies.length) { sec.innerHTML = ''; return; }
        sec.innerHTML = `
            <div class="section-heading"><h2>${heading}</h2></div>
            <div class="poster-grid">
                ${movies.map(m => `
                    <button class="card"
                        data-imdb="${esc(m.id)}"
                        data-title="${esc(m.title)}"
                        data-type="${id === 'series' ? 'series' : 'movie'}"
                        onclick="openCatalogDetail(this)">
                        <div class="poster">
                            ${m.poster_url
                                ? `<img src="${esc(m.poster_url)}" alt="${esc(m.title)}" loading="lazy">`
                                : `<div style="display:grid;place-items:center;height:100%;color:var(--text-muted);font-size:13px;padding:8px;text-align:center">${esc(m.title)}</div>`
                            }
                        </div>
                        <strong>${esc(m.title)}</strong>
                        <small>${m.year || ''} ${m.rating ? '★ ' + m.rating.toFixed(1) : ''}</small>
                    </button>`).join('')}
            </div>`;
    } catch (e) {
        sec.innerHTML = `<div class="notice">Не удалось загрузить каталог: ${esc(e.message)}</div>`;
    }
}

// ── Actions ──────────────────────────────────────────────────────────────────
function openDetail(btn) {
    navigate('detail', {
        hash: btn.dataset.hash,
        title: btn.dataset.title,
        magnet: btn.dataset.magnet,
        targetSeason: btn.dataset.season,
        targetEpisode: btn.dataset.episode
    });
}

function openDetailByHash(btn) {
    navigate('detail', {
        hash: btn.dataset.hash,
        title: btn.dataset.title,
        magnet: null,
    });
}

async function openCatalogDetail(btn) {
    navigate('meta', { imdb: btn.dataset.imdb, title: btn.dataset.title, type: btn.dataset.type, poster: btn.querySelector('img')?.src });
}

async function reloadFiles(hash, title) {
    navigate('detail', {hash, title, magnet: null});
}

window.renderSeason = function(seasonKey, hash) {
    const data = window._currentTorrentData;
    if (!data) return;
    const isMovies = seasonKey === 'movies';
    const list = isMovies ? (data.movies || data) : (data.seasons[seasonKey] || []);
    
    const container = document.getElementById('season-files');
    if (!container) return;
    
    container.innerHTML = `<div class="files">${
        list.map((f, i) => {
            let hasNext = false;
            if (data.flat_files && data.flat_files.length > 1) {
                const idx = data.flat_files.findIndex(x => x.id === f.id);
                hasNext = idx >= 0 && idx < data.flat_files.length - 1;
            } else if (!data.flat_files) {
                hasNext = list.length > 1 && i < list.length - 1;
            }
            return `
            <div class="file">
                <strong>${esc(f.name)}</strong>
                <small>${formatSize(f.length)}</small>
                <div style="display: flex; gap: 8px">
                    ${hasNext ? `
                        <button class="secondary"
                            data-hash="${esc(hash)}"
                            data-file-id="${f.id}"
                            onclick="playNext(this)">
                            ⏭ ${t('continue')}
                        </button>
                    ` : ''}
                    <button class="primary"
                        data-hash="${esc(hash)}"
                        data-file-id="${f.id}"
                        data-file-name="${esc(f.name)}"
                        data-start-time="${f.playback_timecode || 0}"
                        onclick="playFile(this)">
                        ${t('play')}
                    </button>
                </div>
            </div>`;
        }).join('')
    }</div>`;
};

async function playFile(btn) {
    const isContinue = btn.classList.contains('continue-item');
    const originalLabel = btn.querySelector('strong') || btn;
    btn.disabled = true;
    if (!isContinue) btn.textContent = '…';
    try {
        await API.post('/api/player/play', {
            hash: btn.dataset.hash,
            file_id: parseInt(btn.dataset.fileId),
            file_name: btn.dataset.fileName,
            start_time: parseInt(btn.dataset.startTime || 0),
        });
        if (!isContinue) btn.textContent = t('play');
    } catch (e) {
        alert(t('mpv_start_error', {error: e.message}));
        if (!isContinue) btn.textContent = t('play');
    } finally {
        btn.disabled = false;
    }
}

async function stopPlayback() {
    try {
        await API.post('/api/player/stop', {});
    } catch (e) {
        console.error("Failed to stop player:", e);
    }
}

window.stopPlayback = stopPlayback;

async function playNext(btn) {
    btn.disabled = true;
    const oldText = btn.textContent;
    btn.textContent = '…';
    try {
        await API.post('/api/player/next', {
            hash: btn.dataset.hash,
            file_id: parseInt(btn.dataset.fileId)
        });
    } catch (e) {
        alert(t('start_error', {error: e.message}));
    } finally {
        btn.textContent = oldText;
        btn.disabled = false;
    }
}

async function removeTorrent(btn) {
    if (!confirm(t('confirm_delete_from_ts'))) return;
    const hash = btn.dataset.hash;
    btn.disabled = true;
    try {
        await API.del(`/api/player/torrent/${hash}`);
        navigate('library');
    } catch (e) {
        alert(e.message);
        btn.disabled = false;
    }
}

window.deleteSelectedTorrents = async function() {
    const checkboxes = document.querySelectorAll('.lib-checkbox:checked');
    if (checkboxes.length === 0) {
        alert(t('select_torrents_to_delete'));
        return;
    }
    if (!confirm(t('confirm_delete_multiple_ts', {count: checkboxes.length}))) return;
    
    for (const cb of checkboxes) {
        cb.disabled = true;
        try {
            await API.del(`/api/player/torrent/${cb.value}`);
        } catch (e) {
            console.error('Failed to remove', cb.value, e);
        }
    }
    navigate('library');
};

window.deleteAllTorrents = async function() {
    const all = document.querySelectorAll('.lib-checkbox');
    if (all.length === 0) return;
    if (!confirm(t('confirm_delete_all_ts', {count: all.length}))) return;

    for (const cb of all) {
        try {
            await API.del(`/api/player/torrent/${cb.value}`);
        } catch (e) {
            console.error('Failed to remove', cb.value, e);
        }
    }
    navigate('library');
};

// ── Helpers ──────────────────────────────────────────────────────────────────
function esc(str) {
    return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function formatTime(secs) {
    if (!secs) return '';
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    return h
        ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
        : `${m}:${String(s).padStart(2,'0')}`;
}

function formatSize(bytes) {
    if (!bytes) return '';
    if (bytes > 1e9) return (bytes / 1e9).toFixed(1) + ' ' + t('gb');
    if (bytes > 1e6) return (bytes / 1e6).toFixed(0) + ' ' + t('mb');
    return (bytes / 1e3).toFixed(0) + ' ' + t('kb');
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── Nav wiring ────────────────────────────────────────────────────────────────
document.querySelectorAll('.nav button[data-page]').forEach(btn => {
    btn.addEventListener('click', () => {
        if (btn.dataset.page === 'search' && state.page !== 'search') {
            state.searchQuery = '';
            state.searchHTML = '';
        }
        navigate(btn.dataset.page);
    });
});

// Init
(async function() {
    await loadI18n();
    navigate('home');
    document.querySelectorAll('[data-i18n]').forEach(el => el.textContent = t(el.dataset.i18n));
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => el.placeholder = t(el.dataset.i18nPlaceholder));
    
    API.get('/api/settings/health').then(h => { if(h.error) alert(h.error + '\n\n' + t('ts_download_prompt')); }).catch(console.error);
})();

window.downloadBackup = () => {
    const a = document.createElement('a');
    a.href = '/api/settings/backup';
    a.download = 'pirate_cinema_backup.zip';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
};

window.loadDiagnostics = async () => {

    const out = document.getElementById('diag-output');

    out.style.display = 'grid';

    try {

        const d = await API.get('/api/settings/diagnostics');

        document.getElementById('diag-ts').textContent = d.torrserver_version;

        document.getElementById('diag-mpv').textContent = d.mpv_path;

        document.getElementById('diag-db').textContent = formatSize(d.db_size);

        document.getElementById('diag-err').textContent = d.last_error || t('no_errors');

    } catch(e) {

        document.getElementById('diag-err').textContent = t('load_error', {error: e.message});

    }

};



window.uploadBackup = async (input) => {
    const file = input.files[0];
    if (!file) return;
    if (!confirm(t('confirm_restore'))) {
        input.value = '';
        return;
    }
    
    try {
        const res = await fetch('/api/settings/restore', { method: 'POST', body: file, headers: { 'Content-Type': 'application/zip' } });
        if (!res.ok) throw new Error(await res.text());
        alert(t('restore_success'));
        location.reload();
    } catch (e) {
        alert(t('restore_error', {error: e.message}));
    }
    input.value = '';
};

window.removeHistory = async (btn) => {
    const hash = btn.dataset.hash;
    if(!confirm(t('confirm_delete_history'))) return;
    try {
        await API.del('/api/library/history/' + hash);
        btn.closest('.continue-item-wrapper').remove();
        const list = document.querySelector('.continue-list');
        if (list && list.children.length === 0) {
            document.getElementById('continue-section').innerHTML = '';
        }
    } catch(e) {
        alert(t('error', {error: e.message}));
    }
};
