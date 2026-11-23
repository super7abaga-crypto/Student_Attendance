# QA evidence — Engineer B release preparation

Date: 23 November 2026 (Africa/Lagos)

Branch: `feat/engineer-b-attendance`
Workspace verification only; no staging or production environment was accessed.

The checkpoint implementation and tests have since changed. The suite result below was recorded before the final manual-checkout validation and documentation edits, so it is historical evidence and must be rerun before a release review.

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

- pytest: **46 passed, 1 skipped**.
- Django test runner: the most recent earlier run recorded **52 tests passed, 1 skipped**; the test database was destroyed afterward. This run predates the final working-tree edits noted above.
- Django system check: no issues.
- Migration check: no model changes detected.
- Static collection dry run: 160 static files found and ready for collection.
- `git diff --check`: clean.
- The PostgreSQL concurrency test is present but skipped on this workspace's SQLite database because SQLite's locking behavior does not validate the production race. Run it against PostgreSQL in staging before approval.

## Specific release checks

- Timezone task tests cover Lagos and Los Angeles on opposite sides of UTC midnight, local pre-close/post-close behavior, no attendance row for the wrong local date, bounded prior-day catch-up, and repeat-task idempotency.
- Beat configuration tests cover the 15-minute UTC absence schedule and daily UTC monthly-close schedule.
- Login and QR scan rate-limit tests verify HTTP 429 enforcement.
- CSV test verifies export headers/content and apostrophe escaping for spreadsheet formulas. It also caught and fixed DRF treating `format=csv` as a renderer override (previously 404).
- Migration tests verify the 0004 historical-status conversion, retained rows, and duplicate-date abort behavior. No populated external database was used.
- Checkpoint tests were updated to cover separate morning/afternoon/evening records, checkout semantics, checkpoint-specific duplicates, and absence materialization. They have not been rerun against the final working tree yet.

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
