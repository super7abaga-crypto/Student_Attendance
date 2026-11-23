# Migration 0004 safety plan

## Earlier primary-key migration (`0003`)

Migration `0003_alter_mentorcampusaccess_id_alter_sessionschedule_id` now converts the two legacy auto-increment IDs to UUIDs without dropping their rows. On PostgreSQL it assigns each old ID a deterministic UUIDv5 derived from the table name and old integer ID, then replaces the primary-key column. The current schema has no foreign keys referencing either ID; the migration checks for inbound foreign keys and stops before changing a table if one is found. SQLite uses Django's table rebuild operation. Databases that already recorded `0003` are not replayed by Django; the repair applies to fresh/unmigrated databases. Do not fake or roll back this migration to force it to run on a populated database.

Before applying `0003` to an existing PostgreSQL database, take and verify a backup, confirm both tables have the expected BIGINT or UUID `id` type, and inspect that no external application/database objects depend on those IDs. The migration preserves every row and emits stable UUIDs, but numeric IDs change and external integrations that store them must be updated. Validate row counts and references in an isolated restored copy first. This work has not been run against production data.

## Approval status

**Do not run migration 0004 against production until the release owner has reviewed and approved the duplicate report, backup/restore rehearsal, staging result, and rollout plan.** Documentation and code review do not constitute production approval. The migration has not been run against production as part of this work.

## Migration effects

`0004_daily_attendance_policy` replaces the unique key `(student_id, attendance_date, session_type)` with `(student_id, attendance_date)`. This permits at most one daily row, regardless of QR window. It changes the attendance and adjustment status choices from `on_time`/`late`/`absent` to `present`/`late`/`absent` and updates the campus/date index.

The migration **does not delete, merge, or choose a winning attendance row**. It checks for every student/date with more than one attendance row before converting any historical statuses. If it finds even one duplicate group, it raises an error and aborts; on PostgreSQL the migration is atomic, so its preceding constraint change rolls back too. Resolve duplicates only through a separately approved, documented data-cleanup plan, then repeat the preflight query and backup process.

When preflight has zero duplicate groups, every existing `AttendanceLog` row is retained with the same primary key, student, campus, track/cohort snapshots, session/action, date, scan timestamp, location fields, source, and session-run relation. No attendance rows are deleted. The migration changes only historical status values `on_time` to `present` in `AttendanceLog.status`, `AttendanceAdjustment.original_status`, and `AttendanceAdjustment.new_status`; `late` and `absent` remain unchanged. This preserves the meaning and audit links of old on-time records while changing the stored/API vocabulary. Consumers and exports that expect `on_time` must use `present` after deployment. The migration's data conversion is intentionally not reversed by its `RunPython.noop` reverse handler; rollback must restore the pre-migration database backup rather than assume reversing schema operations restores old status values.

## Pre-migration duplicate-count query

Run against the target database and save the output with the release record. Both statements must show zero duplicate groups/rows before proceeding:

```sql
-- List every conflict and all attendance row IDs so nothing is silently chosen.
SELECT student_id,
       attendance_date,
       COUNT(*) AS record_count,
       ARRAY_AGG(id ORDER BY scanned_at NULLS LAST, created_at, id) AS attendance_ids,
       ARRAY_AGG(session_type ORDER BY scanned_at NULLS LAST, created_at, id) AS session_types
FROM core_attendancelog
GROUP BY student_id, attendance_date
HAVING COUNT(*) > 1
ORDER BY attendance_date, student_id;

-- Count conflicting student/date groups and the total rows in those groups.
WITH duplicates AS (
    SELECT student_id, attendance_date, COUNT(*) AS record_count
    FROM core_attendancelog
    GROUP BY student_id, attendance_date
    HAVING COUNT(*) > 1
)
SELECT COUNT(*) AS duplicate_groups,
       COALESCE(SUM(record_count), 0) AS rows_in_duplicate_groups,
       COALESCE(SUM(record_count - 1), 0) AS excess_rows_if_daily_uniqueness_were_enforced
FROM duplicates;
```

Expected result: no rows from the first query, and `duplicate_groups = 0`, `rows_in_duplicate_groups = 0`, `excess_rows_if_daily_uniqueness_were_enforced = 0` from the second. The `excess_rows_if_daily_uniqueness_were_enforced` number is diagnostic only: the migration does not delete that many rows or select a keeper.

## Backup and restoration rehearsal

Use a restricted maintenance window. Stop web writers and Celery worker/Beat processes before the final backup and migration. Keep the backup encrypted and access-controlled. Example PostgreSQL commands (run from a secure host with `DATABASE_URL` set):

```sh
pg_dump --format=custom --no-owner "$DATABASE_URL" --file attendance-before-core-0004.dump
sha256sum attendance-before-core-0004.dump
createdb attendance_core_0004_restore
pg_restore --no-owner --dbname=attendance_core_0004_restore attendance-before-core-0004.dump
```

On Windows PowerShell, calculate the file digest with:

```powershell
Get-FileHash .\attendance-before-core-0004.dump -Algorithm SHA256
```

Point an isolated staging copy at the restored database. Repeat the duplicate-count query; verify it returns zero; apply migrations there; verify the migration state; compare row counts and sample primary keys/metadata; and confirm `on_time` no longer appears in the three converted status columns. Rehearse restoration into a separate empty database and record the result. Do not use a production restore target for the rehearsal.

If the production migration is ever approved and fails, stop deployment activity, preserve logs, and restore the verified pre-migration backup using the database provider's documented restore procedure before restarting writers. Do not try to repair the partially applied migration by deleting attendance rows.

## Migration 0005 automated-absence source

`0005_automated_absence_source` adds the `system` source choice and changes rows marked `location_result = 'system_daily_absence'` and `status = 'absent'` from `manual` to `system`. No rows are inserted or deleted. This distinguishes scheduled system absences from mentor-entered manual absences in new API responses and exports. Previously closed monthly report snapshots are immutable and are not rewritten; regenerate only through the existing approved report-reopen workflow if corrected historical export labels are required.

## Required approval before production

The release owner must approve: zero-duplicate query output; identified migration version and reviewed diff; encrypted backup checksum; successful isolated restore rehearsal; successful staging migration and data comparison; client/export handling for `present`; rollback owner and recovery window; and the production maintenance window. No production migration is authorized by this document.
