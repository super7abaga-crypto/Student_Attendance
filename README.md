# LEARN 2EARN — Student Attendance Portal

A responsive, browser-based student portal branded for **LEARN 2EARN**, built to plug into
Engineer B's Attendance Management System backend. Static HTML/CSS/JS, no build step, no
framework.

## Brand and UI source

The logo and interface follow the live Learn2Earn fellowship portal
(`fellowship.learn2earn.ng/dashboard/attendance`):

- **Logo**: the official `assets/learn2earn-logo.svg` (taken from the live site). It renders
  white in the sidebar via `filter: brightness(0) invert(1)`, exactly like the live portal, and
  in full colour on the white sign-in card. `assets/learn2earn-mark.png` and `favicon.png` are
  crops of the same artwork, so there is a single source of truth.
- **Design tokens** mirror the live app: primary `#0950c3`, secondary/accent orange `#f97415`,
  success `#16a249`, warning `#f59f0a`, background `#fcfcfd`, border `#e0e5eb`, 12px radius,
  Plus Jakarta Sans for display type and Inter for body text (Google Fonts, with a system
  fallback so the portal still works offline).
- **Layout**: deep-blue gradient sidebar with an orange active marker, sticky white top bar,
  four stat cards with muted icon tiles, then the two-panel row (recent attendance table and
  the profile card) with soft-shadow cards that lift on hover.

## What works right now

- Student registration and username login (username normalised to lowercase, spaces removed).
- Dashboard with this month's sessions attended, on time, late, and attendance rate.
- Mobile camera QR scanner (`html5-qrcode`, vendored locally so it also works offline).
- Check-in confirmation card showing full name, username, session, WAT date/time and the
  server's `On Time` / `Late` result.
- Duplicate check-in messaging, scan lock while a request is in flight, and re-scan support.
- Monthly attendance history with a month picker.
- Session expiry handling: a `401` sends the student back to sign in with a clear message.
- A local mock API (`server.py`, Python standard library only) that implements the contract,
  so the portal runs and can be demoed before Engineer B's backend exists.

### Session windows (WAT)

A scan counts as **On Time** from the moment the mentor's QR code is generated until the
cutoff minute, inclusive. Every minute after the cutoff is **Late**; nobody is refused for
being late, they are recorded as late.

| Session   | Window opens | On time until | Late from |
|-----------|--------------|---------------|-----------|
| Morning   | when the QR is generated (09:00) | 09:10 | 09:11 |
| Afternoon | when the QR is generated (13:00) | 13:10 | 13:11 |
| Evening   | when the QR is generated (17:00) | 17:15 | 17:16 |

The kiosk keeps minting the session's code for three hours after its start, so a student who
arrives after the cutoff still scans a live code and is simply marked late. The cutoff times
live in `SESSIONS` in `server.py` and must match Engineer B's server, which is the authority
on `status`.

## Project files

```text
engineer-a-student-portal/
├── index.html              # markup (auth screen, dashboard, scanner, history, confirmation)
├── styles.css              # all styling + responsive rules
├── app.js                  # all behaviour; CONFIG lives at the top
├── assets/
│   ├── learn2earn-logo.svg  # official lockup, used in sidebar, sign-in card and kiosk
│   └── learn2earn-mark.png  # mark-only crop for compact use
├── favicon.png
├── vendor/
│   └── html5-qrcode.min.js # vendored scanner library (CDN fallback stays in index.html)
├── server.py               # local API + static server (stdlib only, dev only)
├── dev/
│   ├── kiosk.html          # dev page that shows a live, signed test QR
│   └── .data.json          # created at runtime, git-ignored
├── .vscode/                # F5 launch config + recommended extensions
├── API_CONTRACT.md         # the shared contract with Engineer B
├── requirements.txt        # deliberately empty: no third-party packages
└── README.md
```

## Quick start in VS Code

1. Open the `engineer-a-student-portal` folder in VS Code (`File → Open Folder`).
2. Press **F5** and pick **“Run portal + dev API (Python)”**. The browser opens
   `http://localhost:8000` with the portal already talking to the local API.
   - Prefer a terminal? `python server.py` does the same thing.
3. Sign in with the seeded demo account:

   ```text
   username: demo_student
   password: demo12345
   ```

   Or create your own account from the **Create account** tab.
4. To test a scan without a phone: open `http://localhost:8000/dev/kiosk.html` in a second
   window (or on your phone) and point the portal's camera at the QR code.

Python 3.8 or newer is required for the dev server, and nothing else: `server.py` uses the
standard library only, so there is no `pip install`, no virtualenv and no `node_modules`.

### Testing on a phone (same Wi-Fi)

The dev server listens on all interfaces, and the portal calls whatever origin served it,
so no configuration is needed:

1. On the PC run `ipconfig` and note the Wi-Fi adapter's IPv4 address (e.g. `192.168.1.42`).
2. On the phone open `http://192.168.1.42:8000`. If nothing loads, allow the port once:
   `New-NetFirewallRule -DisplayName "Portal 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow`
3. Camera access needs `localhost` or HTTPS, so a plain LAN address loads the UI but the
   scanner will refuse. For a real scan from a phone, put the dev server behind any HTTPS
   tunnel service and open the `https://…` address it gives you. On Android you can instead
   trust the plain address under `chrome://flags` -> "Insecure origins treated as secure".

`API_BASE_URL` in `app.js` follows `window.location.origin`, so it works unchanged from
`localhost`, a LAN IP, or an HTTPS tunnel. Override it only when the frontend must talk to a
different host (for example Engineer B's server).

### Scanning Engineer B's QR with this dev server

Codes minted by Engineer B's kiosk are signed with their secret, which this stand-in does not
hold, so by default it answers "This QR code was not issued by the attendance system." That
rejection is correct: only their server can verify their signature. To walk through the scan
flow locally with their code, start the dev server in permissive mode:

```powershell
$env:ALLOW_FOREIGN_QR = "1"
python server.py
```

It then accepts a well-formed `ATTv1` payload from another issuer, logs
`[dev] accepted a QR payload signed by another issuer`, and maps `session_type` / `scan_date` /
ISO `expires_at` onto its own session table. Codes that are malformed, expired, or for another
day are still rejected. Leave the flag off for anything resembling real attendance.

### Other ways to run the frontend

- **VS Code Live Server** (`ritwickdey.liveserver`) on `index.html` → `http://localhost:5500`.
  Then run `python server.py` for the API and set `CONFIG.API_BASE_URL` in `app.js`
  accordingly.
- **Python**: `python -m http.server 5500` in this folder (the API still needs the dev server
  or Engineer B's backend).

The camera only works on `localhost` or over HTTPS. A plain-HTTP page served from another
machine on your network cannot open the camera.

## Connect to Engineer B's backend

Edit the top of `app.js`:

```js
const CONFIG = {
  API_BASE_URL: "https://your-backend.example.com/api/v1",
  DEMO_MODE: false,
  PERSIST_SESSION: false,
};
```

- `API_BASE_URL` must end at the API root (no trailing slash).
- `PERSIST_SESSION: true` keeps the session in `sessionStorage` so a page refresh does not
  sign the student out. Leave it `false` for production; agree a proper session strategy
  (HttpOnly refresh cookie or short-lived token) with Engineer B.
- The backend must allow CORS for the frontend origin.

Read `API_CONTRACT.md` before integration. It defines the four endpoints, payloads,
response shapes, error codes and the security responsibilities of each engineer.

## What changed in this revision

Backend moved from Node to Python:

- `dev/mock-server.js` is gone. `server.py` is the same server rewritten with the Python
  standard library only (`http.server`, `hashlib.scrypt`, `hmac`), so the project no longer
  needs Node or `npm install`.
- Same routes, same request and response shapes, same error strings, same `ATTv1` QR format,
  same WAT cutoffs (09:10 / 13:10 / 17:15) and the same `ALLOW_FOREIGN_QR` dev switch.
- `package.json` is removed; `requirements.txt` stays empty on purpose. Start with
  `python server.py`, or press F5 and pick the Python launch config.
- One real bug found while porting: a request whose body was not read (401/404 early
  returns) left bytes in the socket, so the next keep-alive request on that connection was
  parsed as garbage. `server.py` drains the body on every request.

Frontend (`app.js`, `index.html`, `styles.css`):

- **Current month is calculated in WAT**, not UTC, so a student at 00:30 on the 1st no
  longer sees the previous month.
- **History filter no longer overwrites the dashboard.** The dashboard month and the
  picked month are stored separately; previously filtering October replaced the dashboard
  numbers.
- **`401` handling**: an expired or revoked token now clears the session and returns the
  student to sign in with “Your session ended”.
- **Duplicate scans reach the server** (it is the authority) instead of being swallowed by a
  client-side guard, and the duplicate response is recognised from `409` +
  `already_checked_in` / `DUPLICATE_ATTENDANCE`.
- **Double-submit protection** on both forms, plus a fallback when `event.submitter` is
  missing (Enter key).
- Attendance rate is clamped to 100% and shows `—` when the backend omits `total_sessions`.
- Confirmation card: falls back to the current time if the response has no timestamp, and
  closes with Escape or a backdrop click.
- `watMonthKey()` / `watParts()` centralise all `Africa/Lagos` formatting.
- Scanner library vendored in `vendor/` with the CDN kept as a fallback; missing-library and
  camera-permission errors now show a readable message instead of failing silently.
- Mobile: inputs are 16px so iOS does not zoom the page on focus; long names truncate with
  an ellipsis; `prefers-reduced-motion` respected; visible keyboard focus outlines.
- Small robustness fixes: `noscript` notice, favicon, guarded DOM lookups in
  `stopScanner()`, no `undefined` view ids in `showView()`.
- **Learn2Earn rebrand + UI match**: the "A" mark is replaced by the official Learn2Earn logo,
  the whole interface was rebuilt on the live portal's design system (see above), and the
  sign-in screen is now the same centred card on the blue gradient. The sub-label reads
  STUDENT PORTAL instead of MENTOR CONSOLE.

Dev tooling (new):

- `server.py` — implements the contract with scrypt password hashing, HMAC-signed
  tokens, `ATTv1` signed QR payloads, WAT session cutoffs and database-level duplicate
  protection. Serves the frontend too. Data is mirrored to `dev/.data.json` (git-ignored).
- `dev/kiosk.html` — shows a live, signed QR that rotates every 30 seconds for scan testing.
- `.vscode/launch.json`, `requirements.txt` — one keypress to run everything.

The mock server is a development aid only. It is not hardened, has no rate limiting and
stores data in a JSON file. Delete `server.py`, `dev/kiosk.html` and `dev/.data.json` before handing
the frontend to the institution if you do not want them in the repository.

## Suggested test checklist

- [ ] Register with mixed-case username and spaces; verify the normalised username is used.
- [ ] Attempt duplicate username registration → “That username is already taken.”
- [ ] Attempt a weak password and a mismatched confirmation.
- [ ] Login with valid and invalid credentials.
- [ ] Verify a student cannot read another student's attendance (call the endpoint by hand).
- [ ] Scan a valid, active session QR code → confirmation card with server status.
- [ ] Scan an expired or forged QR code → clear error message.
- [ ] Scan twice for the same session → only one record exists.
- [ ] Verify On Time / Late comes from the backend, not the browser clock.
- [ ] Test camera permissions on Android and iOS over HTTPS.
- [ ] Test layout at phone, tablet and desktop widths.

## Security notes

This is Engineer A's frontend integration module, not an attendance backend. It never
creates trusted attendance records itself: the backend authenticates the student, validates
signed QR payloads, computes lateness from server time, enforces uniqueness in the database
and returns the authoritative result.

Registration is open in the UI. If the institution requires an invitation code,
matriculation number or mentor approval, add it to the shared contract first.

The QR library is vendored, but Google Fonts in `styles.css` still needs internet access on
first load; the page falls back to system fonts offline.
