# Learn2Earn Fellowship Attendance

Engineer B's Django backend and Learn2Earn branded mentor portal for campus scoped attendance. The former Node server is disabled; its source is preserved in `legacy/server.js.disabled` for review and JSON migration only. Django is the only active backend.

## Run locally on Windows

Python 3.12+ is required. For local development, the project uses a private SQLite database at `data/dev.sqlite3`; production settings require PostgreSQL.

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open <http://127.0.0.1:8000>. PowerShell users who prefer the old npm command can run `npm.cmd start`; it now launches Django's development server. Do not use `runserver` in production.

The first `createsuperuser` account signs into the admin console at `/django-admin/` (it does not sign into the mentor portal). There create a campus and its tracks/cohorts, set the campus latitude, longitude and approved geofence radius, add mentor/administrator users, and grant campus memberships using **Mentor campus accesses**. Or load the provided directory with `python manage.py seed_campuses`; the command is repeat-safe. Super administrators can add individual directory entries from the portal’s **Campuses** page. Directory entries start without verified coordinates, so set the campus latitude and longitude in Django Admin before QR scans can pass geofencing. Then mentors sign into the branded portal using their own username and password. Campus coordinates and mentor campus access are required before QR attendance can operate.

For a fresh installation the first Django superuser is created with `createsuperuser`. To migrate the legacy mentor account and JSON records, see [the migration guide](docs/MIGRATION.md).

## Current implementation

- Django 5.2, Django REST Framework, Django ORM and migrations.
- Separate Engineer A student portal at `/student/`; its collected assets live under `/static/student/` while the mentor portal stays at `/`.
- PostgreSQL settings for production; local SQLite only for development and tests.
- UUID records for campuses, students, session schedules, attendance and reports.
- Individual Django mentor accounts and independent sessions, plus student username/password authentication and DRF student tokens.
- Campus memberships and role/campus scoping for campus administrators, mentors and read only attendance officers.
- Server side HMAC-SHA256 QR tokens with campus, session, action, run ID, timestamps and nonce; 30 second lifetime and immediate revocation on session close.
- Morning, afternoon and evening QR windows, WAT lateness evaluation and campus geofence verification with GPS accuracy.
- Database unique constraint for one student record per WAT calendar date, manual corrections with reasons and audit history.
- One daily attendance result: Present through 9:10 AM, 1:10 PM or 5:10 PM in the selected window; Late from 9:11 AM, 1:11 PM or 5:11 PM. Unrecorded active students become Absent after the evening window closes.
- Campus and student administration, roster CSV import/export, dashboard polling, attendance CSV, monthly CSV/JSON reports and Celery Beat monthly closure.
- API schema at `/api/v1/schema/`, Swagger at `/api/v1/docs/`, and Redoc at `/api/v1/redoc/`.

## PostgreSQL and production

Copy the settings in `.env.example` to `.env` and generate two distinct random secrets (at least 50 characters for `DJANGO_SECRET_KEY`, 48 for `ATTENDANCE_SECRET`). Set `DATABASE_URL` to PostgreSQL, `DJANGO_ALLOWED_HOSTS` to the actual host, `CSRF_TRUSTED_ORIGINS` and `CORS_ALLOWED_ORIGINS` to approved HTTPS origins, and `DB_SSLMODE=require` for a remote database. Production settings refuse SQLite, short or example secrets, and localhost-only hosts.

Production uses Gunicorn behind a TLS reverse proxy, PostgreSQL, Redis, a Celery worker and Celery Beat. See [deployment and backups](docs/DEPLOYMENT.md). Do not put `.env`, the `data/` directory, exports or uploaded CSV files in static hosting.

## Verification

Run `python manage.py migrate`, `python manage.py check`, and `python -m pytest -q`. The included suite checks WAT cutoffs, daily duplicate constraints across attendance windows, end-of-day absence creation, campus geofencing, exact QR expiry, legacy password migration and private static file handling.

Browser GPS is a useful on campus check, not proof against a determined GPS spoofer. The API records location accuracy and rejects a fix unless the campus distance plus reported accuracy fits within the approved radius. A future trusted Wi-Fi or staffed physical kiosk check can add another signal.
