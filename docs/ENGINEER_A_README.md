# LEARN 2EARN — Student Attendance Portal (Engineer A)

A responsive, browser-based student portal for the LEARN 2EARN attendance system. It lets a
student register, sign in, see their attendance record, and check in by scanning the QR code
their mentor displays.

**This repository is Engineer A's student-facing module plus a local development server.**
It is not the production attendance backend. Engineer B owns the real backend, the real
database and the QR issuing kiosk. Section 16 explains the split.

---

## Documentation status

This README was written by reading the code in this repository, not from earlier plans or
discussions. Every endpoint, field, command and behaviour below was checked against
`server.py`, `app.js`, `index.html`, `dev/kiosk.html` and `API_CONTRACT.md` on 18 November 2026.

Where the approved attendance policy differs from what the code currently does, the
difference is stated explicitly instead of being hidden. Read section 8 and section 9 before
assuming the portal already records one attendance per day: **it does not yet.**

| Area | State |
|------|-------|
| Registration, login, session handling | Implemented (frontend + local dev API) |
| Dashboard statistics and recent activity | Implemented |
| Attendance history with month filter | Implemented |
| Camera QR scanner and check-in request | Implemented |
| Check-in confirmation card | Implemented |
| Local development API (`server.py`) | Implemented, dev only, not hardened |
| Signed `ATTv1` QR minting (dev kiosk) | Implemented, dev only |
| One attendance record per student per day | **Pending — code is per session** |
| Statuses Present / Late / Absent | **Partially — only On Time / Late exist; Absent not implemented** |
| Production database | **Pending — Engineer B; local server uses a JSON file** |
| Mentor/admin interface, absence marking, reporting | **Not started** |

---

## 1. Project overview and objectives

The LEARN 2EARN fellowship runs three teaching sessions a day and needs a trustworthy
attendance record. The paper-and-signature-sheet process is slow and easy to falsify, so
attendance is taken by QR code instead.

Objectives of this module:

1. Give each student a private account so their attendance is tied to a real identity.
2. Let a student check in by scanning the mentor's QR code with a phone camera, with no
   typing and no manual entry.
3. Make the **server**, never the browser, decide whether a scan counts and whether it is on
   time or late.
4. Show the student an immediate, unambiguous result, and a history they can check later.
5. Refuse duplicate scans instead of silently creating extra records.
6. Use `Africa/Lagos` (WAT) for every date and time decision, because the institution's day
   boundaries are WAT boundaries.

Out of scope for Engineer A: the database, the production API, the mentor kiosk, and the
final decision on attendance policy.

---

## 2. Current system architecture

```text
┌──────────────────────────────┐        ┌─────────────────────────────┐
│  Browser (student's phone)   │        │  Engineer B's backend       │
│                              │        │  (production, not in repo)  │
│  index.html + styles.css     │ HTTPS  │  - real database            │
│  app.js                      │───────▶│  - verifies QR signature    │
│  vendor/html5-qrcode.min.js  │  JSON  │  - computes status          │
│                              │        │  - enforces uniqueness      │
└──────────────────────────────┘        └─────────────────────────────┘
                │
                │ during local development only
                ▼
┌──────────────────────────────┐        ┌─────────────────────────────┐
│  server.py (this repo)       │        │  dev/kiosk.html (this repo) │
│  static files + /api/v1      │◀───────│  asks server.py for a live  │
│  in-memory + dev/.data.json  │        │  signed test QR             │
└──────────────────────────────┘        └─────────────────────────────┘
```

- **Frontend**: static files, no framework, no build step. One HTML page with four views
  (auth, dashboard, scanner, history) plus a confirmation modal.
- **API base URL**: derived at runtime from `window.location.origin`, so the same build works
  on `localhost`, on a LAN address and behind an HTTPS tunnel without editing code.
- **Local API**: `server.py`, Python standard library only. It implements the endpoints in
  `API_CONTRACT.md` so the portal can be run and demonstrated before Engineer B's backend is
  available. It also serves the static files.
- **Storage**: in memory, mirrored to `dev/.data.json`. There is no database engine anywhere
  in this repository.
- **QR issuing**: only the dev kiosk in this repository mints codes, and only for testing.

---

## 3. Repository and folder structure

```text
Student_Attendance/
├── index.html               # all markup: auth screen, dashboard, scanner, history, modal
├── styles.css               # all styling, design tokens, responsive rules
├── app.js                   # all behaviour; CONFIG block at the top
├── server.py                # local dev API + static file server (stdlib only)
├── requirements.txt         # intentionally empty: no third-party packages
├── API_CONTRACT.md          # the agreed frontend ↔ backend contract with Engineer B
├── README.md                # this file
├── LICENSE
├── .gitignore
├── assets/
│   ├── learn2earn-logo.svg  # official Learn2Earn lockup
│   └── learn2earn-mark.png  # mark-only crop
├── vendor/
│   └── html5-qrcode.min.js  # scanner library, vendored so it works offline
├── dev/
│   └── kiosk.html           # dev-only page showing a live signed test QR
├── .vscode/
│   ├── launch.json          # F5 → run server.py
│   ├── settings.json
│   └── extensions.json
└── favicon.png
```

`dev/.data.json` is created at runtime and is git-ignored. It does not exist in a fresh clone.

---

## 4. Student registration and login

**Registration** (`index.html` → `#registerForm`, handler `registerStudent()` in `app.js`).

| Field | Rule | Where enforced |
|-------|------|----------------|
| Full name | at least 2 characters, whitespace collapsed | browser and `server.py` |
| Attendance username | 3–30 chars, `a-z 0-9 _ -` only, lowercased, spaces removed as you type | browser and `server.py` |
| Password | at least 8 characters | browser and `server.py` |
| Confirm password | must match | browser only |

Both sides validate on purpose: the browser gives instant feedback, the server refuses to
trust it. The server also enforces uniqueness and returns `409` with
`"That username is already taken."` if the username exists.

On success the server returns an access token and the student object, and the UI goes straight
to the dashboard. If a backend ever returns the student without a token, the UI falls back to
"Account created. Please sign in with your new details."

**Login** (`#loginForm`, handler `loginStudent()`). Username and password are posted to
`/auth/login`. A wrong username and a wrong password give the same `401` message,
`"Incorrect username or password."`, so the endpoint does not reveal which accounts exist.

**Session handling.** The token is held in memory only. `PERSIST_SESSION` in `app.js` is
`false`, so refreshing the page signs the student out. Set it to `true` to keep the session in
`sessionStorage` for local demos; that is not a production pattern, because script on the page
could read it.

**Token expiry.** Tokens last 2 hours (`TOKEN_TTL_MS` in `server.py`). Any `401` clears the
token, returns the student to the sign-in screen and shows "Your session ended. Please sign in
again."

**Logout.** `POST /auth/logout` returns `{"ok": true}` and the browser discards the token.
The dev server does not revoke the token server-side, so a copied token stays valid until it
expires. See section 15.

---

## 5. Student dashboard and attendance history

**Dashboard** (`#dashboardView`) shows:

- a welcome line with the student's first name;
- four stat cards for the current WAT month: **Sessions attended**, **On-time attendance**,
  **Late attendance**, **Attendance rate**;
- **Recent attendance** — the five newest records for the current month;
- **My profile** — full name, attendance username, account status.

**Attendance history** (`#historyView`) shows the full record for a month chosen with a
`<input type="month">` picker, with a live record count.

Two behaviours worth knowing, both deliberate:

- The dashboard month and the history month are tracked separately. Changing the history
  filter used to overwrite the dashboard numbers; it no longer does.
- **Attendance rate is only shown when the server supplies a real denominator.** `app.js`
  divides records by `total_sessions` and shows `—` if that field is missing, rather than
  inventing a percentage. The dev server's own `total_sessions` is a **placeholder**
  (15 for the current month, 20 otherwise) so the card has something to render during a demo.
  Do not read that number as a real curriculum total; see section 15.

All dates and times are formatted in `Africa/Lagos` by `watParts()` and `watMonthKey()` in
`app.js`, including the "current month" calculation, so a student checking at 00:30 WAT on the
1st does not see the previous month.

---

## 6. QR-code generation and scanning workflow

**Who generates the code.** The mentor's kiosk, which is Engineer B's component. A code is an
`ATTv1` payload:

```text
ATTv1.<base64url(payload)>.<base64url(HMAC-SHA256(payload, QR_SECRET))>

payload = {"session": "morning", "token": "<random>", "expiresAt": <epoch ms>, "scanDate": "2026-11-18"}
```

This repository contains no production QR issuer. `dev/kiosk.html` asks `server.py` for a live
test code so the scan flow can be exercised without the mentor kiosk.

**Scan flow, step by step:**

1. Student opens **Scan attendance** and taps *Start camera*.
2. `html5-qrcode` requests the rear camera and decodes the QR frame by frame.
3. On the first decode the scanner stops and locks (`scanLocked`), so one physical scan cannot
   fire several requests.
4. `app.js` posts `{"qr_payload": "<decoded text>"}` to `/attendance/check-in` with the bearer
   token. The browser never parses the payload and never decides anything.
5. The server verifies, in this order: format → signature → known session → not expired →
   correct `scanDate` → not already recorded.
6. On success (`201`) the confirmation card shows name, username, session, WAT date and time,
   and the server's status. The dashboard refreshes.
7. On a duplicate (`409` with `code: "DUPLICATE_ATTENDANCE"`) the student is told
   "Already checked in for this session" and the existing record is left untouched.

**Error messages the student can see** (all verified against `server.py`):

| Situation | Response |
|-----------|----------|
| Payload is not an `ATTv1` string | `400` "This is not an attendance QR code." |
| Bad base64/JSON inside the payload | `400` "This QR code is damaged. Ask your mentor to show a fresh one." |
| Signature does not match | `400` "This QR code was not issued by the attendance system." |
| Unknown session name | `400` "Unknown attendance session." |
| Past `expiresAt` | `400` "This QR code has expired. Scan the current one." |
| `scanDate` is not today in WAT | `400` "This QR code is for a different day." |
| Same student, same session, same day | `409` "Already checked in for this session." |
| Missing or expired token | `401` "Your session has expired. Please sign in again." |

The signature check runs first, so a forged code always gets the "not issued by the attendance
system" message, even if it is also expired. That ordering is intentional.

**Camera requirement.** `getUserMedia` only works on `localhost` or over HTTPS. A plain-HTTP
LAN address such as `http://192.168.1.42:8000` loads the portal but the scanner cannot open the
camera. Section 14 covers the workarounds.

---

## 7. Daily attendance rules and duplicate prevention

### 7.1 Approved policy (from the project supervisor)

- The system records **one attendance record per student per calendar day**.
- This is general daily attendance, **not** attendance per subject, class or individual
  session.
- A duplicate scan must not create a second record for that student on that day.
- The backend is authoritative for validation and status.
- Statuses are **Present**, **Late** and **Absent**.
- Dates and time calculations use `Africa/Lagos`.
- QR validation and attendance recording follow the approved daily workflow.

### 7.2 What the code in this repository actually does

**The code is session-based, not daily. This is the main gap between policy and
implementation, and it is not a documentation wording issue.**

- `server.py` defines three session windows in `SESSIONS`: morning, afternoon, evening.
- A check-in builds its uniqueness key as `session_id = f"{scanDate}-{session}"`, for example
  `2026-11-18-morning`.
- The duplicate check in `check_in()` matches on `(student_id, session_id)`. It therefore
  prevents the same student scanning the *same session* twice, and deliberately allows a
  different session later the same day.
- Verified on 18 November 2026 against a clean database: scanning the morning, afternoon and
  evening codes with one student produced **three records dated 2026-11-18**, while a second
  morning scan returned `409 DUPLICATE_ATTENDANCE`.

So today the system enforces "one record per student per session", which is the opposite of the
approved "one record per student per day".

### 7.3 What has to change to satisfy the policy

| # | Change | File |
|---|--------|------|
| 1 | Duplicate key becomes `(student_id, scan_date)`; the second scan of the day returns the duplicate response regardless of session | `server.py` `check_in()` |
| 2 | `session_id` / `session_name` stop being the record identity; the record is keyed by attendance date | `server.py` row shape, `app.js` table |
| 3 | One daily cutoff replaces the three session cutoffs, so "Late" has a single meaning | `server.py` `SESSIONS`, needs a policy decision (see below) |
| 4 | Absence marking: a scheduled end-of-day job writes `absent` for enrolled students with no record that day. No scheduler exists in this repository | new component, Engineer B |
| 5 | History table column "Session" becomes the attendance date; status labels become Present / Late / Absent | `index.html`, `app.js` |
| 6 | Contract and UI vocabulary updated from `on_time`/`late` per session to daily `present`/`late`/`absent` | `API_CONTRACT.md`, `app.js` |

**Open question for the supervisor before change 3 is coded:** with one record per day, what
time makes a student late? The current three cutoffs (09:10, 13:10, 17:15) cannot all survive.
The most likely reading is that a student is Present if they check in during any session that
day and Late if their first check-in is after that session's cutoff, with the day's earliest
record kept. That needs confirming; the README does not assume it.

### 7.4 Duplicate prevention that does exist today

- The server decides, not the browser. `app.js` stops the scanner after one decode but
  explicitly lets the server answer, because a client guard cannot be trusted.
- The check runs inside `DB_LOCK` and the insert happens in the same critical section, so two
  simultaneous requests cannot both create a row in this single-process server.
- Engineer B must enforce the same rule with a database constraint, not application code alone.
  In production that is `UNIQUE (student_id, attendance_date)` once the daily policy lands.

---

## 8. Attendance statuses

### 8.1 Approved set

| Status | Meaning |
|--------|---------|
| **Present** | Checked in on time for the day |
| **Late** | Checked in, but after the day's cutoff |
| **Absent** | No check-in recorded for the day |

### 8.2 What the code supports

Only two statuses exist: `on_time` and `late`. Both are computed by `server.py` from the server
clock in WAT, compared against the cutoff of the session named in the QR payload.

| Policy status | Current value in code | Displayed label today |
|---------------|----------------------|----------------------|
| Present | `on_time` | "On Time" |
| Late | `late` | "Late" |
| Absent | **does not exist** | — |

`API_CONTRACT.md` specifies `status` as `on_time` or `late`, and `app.js` treats anything that
is not `late` as on time. There is no absence record, no absence computation and no way to mark
a student absent in this repository. Absence can only come from a backend process that knows
the enrolled roster and runs at end of day.

The cutoff itself is inclusive: a scan at exactly the cutoff minute is on time, one minute
later is late. A late scan is still recorded; lateness never rejects a student.

---

## 9. Backend API configuration and endpoints

**Base URL.** `CONFIG.API_BASE_URL` in `app.js` is computed at load time:

```js
API_BASE_URL: (() => {
  const { protocol, origin } = window.location;
  if (protocol === "http:" || protocol === "https:") return `${origin}/api/v1`;
  return "http://localhost:8000/api/v1";   // opened from file://
})(),
```

So the portal always calls the host that served it. Override it only when the frontend must
talk to a different host, for example Engineer B's server during integration. No trailing
slash.

**Endpoints implemented by `server.py`** (all verified with `curl` on 18 November 2026):

| Method | Path | Auth | Purpose | Success | Failures |
|--------|------|------|---------|---------|----------|
| POST | `/api/v1/auth/register` | no | create a student | `201` token + student | `409` username taken, `422` validation |
| POST | `/api/v1/auth/login` | no | sign in | `200` token + student | `401` bad credentials |
| POST | `/api/v1/auth/logout` | bearer | sign out | `200 {"ok":true}` | — |
| GET | `/api/v1/students/me/attendance?month=YYYY-MM` | bearer | one month of the caller's records | `200 {records, total_sessions}` | `401` no/expired token, `422` bad month |
| POST | `/api/v1/attendance/check-in` | bearer | validate a scanned QR and record attendance | `201` record | `400` QR problems, `401`, `409` duplicate |
| GET | `/api/v1/dev/qr?session=morning\|afternoon\|evening` | no | mint a test QR (**dev only**) | `200` payload + metadata | — |
| POST | `/api/v1/dev/reset` | no | wipe and reseed data (**dev only**) | `200` | — |

Any other path returns `404 {"detail": "No route for <METHOD> <path>"}`. `GET /api/v1/...`
routes reject non-matching methods with the same `404` shape rather than `405`.

`API_CONTRACT.md` is the authoritative description of request and response bodies. It is the
document Engineer B codes against.

---

## 10. Database structure and persistence

**There is no database in this repository.** `server.py` keeps everything in two Python lists
and mirrors them to `dev/.data.json` after every write. This exists so the portal can be
demonstrated before Engineer B's backend is ready.

Stored shapes, exactly as written to `dev/.data.json`:

```jsonc
{
  "students": [
    {
      "id": "uuid4",
      "full_name": "Demo Student",
      "username": "demo_student",
      "password_salt": "hex",          // scrypt salt, 16 bytes
      "password_hash": "hex",          // scrypt n=16384 r=8 p=1 dklen=64
      "track": "General",
      "created_at": "2026-11-18T15:10:17.783Z"
    }
  ],
  "attendance": [
    {
      "id": "uuid4",
      "student_id": "uuid4",           // taken from the token, never from the request body
      "session_id": "2026-11-18-morning",
      "session_name": "Morning session",
      "attended_at": "2026-11-18T08:04:00.000Z",
      "status": "on_time",             // or "late"
      "scan_date": "2026-11-18",       // WAT calendar date
      "month": "2026-11"               // WAT month, used by the history filter
    }
  ]
}
```

`GET /students/me/attendance` returns a reduced view: `id`, `session_id`, `session_name`,
`attended_at`, `status`. `student_id`, `scan_date` and `month` stay server-side.

**Limits of this persistence:** single process, no transactions, no indexes, whole-file rewrite
on each write, no concurrent-writer safety beyond a thread lock, and no backup. Deleting
`dev/.data.json` resets everything. Passwords are never stored in plaintext.

**What Engineer B needs instead:** a real table per entity, a unique constraint implementing
the duplicate rule, indexes on `(student_id, attended_at)` and on the month key, and a
transaction-safe insert so two simultaneous scans cannot both succeed.

---

## 11. Installation and setup

Requirements:

- **Python 3.8 or newer** (3.9+ recommended). `server.py` uses only the standard library:
  `http.server`, `hashlib.scrypt`, `hmac`, `json`, `secrets`, `uuid`.
- A modern browser with a camera for the scan step.
- No Node.js, no npm, no build tools, no virtualenv, no `pip install`.

```bash
git clone https://github.com/super7abaga-crypto/Student_Attendance.git
cd Student_Attendance
python --version          # confirm 3.8+
```

On Windows use `python`; on macOS/Linux use `python3` if `python` is not present.

Optional VS Code extensions are listed in `.vscode/extensions.json` (Python and the Python
debugger). They are convenience only; nothing breaks without them.

---

## 12. How to run the frontend and backend

The dev server serves both, so one command runs everything.

**Option A — terminal**

```bash
python server.py
```

Expected output:

```text
  LEARN 2EARN dev server (Python)
  Portal : http://localhost:8000
  API    : http://localhost:8000/api/v1
  Kiosk  : http://localhost:8000/dev/kiosk.html  (live test QR)
  Demo   : demo_student / demo12345
```

**Option B — VS Code**: open the folder, press **F5**, choose
*"Run portal + dev API (Python)"*. It runs `server.py` and opens the browser at
`http://localhost:8000`.

Then:

1. Open `http://localhost:8000`.
2. Sign in with the seeded account `demo_student` / `demo12345`, or create your own.
3. Open `http://localhost:8000/dev/kiosk.html` in a second window to get a live QR, and point
   the portal's camera at it.

Stop the server with `Ctrl+C`.

**Frontend without the dev API** (only useful when pointing at Engineer B's backend): serve the
folder with any static server, for example `python -m http.server 5500`, and set
`CONFIG.API_BASE_URL` in `app.js` to that backend. The camera still needs `localhost` or HTTPS.

**Port already in use?** `PORT=8080 python server.py` (macOS/Linux) or
`$env:PORT=8080; python server.py` (PowerShell).

---

## 13. Environment variables and configuration

### 13.1 Server (`server.py`)

| Variable | Default | Effect |
|----------|---------|--------|
| `PORT` | `8000` | TCP port |
| `HOST` | `0.0.0.0` | Bind address. `0.0.0.0` lets phones on the LAN connect; use `127.0.0.1` to keep it local |
| `APP_SECRET` | random per start | HMAC key for access tokens. Random means **every restart invalidates all tokens**; set a fixed value to keep sessions across restarts |
| `QR_SECRET` | random per start | HMAC key for `ATTv1` QR codes. Random means codes minted before a restart stop verifying after it |
| `ALLOW_FOREIGN_QR` | off | `1`/`true`/`yes` accepts a well-formed `ATTv1` code signed by another issuer. **Development only** |

Example:

```powershell
$env:APP_SECRET = "local-dev-only-change-me"
$env:QR_SECRET  = "local-dev-only-change-me"
$env:PORT       = "8000"
python server.py
```

Neither secret is read from a file, and no `.env` loader exists. Set them in the shell that
starts the server.

### 13.2 Frontend (`CONFIG` at the top of `app.js`)

| Key | Current value | Effect |
|-----|---------------|--------|
| `API_BASE_URL` | derived from `window.location.origin` | Which API the portal calls |
| `DEMO_MODE` | `false` | **Vestigial.** It only changes the connection note text. No offline or browser-storage demo mode exists |
| `PERSIST_SESSION` | `false` | `true` keeps the token in `sessionStorage` so a refresh does not sign out. Local demos only |
| `SESSION_STORAGE_KEY` | `"attendly.session"` | Storage key name, kept from the earlier name of the project. Harmless; change it if the legacy name is confusing |

### 13.3 Testing on a phone over the LAN

1. On the PC run `ipconfig` and note the Wi-Fi adapter's IPv4 address (for example
   `192.168.1.42`).
2. On the phone open `http://192.168.1.42:8000`. If nothing loads, allow the port once in an
   elevated PowerShell:

   ```powershell
   New-NetFirewallRule -DisplayName "Portal 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
   ```

3. The UI will load, but **the camera will refuse** on a plain-HTTP LAN address. Either run an
   HTTPS tunnel (`cloudflared tunnel --url http://localhost:8000`, then open the `https://…`
   address on the phone), or on Android add the LAN origin to
   `chrome://flags/#unsafely-treat-insecure-origin-as-secure` and relaunch Chrome. Neither
   workaround is suitable for production; production must be HTTPS.

---

## 14. Testing instructions

There is no automated test suite in this repository. Testing is manual and repeatable with the
steps below; all of them were run on 18 November 2026.

### 14.1 Seeded account

| Username | Password | Notes |
|----------|----------|-------|
| `demo_student` | `demo12345` | Created on first start, with up to three sample records from the previous days of the current month |

### 14.2 API checks with curl

```bash
# 1. Sign in and keep the token
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo_student","password":"demo12345"}'

TOKEN="<access_token from the response>"

# 2. This month's records (200)
curl -s "http://localhost:8000/api/v1/students/me/attendance?month=2026-11" \
  -H "Authorization: Bearer $TOKEN"

# 3. No token (401)
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/v1/students/me/attendance

# 4. Malformed month (422)
curl -s -o /dev/null -w "%{http_code}\n" \
  "http://localhost:8000/api/v1/students/me/attendance?month=nope" \
  -H "Authorization: Bearer $TOKEN"

# 5. Mint a test QR and scan it
QR=$(curl -s "http://localhost:8000/api/v1/dev/qr?session=morning" | python3 -c "import sys,json;print(json.load(sys.stdin)['qr_payload'])")
curl -s -X POST http://localhost:8000/api/v1/attendance/check-in \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d "{\"qr_payload\":\"$QR\"}"                      # 201 first time

# 6. Scan the same code again (409 DUPLICATE_ATTENDANCE)
curl -s -X POST http://localhost:8000/api/v1/attendance/check-in \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d "{\"qr_payload\":\"$QR\"}"

# 7. Garbage payload (400)
curl -s -X POST http://localhost:8000/api/v1/attendance/check-in \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"qr_payload":"hello"}'

# 8. Reset the dev data
curl -s -X POST http://localhost:8000/api/v1/dev/reset
```

On PowerShell, `curl` is an alias for `Invoke-WebRequest`; use `curl.exe` for the commands
above, or run them in Git Bash.

### 14.3 Browser checks

- [ ] Register with a mixed-case username containing spaces; the field lowercases and strips
      spaces as you type.
- [ ] Register a username that already exists → "That username is already taken."
- [ ] Register with a 7-character password → "Your password must contain at least 8 characters."
- [ ] Register with mismatched confirmation → "The passwords do not match."
- [ ] Sign in with a wrong password → "Incorrect username or password."
- [ ] Dashboard stat cards match the records returned by the API for the current month.
- [ ] Change the history month; the dashboard numbers must not change.
- [ ] Start the camera on `localhost`, scan the kiosk code → confirmation card with the
      server's status, then the dashboard refreshes.
- [ ] Scan the same code twice → "Already checked in for this session."
- [ ] Scan an old code (wait past 2 minutes) → "This QR code has expired. Scan the current one."
- [ ] Restart the server without `QR_SECRET` set, then scan a code from before the restart →
      "This QR code was not issued by the attendance system."
- [ ] Resize to 390px width: sidebar collapses to the menu button, tables stay readable.

### 14.4 Testing with Engineer B's QR codes

Codes from Engineer B's kiosk are signed with their secret, which this dev server does not
hold, so they are rejected by default with "This QR code was not issued by the attendance
system." That rejection is correct behaviour, not a bug. To walk through the scan flow with one
of their codes locally:

```powershell
$env:ALLOW_FOREIGN_QR = "1"
python server.py
```

The server then accepts a well-formed `ATTv1` payload from another issuer, prints
`[dev] accepted a QR payload signed by another issuer (ALLOW_FOREIGN_QR=1)`, and maps
`session_type`, `scan_date` and ISO `expires_at` onto its own session table. Malformed,
expired and wrong-day codes are still refused. Never enable this for real attendance.

---

## 15. Current limitations and outstanding work

**Policy not yet implemented**

1. **Daily attendance is not implemented.** Records are per session; one student can hold three
   records for one day. See section 7.
2. **Absent does not exist.** No absence record, no absence computation, no end-of-day process.
3. **Status names differ from the policy.** The code uses `on_time` / `late`; the policy says
   Present / Late / Absent. One daily cutoff has to be agreed first.
4. **One daily cutoff is undecided**, which blocks items 1–3.

**Backend and data**

5. **No production database.** `dev/.data.json` is a single-process JSON mirror.
6. **`total_sessions` is a placeholder** (15 for the current month, 20 otherwise). The
   attendance-rate card is therefore illustrative, not a real percentage.
7. **Logout does not revoke tokens.** They stay valid until the 2-hour expiry.
8. **Secrets are random per start** unless `APP_SECRET` / `QR_SECRET` are set, so a restart
   invalidates every session and every outstanding QR code.
9. **No rate limiting, no lockout, no audit log, no password reset, no email verification.**
10. **CORS is `*`** on every response. Fine for a dev stand-in, wrong for production.

**Frontend**

11. **Session is lost on refresh** because `PERSIST_SESSION` is `false` by design.
12. **Camera needs `localhost` or HTTPS**; a plain LAN address cannot scan.
13. **The scanner library falls back to a CDN** if `vendor/html5-qrcode.min.js` is missing, so a
    blocked network shows "The QR scanner library did not load."
14. **Google Fonts needs internet on first load**; the page falls back to system fonts offline.
15. **Registration is open.** If the institution needs an invitation code, matriculation number
    or mentor approval, that belongs in the contract first.
16. **No mentor or admin view**: no roster, no manual correction, no export.

**Dev-only code that must not ship**

17. `server.py`, `dev/kiosk.html`, `dev/.data.json`, `POST /dev/reset`, `GET /dev/qr` and
    `ALLOW_FOREIGN_QR` are development aids. Delete or exclude them before any real deployment.

---

## 16. Integration responsibilities (Engineer A ↔ Engineer B)

**Engineer A — this module (frontend + local dev server)**

- Normalises username input and validates forms for a usable interface.
- Displays the authenticated student and their records.
- Opens the camera, decodes the QR and posts the raw payload.
- Displays the server's verdict, including duplicates, without reinterpretation.
- Formats timestamps in `Africa/Lagos` for display only.
- Maintains `API_CONTRACT.md` and this README.

**Engineer B — backend and system owner**

- Owns the database, its schema, migrations and backups.
- Repeats username normalisation and enforces uniqueness.
- Hashes passwords and verifies credentials; issues and validates sessions or tokens.
- Derives the student from the authenticated principal, never from the request body.
- Signs QR payloads and verifies signature, expiry, session state and eligibility.
- Computes status from server time in `Africa/Lagos`.
- Enforces the duplicate rule with a database constraint and a transaction-safe insert.
- Implements the daily-attendance policy and absence marking once the cutoff is agreed.
- Returns records only for the authenticated student.
- Owns rate limiting, CORS allow-listing, audit logging and HTTPS.
- Owns the production QR issuing kiosk.

**Shared, must be agreed in writing before either side changes behaviour:** API base URL,
endpoint paths and payload shapes, status vocabulary, the daily cutoff time, whether
registration is open, and the token/session strategy. All of it lives in `API_CONTRACT.md`.

---

## Appendix: recent changes

- Backend moved from Node.js to Python (`server.py`, standard library only); `package.json`,
  `node_modules` and `dev/mock-server.js` are gone.
- One real bug fixed during that port: a request whose body was never read (early `401`/`404`
  returns) left bytes in the socket and corrupted the next keep-alive request. The server now
  drains the body on every request.
- Current month and all date formatting use `Africa/Lagos` instead of UTC.
- History filter no longer overwrites the dashboard figures.
- `401` clears the session and returns the student to sign-in.
- Duplicate scans are answered by the server instead of a client-side guard.
- Double-submit protection on both auth forms.
- Attendance rate is clamped to 100% and shows `—` when the denominator is missing.
- Learn2Earn rebrand: official logo, live-portal design tokens (primary `#0950c3`, accent
  `#f97415`), gradient sidebar, two-panel dashboard.

## License

See `LICENSE`.
