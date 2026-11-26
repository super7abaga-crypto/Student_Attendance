const { chromium } = require('playwright-core');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { assertDisposableDatabase } = require('./e2e-guard');

// Runs the portal against Partner B's REAL Django backend (no mocks).
// Prerequisites are documented in tests/README.md.
const DJ = process.env.DJANGO_DIR || path.join(__dirname, '..', '..', 'Student_Attendance-backend');
const API = process.env.API_BASE || 'http://127.0.0.1:8010/api/v1';
const PORTAL = process.env.PORTAL_URL || 'http://127.0.0.1:8020/index.html';
const SHOTS = process.env.SHOTS || path.join(__dirname, 'screenshots');
const CHROME = process.env.CHROME_PATH || '/usr/bin/google-chrome';
// These secrets must match the ones the backend under test is running with, or the
// QR tokens minted here fail signature verification on the server. CI supplies its
// own values, so honour the environment and fall back to the documented local pair.
const ENV = { ...process.env, DJANGO_SETTINGS_MODULE: process.env.DJANGO_SETTINGS_MODULE || 'config.settings.dev',
  ATTENDANCE_SECRET: process.env.ATTENDANCE_SECRET || 'local-audit-qr-secret-0123456789abcdef',
  DJANGO_SECRET_KEY: process.env.DJANGO_SECRET_KEY || 'local-audit-django-secret-0123456789abcdef' };

let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log('  PASS  ' + name); }
  else { fail++; console.log('  FAIL  ' + name + (detail ? '  ->  ' + String(detail).slice(0, 200) : '')); }
};
const sh = (code) => execSync(`python3 manage.py shell -c "${code.replace(/"/g, '\\"')}"`, { cwd: DJ, env: ENV, encoding: 'utf8' });

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });

  // Issue #5: never touch rows this run did not create. Refuse a database whose
  // name does not look disposable, then seed and clean only E2E fixtures.
  const dbName = sh("from django.conf import settings; print('DBNAME:' + str(settings.DATABASES['default'].get('NAME','')))").trim().split('\n').pop().replace('DBNAME:', '').trim();
  try {
    assertDisposableDatabase(dbName, { allowNonIsolated: process.env.E2E_ALLOW_NON_ISOLATED_DB === '1' });
  } catch (guardError) {
    console.error(guardError.message);
    process.exit(2);
  }
  const seed = JSON.parse(sh("from apps.core.models import Campus, Student, MentorCampusAccess, AttendanceLog; from django.contrib.auth import get_user_model; from django.utils import timezone; from zoneinfo import ZoneInfo; import json; U=get_user_model(); tzs=['America/Sao_Paulo','America/New_York','Africa/Lagos','Asia/Kolkata','Asia/Tokyo']; now=timezone.now(); tz=next((z for z in tzs if 9 <= timezone.localtime(now, ZoneInfo(z)).hour < 11), 'Africa/Lagos'); c,_=Campus.objects.get_or_create(name='E2E Campus', defaults={'latitude':4.8156,'longitude':7.0498,'geofence_radius_m':300,'timezone':tz,'active':True}); c.timezone=tz; c.latitude=4.8156; c.longitude=7.0498; c.geofence_radius_m=300; c.active=True; c.save(); m,_=U.objects.get_or_create(username='e2e.mentor', defaults={'role':U.Role.CAMPUS_ADMIN,'is_staff':True}); m.set_password('e2e-mentor-password-123'); m.save(); MentorCampusAccess.objects.get_or_create(user=m, campus=c); u,_=U.objects.get_or_create(username='e2e.student', defaults={'role':U.Role.STUDENT,'first_name':'E2E','last_name':'Student','assigned_campus':c}); u.set_password('e2e-student-password-123'); u.assigned_campus=c; u.save(); st,_=Student.objects.get_or_create(user=u, defaults={'campus':c}); print(json.dumps({'campus':c.name,'username':'e2e.student','password':'e2e-student-password-123','timezone':tz,'deleted':AttendanceLog.objects.filter(student=st).delete()[0]}))").trim().split('\n').pop());
  console.log('   fixtures: ' + seed.campus + ' (' + seed.timezone + '), student ' + seed.username + ', removed ' + seed.deleted + ' prior E2E rows');

  const browser = await chromium.launch({ executablePath: CHROME,
    args: ['--no-sandbox', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
  try {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 },
    permissions: ['geolocation'], geolocation: { latitude: 4.8156, longitude: 7.0498, accuracy: 15 } });
  await context.addInitScript((api) => { window.LEARN2EARN_API_BASE = api; }, API);
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => consoleErrors.push(String(e)));

  console.log('\n1. Login against real Django');
  await page.goto(PORTAL, { waitUntil: 'networkidle' });
  await page.fill('#loginUsername', seed.username);
  await page.fill('#loginPassword', seed.password);
  await page.click('#loginFormEl button[type=submit]');
  await page.waitForSelector('#authScreen.hidden', { timeout: 8000 }).catch(() => {});
  check('portal opened after real login', await page.isVisible('#dashboardView'));
  check('full name from Django', (await page.textContent('#topName')).trim() === 'E2E Student', await page.textContent('#topName'));
  check('username from Django', (await page.textContent('#topUsername')).trim() === '@' + seed.username, await page.textContent('#topUsername'));
  const campusTop = (await page.textContent('#topCampus')).trim();
  const campusProfile = (await page.textContent('#profileCampus')).trim();
  check('campus shows campus_name, not the UUID', campusTop === seed.campus && campusProfile === seed.campus, 'topCampus=' + campusTop + ' profileCampus=' + campusProfile);
  await page.screenshot({ path: path.join(SHOTS, 'e2e-dashboard.png') });

  console.log('\n2. Session persistence (same tab reload)');
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);
  check('session restored after reload', await page.isVisible('#dashboardView'));

  console.log('\n3. Live QR scan (backend-minted, 30s TTL)');
  sh("from apps.core.models import Campus, SessionRun; from apps.core import services; from django.utils import timezone; from django.contrib.auth import get_user_model; import json; U=get_user_model(); m=U.objects.get(username='e2e.mentor'); c=Campus.objects.get(name='E2E Campus'); r,_=SessionRun.objects.get_or_create(campus=c, attendance_date=timezone.localdate(), session_type='morning', defaults={'attendance_action':'check_in','started_by':m}); json.dump(services.mint_qr(r), open('/tmp/env2.json','w'))");
  const envelope = JSON.parse(fs.readFileSync('/tmp/env2.json', 'utf8'));
  await page.evaluate((p) => window.onQrDecoded(p), JSON.stringify(envelope));
  await page.waitForSelector('#confirmationModal:not(.hidden)', { timeout: 15000 }).catch(() => {});
  const cardOpen = await page.isVisible('#confirmationModal');
  check('confirmation card opened for a real scan', cardOpen);
  if (cardOpen) {
    const status = (await page.textContent('#confirmStatus')).trim();
    const raw = await page.getAttribute('#confirmStatus', 'data-status');
    // The backend decides present versus late; this run may sit inside the on-time
    // window or after the lateness boundary, so assert the portal mirrors whatever
    // the backend said rather than assuming a late scan.
    const labelFor = { present: 'PRESENT', late: 'LATE', absent: 'ABSENT', on_time: 'ON TIME' };
    check('status is the backend value',
      ['present', 'late'].includes(raw) && status === labelFor[raw],
      'data-status=' + raw + ' label=' + status);
    check('attendance_action from backend', (await page.textContent('#confirmAction')).trim() === 'check_in', await page.textContent('#confirmAction'));
    check('session label readable', (await page.textContent('#confirmSession')).trim() === 'Morning Session', await page.textContent('#confirmSession'));
    const cardDate = (await page.textContent('#confirmDate')).trim();
    check('date from backend', /^\d{1,2} [A-Z][a-z]{2} \d{4}$/.test(cardDate), cardDate);
    check('time from backend', /\d{2}:\d{2}/.test(await page.textContent('#confirmTime')), await page.textContent('#confirmTime'));
    check('student name on card', (await page.textContent('#confirmName')).trim() === 'E2E Student', await page.textContent('#confirmName'));
    await page.screenshot({ path: path.join(SHOTS, 'e2e-scan-success.png') });
    await page.click('#closeConfirmation');
    await page.waitForTimeout(400);
  }

  console.log('\n4. Duplicate scan against real Django');
  await page.evaluate((p) => window.onQrDecoded(p), JSON.stringify(envelope));
  await page.waitForTimeout(2500);
  const notice = (await page.textContent('#scanNotice')).trim();
  check('duplicate message shown', /already completed this checkpoint/i.test(notice), notice);
  const dupCard = await page.isVisible('#confirmationModal');
  check('duplicate shows the original record from history', dupCard);
  if (dupCard) {
    check('duplicate card keeps the backend name', (await page.textContent('#confirmName')).trim() === 'E2E Student', await page.textContent('#confirmName'));
    check('duplicate card keeps the backend time', /\d{2}:\d{2}/.test(await page.textContent('#confirmTime')), await page.textContent('#confirmTime'));
  }
  await page.screenshot({ path: path.join(SHOTS, 'e2e-duplicate.png') });
  if (dupCard) await page.click('#closeConfirmation').catch(() => {});

  console.log('\n5. Attendance history from Django');
  await page.evaluate(() => showView('history'));
  await page.waitForTimeout(1500);
  const rows = await page.locator('#historyRows tr').count();
  const rowText = (await page.textContent('#historyRows')).replace(/\s+/g, ' ');
  check('history row rendered', rows >= 1, 'rows=' + rows);
  check('history shows morning session', /Morning Session/.test(rowText), rowText.slice(0, 120));
  check('history shows the backend status badge', /PRESENT|Present|LATE|Late/.test(rowText), rowText.slice(0, 120));
  await page.screenshot({ path: path.join(SHOTS, 'e2e-history.png') });

  console.log('\n5b. Three checkpoints on one campus-local day (real backend data)');
  sh("from apps.core.models import AttendanceLog, Student; from django.utils import timezone; import json; s=Student.objects.get(user__username='e2e.student'); day=timezone.localdate(); made=[]; "
     + "\nfor sess, act, tm in [('afternoon','check_in','13:05:00'), ('evening','check_out','17:05:00')]:\n"
     + "    AttendanceLog.objects.get_or_create(student=s, attendance_date=day, session_type=sess, defaults={'campus': s.campus, 'attendance_action': act, 'status': 'present', 'source': 'qr', 'location_verified': True, 'location_accuracy_m': 12, 'location_distance_m': 40})\n"
     + "print('ROWS:' + str(AttendanceLog.objects.filter(student=s, attendance_date=day).count()))");
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  const checkpointRows = await page.$$eval('#checkpointRows tr', (trs) => trs.map((tr) => tr.textContent.replace(/\s+/g, ' ').trim()));
  check('all three checkpoints are listed', checkpointRows.length === 3, JSON.stringify(checkpointRows));
  check('every checkpoint shows a recorded state', checkpointRows.every((r) => /PRESENT|LATE|ABSENT/i.test(r)), JSON.stringify(checkpointRows));
  check('evening shows the check-out action', /Evening.*Check-out/i.test(checkpointRows.join(' | ')), JSON.stringify(checkpointRows));
  const dayRows = await page.$$eval('#historyRows tr', (trs) => trs.map((tr) => tr.textContent.replace(/\s+/g, ' ').trim()));
  check('history shows three records for the day', dayRows.length >= 3, JSON.stringify(dayRows.slice(0, 4)));
  check('history distinguishes check-in from check-out',
    dayRows.some((r) => /Check-in/i.test(r)) && dayRows.some((r) => /Check-out/i.test(r)), JSON.stringify(dayRows.slice(0, 4)));
  await page.screenshot({ path: path.join(SHOTS, 'e2e-three-checkpoints.png') });

  console.log('\n6. Logout');
  await page.click('#logoutBtn');
  await page.waitForTimeout(1200);
  check('returned to login', await page.isVisible('#loginForm'));
  check('sessionStorage cleared', await page.evaluate(() => sessionStorage.getItem('learn2earn.student.session') === null));

  const unexpected = consoleErrors.filter(e => !/Failed to load resource/i.test(e) && !/play\(\) request was interrupted/i.test(e));
  check('no unexpected console errors', unexpected.length === 0, unexpected.slice(0, 3).join(' | '));

  } catch (runError) {
    // A failed run must still leave the database as it found it.
    fail += 1;
    console.error('   run error: ' + (runError && runError.message ? runError.message : runError));
  } finally {
    try { await browser.close(); } catch (_) { /* already closed */ }
    const cleaned = sh("from apps.core.models import AttendanceLog, Student; st=Student.objects.filter(user__username='e2e.student').first(); print('CLEANED:' + str(AttendanceLog.objects.filter(student=st).delete()[0] if st else 0))").trim().split('\n').pop().replace('CLEANED:', '');
    console.log('   cleanup: removed ' + cleaned + ' E2E attendance rows; other students untouched');
  }
  console.log(`\nRESULT: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
