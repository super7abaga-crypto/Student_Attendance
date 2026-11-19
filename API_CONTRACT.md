# Engineer A ↔ Engineer B API Integration Contract

> **Status note (18 November 2026).** This contract describes the session-based API that is
> implemented today. The project supervisor has approved a change to **one attendance record
> per student per calendar day**, with statuses Present / Late / Absent, which is **not yet
> implemented** in `server.py` or this contract. The open question is which single daily cutoff
> defines Late; until that is agreed, the session cutoffs below remain in force. See section 7
> of `README.md` for the required changes.

This frontend is intentionally independent of Engineer B's implementation. The API base URL is configured at the top of `app.js` and is derived from the page's own origin, so the portal calls whichever host served it:

```js
API_BASE_URL: (() => {
  const { protocol, origin } = window.location;
  if (protocol === "http:" || protocol === "https:") return `${origin}/api/v1`;
  return "http://localhost:8000/api/v1";   // opened from file://
})(),
```

Override it only when the frontend must talk to a different host, for example Engineer B's server during integration. No trailing slash. The backend must enable CORS for the frontend origin.

## Required endpoints

All JSON requests use `Content-Type: application/json`. Authenticated requests use:

`Authorization: Bearer <access_token>`

### 1. Register student

`POST /auth/register`

Request:
```json
{
  "full_name": "Myles Odeh",
  "username": "myles_odeh",
  "password": "a-long-password"
}
```

The frontend normalizes usernames to lowercase and removes spaces. The backend MUST repeat validation and normalization; never trust frontend validation. Username must be unique. Hash passwords with a password-hashing algorithm such as Argon2id or bcrypt. Never store plaintext passwords.

Suggested success response (201):
```json
{
  "access_token": "signed-access-token",
  "token_type": "bearer",
  "student": {
    "id": "student-id",
    "full_name": "Myles Odeh",
    "username": "myles_odeh"
  }
}
```

If registration does not automatically sign in, return the created student object without an access token; the UI will ask the student to sign in.

### 2. Login

`POST /auth/login`

Request:
```json
{"username":"myles_odeh","password":"a-long-password"}
```

Success response:
```json
{
  "access_token": "signed-access-token",
  "token_type": "bearer",
  "student": {
    "id": "student-id",
    "full_name": "Myles Odeh",
    "username": "myles_odeh"
  }
}
```

Invalid credentials: HTTP 401 with a safe message. Do not reveal whether username or password was incorrect.

### 3. Current student's attendance history

`GET /students/me/attendance?month=2026-11`

Success response:
```json
{
  "records": [
    {
      "id": "attendance-id",
      "session_id": "session-id",
      "session_name": "Web Development - Morning",
      "attended_at": "2026-11-18T08:15:30+01:00",
      "status": "on_time"
    }
  ],
  "total_sessions": 20
}
```

`total_sessions` is optional. If absent, the frontend intentionally displays no attendance percentage rather than inventing a denominator. `status` must be `on_time` or `late`. `attended_at` should be an ISO-8601 timestamp with timezone. The UI formats it in `Africa/Lagos` (WAT).

### Session windows and status (WAT)

`status` is decided by the time the scan is received, never by the client.

| Session   | On time from | On time until | Late from |
|-----------|--------------|---------------|-----------|
| Morning   | QR generation (09:00) | 09:10 | 09:11 |
| Afternoon | QR generation (13:00) | 13:10 | 13:11 |
| Evening   | QR generation (17:00) | 17:15 | 17:16 |

The cutoff minute itself is on time. A late scan must still be recorded with
`status: "late"` rather than rejected; only codes that are malformed, forged, for another
day, or past expiry are refused.

### 4. Check in using QR payload

`POST /attendance/check-in`

Request:
```json
{"qr_payload":"opaque-signed-qr-payload"}
```

Success response:
```json
{
  "attendance_id": "attendance-id",
  "student": {
    "id": "student-id",
    "full_name": "Myles Odeh",
    "username": "myles_odeh"
  },
  "session_id": "session-id",
  "session_name": "Web Development - Morning",
  "attended_at": "2026-11-18T08:15:30+01:00",
  "status": "on_time"
}
```

Duplicate check-in should return HTTP 409, preferably:
```json
{
  "detail": "Already checked in for this session.",
  "code": "DUPLICATE_ATTENDANCE",
  "already_checked_in": true
}
```

The UI also recognizes `already_checked_in: true` in a success response.

## Security and responsibility boundaries

Engineer A (this module):
- Normalizes username input for a good user experience.
- Displays authenticated student data and attendance records.
- Opens the browser camera and submits the scanned QR payload.
- Displays the server's attendance result and duplicate response.
- Formats server timestamps for `Africa/Lagos`.

Engineer B (backend / system owner):
- Validates and normalizes usernames again; enforces uniqueness in the database.
- Hashes passwords and verifies login credentials.
- Issues and validates signed access tokens or secure sessions.
- Derives student identity from the authenticated principal, never from a student ID supplied by the browser.
- Signs QR payloads and verifies signature, expiry, session state and eligibility.
- Uses server time in the configured institutional timezone/rules to calculate `on_time` or `late`.
- Enforces duplicate attendance with a database uniqueness constraint and a transaction-safe insert. Today the agreed key is unique `(student_id, session_id)`; under the approved daily-attendance policy it becomes unique `(student_id, attendance_date)`.
- Returns attendance records only for the authenticated student.
- Applies rate limits, input validation, CORS allow-listing and audit logging.

## Integration checklist for Engineer B

- [ ] Confirm API base URL and update `CONFIG.API_BASE_URL` in `app.js`.
- [ ] Implement the endpoints and response shapes documented above, or agree on a mapping before changing the frontend.
- [ ] Configure CORS for the deployed frontend origin.
- [ ] Confirm whether registration is open or requires an invitation/student code. If approval is required, add the agreed field and validation to the registration contract.
- [ ] Confirm token expiry and refresh/logout strategy. For production, prefer secure, HttpOnly, SameSite cookies for refresh sessions; avoid long-lived tokens in localStorage.
- [ ] Serve the frontend over HTTPS so mobile browsers can access the camera.
- [ ] Test duplicate check-in using two simultaneous requests; only one attendance row may be created.
- [ ] Confirm the single daily cutoff for the approved one-record-per-day policy, then agree the status vocabulary (`present` / `late` / `absent`) and the absence-marking process before either side changes code.
