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
    "campus": "b3a1…-uuid",
    "campus_name": "Lagos Campus",
    "campus_timezone": "Africa/Lagos"
  }
}
```

The portal reads `token` (falling back to `access_token` / `key`) and the profile from
`student` (falling back to `user` / `profile`). `campus` is Django's campus UUID and
`campus_name` is the readable label, so the portal shows the name and never the UUID.
`campus_timezone` is an IANA zone; when it is present the portal uses it to decide the
campus-local date and to label the time column, and when it is absent the portal falls back
to the campus-local date carried by attendance records rather than assuming a zone.

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
    "status": "late",
    "attendance_action": "check_in"
  }
}
```

**Response fields the portal reads.** `full_name`, `username`, `session_type`,
`attendance_date`, `scanned_at`, `scan_time_wat`, `status`, `attendance_action`.

`status` is rendered from the backend value only; the portal never computes it and never
compares the device clock with a cutoff. The canonical values are `present`, `late` and
`absent`, humanised as "Present", "Late" and "Absent". `on_time` is legacy data written
before the daily policy and is still displayed as "On Time" for historical rows only; it is
not a current status. Any other string is shown verbatim, and the raw value is always kept in
`data-status`, so a change of vocabulary on the backend never breaks the portal.

`attendance_action` is shown verbatim in the confirmation card's "BACKEND ACTION" row and
kept in `data-action`. The portal does not branch on its value: the duplicate path is driven
by HTTP 409 and `code: duplicate_attendance`, not by this field.

`attendance_action` values are `check_in` and `check_out` per Engineer B's published contract
(`docs/ENGINEER_A_API.md`); the mock mirrors them (override with `MOCK_ATTENDANCE_ACTION`).

**Duplicate responses carry the existing record.** Engineer B's 409 returns
`{success: false, code: "duplicate_attendance", message, attendance: {...}}`. The portal uses
that `attendance` object directly, so it never depends on a cached list. Only if a response
omits it does the portal re-read `/student/attendance-history/` and match the record for that
checkpoint and campus-local date. When no record can be found the notice is shown without a
card: the portal never invents attendance data.

Error codes the portal maps to student-readable messages:

| HTTP | `code` | Meaning |
|---|---|---|
| 409 | `duplicate_attendance` | Attendance already recorded for this checkpoint (one record per student, campus-local day and checkpoint). The same student may scan at later checkpoints that day. |
| 403 | `qr_expired` | QR past its 30-second life |
| 400 | `invalid_qr` | Malformed or not an attendance code |
| 403 | `wrong_campus` | Outside the campus geofence |
| 403 | `session_inactive` | No open session for that QR |
| 403 | `gps_accuracy` | Location too imprecise |

Cutoffs, the status enum and duplicate protection are Engineer B's. The settled defaults
are morning 09:00–12:00, afternoon 13:00–16:00 and evening 17:00–20:00 campus-local, with
lateness starting at 09:11:00 and 13:11:00 (the whole 09:10 and 13:10 minutes are on time)
and the evening checkpoint never late. The portal displays whatever status the backend
returns and never recomputes it.
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

The portal displays the campus-local clock time from `scan_time_local` (falling back to the
legacy `scan_time_wat`, which now carries the same campus-local value). `scanned_at` is the
canonical instant and is serialized as explicit UTC (`...Z`); the confirmation card shows it
verbatim as RECORDED (CANONICAL). `scanned_at_local` carries the same instant with its
campus offset. The time column heading follows `campus_timezone` when the backend supplies
it, so a São Paulo campus is labelled with its own zone rather than WAT. Month filtering
happens in the frontend on `attendance_date`. No percentage or total-session figure is
shown, because this endpoint does not supply a reliable denominator.

## Attendance rules (backend-owned)

| Checkpoint | Opens | Present through | Late from | Closes | Action |
|---|---|---|---|---|---|
| Morning | 09:00 | 09:10:59 | 09:11:00 | 12:00 | `check_in` |
| Afternoon | 13:00 | 13:10:59 | 13:11:00 | 16:00 | `check_in` |
| Evening | 17:00 | — | never late | 20:00 | `check_out` |

Times are campus-local, from `campus.timezone`; the server's own zone is never used for a
boundary. One record exists per student, per campus-local date and per checkpoint, so a
student may hold a morning, an afternoon and an evening record on the same day, while a
repeat scan inside one checkpoint returns `409 duplicate_attendance` with the existing record.
After each checkpoint closes, the backend creates one `absent` row for each enrolled student
who has no record for that checkpoint; a completed checkpoint never receives an absence, and
a scheduler retry cannot create a second one. The portal does not enforce or recompute any of
this.

## Open policy conflicts — for the Project Manager and CEO

1. **Daily versus per-checkpoint records — resolved.** The CEO approved the three-checkpoint
   model on 23 November 2026: one record per student, campus-local day and checkpoint, with
   morning and afternoon `check_in`, evening `check_out`, and a 409 for a repeat inside one
   checkpoint. The portal follows that model.
2. **Evening cutoff — settled.** Evening is a `check_out` that closes at 20:00 and is never
   late, so the older 17:10-versus-17:15 question no longer applies.
3. **Cutoff boundary — settled.** The CEO ruled that lateness starts at 09:11:00 and
   13:11:00, so the whole 09:10 and 13:10 minutes are on time. The mock, the contract and
   Partner B's backend now agree, and no frontend code depends on the old rule.

## CORS

The Django deployment must allow the student portal origin. If the portal is served from the
same host at `/student/`, the requests are same-origin and need no CORS headers. The local
mock sends `Access-Control-Allow-Origin: *` for convenience only.
