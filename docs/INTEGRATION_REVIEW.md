# Joint integration review: PR #3 against the PR #4 backend

Date: 25 November 2026 (Africa/Lagos)
Backend under test: `feat/engineer-b-attendance` at `6f2dc33` (PR #4)
Portal under test: `feat/django-student-integration` at `6f68e41` (PR #3)
Environment: local workspace only. No staging host, no production data, no
browser end-to-end run.

## Method

The two branches were merged into a throwaway local branch (`trial/integration`)
that was never pushed. The merge was resolved with the ownership rules in
`SHARED_FILES.md`, then the backend checks and both test suites were run on the
combined tree. The branch was deleted afterwards; nothing was merged into either
pull request.

## Merge result

Seven conflicts, exactly the shared set, plus one modify/delete:

```
CONFLICT (content): API_CONTRACT.md
CONFLICT (content): README.md
CONFLICT (content): app.js
CONFLICT (modify/delete): dev/kiosk.html
CONFLICT (content): index.html
CONFLICT (content): server.py
CONFLICT (content): styles.css
```

Partner A's new files merged without conflict: `tests/` (Node API, UI and E2E
scripts), `docs/screenshots/` (13 PNGs), `HOSTING.md`.

Resolution applied for the trial: Partner B's version for the five root files,
the `dev/kiosk.html` deletion kept, Partner A's documents and tests taken as
added.

## Verification on the combined tree

| Check | Result |
|---|---|
| `python manage.py check` | No issues |
| `python -m pytest -q` (SQLite) | 63 passed, 1 skipped |
| `python -m pytest -q` (PostgreSQL 16.2) | 64 passed, 0 skipped |
| `python -m pyflakes apps config manage.py` | Clean |

The backend survives the merge intact: no migration conflicts, no model or
service conflicts, and the PostgreSQL concurrency test still passes.

## Findings

1. **Partner A's portal is ahead of the snapshot in the backend branch.** Partner
   A's `app.js` is 904 lines; Partner B's `static/student/app.js` is 754, with 188
   differing lines after whitespace normalisation. The merged tree therefore runs
   an older copy of the portal. Partner A's branch is the source of truth for
   `static/student/` and must replace the snapshot before sign-off.
2. **Issue #5 is fixed in PR #3's current head.** The E2E script no longer calls
   `AttendanceLog.objects.all().delete()`; cleanup is scoped to the student the
   script seeds, and the seed creates its own campus, mentor and student. The
   destructive-cleanup blocker recorded in `QA_EVIDENCE.md` can be cleared for
   PR #3, but the script was still not executed here because it needs a browser
   and a running server.
3. **The seven-file overlap is structural.** The root `app.js`, `index.html` and
   `styles.css` mean the student portal in PR #3 and the mentor console in PR #4.
   Merging in the wrong order risks silently discarding one product.
4. **`dev/kiosk.html` is dead either way.** The mentor console serves its own
   kiosk page, so Partner A's fixes to the standalone kiosk file are superseded.
5. **`server.py` should be deleted outside this merge.** It is a retired demo
   backend, and both branches modify a file nobody should run.

## What is still required before sign-off

- Replace `static/student/app.js`, `static/student/styles.css` and
  `templates/student/index.html` with Partner A's latest versions and re-run the
  suite.
- Run Partner A's E2E script against the Django backend with a disposable
  database, now that its cleanup is scoped.
- Re-run the merge after PR #4 lands, when the conflict set disappears.
- Obtain CEO approval before either PR merges.

## Merge gate

Neither PR #3 nor PR #4 may be merged without explicit CEO authorization. This
document is review evidence, not an approval.
