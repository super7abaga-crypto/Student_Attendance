# Engineer A ↔ Engineer B API contract

Base URL: `https://<deployment-host>/api/v1/`. The student portal is `/student/`; the mentor portal is `/`.

## Attendance rule

One attendance record exists per student per Africa/Lagos calendar date. The database enforces `UNIQUE(student_id, attendance_date)`.

Mentors open a QR window for `morning`, `afternoon`, or `evening`. The window tells clients when the student scanned; it does not create another daily record. A later successful scan on the same WAT date returns `409 duplicate_attendance`.

| Window | Present through | Late from |
|---|---:|---:|
| Morning | 09:10 WAT, inclusive | 09:11 WAT |
| Afternoon | 13:10 WAT, inclusive | 13:11 WAT |
| Evening | 17:10 WAT, inclusive | 17:11 WAT |

Status values are `present`, `late`, and `absent`. At 20:01 WAT, Celery Beat records `absent` for active students registered on or before that date who have no daily record. A summary or monthly report also materializes missing Absences after the evening window closes.

## Authentication and access

Students use `Authorization: Token <token>`. `POST auth/student/login/` creates a token that expires after 12 hours. Mentors use a Django session created by `POST auth/mentor/login/`; send the `csrftoken` cookie as `X-CSRFToken` on unsafe requests.

Roles are `super_admin`, `campus_admin`, `mentor`, `attendance_officer`, and `student`. Campus membership is checked on the server. Attendance officers are read-only; mentors need the corresponding per-campus permission to manage students, correct attendance, or export data.

## Student API

### `POST auth/student/login/`

Request: `{ "username": "ada.okafor", "password": "…" }`.

Success: `200 { "success": true, "token": "…", "student": { "id", "full_name", "username", "campus", "campus_name" } }`.

Failures: `401 invalid_credentials`; `403 student_inactive`.

### `GET student/profile/`

Requires a student token. Returns the authenticated student profile with campus, track, cohort, registration date, and active state. A non-student or inactive student receives `403`.

### `GET student/attendance-history/`

Requires a student token. Returns an array of at most 500 attendance objects, newest first. An object includes `id`, student identity, campus, `session_type`, `attendance_action`, `attendance_date`, `scanned_at`, `scan_time_wat`, `status`, `source`, and location-verification fields. Only the authenticated student’s records are returned.

### `POST attendance/scan/`

Requires a student token. Send either `qr_token` or a QR-envelope string in `qr_payload`, plus `latitude`, `longitude`, and `accuracy`.

```json
{
  "qr_payload": "{\"version\":1,\"token\":\"signed-server-token\",\"expires_at\":1794908400}",
  "latitude": 6.5244,
  "longitude": 3.3792,
  "accuracy": 15
}
```

Success is `201 { "success": true, "attendance": { … } }`. The server derives the student from the token and validates QR signature, 30-second expiry, active session, campus, GPS accuracy, and geofence.

| HTTP | Code | Recovery |
|---:|---|---|
| 400 | `invalid_qr` | Scan a current Learn2Earn QR. |
| 400 | `gps_required` | Send fresh location and accuracy. |
| 403 | `qr_expired` | Wait for the kiosk refresh, then rescan. |
| 403 | `session_inactive` | Ask the mentor to open the attendance window. |
| 403 | `wrong_campus` | Scan inside the assigned campus geofence. |
| 403 | `gps_accuracy` | Retry when GPS accuracy improves. |
| 403 | `location_unconfigured` | QR scanning remains disabled until campus coordinates are configured. |
| 403 | `student_inactive` | Contact a campus administrator. |
| 409 | `duplicate_attendance` | Keep the existing daily record; do not retry in another window. |

### `POST auth/logout/`

Deletes the student token or ends the mentor session and returns `200 { "success": true }`.

Student self-registration is disabled. `POST auth/student/register/` is a staff operation requiring authorised campus access.

## Mentor and administration API

The endpoints below require a mentor session and relevant campus access unless noted.

- `POST auth/mentor/login/` — creates a session and returns `csrf_token`, `display_name`, and `role`.
- `GET/PATCH auth/mentor/profile/` — reads or updates the authenticated mentor profile.
- `GET/POST admin/campuses/`; `GET/PATCH admin/campuses/{campus_id}/` — list/detail; creation is super-admin only.
- `GET/POST admin/campuses/{campus_id}/schedules/` — reads or updates campus QR windows; writes need administrator access.
- `GET admin/tracks/?campus_id=<uuid>` — active tracks for an authorised campus.
- `GET/PATCH admin/students/{id}/`; `GET admin/students/?campus=<uuid>` — scoped student roster.
- `POST admin/students/bulk_import/?campus_id=<uuid>` — CSV import, maximum 2 MB / 5,000 rows.
- `GET admin/students/export/?campus=<uuid>` — protected CSV roster export.
- `POST admin/students/{id}/deactivate/`, `/reactivate/`, `/transfer/` — transfer needs a destination `campus_id` and reason.
- `POST mentor/qr/start/` with `{ "campus_id": "…", "session_type": "morning" }` — opens a window only during its configured schedule.
- `GET mentor/qr/current/?campus_id=<uuid>&session_type=morning` — current signed QR envelope, expiry, and protected PNG URL.
- `GET mentor/qr/image/?token=<signed-token>` — no-store QR PNG for an authorised mentor.
- `POST mentor/qr/end/` with `{ "session_id": "…" }` — closes the session and revokes QR tokens.
- `GET mentor/attendance/?campus_id=<uuid>&date=YYYY-MM-DD&status=late&session_type=morning&format=csv` — paginated records or protected CSV. It materializes completed-day Absences before returning date-specific results.
- `GET mentor/attendance/summary/?campus_id=<uuid>&date=YYYY-MM-DD` — `{ campus, date, timezone, summary }`; `summary` contains `active_students`, `present`, `on_time` (count with `present` status), `late`, `absent`, `attendance_percentage`, and dashboard window counts.
- `POST mentor/attendance/manual/` — creates or corrects one daily record; a reason is mandatory. Absent cannot be created before the evening window closes.
- `POST mentor/attendance/location-override/` — audited correction for a matching recent GPS rejection.
- `GET admin/reports/?campus_id=<uuid>&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` — aggregate report.
- `GET admin/monthly-reports/?campus_id=<uuid>`; `POST admin/monthly-close/`; `POST admin/monthly-reports/{id}/reopen/` — monthly-report lifecycle.
- `GET admin/reports/{id}/csv/` and `/json/` — protected monthly exports.

Swagger and the generated schema are at `/api/v1/docs/` and `/api/v1/schema/`.
