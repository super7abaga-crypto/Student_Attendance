# LEARN 2EARN — Student Attendance Portal

Engineer A's student-facing half of the Learn2Earn Attendance System: a responsive,
framework-free browser portal that signs students in, scans the mentor's session QR code,
sends the scan with a fresh GPS fix, and shows the attendance record the backend returns.

Engineer B owns the Django backend, the database, QR issuance, geofencing and every
attendance decision. **This repository is the frontend plus a local mock for development.**

**State of this repository:** the frontend integration is implemented and tested against a
local mock of the contract. It has **not** been run against Engineer B's Django backend,
because that API is not reachable yet (see [§15](#15-current-limitations-and-outstanding-work)).
Nothing here is production-verified.

---

## 1. Project overview and objectives

- Give each student a single place to sign in, check in by scanning the mentor's QR code, and
  review their attendance history.
- Keep attendance authority on the server: the browser never decides whether a QR is valid,
  whether a student is on campus, or whether a scan is On Time or Late.
- Stay deployable inside Django at `/student/` without a build step or a JavaScript framework.
- Work on phones (the primary device), tablets and desktops.

Out of scope for Engineer A: enrollment, mentor tooling, QR issuance, geofencing, duplicate
policy, reporting. Those belong to Engineer B.

## 2. Current system architecture

```
Student device (browser)
  index.html + styles.css + app.js
  vendor/html5-qrcode.min.js          camera decoding, on-device only
        │
        │  HTTPS, Authorization: Token <token>
        ▼
Engineer B — Django REST API  /api/v1/
  POST /auth/student/login/      POST /auth/logout/
  GET  /student/attendance-history/
  POST /attendance/scan/         QR validation · geofence · status · duplicates
        │
        ▼
Django database (Engineer B)   ← source of truth

Local development only:
  server.py  = mock of the four student endpoints, JSON file storage
  dev/kiosk.html = mentor-style QR for scan testing
```

The portal holds no attendance logic. It sends the exact decoded QR text plus coordinates and
renders the response.

## 3. Repository and folder structure

```
index.html                  single page: login, dashboard, scanner, history
styles.css                  Learn2Earn design system + integration additions
app.js                      all behaviour; CONFIG at the top
favicon.png
assets/
  learn2earn-logo.svg       official lockup (sidebar, sign-in card, kiosk)
  learn2earn-mark.png       mark-only crop
vendor/
  html5-qrcode.min.js       vendored scanner library (CDN fallback in index.html)
  qrcode.min.js             vendored QR library for the dev kiosk
dev/
  kiosk.html                dev-only page that shows a live 30-second test QR
server.py                   dev-only mock of Engineer B's student endpoints
API_CONTRACT.md             the endpoints, payloads and error codes the portal calls
HOSTING.md                  what Engineer B needs to serve this at /student/
docs/screenshots/           evidence captured from the local test run
requirements.txt            no third-party packages
LICENSE
```

## 4. Student registration and login

**There is no student self-registration.** The pilot is mentor-controlled: accounts and campus
assignments are created in Engineer B's backend. The login card states this:

> Your account must be created by a mentor or administrator. Please contact your mentor to
> obtain your login details.

- `POST /auth/student/login/` with `{username, password}`.
- The username is lower-cased and stripped of spaces before sending; Django remains the
  authority on whether the account exists and is active.
- On success the portal stores `{token, student, savedAt}` in **`sessionStorage`** and shows the
  student's full name, username and campus in the header and profile panel.
- Authenticated calls use **`Authorization: Token <token>`**. `Bearer` is never sent.
- A refresh in the same tab restores the session; a new tab starts at login. Sessions older
  than **12 hours** are discarded locally.
- `POST /auth/logout/` is called, then the local session is cleared whether or not the request
  succeeds.
- Any `401` clears the session and returns to login with "Your session ended. Please sign in
  again."

## 5. Student dashboard and attendance history

Dashboard (current month, WAT):

- Sessions attended, On-time attendance, Late attendance, and Last check-in.
- **No attendance percentage and no total-session figure.** `GET /student/attendance-history/`
  returns records only, so a denominator would be invented.
- Recent attendance table, five most recent records.

History view:

- `GET /student/attendance-history/` (bare list), month filter applied in the browser on
  `attendance_date`.
- Columns: session, date, time (WAT, from `scan_time_wat`), status badge.
- Loading, empty ("No attendance recorded for …") and error states are implemented.

## 6. QR-code generation and scanning workflow

QR **generation** is Engineer B's mentor kiosk. The portal only consumes codes.

1. Student opens **Scan attendance** and presses **Start camera** (permission required; HTTPS
   outside `localhost`).
2. The camera decodes a QR. The portal keeps the decoded text **exactly** as produced and
   does not parse or pre-validate it.
3. It requests a **fresh** geolocation fix (`enableHighAccuracy`, `maximumAge: 0`, 15 s
   timeout), showing "Verifying scan…".
4. It posts `{qr_payload, latitude, longitude, accuracy}` to `POST /attendance/scan/`.
5. `201` → confirmation card filled from the returned `attendance` object.
6. Recoverable failures → readable message plus **Try scanning again** / **Restart camera**.
7. Only one scan can be in flight; the scanner stops and buttons lock until the response lands.

The mentor kiosk emits JSON such as
`{"version":1,"token":"signed-token","expires_at":1794908400}`. Tokens live 30 seconds; the
backend decides that, not the portal.

## 7. Checkpoint attendance rules and duplicate prevention

- The backend decides every rule: session state, QR validity, geofence, duplicate protection,
  Present versus Late.
- Duplicate protection is **per student, per campus-local day and per checkpoint**. A repeat
  scan inside one checkpoint returns `409 duplicate_attendance` with the existing record; the
  portal shows "You have already completed this checkpoint today." and keeps that record
  visible. A later checkpoint on the same day is a new, legitimate record.
- Three records can exist on one day: morning `check_in`, afternoon `check_in`, evening
  `check_out`. The dashboard lists all three and the history table shows the action per row.
- The portal implements no rule of its own and never computes a status. See
  [§15](#15-current-limitations-and-outstanding-work) for the open backend gaps.

## 8. Attendance statuses

| Backend value | Shown as | Notes |
|---|---|---|
| `present` | Present | green badge, canonical |
| `late` | Late | amber badge |
| `absent` | Absent | red badge; never counted as attended |
| `on_time` | On Time | legacy historical rows only, not a current status |
| anything else | the raw value | shown verbatim, neutral grey badge |

`statusClass()` colours only `late`, `absent` and the on-time family (`on_time` and `present`).
Anything unrecognised is neutral grey, so an unknown backend status is never mistaken for a
good one. The dashboard counts only `present`, `late` and legacy `on_time`; absences never
appear in the attendance count or in "Last check-in".

The raw value is always kept in `data-status` on the badge, and the portal never derives
status from the device clock. If Engineer B renames a value, the badge follows with no code
change.

**Campus.** The backend sends the campus UUID in `campus` and the readable name in
`campus_name`. The portal displays `campus_name` everywhere and keeps the UUID only as
`student.campus_id`, so a student never sees an identifier.

**Duplicates.** Engineer B's 409 carries no `attendance` object, so on a duplicate the portal
re-reads the student's own history and shows today's existing record, clearly marked as
already completed that checkpoint. If history has nothing for that checkpoint it says so and shows no card; it never
fabricates a record.

`attendance_action` is rendered verbatim in the confirmation card's BACKEND ACTION row and
kept in `data-action`. The portal does not branch on it: duplicates are detected from HTTP 409
plus `code: duplicate_attendance`. The authoritative enum is still outstanding from Engineer B
(see `API_CONTRACT.md`); the mock emits `checked_in` only so the field can be tested.

Current contract cutoffs (WAT): morning **09:10**, afternoon **13:10**, evening **17:10**; a
scan exactly at the cutoff is Late. An earlier instruction said evening 17:15, so the two
sources disagree — the backend's answer is what the UI displays.

## 9. Backend API configuration and endpoints

Base URL resolution, in order: `window.LEARN2EARN_API_BASE` → the `learn2earn-api-base` meta tag
in `index.html` → `<page origin>/api/v1` → `https://fellowship.learn2earn.ng/api/v1/` for
`file://`. One place to change it; no call site hard-codes a host.

| Method | Endpoint | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/student/login/` | none | token + student profile |
| POST | `/auth/logout/` | Token | end the session |
| GET | `/student/attendance-history/` | Token | bare list of records |
| POST | `/attendance/scan/` | Token | QR + GPS → attendance record |

Error codes handled: `duplicate_attendance` (409), `qr_expired` (403), `invalid_qr` (400),
`wrong_campus` (403), `session_inactive` (403), `gps_accuracy` (403), `gps_required` (400),
`401` session expiry, plus safe fallbacks for `403/429/5xx`. Full payloads are in
[`API_CONTRACT.md`](API_CONTRACT.md).

## 10. Database structure and persistence

The frontend has **no database**. It keeps only the session token and student profile in
`sessionStorage`.

Persistence belongs to Engineer B. The local mock mirrors it in `dev/.data.json` (git-ignored)
with two collections:

```jsonc
// students
{ "id", "full_name", "username", "password_salt", "password_hash",
  "campus", "is_active", "created_at" }

// attendance
{ "id", "student_id", "full_name", "username", "session_type",
  "attendance_date", "scanned_at", "scan_time_wat", "status",
  "campus", "session_id", "accuracy", "latitude", "longitude", "distance_m" }
```

The mock is a demonstration aid. It has no migrations, no concurrency guarantees beyond a
process lock, no rate limiting and no production hardening.

## 11. Installation and setup

Requirements: **Python 3.8+**. No third-party packages, no `pip install`, no Node.js, no build
step.

```bash
git clone https://github.com/super7abaga-crypto/Student_Attendance.git
cd Student_Attendance
```

## 12. How to run the frontend and backend

```bash
python server.py
```

- Portal: <http://127.0.0.1:8000/student/>
- API base: `http://127.0.0.1:8000/api/v1`
- Test kiosk: <http://127.0.0.1:8000/dev/kiosk.html>
- Demo student: `demo_student` / `demo12345` (Lagos Campus)

In VS Code, **F5** runs the same server (`.vscode/launch.json`) and opens the portal.

To use the portal against a different backend, set the meta tag in `index.html`:

```html
<meta name="learn2earn-api-base" content="http://127.0.0.1:8000/api/v1">
```

The frontend can also be served on its own (`python -m http.server 5500`) with the API base
pointing at Django; camera and GPS then need `localhost` or HTTPS.

## 13. Environment variables and configuration

`server.py` (development mock):

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | listening port |
| `HOST` | `127.0.0.1` | use `0.0.0.0` to reach it from a phone on the same network |
| `APP_SECRET` | random per start | signs 12-hour session tokens |
| `QR_SECRET` | random per start | signs mock QR tokens |
| `CAMPUS_NAME` | `Lagos Campus` | campus label on the student profile |
| `CAMPUS_LAT` / `CAMPUS_LON` | `6.5244` / `3.3792` | mock geofence centre |
| `CAMPUS_RADIUS_M` | `300` | mock geofence radius |
| `MAX_ACCURACY_M` | `100` | reject fixes worse than this |
| `SESSION_OPEN_MINUTES` | `180` | how long a session accepts scans |
| `DATA_FILE` | `dev/.data.json` | where the mock persists its data |
| `MOCK_NOW_WAT` | unset | pins the mock clock, e.g. `09:10`, so cutoffs are testable |
| `MOCK_ATTENDANCE_ACTION` | `check_in` | mock-only override; each checkpoint otherwise uses its own action (`check_in`, `check_in`, `check_out`) |

`app.js`: `CONFIG.API_BASE_URL`, `SESSION_STORAGE_KEY`, `SESSION_HOURS` (12), `GPS_OPTIONS`,
`RECENT_ROWS`. No secrets live in the frontend, and none should ever be added.

## 14. Testing instructions

Manual checks against the mock (all of these were run for this revision):

```bash
# login
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/student/login/ \
  -H "Content-Type: application/json" \
  -d '{"username":"demo_student","password":"demo12345"}'

# history (bare list)
curl -s http://127.0.0.1:8000/api/v1/student/attendance-history/ \
  -H "Authorization: Token <token>"

# a scan, on campus
curl -s -X POST http://127.0.0.1:8000/api/v1/attendance/scan/ \
  -H "Content-Type: application/json" -H "Authorization: Token <token>" \
  -d '{"qr_payload":"<payload from /api/v1/dev/qr>","latitude":6.5244,"longitude":3.3792,"accuracy":15}'
```

In the browser: sign in, refresh (session must survive), open history, filter a month with no
records, then scan the kiosk QR. Test the failure paths by moving the geolocation, denying
location, and scanning an expired code.

### Automated suites (in this repository)

Both suites are self-contained: they start their own mock on a free port with fixed dev
secrets and a throwaway data file, so they never touch `dev/.data.json` and never need a
server running first.

```bash
# API contract suite: standard library only, no install
python3 tests/api-test.py

# Browser suite: installs playwright-core, drives the real Chrome/Chromium
cd tests
npm install
npm test
```

`tests/api-test.py` runs 74 checks: login success and failure, Token scheme (Bearer rejected),
bare-list history with contract fields, logout and idempotent logout, forged/expired token,
valid scan with every documented field including `attendance_action`, duplicate 409 keeping the
original record, expired QR, malformed QR, wrong campus, poor accuracy, missing GPS, inactive
session, static assets under `/student/`, a pinned-clock scenario for **09:05 present**,
**09:10 present**, **09:11 late**, and a three-checkpoint day (morning, afternoon and evening
on one campus-local date, each with its own duplicate).

`tests/ui-test.js` runs 104 checks in Chromium with a fake camera and mocked geolocation: login
screen and enrollment notice, invalid login, login, session restore after refresh, dashboard
stats, history rendering and month filtering including the empty month, successful scan into
the confirmation card, duplicate keeping the original record, expired QR, malformed QR, wrong
campus, GPS denied, scan locking and retry, logout and 401 handling, three viewports with no
horizontal overflow, assets under `/student/`, the dev kiosk rendering and refreshing, and
backend status vocabulary, attendance counts that exclude absences, checkpoint-scoped
duplicate copy, and campus-local date handling for Lagos, Sao Paulo, New York and Tokyo.
Screenshots land in `tests/screenshots/`; committed copies are in
[`docs/screenshots/`](docs/screenshots).

Two further suites cover real integration and layout:

```bash
# End-to-end against Engineer B's Django on a disposable database (PostgreSQL or SQLite).
# The script refuses to run unless the database name contains e2e, test or sandbox.
DJANGO_DIR=../backend DATABASE_URL=postgresql://.../e2e_portal \
  node tests/e2e-django.js          # 27 checks

# Responsive audit: desktop 1440, tablet 834, phone 390 against any running portal.
PORTAL_URL=http://127.0.0.1:8020/index.html API_BASE=http://127.0.0.1:8010/api/v1 \
  PORTAL_USER=... PORTAL_PASS=... node tests/responsive-test.js   # 38 checks
```

Results recorded for this revision: `api-test.py` 74 passed; `ui-test.js` 104 passed (run twice);
`e2e-django.js` 27 passed against Django with a **non-Lagos** campus (`America/Sao_Paulo`);
`responsive-test.js` 38 passed.

**These are mock tests.** They prove the frontend honours the documented contract and handles
each response shape; they do not prove behaviour against Engineer B's backend. See section 15
for the blocked live tests.

The suites accept `BASE_URL` and `CHROME_PATH` environment variables, so the same browser suite
can be pointed at a deployed student portal once the backend is reachable.

## 15. Current limitations and outstanding work

**Attendance model (settled).** The CEO approved the three-checkpoint model on 23 November
2026: one record per student, campus-local day and checkpoint; morning and afternoon are
`check_in`, evening is `check_out`; a repeat scan inside one checkpoint returns 409 with the
existing record; one absence per checkpoint, created only after that checkpoint's own close;
lateness starts at 09:11 and 13:11. The portal follows this model and does not enforce it.

Blocked on Engineer B:

- **`campus_timezone` / `campus_local_date` are not exposed.** The student login payload
  carries only `campus` (UUID) and `campus_name`. Until an IANA zone or a campus-local date is
  added, the portal cannot say which checkpoints are still open or closed; it shows the
  campus-local date returned by the most recent scan, and otherwise labels the panel as the
  most recent recorded day. It never assumes `Africa/Lagos`.
- **Timestamps are labelled WAT.** The backend field is `scan_time_wat`, computed with the
  server's `TIME_ZONE`, so the history table keeps the `TIME (WAT)` heading. A zone-neutral
  value (for example `scanned_at` plus `campus_timezone`) would let the portal render
  campus-local times.
- **No deployed API.** `https://fellowship.learn2earn.ng/api/v1/` still answers every path with
  the marketing page, so the portal cannot be pointed at production yet.
- **No CI on the pull requests.** Nothing runs these suites automatically.

Not verified:

- **Real-device testing.** No phone was available to this environment and no HTTPS deployment
  exists, so camera permission, GPS permission and a real QR scan were not exercised on
  hardware. The 390x844 and 834x1112 runs are browser device emulation, not a physical device.

Known frontend limitations:

- Logout cannot revoke a Django token; the 12-hour server-side expiry is the real control.
- Camera and geolocation require HTTPS (or `localhost`); a plain-HTTP LAN address will fail.
- The kiosk test page uses the vendored `vendor/qrcode.min.js`, so it draws a code with no
  internet access.

## 16. Integration responsibilities

| Engineer A (this repo) | Engineer B (Django) |
|---|---|
| Login screen, dashboard, scanner UI, confirmation card, history | Authentication, token issuance and expiry, account and campus assignment |
| Sends the exact QR text and a fresh GPS fix | QR issuance and validation, 30-second expiry |
| Displays status, session, date and time from the response | Session state, cutoffs, On Time / Late, duplicate protection |
| Month filtering, loading/empty/error states | Geofence calculation, attendance storage, reporting |
| Static bundle ready for `/student/` | Serving it at `/student/`, CORS if not same-origin |

---

## Appendix — documentation state

| Area | State |
|---|---|
| Login-only enrollment | Implemented |
| Token auth (`Token`, 12 h, sessionStorage) | Implemented |
| Session restore, logout, 401 handling | Implemented |
| QR scan with exact payload + GPS | Implemented |
| Confirmation card from backend fields | Implemented |
| Duplicate and error handling | Implemented |
| Attendance history + month filter | Implemented |
| `/student/` relative paths | Implemented, verified locally |
| Live Django integration | **Blocked** — API not reachable |
| Daily (one-per-day) attendance rule | **Pending decision**, not implemented anywhere in this repo |

## Change log

- **19 Nov 2026** — Django integration: login-only enrollment, `Token` auth with 12-hour
  sessionStorage sessions, `/auth/student/login/`, `/auth/logout/`,
  `/student/attendance-history/`, `/attendance/scan/` with GPS, backend-driven statuses and
  error codes, month filtering, `/student/` hosting support, `HOSTING.md`, contract rewrite,
  and `server.py` repurposed as a mock of the Django contract.
- **19 Nov 2026 (review round 1)** — dev kiosk repaired (stray script before `<!DOCTYPE>`
  removed, `payload` field aligned with `server.py`, WAT clock fixed, QR library vendored so
  the code draws offline), `attendance_action` surfaced, status vocabulary aligned to
  `present`/`late`/`absent`, and reproducible suites added: `tests/api-test.py` (48 checks)
  and `tests/ui-test.js` (68 checks) with `tests/README.md` and npm scripts. `HOSTING.md`
  rewritten around `{% static %}` so assets resolve from `/student/`.
