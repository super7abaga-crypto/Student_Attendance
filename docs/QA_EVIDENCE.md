# QA evidence — Engineer B release preparation

Date: 23 November 2026 (Africa/Lagos)

Branch: `feat/engineer-b-attendance`
Workspace verification only; no staging or production environment was accessed.

The results below include verification of commit `7a0ecef` and the subsequent fixes for legacy mentor hash storage and checkpoint-aware legacy imports. The current test run used SQLite; PostgreSQL-specific confirmation is still required.

## Automated verification

Commands run from the repository root:

```powershell
python -m pytest -q
python manage.py test apps.core.tests -v 1
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py collectstatic --dry-run --noinput
git diff --check
```

Results:

- Django test runner: `python manage.py test apps.core.tests --verbosity 1` — **54 tests run, 1 skipped, 0 failures**; the skip is the PostgreSQL concurrency test. The test database was destroyed afterward.
- Django system check: `python manage.py check` — no issues.
- Migration check: `python manage.py makemigrations --check --dry-run` — no model changes detected.
- `git diff --check` — clean.
- `python -m pytest -q` and `collectstatic --dry-run` results below are from an earlier verification run and were not repeated after these changes.
- Static collection dry run: 160 static files found and ready for collection.
- The PostgreSQL concurrency test is present but skipped on this workspace's SQLite database because SQLite's locking behavior does not validate the production race. Run it against PostgreSQL in staging before approval.
- A legacy mentor-import test now asserts the full scrypt encoding exceeds the old 128-character limit; widening is covered by migration 0007. The test passed on SQLite, but PostgreSQL confirmation remains outstanding.
- Legacy attendance import coverage confirms three different checkpoints on one date are retained and a duplicate for the same checkpoint is skipped.

## Specific release checks

- Timezone task tests cover Lagos and Los Angeles on opposite sides of UTC midnight, local pre-close/post-close behavior, no attendance row for the wrong local date, bounded prior-day catch-up, and repeat-task idempotency.
- Beat configuration tests cover the 15-minute UTC absence schedule and daily UTC monthly-close schedule.
- Login and QR scan rate-limit tests verify HTTP 429 enforcement.
- CSV test verifies export headers/content and apostrophe escaping for spreadsheet formulas. It also caught and fixed DRF treating `format=csv` as a renderer override (previously 404).
- Migration tests verify the 0004 historical-status conversion, retained rows, and duplicate-date abort behavior. No populated external database was used.
- Checkpoint tests cover separate morning/afternoon/evening records, checkout semantics, checkpoint-specific duplicates, and absence materialization.

## Deployment and staging evidence

Portable web/worker/Beat process definitions, required environment variables, PostgreSQL/Redis configuration, static collection, HTTPS proxy requirements, a database-aware health check, and synthetic-data staging instructions are documented in `Procfile`, `docs/DEPLOYMENT.md`, and `docs/STAGING_CHECKLIST.md`.

No hosting provider has been selected, no paid infrastructure was provisioned, and no live staging URL, PostgreSQL/Redis connection, Celery process, HTTPS response, or deployment log was available for verification.

An additional `manage.py check --deploy` attempt using placeholder-only PostgreSQL/Redis URLs did not complete and was stopped. It is not counted as a passing check; repeat it with the selected staging provider's configuration.

## Remaining release blockers

- Run migration 0004 only after the owner approves its documented preflight, backup/restore rehearsal, staging result, and rollout plan. Do not apply it to a populated database before that gate.
- Select a hosting provider, then create an isolated staging environment with synthetic accounts and capture live evidence.
- Supply approved campus coordinates/radius, timezone, mentor access, and synthetic student account before testing QR geofencing.
- Run the PostgreSQL concurrency test in staging; it was skipped on local SQLite.
- Confirm Partner A accepts the additive `record_kind` values. System absence records retain the legacy evening/check-in enum values for compatibility until a later API version can replace them.
- No production deployment, production data changes, merge, or live student test was performed.

## 25 November 2026: P1 corrections, CI and PostgreSQL verification

Branch: `feat/engineer-b-attendance` (PR #4). Workspace verification plus a local
PostgreSQL 16.2 instance. No staging or production environment was accessed.

### What changed

- P1 correction 1, campus timezone: attendance records, the student profile,
  student login, the mentor summary and monthly report boundaries now use the
  campus's own IANA timezone instead of the server default.
- P1 correction 2, timestamp semantics: `scanned_at` is an explicit UTC instant,
  `scanned_at_local` carries the campus offset, `scan_time_local` the campus
  clock time, and QR responses add `issued_at`, `expires_at_iso` and
  `expires_in_seconds` alongside the existing epoch `expires_at`.
- `MentorCampusAccess` was missing from the `views.py` imports, so a mentor
  roster export without a campus parameter returned HTTP 500. Fixed.
- Ten new tests in `apps/core/tests/test_timezone_contract.py` cover the new
  fields, the legacy alias, a non-Lagos campus, the summary offset, QR expiry
  consistency, campus-timezone report boundaries and the roster export path.

### Results

| Command | Result |
|---|---|
| `python -m pytest -q` (SQLite) | 63 passed, 1 skipped |
| `python -m pytest -q` (PostgreSQL 16.2) | **64 passed, 0 skipped** |
| `python manage.py check` | No issues |
| `python manage.py makemigrations --check --dry-run` | No changes detected |
| `python -m pyflakes apps config manage.py` | Clean |
| `python manage.py check --deploy` with generated secrets | No issues |
| `python manage.py check` with placeholder secrets | Refused, as designed |

The PostgreSQL run clears the earlier gap: the concurrency test previously
skipped on SQLite now executes and passes, and the suite is green with the new
tests included. The production settings check that had been stopped in the
previous run now completes cleanly with realistic values.

### CI

`.github/workflows/backend-tests.yml` runs four jobs on every push and pull
request: static analysis (pyflakes plus byte-compilation), the SQLite suite with
the system and missing-migration checks, the PostgreSQL suite with a service
container, and the production settings guard that also asserts placeholder
secrets are refused. The PostgreSQL job uses Django's test runner while the
SQLite job uses pytest, so both configured runners are exercised on every run.

### Still outstanding

- Staging environment, PostgreSQL migration rehearsal for 0004, 0006 and 0007,
  and live `/health/` evidence remain blocked on a hosting provider.
- The browser end-to-end run is not performed here. Partner A's script is now
  scoped to its own fixtures, so the blocker recorded above is cleared for PR #3.
- Partner A's latest portal files still need to replace the snapshot in
  `static/student/`; see `INTEGRATION_REVIEW.md`.
