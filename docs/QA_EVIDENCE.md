# QA evidence — Engineer B backend

Date: 21 November 2026 (Africa/Lagos)  
Workspace: `C:\Users\SummerTek\Student_Attendance`

## Automated verification

Commands run from the project root:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test apps.core.tests -v 1
python -m pytest -q
```

Results:

- `manage.py check`: no issues.
- `makemigrations --check --dry-run`: no model changes detected.
- Django test runner: **38 tests passed, 0 failures/errors**.
- pytest: **38 passed**.
- Migration 0004 is applied by Django when the test database is built. Two dedicated `MigrationExecutor` tests cover historical `on_time` conversion/row retention and duplicate-date abort/row preservation.
- Daily duplicate coverage verifies the database unique constraint rejects a second scan across QR windows.
- Cutoff coverage verifies the full last-on-time minute and the 09:11:00, 13:11:00, and 17:11:00 WAT transitions, including the final microsecond before each transition.
- Absence coverage verifies no absence is generated before close and a missing active student is marked absent after the evening window closes.
- GPS/geofence coverage checks outside-campus rejection, low-accuracy rejection, and failed closed behavior.
- Configuration checks reject incomplete/out-of-range campus coordinates and schedules with cutoff times outside the open window.
- Permission coverage checks student identity/authentication, mentor session and CSRF, student-management grants, and staff/campus access restrictions.
- Location-override coverage checks that a correction matches the current date and session and cannot change a closed month.

The commands above were run after the cutoff correction and backend hardening changes. They
verify the current local code, but do not replace live staging or deployment checks.

The Django test runner emits expected HTTP 400/401/403/409/404 log lines for rejection cases; these are asserted cases, not test failures.

## Manual QA and deployment evidence

Not verified in a live deployment. No live HTTPS URL, production or staging credentials, approved pilot campus coordinates/radius, mentor account, or test-student account were supplied. No live portal/kiosk screenshots, PostgreSQL/Redis connection evidence, Celery worker/Beat startup logs, or remote static-asset responses are available. See `DEPLOYMENT_STATUS.md`; the release is not production-ready.

## Kiosk reference audit

The Django backend routes the mentor kiosk through `/api/v1/mentor/qr/*`. The obsolete `dev/kiosk.html` file and its `server.py` startup-banner reference have been removed; the Django portal at `/` is the mentor entry point. This source audit is not evidence of live kiosk behavior.
