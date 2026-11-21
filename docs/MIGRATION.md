# Legacy JSON migration

The Django migration is additive. It does not delete or edit the old files. The checked in workspace currently contains an empty attendance roster/log JSON and a legacy mentor scrypt hash; the actual local `data/` directory is ignored by Git and stays outside static serving.

1. Back up `data/` before migration.
2. Install dependencies and run `python manage.py migrate`.
3. Create a superuser with `python manage.py createsuperuser`.
4. In Django Admin, create the destination campus with its real address, coordinates, radius and timezone. Configure tracks/cohorts and mentor access.
5. Dry run the import:

```powershell
python manage.py import_legacy_json --source data/attendance.json --mentor-profile data/mentor_profile.json --campus-id <campus-uuid> --dry-run
```

6. Review dry run counts and row validation. Then run the same command without `--dry-run`.

Students imported without credentials get an unusable Django password; issue each learner a new initial password using the student registration/admin workflow. Historical log rows with no roster profile are imported as inactive students. Duplicate username/session rows and malformed rows are reported and skipped; the source JSON remains unchanged so corrections can be made and retried.

The old mentor profile is imported as `legacy-mentor` and assigned only to the selected campus. A custom Django hasher verifies the old Node scrypt hash once; Django upgrades it to Argon2 after the first valid login. The legacy profile and its old session identifier are not used by the new app. Rotate the legacy mentor password after sign-in.
