# Shared files between the student portal and the Django integration

The student portal was merged into `main` first (PR #3, head `5cb4257`, merge `0fcb4e8`,
recovery workflow via PR #8, merge `8d332a8`). PR #4 adds the Django backend on top of it.
This page records what those two efforts share, who owns each file, and how the overlap was
resolved.

## Ownership

| Area | Owner | Files |
|---|---|---|
| Student portal source | Partner A | `app.js`, `index.html`, `styles.css`, `server.py`, `dev/kiosk.html`, `API_CONTRACT.md`, `tests/api-test.py`, `tests/ui-test.js`, `tests/e2e-django.js`, `tests/responsive-test.js` |
| Portal documentation | Partner A | `README.md` portal sections, `API_CONTRACT.md` |
| Django backend | Partner B | `apps/`, `config/`, `manage.py`, `requirements.txt`, `Procfile`, `.env.example` |
| Django portal copies | Partner B (generated) | `templates/student/index.html`, `static/student/*` — synced from Partner A's source, never hand-edited |
| Mentor console | Partner B | `templates/mentor/index.html`, `static/mentor/*` |

A documentation change does not move ownership. Partner A's portal files stay Partner A's
even when they live inside a Django-served tree.

## The eight files both efforts touched

| File | Resolution at this head |
|---|---|
| `app.js` | Byte-identical to `main` (Partner A's portal) |
| `index.html` | Byte-identical to `main` (contains `#enrollNote`) |
| `styles.css` | Byte-identical to `main` |
| `server.py` | Byte-identical to `main` (student API mock) |
| `dev/kiosk.html` | Restored from `main`; no deletion |
| `API_CONTRACT.md` | Byte-identical to `main` |
| `README.md` | Byte-identical to `main`; backend documentation lives in `docs/` |
| `.gitignore` | Union of `main`'s rules and the Django paths `/data/`, `/staticfiles/`, `openapi.yaml` |

Seven files were restored from `main` rather than re-resolved line by line: they are Partner
A's source, and Partner B's earlier versions of them were older snapshots. Only `.gitignore`
needed a genuine merge, because both sides add rules that are still wanted.

## Where each application lives now

| URL | Serves | Source |
|---|---|---|
| `/` | Student portal | root `index.html`, `app.js`, `styles.css` via `apps.core.frontend.portal` |
| `/student/` | Student portal | `templates/student/index.html` + `static/student/*`, synced by `tools/sync_student_portal.py` |
| `/mentor/` | Mentor console | `templates/mentor/index.html` + `static/mentor/*` |
| `/api/v1/` | Attendance API | `apps/core/` |

The mentor console previously occupied the repository root, which is what made the two
efforts collide: the same three paths meant two different applications. It now has its own
template, its own static directory and its own route, so the root can stay Partner A's.

## Recomputing the counts

```bash
git diff --name-only origin/main <pr-head> | wc -l
```

At this head that is **79 files** against `main` (`8d332a8`): 76 additions (the Django backend
and the Django portal copies) and 3 modifications (`.github/workflows/portal-tests.yml`,
`.gitignore`, `requirements.txt`). Re-run the command rather than trusting the number; it
moves whenever the branch gains a file.

## Portal synchronisation

`tools/sync_student_portal.py --check` compares `static/student/app.js` and
`static/student/styles.css` against `static/student/PORTAL_SOURCE.json` and re-derives
`templates/student/index.html` from Partner A's `index.html`. It fails if a copy drifts, and
CI runs it, so a stale copy cannot be merged silently.
