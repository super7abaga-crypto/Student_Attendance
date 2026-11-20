# Deployment and pilot status

**Status: not production-ready.** This repository has deployment configuration and automated tests, but no live URL, production database, Redis service, production secrets, approved pilot coordinates, or startup logs were supplied.

| Required item | Status | Required evidence |
|---|---|---|
| Live HTTPS URL | Pending | Record deployed portal URL. |
| `GET /health/` | Pending | Capture `{ "ok": true, "service": "learn2earn-attendance", "timezone": "Africa/Lagos" }`. |
| PostgreSQL and migrations | Pending | Follow `MIGRATION_SAFETY.md`, configure `DATABASE_URL`, then run `python manage.py migrate --noinput`. |
| Redis, Celery worker, Beat | Pending | Capture successful startup and verify 20:01 WAT daily and 00:15 WAT monthly schedules. |
| Static assets | Pending | Run `python manage.py collectstatic --noinput`; verify mentor and `/static/student/` assets over HTTPS. |
| Production secrets | Pending | Configure secrets, hosts, CSRF origins, CORS origins, and database URL in the deployment secret store. |
| Pilot campus | Blocked | Enter approved coordinates/radius, activate campus, authorise a mentor, and create a test student. |
| Kiosk verification | Pending | Capture mentor login, session activation, QR generation/refresh/expiry, and closure/revocation. |

## Pilot safety gate

QR scanning fails closed with `location_unconfigured` when campus latitude or longitude is missing. Do not begin pilot attendance until approved coordinates, geofence radius, campus activation, mentor access, and a test student have been configured.

## Required live evidence before approval

1. HTTPS portal and health response.
2. PostgreSQL migration output and verified backup/restore record.
3. Redis, Celery worker, and Beat startup logs.
4. Static-asset URLs returning `200`.
5. Redacted screenshots of mentor login, live kiosk QR, refresh, expiry rejection, and session-close rejection.
6. A test-student scan inside the geofence and rejection outside it.
