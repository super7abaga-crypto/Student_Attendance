/*
 * Issue #5 — safety tests for the Django E2E database guard.
 *
 * These never touch a database: they exercise the guard's decision table and then
 * run the real script with unsafe configuration to prove it refuses before any
 * database access.
 *
 *   node tests/e2e-guard-test.js
 */
const { execFileSync } = require('child_process');
const path = require('path');
const { classifyDatabase } = require('./e2e-guard');

let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log('  PASS  ' + name); }
  else { fail++; console.log('  FAIL  ' + name + (detail ? '  ->  ' + String(detail).slice(0, 200) : '')); }
};

const verdict = (db, opts) => classifyDatabase(db, opts || {});

console.log('\n1. Guard decision table');
check('no database name is refused', verdict('').allowed === false, JSON.stringify(verdict('')));
check('undefined name is refused', verdict(undefined).allowed === false);
check('production database is refused', verdict('attendance_prod').allowed === false);
check('production is refused even with the override',
  verdict('attendance_prod', { allowNonIsolated: true }).allowed === false);
check('staging database is refused', verdict('staging_attendance').allowed === false);
check('shared database is refused', verdict('shared_attendance').allowed === false);
check('plain development database is refused', verdict('attendance').allowed === false);
check('sqlite dev file is refused', verdict('/srv/app/data/dev.sqlite3').allowed === false);
check('e2e database is allowed', verdict('e2e_portal').allowed === true);
check('test database is allowed', verdict('attendance_test').allowed === true);
check('sandbox database is allowed', verdict('sandbox_2026_11_25').allowed === true);
check('unusual name needs the explicit override',
  verdict('throwaway_abc123').allowed === false
  && verdict('throwaway_abc123', { allowNonIsolated: true }).allowed === true);

console.log('\n2. The real script refuses unsafe configuration before touching a database');
const script = path.join(__dirname, 'e2e-django.js');
const run = (env) => {
  try {
    const out = execFileSync(process.execPath, [script], {
      encoding: 'utf8', stdio: 'pipe', timeout: 60000,
      env: { ...process.env, ...env },
    });
    return { code: 0, out };
  } catch (error) {
    return { code: error.status, out: String(error.stderr || '') + String(error.stdout || '') };
  }
};

// These two cases need a real Django checkout so the script can resolve the database
// name and reach the guard. Without one they are reported as skipped, never as passed.
const backend = process.env.DJANGO_DIR;
if (!backend) {
  console.log('  SKIP  real-script refusal checks (set DJANGO_DIR to a Django checkout)');
} else {
  const noDb = run({ DJANGO_DIR: backend, DATABASE_URL: '' });
  check('no database configuration refuses to run',
    noDb.code !== 0 && /Refusing to run/i.test(noDb.out), 'code=' + noDb.code + ' out=' + noDb.out.slice(0, 120));

  const prodLike = run({
    DJANGO_DIR: backend,
    DATABASE_URL: 'postgresql://user:pass@db.internal:5432/attendance_prod',
  });
  check('production-like DATABASE_URL refuses to run',
    prodLike.code !== 0 && /Refusing to run/i.test(prodLike.out), 'code=' + prodLike.code + ' out=' + prodLike.out.slice(0, 120));

  const disposable = run({
    DJANGO_DIR: backend,
    DATABASE_URL: 'postgresql://postgres@127.0.0.1:1/e2e_guard_only',
  });
  check('disposable database name passes the guard (fails later on connection)',
    !/Refusing to run/i.test(disposable.out), 'out=' + disposable.out.slice(0, 160));
}

console.log('\nRESULT: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail === 0 ? 0 : 1);
