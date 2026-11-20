# Engineer A API integration

Base URL: `https://fellowship.learn2earn.ng/api/v1/` in production. The mentor portal uses Django sessions; student clients use a per-student DRF token. The scan API derives identity from the authenticated student and does not accept a username as proof of identity.

The student portal is served by Django at `/student/`; the mentor portal remains at `/`. Its HTML is a Django template, and its CSS, JavaScript, logo, and vendored camera scanner are collected from `static/student/`. Production releases must run `python manage.py collectstatic --noinput` so these assets are available under `/static/student/`.

## Student authentication and attendance

### `POST auth/student/login/`

Request: `{ "username": "ada.okafor", "password": "…" }`. The server lowercases the username and removes spaces. Response includes `token` and the student profile. Student tokens expire after 12 hours; sign in again to renew. Send `Authorization: Token <token>` on student endpoints.

### `POST attendance/scan/`

Requires the student token. Request:

```json
{
  "qr_payload": "{\"version\":1,\"token\":\"signed-server-token\",\"expires_at\":1794908400}",
  "latitude": 6.5244,
  "longitude": 3.3792,
  "accuracy": 15
}
```

The camera reads a JSON QR envelope `{ "version": 1, "token": "…", "expires_at": 1794908400 }`. Send that exact decoded string as `qr_payload`; the backend extracts and verifies the signed inner token. It includes the campus UUID, session, action, issue/expiry times, run UUID and random nonce. It expires after 30 seconds, including at the exact expiry second. A screenshot may be reused inside that 30 second window; geofence checks remain required. `qr_token` containing only the inner signed string is also accepted.

Successful response is HTTP 201 with `success: true` and an `attendance` object containing full name, username, assigned campus, `session_type`, `attendance_action` (`check_in`), `attendance_date`, `scanned_at`, `scan_time_wat`, `status`, location verification and source. `session_type` shows the window that accepted the scan, but does not create another daily attendance record. `status` is `present`, `late`, or `absent`. A second scan for the same student and WAT calendar date returns HTTP 409 with `code: "duplicate_attendance"`. Scan failures use stable machine-readable codes: `invalid_qr`, `qr_expired`, `session_inactive`, `wrong_campus`, `gps_required`, `gps_accuracy`, `location_unconfigured`, and `student_inactive`. GPS accuracy and geofence distance are evaluated by the server.

**Cutoff boundary:** Django records a scan through the configured cutoff minute as `present`: 9:10 AM, 1:10 PM, and 5:10 PM are each Present. A scan from 9:11 AM, 1:11 PM, or 5:11 PM in the matching attendance window is `late`. Active students without a daily record become `absent` after the evening window closes.

Other student endpoints:

- `POST auth/student/register/` — campus administrator only; student registration and campus assignment are controlled by Engineer B. This endpoint requires `username`, `password` (12+ characters), `full_name`, and `campus` UUID; student self-registration is not currently enabled.
- `GET student/profile/`
- `GET student/attendance-history/`
- `POST auth/logout/`

## Mentor and administration API

- `POST auth/mentor/login/` — individual username/password, establishes a Django session. Browser requests include the `csrftoken` cookie as `X-CSRFToken` for state changes.
- `GET/PATCH auth/mentor/profile/`
- `GET/POST admin/campuses/` — POST is super administrator only. Campus detail supports GET/PATCH with role checks.
- `GET/POST admin/campuses/{campus_uuid}/schedules/` — schedule write is administrator only.
- `GET admin/tracks/?campus_id=…`
- `GET admin/students/?campus=…&search=…&active=true` — paginated; CSV upload is `POST admin/students/bulk_import/?campus_id=…`; export is `GET admin/students/export/?campus=…`.
- `POST admin/students/{student_uuid}/deactivate/`, `/reactivate/`, `/transfer/` — transfer requires a reason and retains old attendance campus IDs.
- `POST mentor/qr/start/` with `{ "campus_id": "…", "session_type": "morning" }`.
- `GET mentor/qr/current/?campus_id=…&session_type=morning` — returns the signed QR envelope and protected PNG URL.
- `POST mentor/qr/end/` with `{ "session_id": "…" }` — revokes live QR tokens.
- `GET mentor/attendance/?campus_id=…&date=YYYY-MM-DD&session_type=…&status=late&track_name=…&cohort_name=…&source=qr&search=…` — paginated; add `format=csv` for a protected export.
- `GET mentor/attendance/summary/?campus_id=…&date=YYYY-MM-DD`
- `POST mentor/attendance/manual/` — attendance ID or student ID/session, new status and required reason.
- `POST mentor/attendance/location-override/` — requires student, campus, session, reason and a matching recent failed location validation.
- `GET admin/reports/?campus_id=…&date_from=…&date_to=…`
- `GET admin/monthly-reports/?campus_id=…`; `POST admin/monthly-close/` with campus and optional completed year/month; CSV and JSON downloads are permission checked.
- `POST admin/monthly-reports/{report_uuid}/reopen/` with a reason.
- `POST auth/logout/`

Roles: `super_admin`, `campus_admin`, `mentor`, and `attendance_officer`. Campus scope comes from server side memberships; students cannot select another campus. Read only officers cannot perform corrections. API schemas are published through `/api/v1/docs/` and `/api/v1/schema/`.
