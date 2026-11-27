# Governance incident — PR #3 merged without CEO authorization

**Date recorded:** 26 November 2026
**Repository:** `super7abaga-crypto/Student_Attendance`
**Severity:** process and governance, with a material engineering consequence

## What happened

Pull request #3 (`feat/django-student-integration`) was merged into `main` by
`rehobothtek` at **2026-11-26T10:30:12Z** without the merge authorization the CEO
reserved for that decision. The merge was performed from a head commit that predated the
CI implementation prepared for that same pull request, so the merge landed the portal work
and left the CI work behind.

## Evidence

| Fact | Value |
|---|---|
| Merge commit | `0fcb4e81d556feefd21ddc5617aa04251c8d76aa` |
| Parents | `00d25e8ff3c858f120082ddeea62c38685057910` (main before), `5cb425737fa6427ffb6862fc670d3cd4200c6180` (PR #3 head) |
| Merged head | `5cb4257` — "docs: mark three-checkpoint attendance policy as approved" |
| Merged by | `rehobothtek`, `merged_at` 2026-11-26T10:30:12Z |
| Partner A CI head at the time | `70da2fd437efeebd5cc6b7c98bb73c2fd05413bb` |
| Commits stranded | `b108f5e` (workflow + E2E secret fix), `70da2fd` (push trigger widened) |

`git diff --name-status main 70da2fd` on the merged `main` returns exactly two entries:

```
A   .github/workflows/portal-tests.yml
M   tests/e2e-django.js
```

## Consequence

`main` has no `.github/workflows/portal-tests.yml`, so no automated check runs on pull
requests, and `tests/e2e-django.js` on `main` still hardcodes `ATTENDANCE_SECRET`, which
makes the end-to-end suite fail against any backend whose signing secret differs. The
successful CI evidence produced on `70da2fd` (run 45802391278) belongs to a branch whose
pull request was already closed, so that evidence could not protect `main`.

Recovery is in pull request #8 (`ci/restore-portal-tests`, head `df779a3`), which starts
from the merged `main` and restores exactly those two files. Nothing in this document
authorises a revert or rewrite of `main`; that decision belongs to the CEO.

## Ownership crossing

The merged head `5cb4257` was itself a Partner B commit applied to Partner A's branch,
changing one line of `README.md` ("Daily (one-per-day) attendance rule — Pending
decision" replaced by "Three-checkpoint attendance (morning check-in, afternoon check-in,
evening checkout) — Implemented and approved"). The statement is accurate and now sits in
`main` through the merge; it is recorded here as an ownership crossing, not as an error of
fact. It is deliberately not part of recovery PR #8.

## Related defect found while building CI

`tests/e2e-django.js` hardcoded `ATTENDANCE_SECRET` and `DJANGO_SECRET_KEY` for the shell
calls that seed fixtures and mint QR codes. Against a backend running with different
secrets, the minted token failed verification and the suite reported `invalid_qr` with
seven failures. The script now reads both from the environment and falls back to the
documented local pair. This is the second change restored by PR #8.

## How this is prevented from recurring

1. Pull requests carry automated checks before review, so a merge cannot quietly omit them.
2. The E2E backend is pinned by commit (`BACKEND_SHA`) with the resolved SHA asserted, so a
   moving branch cannot change what was tested.
3. Every E2E report records the portal commit and the backend commit it ran against.

## Evidence preserved

- PR #3 CI success on `70da2fd`: run 45802391278, three jobs, all green.
- PR #3 CI failure on `7a15548` (static analysis) and its fix in `c2a44dc` on PR #4.
- The `invalid_qr` E2E failure output and the secret-handling correction.
- PR #8 CI results on head `df779a3`.
