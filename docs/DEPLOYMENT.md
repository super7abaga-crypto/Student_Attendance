# Deployment, schedules and backups

## Required services

- Python 3.12+ runtime and `requirements.txt`.
- PostgreSQL database with migrations applied.
- Redis broker, a Celery worker and a Celery Beat scheduler.
- Gunicorn behind a reverse proxy that terminates HTTPS.
- Persistent private backups for PostgreSQL.

Set `DJANGO_SETTINGS_MODULE=config.settings.production` and the values listed in `.env.example` in the host's secret store. Use a random `DJANGO_SECRET_KEY` (50+ characters) and a separate `ATTENDANCE_SECRET` (48+ characters); do not reuse the sample strings. Configure `DJANGO_ALLOWED_HOSTS` for the deployed hostname, HTTPS `CSRF_TRUSTED_ORIGINS`, and only approved CORS origins. Set `DATABASE_URL` to PostgreSQL and `DB_SSLMODE=require` when supported. Set both `REDIS_URL` and `CELERY_BROKER_URL` to managed Redis service URLs (they may be the same URL); production rejects empty and localhost Redis settings. Production settings force `DEBUG=0`.

For a **new, empty staging database only**, apply migrations and collect static assets:

```sh
python manage.py migrate --noinput
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60
```

Start the web and background processes separately. The repository `Procfile` provides web, worker and beat start commands. Equivalent commands are:

```sh
celery -A config worker --loglevel=INFO
celery -A config beat --loglevel=INFO
```

Celery Beat runs in UTC. Every 15 minutes it checks the prior and current campus-local dates and materializes absent records only for checkpoints whose configured windows have closed. A database uniqueness constraint on student/date/checkpoint plus campus-row serialization makes repeated runs safe. It closes monthly reports daily at 01:15 UTC so local month boundaries are not tied to Lagos. Monthly reports are unique per campus/year/month; source attendance is never deleted. A manual close is available for completed periods only. Reopening a report never erases its audit trail.

The reverse proxy must redirect HTTP to HTTPS and pass `X-Forwarded-Proto: https`. Configure the host's liveness/readiness path as `GET /health/`. Swagger is available at `/api/v1/docs/`; protect or disable public schema routes if deployment policy requires it. Static files are collected to `STATIC_ROOT` and served by WhiteNoise; verify `/static/student/styles.css` returns HTTP 200 after collection.

The hosting provider has not yet been selected. `Procfile` and these commands are portable process definitions, not a provider-specific Blueprint. Use [the staging checklist](STAGING_CHECKLIST.md) to validate a host before using real data. Never attach this branch's migration command to production auto-release until the migration 0004 duplicate/data-conversion safety gate and migration 0006 checkpoint/checkout behavior have been reviewed and approved.

## Backups

Use an encrypted, access controlled PostgreSQL backup location. Example backup and restoration commands (replace variables securely; do not put database passwords in shell history):

```sh
pg_dump --format=custom --no-owner "$DATABASE_URL" > attendance-$(date -u +%F).dump
createdb attendance_restore_test
pg_restore --no-owner --dbname=attendance_restore_test attendance-YYYY-MM-DD.dump
```

Automate backups, retain copies off-host, and periodically test restoring a backup into an isolated database. Monthly report JSON/CSV snapshots live in PostgreSQL and should be included in backups.

## Operational dependencies

Campus coordinates, authorised campus roles, real production credentials, DNS, TLS and database backup policy must be supplied by the Learn2Earn deployment owner. They are not present in the repository; scans should remain unavailable until a campus geofence and authorised users have been configured.
