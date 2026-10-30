// Run with NODE_PATH pointing to a Playwright installation.
const { chromium } = require('playwright');
const { execFileSync } = require('node:child_process');
const assert = require('node:assert/strict');
const path = require('node:path');
const os = require('node:os');
const fs = require('node:fs');

(async () => {
  const html = execFileSync('python', ['-c', 'from backend.services.remote_html import REMOTE_HTML; import sys; sys.stdout.buffer.write(REMOTE_HTML.encode("utf-8"))']).toString('utf8');
  const browser = await chromium.launch({ headless: true, channel: process.env.REMOTE_BROWSER || 'msedge' });
  try {
    for (const width of [320, 390, 768]) {
      const page = await browser.newPage({ viewport: { width, height: 844 } });
      const errors = [];
      const commands = [];
      let offline = false;
      const state = { active:true, hash:'test', file_id:1, file_name:'Сериал · S01E01', duration:3600, timecode:60, is_ready:true, volume:55, is_paused:false, track_list:[] };
      page.on('pageerror', error => errors.push(error.message));
      await page.route('http://remote.test/**', async route => {
        const url = new URL(route.request().url());
        if (url.pathname === '/') return route.fulfill({ contentType:'text/html', body:html });
        if (url.pathname === '/logo.png') return route.fulfill({contentType:'image/png',body:fs.readFileSync('static/logo.png')});
        if (offline) return route.abort();
        let data = {};
        if (url.pathname === '/api/player/active') data = state;
        else if (url.pathname === '/api/window/state') data = {is_pip:false,is_fullscreen:false};
        else if (url.pathname.endsWith('/files')) data = {seasons:{1:[{id:1,name:'S01E01',is_watched:true},{id:2,name:'S01E02'}]}};
        else if (route.request().method() === 'POST') commands.push({url:url.pathname, body:route.request().postDataJSON()});
        await route.fulfill({json:data});
      });
      await page.goto('http://remote.test/');
      await page.locator('#btnEpisodes:not([hidden])').waitFor();
      assert.equal(await page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(9, 11, 16)');
      assert.equal(await page.locator('#btnPlayPause').evaluate(el => getComputedStyle(el).boxShadow), 'none');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.locator('#btnPlayPause').click();
      assert.ok(commands.some(command => command.body?.[0] === 'cycle'));
      await page.getByRole('button', {name:'Громче на 5 процентов'}).click();
      await page.waitForFunction(() => document.getElementById('volLevel').textContent === '60%');
      await page.locator('#btnEpisodes').click();
      await page.locator('#episodeList button[aria-current]').nth(1).click();
      assert.ok(commands.some(command => command.url === '/api/player/play' && command.body.file_id === 2));
      await page.getByRole('button', {name:'Экран',exact:true}).click();
      assert.equal(await page.locator('#screenSheet').evaluate(dialog => dialog.open), true);
      await page.getByRole('button', {name:'Обычное окно',exact:true}).click();
      await page.locator('#screenSheet').waitFor({state:'hidden'});
      await page.locator('#tabSearchBtn').click();
      await page.locator('#miniPlayer').waitFor({state:'visible'});
      await page.locator('.mini-title').click();
      await page.screenshot({path:path.join(process.env.REMOTE_SCREENSHOT_DIR || os.tmpdir(), 'pirate-remote-' + width + '.png'), fullPage:true});
      await page.evaluate(() => {
        const slider = document.getElementById('seekSlider');
        slider.value = 120;
        slider.dispatchEvent(new Event('input'));
      });
      assert.ok(await page.locator('#seekPreview').textContent());
      await Promise.all([
        page.waitForResponse(response => response.url().endsWith('/api/player/command') && response.request().postDataJSON()?.[0] === 'seek'),
        page.locator('#seekSlider').dispatchEvent('change'),
      ]);
      assert.ok(commands.some(command => command.body?.[0] === 'seek' && command.body[1] === 120));
      offline = true;
      await page.evaluate(() => pollState());
      assert.equal(await page.locator('#btnPlayPause').isDisabled(), true);
      offline = false;
      await page.evaluate(() => pollState());
      assert.equal(await page.locator('#btnPlayPause').isDisabled(), false);
      assert.deepEqual(errors, []);
      console.log('Remote interactions and layout passed: ' + width + 'px');
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
