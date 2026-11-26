# Shared files between PR #3 and PR #4

Both pull requests touch the same eight files. Each one is clean against `main`
on its own, so the conflict only appears when the second PR lands. This page
records who owns what and which PR merges first.

Computed from the two pull requests on 26 November 2026 by intersecting their
changed-file lists against `main` (`00d25e8`): `git diff --name-only 00d25e8 <head>`.
PR #3 (`b108f5e`) changes 37 files, PR #4 (`cf8fb6b`) changes 82, and these eight
appear in both. Re-run those two commands rather than trusting these numbers; they
move whenever either branch gains a file.

| File | PR #3 (Partner A) | PR #4 (Partner B) | Owner after merge |
|---|---|---|---|
| `.gitignore` | modified | modified | Shared; preserve compatible rules |
| `API_CONTRACT.md` | modified +164 / −135 | modified +3 / −1 | Partner A |
| `README.md` | modified +300 / −609 | modified +31 / −701 | Split by section |
| `app.js` | modified +842 / −294 | modified +60 / −423 | Partner B |
| `dev/kiosk.html` | modified +95 / −40 | **removed** −76 | Deletion stands |
| `index.html` | modified +56 / −16 | modified +48 / −99 | Partner B |
| `server.py` | modified +406 / −436 | modified −1 | Retired |
| `styles.css` | modified +42 / −0 | modified +46 / −421 | Partner B |

## Why the conflict is structural, not editorial

PR #3 was branched from `main` when the student portal *was* the root
application: `app.js`, `index.html` and `styles.css` at the repository root were
the portal. PR #4 turns the root into the Django mentor console and moves the
student portal to `templates/student/index.html` and `static/student/`.

So both PRs rewrote the same three root files, for different products. It is not
a merge accident that can be resolved line by line; the same path now means two
different applications.

## Per-file resolution

- **`app.js`, `index.html`, `styles.css`**: Partner B's versions stay at the root
  because they are the mentor console. Partner A's portal work is not lost; it
  belongs under `static/student/` and `templates/student/`. Partner B already
  vendored a snapshot of it there, and that snapshot is now behind Partner A's
  branch (see `INTEGRATION_REVIEW.md`).
- **`README.md`**: split. Partner B owns the backend, deployment, migration and
  verification sections. Partner A owns the student portal section and its
  screenshots. Do not let either side overwrite the other wholesale.
- **`API_CONTRACT.md`**: Partner A owns the document. Partner B's change there is
  three lines of contract note and is re-applied on top after Partner A's
  rewrite lands.
- **`dev/kiosk.html`**: Partner B deleted it because the mentor portal has a
  kiosk page at `/kiosk`. Partner A fixed bugs in the file. Accept the deletion
  and treat Partner A's fixes as superseded.
- **`server.py`**: the standard-library demo backend that predates Django. Partner
  B's branch keeps the file with one line removed, and Partner A rewrote it.
  Neither change matters: the file should be deleted in a separate, clearly
  labelled cleanup commit rather than resolved inside a merge.

## Merge order

**PR #4 merges first. PR #3 then rebases onto the merged `main` and re-points the
student portal at `static/student/`.**

Reasons:

1. PR #4 is the larger architectural change and the backend is Partner A's
   dependency. Landing the backend first means Partner A rebases onto a stable
   target once.
2. Partner A's seven commits are portal changes that survive as files. Rebasing
   them onto the new layout is a re-pointing exercise, not a rewrite.
3. The reverse order would force Partner B to resolve seven conflicts inside a
   much larger merge, with a real risk of silently dropping Partner A's
   corrections to the portal.
4. Both PRs currently report `mergeable: clean` against `main`. That is only true
   until the first one lands, so the order must be decided before either merge.

## Sequence that satisfies the release gate

1. Partner B's P1 corrections and CI land on `feat/engineer-b-attendance`.
2. PR #4 is reviewed and approved by the CEO, then merged.
3. Partner A rebases PR #3 onto the new `main`, deletes the root portal files
   from their branch, and points the portal at `static/student/`.
4. Joint integration review re-runs the suite and the end-to-end script against
   the rebased branch.
5. CEO approval for PR #3.

No merge happens before the approval in step 2 and step 5.

## Keeping the served portal in sync

`static/student/app.js`, `static/student/styles.css` and `templates/student/index.html`
are a served copy of Partner A's portal. A manual copy drifts, which is exactly how the
21 November snapshot survived into this branch. The copy is now recorded in
`static/student/PORTAL_SOURCE.json` (source commit plus a sha256 per file) and only
`tools/sync_student_portal.py` should change it:

```bash
# verify the committed copy against the recorded source
python3 tools/sync_student_portal.py --check

# re-copy from a Partner A checkout (app.js and styles.css verbatim; index.html
# through the small static-path adapter) and rewrite the manifest
python3 tools/sync_student_portal.py --source ../student-portal --write
```

`--check` runs in CI before the test suite, and
`apps/core/tests/test_student_portal_copy.py` additionally asserts that `/student/`
serves the three-checkpoint portal and that the served `app.js` is the recorded copy.
Drift therefore fails the build instead of shipping silently.
