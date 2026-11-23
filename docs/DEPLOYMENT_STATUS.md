# Deployment handoff and pilot readiness

**Release status: not production-ready; live deployment is blocked pending infrastructure and pilot configuration.** This file records checked facts from the local workspace. A URL, service, credential, campus location, or startup log must not be marked complete without evidence from the target environment.

## Handoff checklist

| Requirement | Status | Evidence / action required |
|---|---|---|
| Live HTTPS URL | **Not supplied** | Record the deployed student and mentor portal URL after deployment. |
| `GET /health/` | Implemented locally; live check **pending** | The view checks database connectivity and returns `{ "ok": true, "service": "learn2earn-attendance", "database": "ok" }` (or HTTP 503 with `database: unavailable`). Capture the actual HTTPS response and time. |
| Working API endpoints | Local automated API coverage passes; live check **pending** | Run the student auth/profile/history/scan and mentor auth/QR/attendance/summary flows against the deployed service. Swagger: `/api/v1/docs/`; schema: `/api/v1/schema/`. |
| PostgreSQL connected | **Not configured/verified** | Set `DATABASE_URL` in the deployment secret store. Run the approved migration process and capture a redacted connection/deploy log and `showmigrations` output. Local development/tests use SQLite unless `DATABASE_URL` is set. |
| Migrations applied | Local test DB applies migrations; target DB **pending** | Review and approve migration 0004 using `MIGRATION_SAFETY.md`; run it only on staging first and then on production after explicit release approval. |
| Redis and Celery worker | **Not supplied** | Configure the Redis broker and worker service, capture healthy startup and successful task execution. |
| Celery Beat | **Not supplied** | Verify the UTC 15-minute daily absence check and daily 01:15 UTC monthly close task. Capture Beat schedule and task execution evidence; per-campus decisions use each campus's timezone. |
| Static assets collected | Local discovery works; deployment **pending** | Run `python manage.py collectstatic --noinput`; verify `/static/student/` and mentor CSS/JS return HTTP 200 over HTTPS. |
| Production secrets | **Not confirmed** | Configure `DJANGO_SECRET_KEY` (random, at least 50 characters), `ATTENDANCE_SECRET` (random, at least 48 characters), database/broker credentials, `REDIS_URL`, `DJANGO_ALLOWED_HOSTS`, CSRF trusted origins, and CORS origins in the deployment secret manager. Do not put secret values in this handoff. |
| Deployment logs | **Not supplied** | Attach successful build, migration, web startup, worker, Beat, and health-check logs with credentials redacted. |
| Pilot campus configuration | **Blocked** | An authorized Learn2Earn campus representative must supply and approve exact latitude/longitude and geofence radius. Set timezone to `Africa/Lagos`, mark the campus active, and verify campus permissions. Coordinates must not be guessed. |
| Authorized mentor and test student | **Not supplied** | Create accounts through the authorized admin process, assign campus permissions, and record account identifiers (never passwords). |
| Live mentor kiosk verification | **Pending** | With approved campus and mentor, capture login, session start, initial QR, refresh after 30 seconds, rejection of expired QR, session close, and post-close rejection. |
| Mentor portal/kiosk screenshots | **Not supplied** | Capture redacted screenshots from the deployed pilot after the preceding prerequisites are complete. |

## API endpoints for deployment smoke checks

Use the deployed origin plus `/api/v1/`:

- `POST auth/student/login/`, then `GET student/profile/` and `GET student/attendance-history/` using the returned student token.
- `POST auth/mentor/login/` with session cookie and CSRF handling.
- `POST mentor/qr/start/`, poll `GET mentor/qr/current/` through token rotation, then `POST mentor/qr/end/`.
- `GET mentor/attendance/` and `GET mentor/attendance/summary/` using a campus-scoped mentor account.
- `GET /health/` is at the site root, not under `/api/v1/`.

Do not perform a real student QR scan until the pilot campus has approved coordinates and radius, is active, and has `Africa/Lagos` as its timezone. The backend fails closed with `location_unconfigured` when latitude or longitude is absent. Geofence testing also requires a controlled location and an authorized test account.

## Release gate

Production readiness can be claimed only after the live URL and health/API checks, PostgreSQL migration state, Redis/Celery worker and Beat schedule, static asset responses, securely configured production secrets, startup logs, pilot campus/mentor/student setup, and end-to-end kiosk evidence have been captured and reviewed. Migration 0004 must remain unapplied in production until its separate approval gate in `MIGRATION_SAFETY.md` is satisfied.
