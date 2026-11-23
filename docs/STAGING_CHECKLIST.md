# Staging setup and smoke test

Use a newly created, isolated staging environment with synthetic students only. Do not point staging at production PostgreSQL, Redis, secrets, uploads, or backups. Do not run migration `0004_daily_attendance_policy` against any populated database. The automated migration test uses the disposable test database only.

The project does not yet name a hosting provider. Select a provider and its PostgreSQL/Redis products before creating provider-specific configuration. Do not provision paid services without the owner's approval. The portable process definitions are in the root `Procfile`.

## Required services and variables

- Python 3.12 or later; install from `requirements.txt`.
- A fresh PostgreSQL database; set `DATABASE_URL` and `DB_SSLMODE=require` where supported.
- A Redis service reachable by the web app, worker, and Beat; set `REDIS_URL` and `CELERY_BROKER_URL` (they may be the same URL).
- Set `DJANGO_SETTINGS_MODULE=config.settings.production`.
- Generate unique staging-only values for `DJANGO_SECRET_KEY` (at least 50 characters) and `ATTENDANCE_SECRET` (at least 48 characters). Never copy production secrets into staging.
- Configure `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and `CORS_ALLOWED_ORIGINS` for the staging HTTPS hostname/origin.
- Set `CELERY_TASK_ALWAYS_EAGER=0` and `LOG_LEVEL=INFO`.
- Keep credentials in the host's secret manager. Do not commit `.env` files.

## Build and start

```sh
python -m pip install -r requirements.txt
python manage.py check --deploy
python manage.py migrate --plan
python manage.py migrate --noinput
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 60
celery -A config worker --loglevel=INFO
celery -A config beat --loglevel=INFO
```

Only run the migration command against the new empty staging database. Configure exactly one Beat process; multiple Beat schedulers can dispatch duplicate jobs. The task and database constraints are idempotent, but a single scheduler is still the operational requirement.

## Staging smoke checks

After HTTPS and the hostname are configured:

```sh
curl -fsS https://<staging-host>/health/
curl -fsSI https://<staging-host>/static/student/styles.css
curl -fsS https://<staging-host>/api/v1/schema/
celery -A config inspect ping
python manage.py showmigrations --plan
```

Expected results: `/health/` returns `{"ok":true,"service":"learn2earn-attendance","database":"ok"}`; the CSS and schema endpoints return HTTP 200; the Celery inspect command sees a worker; and all intended migrations show `[X]`. Review web, worker, and Beat startup logs, including the UTC 15-minute absence schedule and UTC 01:15 monthly schedule.

## Functional pilot, synthetic accounts only

1. Create a campus with verified latitude/longitude, an approved geofence radius, and the correct IANA timezone. Create a campus administrator/mentor and one synthetic student. Give the mentor the required campus permissions.
2. Confirm `GET /api/v1/docs/` and mentor login work over HTTPS. Do not use a real student's credentials.
3. Activate a scheduled session from the mentor portal and confirm the QR image endpoint returns a PNG. Scan with the synthetic student from inside the configured geofence. Confirm the API returns `present` or `late` from server time, then confirm a repeat scan returns the documented duplicate response.
4. Exercise the daily-absence task using test-only campus time fixtures or a controlled staging clock. Confirm each campus closes only after its own evening cutoff and that repeated task invocations leave one row per student/date.
5. Export a CSV containing a synthetic formula-like name and confirm spreadsheet-dangerous values are prefixed with an apostrophe.
6. Record the staging URL, `/health/` response, API smoke results, migration state, static-file response, worker ping, Beat logs, and test results in `docs/DEPLOYMENT_STATUS.md`.

Do not test geofencing until campus coordinates have been verified. Do not describe staging evidence as proof of production readiness. Production remains blocked on selected hosting, approved campus configuration, migration 0004 review/approval, production secrets, backup/restore evidence, and live production verification.
