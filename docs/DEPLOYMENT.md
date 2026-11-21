# Deployment, schedules and backups

## Required services

- Python 3.12+ runtime and `requirements.txt`.
- PostgreSQL database with migrations applied.
- Redis broker, a Celery worker and a Celery Beat scheduler.
- Gunicorn behind a reverse proxy that terminates HTTPS.
- Persistent private backups for PostgreSQL.

Set all values in `.env.example` in the deployment secret store. Use a random `DJANGO_SECRET_KEY` (50+ characters) and a separate `ATTENDANCE_SECRET` (48+ characters); do not reuse the sample strings. Configure `DJANGO_ALLOWED_HOSTS=fellowship.learn2earn.ng`, HTTPS `CSRF_TRUSTED_ORIGINS`, and only approved CORS origins. Set both `REDIS_URL` and `CELERY_BROKER_URL` to managed Redis service URLs (they may be the same URL); production rejects empty and localhost Redis settings. For PostgreSQL use `DB_SSLMODE=require` when supported. Keep `DEBUG=0` in production.

Apply migrations during a release step, then collect static assets and start the WSGI application:

```sh
python manage.py migrate --noinput
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60
```

Run background processes separately. Celery Beat records daily Absences at 20:01 Africa/Lagos and closes monthly reports at 00:15 on the first day of a month:

```sh
celery -A config worker --loglevel=INFO
celery -A config beat --loglevel=INFO
```

Celery Beat records daily Absences at 20:01 Africa/Lagos after the evening window closes. It closes previous reporting periods at 00:15 Africa/Lagos on the first day of each month and processes missing prior months in order. Reports are unique per campus/year/month; source attendance is never deleted. A manual close is available for completed periods only. Reopening a report never erases its audit trail.

The reverse proxy must redirect HTTP to HTTPS and pass `X-Forwarded-Proto: https`. Health check is `GET /health/`. Swagger is available at `/api/v1/docs/`; protect or disable public schema routes if deployment policy requires it.

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
