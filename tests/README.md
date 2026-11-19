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
scenarios (09:05 present, 09:10 exactly at cutoff late, 09:11 late).

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
