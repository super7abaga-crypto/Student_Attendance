# Student and mentor API contract

This document describes the checked-in Django implementation. API paths below are relative to `/api/v1/`; for example, `POST /auth/student/login/` means `/api/v1/auth/student/login/`. The student portal is `/student/`; the mentor portal is `/`.

## Attendance and time rules

### Timezone and timestamp semantics

`Campus.timezone` is the authoritative IANA timezone for attendance dates, checkpoint
windows, lateness, daily summaries, and automated absences. The backend converts the
server's current instant into that campus timezone before selecting `attendance_date` or
evaluating a schedule; clients must not derive the attendance date from the device clock.
The campus timezone is returned in campus objects and in the mentor summary response.

`scanned_at` is the immutable server-side instant at which a successful scan was recorded,
serialized as an ISO-8601 timestamp with an explicit UTC offset (normally `Z`). It is not
the phone's time and must be treated as an instant. `scan_time_wat` is a display-only
`HH:MM:SS` value formatted in the attendance campus timezone (currently WAT for
`Africa/Lagos`). `attendance_date` is the campus-local calendar date and may differ from
the UTC date around midnight. The portal should display `scan_time_wat` and use
`attendance_date` for grouping; it must not recalculate either value from local device
time.

The database allows one record per student, campus-local date, and checkpoint. The three checkpoints are morning check-in, afternoon check-in, and evening check-out. A duplicate scan in the same checkpoint returns `409 duplicate_attendance`; the same student may scan at later checkpoints on that date. Status values are `present`, `late`, and `absent`.

For the default Africa/Lagos schedule, morning and afternoon scans are `present` through the configured `late_after` minute, and `late` from the next minute onward (09:11 and 13:11 by default). Evening is a checkout and is never marked late. Each missed checkpoint is persisted as `absent` after its own close time. The daily summary marks a student `present` only after all three checkpoints, `late` if all three are complete and either check-in is late, `incomplete` if at least one checkpoint is completed but not all, and `absent` if both check-in windows close without a successful check-in. It marks `pending` before then when no successful checkpoint is recorded.

The defaults are:

| Checkpoint | Opens | Last on-time minute (`late_after`) | Late starts | Closes (exclusive) | Action |
|---|---:|---:|---:|---:|---|
| `morning` | 09:00 | 09:10 | 09:11 | 12:00 | `check_in` |
| `afternoon` | 13:00 | 13:10 | 13:11 | 16:00 | `check_in` |
| `evening` | 17:00 | N/A | N/A | 20:00 | `check_out` |

Morning and afternoon scans through the full 09:10/13:10 minute are `present`; lateness starts at 09:11/13:11. For example, 09:10:59 is present and 09:11:00 is late under the default morning schedule. This follows the project decision that lateness starts at 9:11, not at the beginning of the 9:10 minute. Evening checkout records the timestamp and is not marked late. A scan before a checkpoint opens or at/after its close is rejected as `session_inactive`. Campus schedules can override these windows.

After each checkpoint closes, the scheduled task creates an `absent` row when an enrolled student has no record for that checkpoint. The mentor summary counts a day as `present` when all three checkpoints are complete on time, `late` when all three are complete and a check-in was late, `incomplete` when there is some attendance but a checkpoint is missing, and `absent` when neither check-in was recorded after both check-in windows have closed. `pending` represents a day that is not yet complete and has no attendance evidence. Mentors can correct individual checkpoint records through the audited workflow.

Celery Beat checks in UTC every 15 minutes and evaluates each campus-local checkpoint close. It considers the prior local date for bounded catch-up and the current local date for newly closed checkpoints. Monthly report closure continues daily at 01:15 UTC. Reports store checkpoint rows in their snapshot and do not delete attendance data.

Historical whole-day absence rows retain their original session/action values. New missing-checkpoint rows use the checkpoint's actual action. Clients can use `record_kind: "system_absence"` with `status: "absent"` to identify system-generated rows; mentor-entered absences use `record_kind: "manual_absence"`.

## Authentication and permissions

- Student login is public and returns a DRF token. Send `Authorization: Token <token>` for authenticated student calls. Tokens expire after 12 hours; sign in again to obtain a token.
- Mentor login is public and creates a Django session cookie. For unsafe requests include the `csrftoken` cookie value in `X-CSRFToken`. Session-authenticated endpoints enforce CSRF.
- Authenticated API endpoints use Django REST Framework authentication and permissions. Student-only endpoints verify the authenticated user's role/profile. Staff endpoints allow super-admin, campus-admin, mentor, and attendance-officer roles, then apply campus membership and action-specific permissions. Session start/end and kiosk access are limited to mentors and administrators. Campus schedule changes and monthly close/reopen are limited to administrators for their assigned campus. Student registration and roster changes require `can_manage_students` for that campus (or super-admin / assigned campus-admin access); student read access alone is insufficient. CSV/JSON exports require export permission (administrators are allowed).
- Campus membership is checked server-side. Attendance officers can read scoped attendance but cannot perform mentor-only session actions or corrections.
- Student self-registration is not exposed: `POST /auth/student/register/` is a staff-authorized student creation endpoint. Student creation requires an assigned campus and a password of at least 12 characters.
- Rate limits are 30 anonymous requests/minute, 120 authenticated requests/minute, 5 student/mentor login attempts/minute per IP, and 20 attendance scans/minute per authenticated user. Production uses Redis for the shared cache backing these limits.

## Student endpoints

### `POST /auth/student/login/`

Request: `{ "username": "ada.okafor", "password": "…" }`. Username is normalized to lowercase with whitespace removed.

Success (`200`): `{ "success": true, "token": "…", "student": { "id", "full_name", "username", "campus", "campus_name" } }`.

Errors: `401 invalid_credentials`; `403 student_inactive`.

### `GET /student/profile/`

Requires authentication; student profile only. Returns the `StudentSerializer` object directly, with `id`, `student_code`, `username`, `full_name`, `email`, `campus`, `track`, `track_name`, `cohort`, `cohort_name`, `registration_date`, `active`, and `profile`. Missing student profile or inactive student returns `403`.

### `GET /student/attendance-history/`

Requires authentication; returns a bare JSON array, newest `attendance_date` and `scanned_at` first, capped at 500 rows for the authenticated student. Each object uses the `AttendanceSerializer` shape described below. This API does not return another student's records.

### `POST /attendance/scan/`

Requires student token, QR token (or version-1 QR envelope in `qr_payload`), and fresh `latitude`, `longitude`, `accuracy` values. The server derives the student identity from the token; a client-supplied username is ignored. Example:

```json
{
  "qr_payload": "{\"version\":1,\"token\":\"signed-server-token\",\"expires_at\":1794908400}",
  "latitude": 6.5244,
  "longitude": 3.3792,
  "accuracy": 15
}
```

Success (`201`): `{ "success": true, "attendance": <AttendanceSerializer> }`.

The serializer fields are `id`, `full_name`, `username`, `student_id`, `campus`, `campus_name`, `track_name`, `cohort_name`, `record_kind`, `session_type`, `attendance_action`, `attendance_date`, `scanned_at`, `scan_time_wat`, `status`, `status_label`, `source`, `source_label`, `location_verified`, `location_accuracy_m`, and `location_distance_m`. `record_kind` is additive: `attendance` for present/late rows, `system_absence` for generated checkpoint absences, `manual_absence` for mentor-entered absences. `source` is `qr`, `manual`, or `system`; generated checkpoint absences use `source: "system"` / `source_label: "Automated system"` after migration 0005.

The server validates signed QR token, 30-second expiry, active session and schedule, assigned campus, GPS accuracy, and geofence. If campus coordinates are missing, scanning fails closed with `403 location_unconfigured`.

| HTTP | `code` | Behavior and recovery |
|---:|---|---|
| 400 | `invalid_qr` | Payload missing or malformed; scan the current kiosk QR. |
| 400 | `gps_required` | Location or accuracy is missing; retry with fresh browser location permission. |
| 403 | `student_auth_required` | Sign in as a student. |
| 403 | `student_inactive` | Contact a campus administrator. |
| 403 | `qr_expired` | Wait for QR refresh and scan the current code. |
| 403 | `invalid_qr` | Token/signature/payload invalid; scan the current code. |
| 403 | `session_inactive` | Session is closed, inactive, outside its schedule, or otherwise invalid; contact the mentor. |
| 403 | `wrong_campus` | Move inside the assigned campus geofence and rescan. |
| 403 | `gps_accuracy` | Retry when browser location accuracy meets the server limit. |
| 403 | `location_unconfigured` | Scanning is blocked until campus coordinates are configured. |
| 403 | `location_unavailable` / `invalid_location` / `gps_required` | Obtain a valid location reading and retry. |
| 404 | `student_not_found` | Contact an administrator to repair the student profile. |
| 409 | `duplicate_attendance` | A record already exists for this student, campus-local date, and checkpoint. The response includes the existing serialized record in `attendance`; display its session and time, then let the student continue to a later checkpoint. A duplicate in one checkpoint does not block another checkpoint that day. |

### `POST /auth/logout/`

Deletes the authenticated token if token-authenticated, ends the session if session-authenticated, and returns `{ "success": true }`.

## Mentor and administration endpoints

Except for public login, these endpoints require staff authentication and campus scope. Unless stated otherwise the access-denied response is HTTP `403`; unauthenticated requests receive HTTP `401`. Validation errors use DRF's HTTP `400` response format.

| Method and path | Purpose / response |
|---|---|
| `POST /auth/mentor/login/` | Public login; success `{success, csrf_token, display_name, role}` and session cookie; invalid credentials `401 invalid_credentials`. |
| `GET/PATCH /auth/mentor/profile/` | Authenticated staff profile and campus access; patch can update display name/password. |
| `GET/POST /admin/campuses/`; `GET/PATCH /admin/campuses/{id}/` | Campus directory; creation is super-admin only. Campus details include coordinates, geofence radius, timezone and active state. Coordinates must be supplied as a valid latitude/longitude pair or both left blank; radius is 20–2,000 metres and timezone must be a valid IANA name. |
| `GET/POST /admin/campuses/{id}/schedules/` | Read schedules; create/update requires super-admin or the campus's assigned campus-admin. Schedule fields: `id`, `campus`, `session_type`, `start_time`, `late_after`, `close_time`, `active`; `start_time <= late_after < close_time` is required. |
| `GET /admin/tracks/?campus_id=<uuid>` | Active tracks for a campus the user can access. |
| `GET/PATCH /admin/students/{id}/`; `GET /admin/students/?campus=<uuid>` | Campus-scoped roster. Reads require campus membership; updates and lifecycle actions require `can_manage_students` or super-admin / assigned campus-admin access. |
| `POST /auth/student/register/` | Staff-created student account; campus manage permission required. Duplicate username is `409 username_taken`. |
| `POST /admin/students/{id}/deactivate/`, `/reactivate/`, `/transfer/` | Campus-managed student lifecycle. Transfer requires management access to both campuses and a reason. |
| `GET /admin/students/export/?campus=<uuid>` | CSV roster export; export permission required. |
| `POST /admin/students/bulk_import/?campus_id=<uuid>` | Staff CSV import; max 2 MB and 5,000 rows. Returns `{created, errors}`. |
| `POST /mentor/qr/start/` with `{campus_id, session_type}` | Mentor/admin opens one scheduled session; returns `{session_id, campus, session_type, attendance_action, state}`. Invalid window `400 outside_session_window`; closed run `400 session_closed`. |
| `GET /mentor/qr/current/?campus_id=<uuid>&session_type=morning` | Mints a signed QR envelope valid for 30 seconds. Response includes `version`, `token`, `expires_at`, `qr_payload`, `qr_image_url`, `session_id`, `campus`, `campus_id`, `session_type`, `attendance_action`, `state`, `expires_in_seconds`. No active session/window is `409 session_closed` or `409 outside_session_window`. |
| `GET /mentor/qr/image/?token=<signed-token>` | No-store PNG for an authorized staff member with access to the QR's campus. |
| `POST /mentor/qr/end/` with `{session_id}` | Closes the run and revokes outstanding QR tokens. Unknown run is `404 session_not_found`. |
| `GET /mentor/attendance/?campus_id=<uuid>[&date=YYYY-MM-DD&date_from=…&date_to=…&status=present|late|absent&session_type=…&source=…&track_name=…&cohort_name=…&search=…]` | Paginated response (`count`, `next`, `previous`, `results`), 50 rows/page. Date-specific calls materialize absences for closed checkpoints. `format=csv` returns protected CSV, requires export permission, and escapes spreadsheet formula values with a leading apostrophe. |
| `GET /mentor/attendance/summary/?campus_id=<uuid>[&date=YYYY-MM-DD]` | `{campus: <CampusSerializer>, date, timezone, summary: <object>}`. Summary keys include daily `active_students`, `present`, `late`, `absent`, `incomplete`, `pending`, `not_checked_out`, `attendance_percentage`, `completed_sessions`; checkpoint counts are in `checkpoints.morning`, `.afternoon`, and `.evening`. `morning_check_ins` and `afternoon_check_ins` count successful check-ins; `evening_check_outs` counts successful check-outs. |
| `POST /mentor/attendance/manual/` | Audited status correction or per-checkpoint row creation. A reason is mandatory. A student/date/checkpoint duplicate returns `409 duplicate_attendance`. |
| `POST /mentor/attendance/location-override/` | Mentor/admin audited override requires a matching location rejection from the same session within 15 minutes, today's campus-local date, an open monthly report, a reason, and campus correction access. |
| `GET /admin/reports/?campus_id=<uuid>&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` | `{results: [{campus, records, present, late, absent, by_session}]}` for accessible campuses. |
| `GET /admin/monthly-reports/?campus_id=<uuid>` | `{results: [...]}` monthly-report metadata. |
| `POST /admin/monthly-close/` | Administrator closes a completed month and returns report metadata including CSV URL. |
| `POST /admin/monthly-reports/{report_id}/reopen/` | Administrator reopens a report with audit trail. |
| `GET /admin/reports/{report_id}/csv/` and `/json/` | Protected monthly report downloads; JSON export requires campus export permission. |

Campus-related error codes include `campus_not_found` as a validation error, permission denied as HTTP `403`, `attendance_not_found`/`student_not_found`/`report_not_found`/`session_not_found` as HTTP `404`, and `duplicate_attendance` as HTTP `409` for a duplicate student/date/checkpoint. The 409 response includes the existing checkpoint in `attendance` when found. QR/session errors are listed above. Generic authentication failures follow DRF's `401` response.

## OpenAPI

Swagger UI is `/api/v1/docs/`; schema is `/api/v1/schema/`; ReDoc is `/api/v1/redoc/`.
