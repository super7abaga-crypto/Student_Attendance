# Daily-attendance migration safety — `core.0004`

**Production status: not approved to run.** Run this procedure against a staging database copy first. Do not run `python manage.py migrate` against production until duplicate reporting, backup, restoration rehearsal, and rollout are approved by the deployment owner.

## Migration impact

Migration `0004_daily_attendance_policy` replaces the session-level uniqueness rule with `UNIQUE(student_id, attendance_date)`, converts stored `on_time` values to `present`, and updates adjustment status choices.

It does **not** delete or merge legacy duplicate records. Before changing data or applying the new constraint, the migration checks for more than one record for a student on a date. If any exist, it aborts with an error. All records are retained and the deployment must stop for an approved cleanup decision.

The `on_time` → `present` update changes only the status value. It retains record IDs, timestamps, campus/session metadata, location data, source, and audit relationships. Exports and integrations expecting `on_time` must be updated before release.

## Pre-migration duplicate query

Run this PostgreSQL query and save its result in the release record. It must return zero rows before applying the migration.

```sql
SELECT student_id, attendance_date, COUNT(*) AS record_count,
       ARRAY_AGG(id ORDER BY scanned_at NULLS LAST, created_at, id) AS attendance_ids
FROM core_attendancelog
GROUP BY student_id, attendance_date
HAVING COUNT(*) > 1
ORDER BY attendance_date, student_id;
```

## Backup and restoration rehearsal

1. Put the application in maintenance mode and stop web writers, Celery workers, and Celery Beat.
2. Create an encrypted, access-controlled PostgreSQL backup:

```sh
pg_dump --format=custom --no-owner "$DATABASE_URL" > attendance-before-core-0004.dump
```

3. Record a SHA-256 checksum and restore the dump into an isolated database:

```sh
createdb attendance_core_0004_restore
pg_restore --no-owner --dbname=attendance_core_0004_restore attendance-before-core-0004.dump
```

4. Point `DATABASE_URL` to the restore, run the duplicate query, then run `python manage.py migrate` and `python -m pytest -q`.
5. Confirm the migration with `python manage.py showmigrations core` and inspect sample converted records.
6. If production migration fails, stop release activity and restore the verified dump before resuming service.

## Approval gate

The release owner must approve the zero-duplicate report, verified backup and restore, staging migration, test results, integration vocabulary update, rollback owner, and maintenance window before production migration.
