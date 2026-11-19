# Engineer A ↔ Engineer B API Contract — Student Portal

**Owner of this document:** Engineer A (student portal)
**Backend owner:** Engineer B (Django, source of truth)
**Last updated:** 19 November 2026

This file describes what the student portal calls. It does not describe Engineer B's
internals, and the portal never re-implements a backend decision.

## Base URL

| Environment | Base URL |
|---|---|
| Production | `https://fellowship.learn2earn.ng/api/v1/` |
| Local Django | `http://127.0.0.1:8000/api/v1/` |
| Local mock (dev only) | `http://127.0.0.1:8000/api/v1/` from `server.py` |

The portal resolves the base URL in `app.js` (`CONFIG.API_BASE_URL`):

1. `window.LEARN2EARN_API_BASE` if set before `app.js` loads, else
2. the `learn2earn-api-base` meta tag in `index.html`, else
3. `<page origin>/api/v1` for `http(s)` pages (so Django can serve the portal at `/student/`
   and the API at `/api/v1/` on the same host), else
4. `https://fellowship.learn2earn.ng/api/v1/` when opened from `file://`.

There is exactly one place to change the address, and no call site hard-codes a host.

## Authentication

Django token authentication. The header is **`Authorization: Token <token>`**.
`Bearer` is never sent and is rejected by the local mock.

- Students cannot register. Accounts are created by a mentor or administrator.
- Token lifetime: **12 hours**. The portal stores `{token, student, savedAt}` in
  `sessionStorage`, so a refresh in the same tab keeps the session and a new tab does not.
- On any `401` the portal clears the session and returns to the login screen.

### 1. Student login

`POST /auth/student/login/`

```json
{"username":"student_username","password":"student_password"}
```

`200`:

```json
{
  "token": "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b",
  "student": {
    "id": "3f1c…",
    "full_name": "Myles Odeh",
    "username": "myles_odeh",
    "campus": "Lagos Campus"
  }
}
```

The portal reads `token` (falling back to `access_token` / `key`) and the profile from
`student` (falling back to `user` / `profile`). `campus` may be a string or an object with
`name`/`code`; both are handled.

`401` `{"detail": "Incorrect username or password."}` → shown as-is.

### 2. Logout

`POST /auth/logout/` with the Token header. `200` is enough; the portal clears local state
regardless of the response.

## 3. Scan attendance

`POST /attendance/scan/`

```json
{
  "qr_payload": "{\"version\":1,\"token\":\"signed-token\",\"expires_at\":1794908400}",
  "latitude": 6.5244,
  "longitude": 3.3792,
  "accuracy": 15
}
```

- `qr_payload` is the **exact** decoded camera text. The portal never trims, parses or
  validates it before sending, and never decides whether a QR is valid.
- Coordinates are a fresh `navigator.geolocation` fix per scan (`maximumAge: 0`,
  `enableHighAccuracy: true`).
- QR tokens expire after 30 seconds. The backend owns that check.

`201`:

```json
{
  "detail": "Attendance recorded.",
  "attendance": {
    "full_name": "Myles Odeh",
    "username": "myles_odeh",
    "session_type": "morning",
    "attendance_date": "2026-11-19",
    "scanned_at": "2026-11-19T08:04:12.000Z",
    "scan_time_wat": "09:04:12",
    "status": "late"
  }
}
```

`status` is displayed exactly as returned (`on_time` → "On Time", `late` → "Late",
`present` → "Present", `absent` → "Absent"; any other value is shown verbatim). The raw
value is always kept in `data-status` on the badge. The device clock is never used.

Error codes the portal maps to student-readable messages:

| HTTP | `code` | Meaning |
|---|---|---|
| 409 | `duplicate_attendance` | Already checked in for this session |
| 403 | `qr_expired` | QR past its 30-second life |
| 400 | `invalid_qr` | Malformed or not an attendance code |
| 403 | `wrong_campus` | Outside the campus geofence |
| 403 | `session_inactive` | No open session for that QR |
| 403 | `gps_accuracy` | Location too imprecise |
| 400 | `gps_required` | No coordinates supplied |
| 401 | — | Token missing, expired or revoked |

A `409` may include the original record as `attendance`; when it does, the portal shows that
record in the confirmation card instead of erasing it. When it does not, the message
"Already checked in for this session." is shown and the previous confirmation stays intact.

Any `detail` string from the backend is treated as student-safe text and displayed.

## 4. Attendance history

`GET /student/attendance-history/` with the Token header.

The response is a **bare list**:

```json
[
  {
    "id": "…",
    "full_name": "Myles Odeh",
    "username": "myles_odeh",
    "session_type": "morning",
    "attendance_date": "2026-11-19",
    "scanned_at": "2026-11-19T08:04:12.000Z",
    "scan_time_wat": "09:04:12",
    "status": "late"
  }
]
```

The portal uses `scan_time_wat` verbatim for the time column and falls back to `scanned_at`
formatted in `Africa/Lagos`. Month filtering happens in the frontend on `attendance_date`.
No percentage or total-session figure is shown, because this endpoint does not supply a
reliable denominator.

## Attendance rules (backend-owned)

| Session | Cutoff (WAT) |
|---|---|
| Morning | 09:10 |
| Afternoon | 13:10 |
| Evening | 17:10 |

A scan exactly at the cutoff is **Late**. Duplicate protection is per student, per session,
per day. The portal does not enforce or recompute any of this.

## Open policy conflicts — for the Project Manager and CEO

1. **Daily versus per-session records.** An earlier project decision specified one
   attendance record per student per calendar day. The current contract protects duplicates
   per session, so a student can hold three records in one day. The portal implements
   neither rule itself; it displays whatever the backend records. A decision is required
   before either side changes behaviour.
2. **Evening cutoff 17:10 versus 17:15.** The contract supplied for this task says 17:10;
   an earlier instruction from the student-portal side said 17:15. The portal displays the
   backend's answer, so this only affects Engineer B's calculation and the README table.
3. **Cutoff boundary.** The current contract states a scan exactly at the cutoff is Late.
   The earlier portal mock treated the cutoff minute as on time. The mock now follows the
   contract (`>= cutoff` is Late); no frontend code depends on either rule.

## CORS

The Django deployment must allow the student portal origin. If the portal is served from the
same host at `/student/`, the requests are same-origin and need no CORS headers. The local
mock sends `Access-Control-Allow-Origin: *` for convenience only.
