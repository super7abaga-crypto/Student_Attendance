/*
 * Engineer A - responsive audit for the student portal.
 *
 * Drives a real browser at desktop, tablet and phone viewports against the portal
 * and whatever API the portal is pointed at (local mock or Partner B's Django).
 * Device emulation is NOT a physical-device test: it proves layout, touch sizing
 * and overflow, nothing about a real camera or GPS chip.
 *
 *   PORTAL_URL=http://127.0.0.1:8020/index.html \
 *   PORTAL_USER=demo_student PORTAL_PASS=demo12345 node responsive-test.js
 */
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const PORTAL = process.env.PORTAL_URL || 'http://127.0.0.1:8020/index.html';
const USER = process.env.PORTAL_USER || 'demo_student';
const PASS = process.env.PORTAL_PASS || 'demo12345';
const SHOTS = process.env.SHOTS || path.join(__dirname, 'screenshots-responsive');
const CHROME = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const API = process.env.API_BASE || 'http://127.0.0.1:8010/api/v1';

fs.mkdirSync(SHOTS, { recursive: true });
let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log('  PASS  ' + name); }
  else { fail++; console.log('  FAIL  ' + name + (detail ? '  ->  ' + String(detail).slice(0, 160) : '')); }
};

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900, isMobile: false, dsf: 1 },
  { name: 'tablet', width: 834, height: 1112, isMobile: true, dsf: 2 },
  { name: 'phone', width: 390, height: 844, isMobile: true, dsf: 3 },
];

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, args: ['--no-sandbox', '--use-fake-ui-for-media-stream'] });
  for (const vp of VIEWPORTS) {
    const context = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      isMobile: vp.isMobile, hasTouch: vp.isMobile, deviceScaleFactor: vp.dsf,
      geolocation: { latitude: 4.8156, longitude: 7.0498 }, permissions: ['geolocation'],
    });
    await context.addInitScript((api) => { window.LEARN2EARN_API_BASE = api; }, API);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));

    console.log('\n' + vp.name + ' ' + vp.width + 'x' + vp.height);
    await page.goto(PORTAL, { waitUntil: 'networkidle' });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    check(vp.name + ': login has no horizontal overflow', overflow <= 1, 'overflow=' + overflow);
    const box = await page.locator('#loginFormEl button[type=submit]').boundingBox();
    check(vp.name + ': login button at least 40px tall', !!box && box.height >= 40, box && box.height);
    await page.screenshot({ path: path.join(SHOTS, vp.name + '-01-login.png'), fullPage: true });

    await page.fill('#loginUsername', USER);
    await page.fill('#loginPassword', PASS);
    await page.click('#loginFormEl button[type=submit]');
    await page.waitForTimeout(1500);
    const loggedIn = await page.isVisible('#dashboardView');
    check(vp.name + ': dashboard renders after login', loggedIn);
    if (loggedIn) {
      const o = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      check(vp.name + ': dashboard has no horizontal overflow', o <= 1, 'overflow=' + o);
      check(vp.name + ': checkpoint panel present', (await page.locator('#checkpointRows tr').count()) >= 3);
      check(vp.name + ': profile campus shown', ((await page.textContent('#profileCampus')) || '').trim().length > 0);
      await page.screenshot({ path: path.join(SHOTS, vp.name + '-02-dashboard.png'), fullPage: true });

      const menu = page.locator('.mobile-menu').first();
      if (await menu.isVisible().catch(() => false)) {
        await menu.click();
        await page.waitForTimeout(400);
        const opened = await page.evaluate(() => document.getElementById('sidebar').classList.contains('open'));
        check(vp.name + ': mobile menu opens the sidebar', opened);
      }
      const hist = page.locator('[data-go="history"]').first();
      if (await hist.count()) {
        await hist.click(); await page.waitForTimeout(500);
        const ho = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        check(vp.name + ': history has no horizontal overflow', ho <= 1, 'overflow=' + ho);
        check(vp.name + ': history rows render', (await page.locator('#historyRows tr').count()) >= 1);
        await page.screenshot({ path: path.join(SHOTS, vp.name + '-03-history.png'), fullPage: true });
      }
      const scan = page.locator('.nav-item[data-view="scanner"]').first();
      if (await scan.count()) {
        if (await menu.isVisible().catch(() => false)) {
          const open = await page.evaluate(() => document.getElementById('sidebar').classList.contains('open'));
          if (!open) { await menu.click(); await page.waitForTimeout(400); }
        }
        await scan.click(); await page.waitForTimeout(800);
        const so = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        check(vp.name + ': scan view has no horizontal overflow', so <= 1, 'overflow=' + so);
        check(vp.name + ': scan view is the visible view', await page.isVisible('#scannerView'));
        const startBtn = page.locator('#startScanBtn, #scanStart, [data-action="start-scan"]').first();
        check(vp.name + ': a scan control is reachable', (await startBtn.count()) > 0);
        await page.screenshot({ path: path.join(SHOTS, vp.name + '-04-scan.png'), fullPage: true });
      }
    }
    check(vp.name + ': no page errors', errors.length === 0, errors.join(' | '));
    await context.close();
  }
  await browser.close();
  console.log('\nRESULT: ' + pass + ' passed, ' + fail + ' failed');
  process.exit(fail === 0 ? 0 : 1);
})();
