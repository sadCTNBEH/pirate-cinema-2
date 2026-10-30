// Real MKV -> HLS -> browser playback, resume, seeks, pairing recovery and cleanup.
const {chromium, webkit} = require('playwright');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
const path = require('node:path');
const os = require('node:os');

(async () => {
  const server = spawn('python', ['tests/mobile_ui_server.py'], {stdio:['ignore','pipe','inherit']});
  let browser;
  try {
    const port = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Fixture startup timed out')), 30000);
      server.once('exit', code => {clearTimeout(timer); reject(new Error('Fixture exited: ' + code));});
      server.stdout.once('data', data => {clearTimeout(timer); resolve(Number(data.toString().trim()));});
    });
    const base = 'http://127.0.0.1:' + port;
    let health;
    for (let i = 0; i < 100; i++) {
      try { health = await (await fetch(base + '/health')).json(); break; } catch {}
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(health?.ready);
    browser = process.env.REMOTE_ENGINE === 'webkit'
      ? await webkit.launch({headless:true})
      : await chromium.launch({headless:true, channel:process.env.REMOTE_BROWSER || 'msedge'});
    const context = await browser.newContext({viewport:{width:390,height:844}});
    let page = await context.newPage();
    const errors = [];
    page.on('response', async r => {
      if (r.url().includes('/hls/') && r.status() >= 400) console.log('HLS error', r.status(), r.url());
    });
    page.on('pageerror', e => errors.push(e.message));
    await context.route(base + '/api/player/active', r => r.fulfill({json:{active:false}}));
    await context.route(base + '/api/window/state', r => r.fulfill({json:{}}));
    await page.goto(base + '/remote#pair=' + health.code);
    await page.waitForFunction(() => !!sessionStorage.getItem('pcRemoteToken'));
    // A new Safari tab has no sessionStorage; cookies may also be unavailable.
    await context.clearCookies();
    await page.close();
    page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base + '/remote');
    console.log('Engine:', process.env.REMOTE_ENGINE || 'chromium', 'native HLS:', await page.evaluate(() => document.getElementById('phoneVideo').canPlayType('application/vnd.apple.mpegurl')));
    const assertPaired = async () => {
      const data = await page.evaluate(() => phoneApi('/api/remote/mobile', {hash:'a'.repeat(40), file_id:1}));
      assert.equal(data.resume, 9);
      const playlist = await context.request.get(base + data.url);
      assert.equal(playlist.status(), 200);
      assert.ok((await playlist.text()).startsWith('#EXTM3U'));
      await page.evaluate(token => phoneApi('/api/remote/mobile/' + token + '/progress', {sequence:1, close:true}), data.token);
    };
    await assertPaired();
    // Recover lost tab/cookie credentials from the previously scanned QR capability.
    await page.evaluate(() => {
      localStorage.removeItem('pcRemoteToken');
      sessionStorage.clear();
    });
    await context.clearCookies();
    await page.reload();
    await assertPaired();
    // Existing device credentials remain valid after restarting the PC server.
    await context.request.post(base + '/simulate-restart');
    await context.clearCookies();
    await page.reload();
    await assertPaired();
    console.log('Pairing after a new tab, missing credentials and PC restart passed');
    if (process.env.REMOTE_ENGINE === 'webkit' && !await page.evaluate(() => window.Hls?.isSupported() || document.getElementById('phoneVideo').canPlayType('application/vnd.apple.mpegurl'))) {
      console.log('Windows WebKit runtime has no HLS/H.264 decoder; playback requires Safari on a device');
      return;
    }
    await page.evaluate(() => startPhone({hash:'a'.repeat(40), file_id:1, file_name:'movie.mkv'}));
    console.log('Mobile session prepared');
    assert.equal(await page.locator('#phoneTitle').textContent(), 'Show.S01E01.mkv');
    assert.equal(await page.locator('#phoneResume').textContent(), 'Продолжить с 00:09');
    assert.equal(await page.locator('#phoneResume').isVisible(), true);
    assert.equal(await page.locator('#phonePlayer').getByRole('button', {name:'На весь экран', exact:true}).count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({path:path.join(process.env.REMOTE_SCREENSHOT_DIR || os.tmpdir(), 'pirate-mobile-resume.png'),fullPage:true});
    await page.locator('#phoneResume').click();
    console.log('Resume requested');
    await page.waitForFunction(() => {
      const v = document.getElementById('phoneVideo');
      return !v.paused && v.currentTime >= 10 && v.videoWidth > 0;
    }, {timeout:30000});
    // Seek beyond the initial generation window, then back to an evicted segment.
    for (const target of [47, 3]) {
      console.log('Seeking to ' + target);
      await page.evaluate(t => {document.getElementById('phoneVideo').currentTime = t;}, target);
      await page.waitForFunction(t => {
        const v = document.getElementById('phoneVideo');
        return !v.seeking && !v.paused && v.currentTime > t + .3 && v.currentTime < t + 4;
      }, target, {timeout:30000}).catch(async error => {
        console.log(await page.evaluate(() => {
          const v = document.getElementById('phoneVideo');
          return {time:v.currentTime, paused:v.paused, seeking:v.seeking, ready:v.readyState,
            error:v.error?.message, message:document.getElementById('phoneMessage').textContent,
            buffered:Array.from({length:v.buffered.length}, (_, i) => [v.buffered.start(i),v.buffered.end(i)])};
        }));
        throw error;
      });
    }
    await page.locator('#phoneNext').click();
    await page.waitForFunction(() => document.getElementById('phonePlayBtn').hidden === false);
    assert.equal(await page.locator('#phoneTitle').textContent(), 'Show.S01E02.mkv');
    assert.equal(await page.evaluate(() => phoneSession.file_id), 2);
    assert.equal(await page.locator('#phoneResume').isHidden(), true);
    assert.equal(await page.evaluate(() => phoneSession.resume), 0);
    assert.equal(await page.locator('#phoneNext').isHidden(), true);
    assert.equal(await page.locator('#phonePrevious').isVisible(), true);
    await page.screenshot({path:path.join(process.env.REMOTE_SCREENSHOT_DIR || os.tmpdir(), 'pirate-mobile-previous.png'),fullPage:true});
    await page.locator('#phonePlayBtn').click();
    await page.waitForFunction(() => {
      const video = document.getElementById('phoneVideo');
      return !video.paused && video.currentTime > .5 && video.videoWidth > 0;
    });
    console.log('Next episode title and real playback passed');
    await page.locator('#phonePrevious').click();
    await page.waitForFunction(() => !document.getElementById('phonePlayBtn').hidden);
    assert.equal(await page.locator('#phoneTitle').textContent(), 'Show.S01E01.mkv');
    assert.equal(await page.evaluate(() => phoneSession.file_id), 1);
    assert.equal(await page.locator('#phonePrevious').isHidden(), true);
    assert.equal(await page.locator('#phoneNext').isVisible(), true);
    assert.equal(await page.locator('#phoneResume').textContent(), 'Продолжить с 00:09');
    assert.equal(await page.locator('#phoneResume').isVisible(), true);
    console.log('Previous episode navigation and separate resume times passed');
    assert.deepEqual(errors, []);
    await page.locator('#phoneBack').click();
    console.log('Real mobile HLS playback, cookie-less resume and bidirectional seeks passed');
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
