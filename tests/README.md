# Tests

Two self-contained suites for the student portal. Neither needs a server running first, and
neither touches `dev/.data.json`: each starts its own mock on a free port with fixed dev
secrets and a throwaway data file.

## API suite (no install)

```bash
python3 tests/api-test.py
```

Requires Python 3.9+ and nothing else. 48 checks covering authentication, the Token scheme,
history, every documented scan outcome, static assets under `/student/`, and three pinned-clock
scenarios (09:05 present, 09:10 exactly at cutoff late, 09:11 late) and a three-checkpoint
day (morning, afternoon and evening on one campus-local date, each with its own duplicate).

## Browser suite

```bash
cd tests
npm install
npm test
```

`npm install` pulls `playwright-core` only. The suite launches the system Chrome; set
`CHROME_PATH` if it is not in a standard location. 68 checks covering the login screen,
session restore, dashboard, history and month filtering, scanning with a fake camera and
mocked geolocation, duplicates, error states, scan locking and retry, logout and 401, three
viewports, `/student/` assets, the dev kiosk, and backend status vocabulary.

Screenshots are written to `tests/screenshots/` (git-ignored).

## Pointing the browser suite at a deployed portal

```bash
cd tests
BASE_URL=https://example.com/student/ npm test
```

The suite resets state through `/api/v1/dev/reset`, which only exists in the local mock. Against
a real deployment, expect the login, history and scan checks to run against Engineer B's
backend, and the reset-dependent count checks to be skipped or adjusted.

## What these suites do not prove

They exercise the frontend against a mock that implements the documented contract. They do not
prove behaviour against Engineer B's Django backend. Live login, live history, live scans, real
cutoff decisions, real geofencing and mobile camera over HTTPS still need the deployed API, a
pilot credential and the mentor kiosk.

## Django end-to-end run (no mocks)

`tests/e2e-django.js` drives the portal against **Partner B's real Django backend**. It is the
only suite that proves the integration; the suites above run against the local mock.

### Database safety (issue #5)

The run writes attendance rows, so it refuses to start unless the database is clearly
disposable. `tests/e2e-guard.js` decides before any database access:

| Resolved database name | Result |
|---|---|
| empty or unresolved | refused |
| contains `prod`, `production`, `live`, `staging`, `shared`, `master`, `primary` | refused, **even with the override** |
| contains `e2e`, `test` or `sandbox` as a whole segment | allowed |
| anything else | refused unless `E2E_ALLOW_NON_ISOLATED_DB=1` |

The script seeds its own fixtures (`E2E Campus`, `e2e.mentor`, `e2e.student`), removes only
that student's attendance rows, and runs the same scoped cleanup in a `finally` block so a
crashed or failed run still leaves every other student's history intact.

Safety tests, no database needed:

```bash
cd tests
node e2e-guard-test.js          # 15 checks; set DJANGO_DIR to also exercise the real script
```

### Exact commands

1. Create a disposable database whose name says so:

   ```bash
   createdb -h 127.0.0.1 -p 5432 e2e_portal
   DATABASE_URL=postgresql://postgres@127.0.0.1:5432/e2e_portal \
     DJANGO_SETTINGS_MODULE=config.settings.dev python3 manage.py migrate --noinput
   ```

2. Run the backend with fixed secrets and CORS for the portal origin:

   ```bash
   DATABASE_URL=postgresql://postgres@127.0.0.1:5432/e2e_portal \
   DJANGO_SETTINGS_MODULE=config.settings.dev \
   ATTENDANCE_SECRET=local-audit-qr-secret-0123456789abcdef \
   CORS_ALLOWED_ORIGINS=http://127.0.0.1:8020 \
   python3 manage.py runserver 127.0.0.1:8010 --noreload
   ```

3. Serve the portal from another origin:

   ```bash
   python3 -m http.server 8020 --bind 127.0.0.1 --directory .
   ```

4. Run it:

   ```bash
   cd tests
   DJANGO_DIR=/path/to/backend \
   DATABASE_URL=postgresql://postgres@127.0.0.1:5432/e2e_portal \
   PORTAL_URL=http://127.0.0.1:8020/index.html \
   node e2e-django.js            # 27 checks
   ```

The campus timezone is chosen automatically from a small candidate list so the run does not
depend on the wall clock, and the run reports the campus it used.

### Responsive audit

```bash
PORTAL_URL=http://127.0.0.1:8020/index.html \
API_BASE=http://127.0.0.1:8010/api/v1 \
PORTAL_USER=e2e.student PORTAL_PASS=e2e-student-password-123 \
node responsive-test.js          # 38 checks at 1440, 834 and 390 px
```
