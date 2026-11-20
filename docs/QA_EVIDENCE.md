# QA evidence — Engineer B branch

Date: 20 November 2026 (Africa/Lagos)

## Automated verification

Commands run from `D:\Student_Attendance` with the project Python 3.13 virtual environment:

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\venv\Scripts\python.exe manage.py test apps.core.tests -v 1
.\venv\Scripts\python.exe -m pytest -q
```

Results: Django check reported `0` issues; migration check reported `No changes detected`; Django tests reported `29` passed and `0` failures; pytest reported `29 passed` and `0` failures.

The suite exercises exact cutoff boundaries, a database-enforced daily duplicate across windows, end-of-day Absence generation, QR signature/expiry/revocation, GPS and geofence rejection, authenticated student identity, mentor CSRF/session handling, manual-absence timing, legacy-password migration, and private-file protection.

## Manual QA status

No production or pilot deployment exists in this workspace. No live mentor/kiosk screenshots, HTTPS response, PostgreSQL/Redis evidence, or startup logs are attached. Capture those items in the target environment using `DEPLOYMENT_STATUS.md` before approving production readiness.
