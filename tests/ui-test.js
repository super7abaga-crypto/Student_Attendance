/*
 * Engineer A — browser test suite for the student portal.
 *
 * Runs against the local mock (server.py) or any deployment that implements
 * Engineer B's contract. It never asserts on production data: it resets the
 * mock first, so it only runs against a mock/dev host.
 *
 *   npm install         (once, inside tests/)
 *   npm test            (mock must already be running: python3 server.py)
 *
 * Env: BASE_URL (default http://127.0.0.1:8000), CHROME_PATH, SHOT_DIR
 */
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const BASE_URL = (process.env.BASE_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
const BASE = BASE_URL + '/student/';
const SHOTS = process.env.SHOT_DIR || path.join(__dirname, 'screenshots');
fs.mkdirSync(SHOTS, { recursive: true });

function chromePath() {
  const candidates = [
    process.env.CHROME_PATH,
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  ].filter(Boolean);
  const found = candidates.find((p) => fs.existsSync(p));
  if (!found) {
    throw new Error('Chrome not found. Set CHROME_PATH to your Chrome/Chromium binary.');
  }
  return found;
}
let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log('  PASS  ' + name); }
  else { fail++; console.log('  FAIL  ' + name + (detail ? '  ->  ' + String(detail).slice(0, 160) : '')); }
};
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch({
    executablePath: chromePath(),
    args: ['--no-sandbox', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
  });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    permissions: ['geolocation'],
    geolocation: { latitude: 6.5244, longitude: 3.3792, accuracy: 15 },
  });
  const page = await context.newPage();
  // Reset the mock to a known state so counts are deterministic.
  await page.goto(BASE);
  await page.evaluate(async () => { await fetch('/api/v1/dev/reset', { method: 'POST' }); });
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(String(e)));

  console.log('\n1. Login screen and enrollment notice');
  await page.goto(BASE, { waitUntil: 'networkidle' });
  check('login card visible', await page.isVisible('#loginForm'));
  const enroll = await page.textContent('#enrollNote');
  check('mentor-enrollment message present', /must be created by a mentor or administrator/i.test(enroll), enroll);
  check('no register form in DOM', (await page.locator('#registerForm').count()) === 0);
  check('12-hour session note present', /12 hours/i.test(await page.textContent('.session-note')));
  check('API base shown', /\/api\/v1/.test(await page.textContent('#connectionNote')), await page.textContent('#connectionNote'));
  await page.screenshot({ path: path.join(SHOTS, '01-login-desktop.png') });

  console.log('\n2. Invalid login');
  await page.fill('#loginUsername', 'demo_student');
  await page.fill('#loginPassword', 'wrong-password');
  await page.click('#loginFormEl button[type=submit]');
  await sleep(700);
  check('error shown for bad password', /Incorrect username or password/i.test(await page.textContent('#authAlert')), await page.textContent('#authAlert'));
  check('still on login screen', await page.isVisible('#loginForm'));

  console.log('\n2b. Campus label handling (UUID in `campus`, label in `campus_name`)');
  await page.route('**/auth/student/login/', async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.student = {
      ...body.student,
      campus: '4da96615-fceb-44f2-ba96-7081f96becdb',
      campus_name: 'Lagos Campus',
    };
    await route.fulfill({ response, body: JSON.stringify(body) });
  });
  await page.fill('#loginPassword', 'demo12345');
  await page.click('#loginFormEl button[type=submit]');
  await page.waitForSelector('#authScreen.hidden', { timeout: 5000 }).catch(() => {});
  const campusText = (await page.textContent('#topCampus')).trim();
  check('campus shows the label, never the UUID', campusText === 'Lagos Campus', campusText);
  check('campus UUID kept as the identifier',
    (await page.evaluate(() => JSON.parse(sessionStorage.getItem('learn2earn.student.session') || '{}').student?.campus_id || '')) === '4da96615-fceb-44f2-ba96-7081f96becdb');
  await page.unroute('**/auth/student/login/');
  await page.click('#logoutBtn');
  await sleep(600);

  console.log('\n3. Valid login');
  await page.fill('#loginPassword', 'demo12345');
  await page.click('#loginFormEl button[type=submit]');
  await page.waitForSelector('#authScreen.hidden', { timeout: 5000 }).catch(() => {});
  check('portal opened', await page.isHidden('#authScreen'));
  check('full name in header', (await page.textContent('#topName')).trim() === 'Demo Student');
  check('username in header', (await page.textContent('#topUsername')).includes('demo_student'));
  check('campus in header', /Lagos Campus/.test(await page.textContent('#topCampus')), await page.textContent('#topCampus'));
  check('campus in profile', /Lagos Campus/.test(await page.textContent('#profileCampus')));
  const token = await page.evaluate(() => JSON.parse(sessionStorage.getItem('learn2earn.student.session') || '{}').token || '');
  check('token stored in sessionStorage', token.length > 20);
  check('no localStorage use', await page.evaluate(() => localStorage.length === 0));
  await page.waitForFunction(() => document.getElementById('statAttended').textContent !== '—', null, { timeout: 5000 }).catch(() => {});
  const attended = await page.textContent('#statAttended');
  check('dashboard records loaded', Number(attended) >= 1, 'attended=' + attended);
  const counts = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#historyRows tr')];
    const statuses = rows
      .map((tr) => tr.querySelector('.status-pill'))
      .filter(Boolean)
      .map((el) => String(el.getAttribute('data-status') || '').toLowerCase());
    return { total: statuses.length, absent: statuses.filter((s) => s === 'absent').length };
  });
  check('seeded history contains an absence to test against', counts.absent >= 1, JSON.stringify(counts));
  check('attendance count excludes absences',
    Number(attended) === counts.total - counts.absent,
    `attended=${attended} total=${counts.total} absent=${counts.absent}`);
  const lastStatus = await page.getAttribute('#recentRows tr:first-child .status-pill', 'data-status').catch(() => null);
  check('last check-in is never an absence', String(lastStatus || '').toLowerCase() !== 'absent', 'last=' + lastStatus);
  check('no attendance percentage card', (await page.locator('text=/Attendance rate/i').count()) === 0);
  check('last check-in card populated', (await page.textContent('#statLast')).match(/\d{2}:\d{2}/) !== null, await page.textContent('#statLast'));
  await page.screenshot({ path: path.join(SHOTS, '02-dashboard-desktop.png') });

  console.log('\n4. Session restoration after refresh');
  await page.reload({ waitUntil: 'networkidle' });
  await sleep(400);
  check('session restored after refresh', await page.isHidden('#authScreen'));
  check('student name restored', (await page.textContent('#topName')).trim() === 'Demo Student');

  console.log('\n5. Attendance history + month filtering');
  await page.click('.nav-item[data-view="history"]');
  await sleep(700);
  check('history view active', await page.isVisible('#historyView'));
  check('history rows rendered', (await page.locator('#historyRows tr').count()) >= 1);
  check('session label readable', /Morning Session|Afternoon Session|Evening Session/.test(await page.textContent('#historyRows')), await page.textContent('#historyRows'));
  check('status badge present', (await page.locator('#historyRows .status-pill').count()) >= 1);
  check('count text shows records', /record/.test(await page.textContent('#historyCount')), await page.textContent('#historyCount'));
  await page.screenshot({ path: path.join(SHOTS, '03-history-desktop.png') });
  await page.fill('#monthFilter', '2020-01');
  await page.dispatchEvent('#monthFilter', 'change');
  await sleep(300);
  check('empty state for month with no records', /No attendance recorded for 2020-01/.test(await page.textContent('#historyRows')), await page.textContent('#historyRows'));
  check('zero count shown', (await page.textContent('#historyCount')) === '0 records');
  const month = await page.evaluate(() => new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Lagos', year: 'numeric', month: '2-digit' }).format(new Date()));
  await page.fill('#monthFilter', month);
  await page.dispatchEvent('#monthFilter', 'change');
  await sleep(300);
  check('records return for current month', /record/.test(await page.textContent('#historyCount')) && !/No attendance/.test(await page.textContent('#historyRows')));

  console.log('\n6. Successful scan with GPS');
  await page.click('.nav-item[data-view="scanner"]');
  await sleep(300);
  check('scanner view active', await page.isVisible('#scannerView'));
  await page.screenshot({ path: path.join(SHOTS, '04-scanner-desktop.png') });
  const qr = await page.evaluate(async () => (await (await fetch('/api/v1/dev/qr?session=morning')).json()).payload);
  await page.evaluate((payload) => window.onQrDecoded(payload), qr);
  await page.waitForSelector('#confirmationModal:not(.hidden)', { timeout: 8000 }).catch(() => {});
  check('confirmation card opened', await page.isVisible('#confirmationModal'));
  check('confirmation name from backend', (await page.textContent('#confirmName')).trim() === 'Demo Student');
  check('confirmation session label', /Morning Session/.test(await page.textContent('#confirmSession')), await page.textContent('#confirmSession'));
  check('confirmation date', /\d{2} \w{3} \d{4}/.test(await page.textContent('#confirmDate')), await page.textContent('#confirmDate'));
  check('confirmation time', /\d{2}:\d{2}/.test(await page.textContent('#confirmTime')), await page.textContent('#confirmTime'));
  const statusText = (await page.textContent('#confirmStatus')).trim();
  const statusRaw = await page.getAttribute('#confirmStatus', 'data-status');
  check('attendance_action shown from backend', (await page.textContent('#confirmAction')).trim() === 'check_in', await page.textContent('#confirmAction'));
  // The badge must echo the backend's own value; the label is only a humanised copy.
  const expectedLabel = { present: 'PRESENT', late: 'LATE', absent: 'ABSENT', on_time: 'ON TIME' }[statusRaw];
  check('status comes from backend',
    ['present', 'late', 'absent', 'on_time'].includes(statusRaw) && statusText === expectedLabel,
    'data-status=' + statusRaw + ' label=' + statusText);
  await page.screenshot({ path: path.join(SHOTS, '05-confirmation-success.png') });
  await page.click('#closeConfirmation');
  await sleep(300);

  console.log('\n7. Duplicate scan keeps the original record');
  await page.evaluate((payload) => window.onQrDecoded(payload), qr);
  await page.waitForSelector('#confirmationModal:not(.hidden)', { timeout: 8000 }).catch(() => {});
  await sleep(300);
  check('duplicate message shown', /already completed this checkpoint/i.test(await page.textContent('#scanNotice')), await page.textContent('#scanNotice'));
  check('duplicate card opens with original record', /already recorded/i.test(await page.textContent('#confirmationTitle')), await page.textContent('#confirmationTitle'));
  check('original name preserved', (await page.textContent('#confirmName')).trim() === 'Demo Student');
  check('original time preserved', /\d{2}:\d{2}/.test(await page.textContent('#confirmTime')));
  await page.screenshot({ path: path.join(SHOTS, '06-duplicate.png') });
  await page.click('#closeConfirmation');
  await sleep(300);

  // Engineer B's real 409 carries no attendance object, so the portal must fall back to
  // the student's own history instead of showing an empty or invented card.
  await page.route('**/attendance/scan/', async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    delete body.attendance;
    delete body.record;
    await route.fulfill({ response, body: JSON.stringify(body) });
  });
  await page.evaluate((payload) => window.onQrDecoded(payload), qr);
  await page.waitForSelector('#confirmationModal:not(.hidden)', { timeout: 8000 }).catch(() => {});
  await sleep(400);
  check('409 without a body record still shows the history record',
    /already recorded/i.test(await page.textContent('#confirmationTitle')), await page.textContent('#confirmationTitle'));
  check('fallback record keeps the backend name', (await page.textContent('#confirmName')).trim() === 'Demo Student', await page.textContent('#confirmName'));
  check('fallback record keeps the backend time', /\d{2}:\d{2}/.test(await page.textContent('#confirmTime')), await page.textContent('#confirmTime'));
  await page.screenshot({ path: path.join(SHOTS, '06b-duplicate-from-history.png') });
  await page.click('#closeConfirmation');
  await page.unroute('**/attendance/scan/');

  console.log('\n7b. Checkpoint panel and per-checkpoint history');
  const checkpointRows = await page.$$eval('#checkpointRows tr', (rows) =>
    rows.map((row) => row.textContent.replace(/\s+/g, ' ').trim()));
  check('three checkpoints are listed for today', checkpointRows.length === 3, JSON.stringify(checkpointRows));
  const morningRow = checkpointRows.find((row) => /Morning/i.test(row)) || '';
  check('morning checkpoint shows a recorded state', /PRESENT|LATE/i.test(morningRow), morningRow);
  check('morning checkpoint shows the check-in action', /Check-in/i.test(morningRow), morningRow);
  check('later checkpoints are still open, not duplicates',
    checkpointRows.filter((row) => /NOT RECORDED YET/i.test(row)).length >= 1, JSON.stringify(checkpointRows));

  const historyHead = await page.$$eval('#historyView thead th', (cells) => cells.map((c) => c.textContent.trim()));
  check('history exposes an ACTION column', historyHead.includes('ACTION'), JSON.stringify(historyHead));
  const historyActions = await page.$$eval('#historyRows tr td[data-label="Action"]', (cells) => cells.map((c) => c.textContent.trim()));
  check('history rows show a humanised action', historyActions.every((value) => /Check-(in|out)/i.test(value)), JSON.stringify(historyActions.slice(0, 4)));
  const historySessions = await page.$$eval('#historyRows tr td[data-label="Session"]', (cells) => cells.map((c) => c.textContent.trim()));
  check('history names the checkpoint, not a generic day', historySessions.every((value) => /Morning|Afternoon|Evening/i.test(value)), JSON.stringify(historySessions.slice(0, 4)));
  await page.screenshot({ path: path.join(SHOTS, '10-checkpoints.png') });

  console.log('\n8. Expired QR');
  const expired = await page.evaluate(async () => {
    const r = await fetch('/api/v1/dev/qr?session=morning');
    const d = await r.json();
    return JSON.stringify({ version: 1, token: d.payload ? JSON.parse(d.payload).token : 'x', expires_at: 1 });
  });
  await page.evaluate((p) => window.onQrDecoded(p), expired);
  await sleep(1200);
  check('expired message shown', /expired/i.test(await page.textContent('#scanNotice')), await page.textContent('#scanNotice'));
  check('retry controls offered', await page.isVisible('#scanRetry'));
  await page.screenshot({ path: path.join(SHOTS, '07-expired-qr.png') });

  console.log('\n9. Malformed QR');
  await page.evaluate(() => window.onQrDecoded('https://example.com/not-an-attendance-code'));
  await sleep(1200);
  check('malformed QR rejected with clear message', /not recognised|not an attendance|invalid/i.test(await page.textContent('#scanNotice')), await page.textContent('#scanNotice'));

  console.log('\n10. Wrong campus');
  await context.setGeolocation({ latitude: 9.0579, longitude: 7.4951, accuracy: 15 });
  const freshQr = await page.evaluate(async () => (await (await fetch('/api/v1/dev/qr?session=afternoon')).json()).payload);
  await page.evaluate((p) => window.onQrDecoded(p), freshQr);
  await sleep(1500);
  check('wrong-campus message shown', /geofence|outside the campus|campus/i.test(await page.textContent('#scanNotice')), await page.textContent('#scanNotice'));
  await page.screenshot({ path: path.join(SHOTS, '08-wrong-campus.png') });

  console.log('\n10b. Backend error mapping: location_unconfigured and student_inactive');
  await context.setGeolocation({ latitude: 6.5244, longitude: 3.3792, accuracy: 15 });
  const stubScan = async (status, body) => {
    await page.route('**/api/v1/attendance/scan/', (route) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }));
  };
  const clearRoutes = () => page.unroute('**/api/v1/attendance/scan/');

  await stubScan(403, { success: false, code: 'location_unconfigured', message: 'Campus location is not configured.' });
  const errQr = await page.evaluate(async () => (await (await fetch('/api/v1/dev/qr?session=morning')).json()).payload);
  await page.evaluate((p) => window.onQrDecoded(p), errQr);
  await sleep(1200);
  const configNotice = await page.textContent('#scanNotice');
  check('location_unconfigured explains campus configuration',
    /campus location settings have not been configured/i.test(configNotice), configNotice);
  check('location_unconfigured does not blame the student',
    !/outside (your|the) campus|move closer/i.test(configNotice), configNotice);
  await clearRoutes();

  await stubScan(403, { success: false, code: 'student_inactive', message: 'Student account is inactive.' });
  await page.evaluate((p) => window.onQrDecoded(p), errQr);
  await sleep(1200);
  const inactiveNotice = await page.textContent('#scanNotice');
  check('student_inactive names the account problem', /account is inactive/i.test(inactiveNotice), inactiveNotice);
  check('student_inactive is not shown as a session problem', !/no active attendance session/i.test(inactiveNotice), inactiveNotice);
  await clearRoutes();

  console.log('\n10c. Duplicate with an unreadable history stays honest');
  await stubScan(409, { success: false, code: 'duplicate_attendance', message: 'Attendance has already been recorded for today.' });
  await page.route('**/api/v1/student/attendance-history/', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Server error' }) }));
  await page.evaluate((p) => window.onQrDecoded(p), errQr);
  await sleep(1400);
  const failedNotice = await page.textContent('#scanNotice');
  check('duplicate fallback names the checkpoint', /already completed this checkpoint/i.test(failedNotice) && !/for today|for this session/i.test(failedNotice), failedNotice);
  check('duplicate refresh failure is stated honestly',
    /could not refresh/i.test(failedNotice), failedNotice);
  await page.unroute('**/api/v1/student/attendance-history/');
  await clearRoutes();

  console.log('\n10d. Camera is released when leaving the scanner');
  await page.click('[data-view="scanner"]').catch(() => {});
  await sleep(300);
  await page.click('#startScanBtn').catch(() => {});
  await sleep(1800);
  const cameraOn = !(await page.isDisabled('#stopScanBtn'));
  await page.click('[data-view="history"]').catch(() => {});
  await sleep(1200);
  check('camera started for the lifecycle check', cameraOn);
  check('camera released after navigating away', await page.isDisabled('#stopScanBtn'));
  await page.click('[data-view="scanner"]').catch(() => {});
  await sleep(300);

  console.log('\n10e. Campus-local dates do not assume Africa/Lagos');
  const tzChecks = await page.evaluate(() => {
    const instant = new Date('2026-11-24T02:30:00Z');
    return {
      lagos: window.campusDateFor('Africa/Lagos', instant),
      saoPaulo: window.campusDateFor('America/Sao_Paulo', instant),
      newYork: window.campusDateFor('America/New_York', instant),
      tokyo: window.campusDateFor('Asia/Tokyo', instant),
      unknown: window.campusDateFor('', instant),
      invalid: window.campusDateFor('Not/AZone', instant),
    };
  });
  check('Lagos campus date is 2026-11-24', tzChecks.lagos === '2026-11-24', JSON.stringify(tzChecks));
  check('Sao Paulo campus date is 2026-11-23', tzChecks.saoPaulo === '2026-11-23', JSON.stringify(tzChecks));
  check('New York campus date is 2026-11-23', tzChecks.newYork === '2026-11-23', JSON.stringify(tzChecks));
  check('Tokyo campus date is 2026-11-24', tzChecks.tokyo === '2026-11-24', JSON.stringify(tzChecks));
  check('no timezone yields no invented date', tzChecks.unknown === null && tzChecks.invalid === null, JSON.stringify(tzChecks));
  const panelHint = await page.textContent('#checkpointHint');
  check('checkpoint panel labels the day it is showing', /campus-local date|most recent recorded day/i.test(panelHint), panelHint);

  console.log('\n11. GPS denied');
  await context.setGeolocation({ latitude: 6.5244, longitude: 3.3792, accuracy: 15 });
  await context.clearPermissions();
  const qr2 = await page.evaluate(async () => (await (await fetch('/api/v1/dev/qr?session=afternoon')).json()).payload);
  await page.evaluate((p) => window.onQrDecoded(p), qr2);
  await sleep(1500);
  check('GPS-denied message shown', /Location permission is required/i.test(await page.textContent('#scanNotice')), await page.textContent('#scanNotice'));
  await page.screenshot({ path: path.join(SHOTS, '09-gps-denied.png') });

  console.log('\n12. Scan locking and retry');
  await context.grantPermissions(['geolocation'], { origin: 'http://127.0.0.1:8000' });
  const lockProbe = await page.evaluate(async () => {
    let calls = 0;
    const realFetch = window.fetch;
    window.fetch = (...args) => { if (String(args[0]).includes('/attendance/scan/')) calls++; return realFetch(...args); };
    const qr = (await (await realFetch('/api/v1/dev/qr?session=evening')).json()).payload;
    const p1 = window.onQrDecoded(qr);
    const p2 = window.onQrDecoded(qr);
    const p3 = window.onQrDecoded(qr);
    await Promise.all([p1, p2, p3]);
    window.fetch = realFetch;
    return calls;
  });
  check('only one scan submitted while locked', lockProbe === 1, 'scan requests=' + lockProbe);
  const retryVisible = await page.isVisible('#scanRetry');
  check('retry controls visible after recoverable failure', retryVisible);
  await page.click('#retryScanBtn').catch(() => {});
  await sleep(600);
  check('retry clears the notice and restarts', await page.isHidden('#scanNotice'), 'notice hidden');

  console.log('\n13. Logout and expired-token handling');
  await page.click('#logoutBtn');
  await sleep(700);
  check('returned to login after logout', await page.isVisible('#loginForm'));
  check('sessionStorage cleared', await page.evaluate(() => sessionStorage.getItem('learn2earn.student.session') === null));
  await page.fill('#loginUsername', 'demo_student');
  await page.fill('#loginPassword', 'demo12345');
  await page.click('#loginFormEl button[type=submit]');
  await page.waitForSelector('#authScreen.hidden', { timeout: 5000 }).catch(() => {});
  await page.evaluate(() => sessionStorage.setItem('learn2earn.student.session', JSON.stringify({ token: 'dead.token', student: { full_name: 'Demo Student', username: 'demo_student' }, savedAt: Date.now() })));
  await page.reload({ waitUntil: 'networkidle' });
  await sleep(1200);
  check('401 returns to login with message', await page.isVisible('#loginForm') && /session ended|sign in again/i.test(await page.textContent('#authAlert')), await page.textContent('#authAlert'));

  console.log('\n14. Responsive layouts');
  for (const [name, width, height] of [['mobile', 390, 844], ['tablet', 820, 1024], ['desktop', 1440, 900]]) {
    await page.setViewportSize({ width, height });
    await page.goto(BASE, { waitUntil: 'networkidle' });
    await sleep(400);
    await page.screenshot({ path: path.join(SHOTS, `10-login-${name}.png`), fullPage: false });
    if (await page.isVisible('#loginForm')) {
      await page.fill('#loginUsername', 'demo_student');
      await page.fill('#loginPassword', 'demo12345');
      await page.click('#loginFormEl button[type=submit]');
      await page.waitForSelector('#authScreen.hidden', { timeout: 5000 }).catch(() => {});
      await sleep(600);
    }
    await page.screenshot({ path: path.join(SHOTS, `11-dashboard-${name}.png`) });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    check(`${name} (${width}px): no horizontal overflow`, overflow <= 1, 'overflow=' + overflow);
    await page.evaluate(() => { sessionStorage.clear(); });
  }

  console.log('\n15. Assets under /student/');
  for (const asset of ['styles.css', 'app.js', 'favicon.png', 'assets/learn2earn-logo.svg', 'vendor/html5-qrcode.min.js']) {
    const status = await page.evaluate(async (a) => (await fetch(a, { method: 'GET' })).status, asset);
    check('asset loads under /student/: ' + asset, status === 200, 'status=' + status);
  }


  console.log('\n16. Dev kiosk renders and refreshes');
  const kioskPage = await context.newPage();
  await kioskPage.goto(BASE_URL + '/dev/kiosk.html', { waitUntil: 'networkidle' });
  await sleep(900);
  check('kiosk has no stray script before <!DOCTYPE>', await kioskPage.evaluate(() => document.doctype !== null && document.documentElement.tagName === 'HTML'));
  const firstPayload = (await kioskPage.textContent('#payload')).trim();
  check('kiosk payload rendered from server field', firstPayload.startsWith('{"version": 1') || firstPayload.startsWith('{"version":1'), firstPayload.slice(0, 40));
  check('kiosk QR canvas drawn', (await kioskPage.locator('#qr canvas, #qr img').count()) > 0);
  check('kiosk shows WAT server time', /\d{2}:\d{2}:\d{2} WAT/.test(await kioskPage.textContent('#serverTime')), await kioskPage.textContent('#serverTime'));
  check('kiosk shows cutoff with WAT', /\d{2}:\d{2} WAT/.test(await kioskPage.textContent('#cutoff')), await kioskPage.textContent('#cutoff'));
  check('kiosk countdown is numeric', /^\d+$/.test((await kioskPage.textContent('#countdown')).trim()), await kioskPage.textContent('#countdown'));
  await kioskPage.reload({ waitUntil: 'networkidle' });
  await sleep(900);
  const secondPayload = (await kioskPage.textContent('#payload')).trim();
  check('kiosk refreshes to a new code', secondPayload !== firstPayload && secondPayload.length > 20);
  check('kiosk redraws QR after refresh', (await kioskPage.locator('#qr canvas, #qr img').count()) > 0);
  await kioskPage.screenshot({ path: path.join(SHOTS, 'kiosk.png') });
  await kioskPage.close();

  console.log('\n17. Status vocabulary from the backend');
  await page.setViewportSize({ width: 1280, height: 900 });
  const badge = await page.evaluate(async () => {
    const res = await fetch('/api/v1/student/attendance-history/', {
      headers: { Authorization: 'Token ' + (JSON.parse(sessionStorage.getItem('learn2earn.student.session') || '{}').token || '') },
    });
    const rows = await res.json();
    return Array.isArray(rows) ? rows.map((r) => r.status) : [];
  });
  const classes = await page.evaluate(() => ({
    late: window.statusClass('late'),
    absent: window.statusClass('absent'),
    onTime: window.statusClass('on_time'),
    present: window.statusClass('present'),
    legacy: window.statusClass('on_time'),
    unknown: window.statusClass('excused'),
    empty: window.statusClass(''),
  }));
  check('late classifies as late', classes.late === 'late', classes.late);
  check('absent classifies as absent', classes.absent === 'absent', classes.absent);
  check('on_time classifies as on-time', classes.onTime === 'on-time', classes.onTime);
  check('present alias still classifies as on-time', classes.present === 'on-time', classes.present);
  check('legacy on_time classifies as on-time', classes.legacy === 'on-time', classes.legacy);
  check('unknown status is neutral, never on-time', classes.unknown === 'neutral', classes.unknown);
  check('empty status is neutral', classes.empty === 'neutral', classes.empty);

  check('history statuses are backend vocabulary', badge.every((s) => ['present', 'late', 'absent', 'on_time'].includes(s)), JSON.stringify(badge.slice(0, 4)));

  // Expected HTTP error responses (401/403/409) are logged by Chrome as resource errors;
  // only unexpected JavaScript/console errors matter here.
  const unexpected = errors.filter((e) =>
    !/Failed to load resource/i.test(e) &&
    !/play\(\) request was interrupted/i.test(e));   // headless fake-camera teardown
  check('no unexpected console errors', unexpected.length === 0, unexpected.slice(0, 3).join(' | '));

  console.log(`\nRESULT: ${pass} passed, ${fail} failed`);
  await browser.close();
  process.exit(fail === 0 ? 0 : 1);
})().catch((error) => { console.error('HARNESS ERROR', error); process.exit(2); });
