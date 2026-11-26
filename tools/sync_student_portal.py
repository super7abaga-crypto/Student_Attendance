#!/usr/bin/env python3
"""Synchronise the Django-served student portal with Partner A's source.

The backend serves the student portal from ``templates/student/index.html`` and
``static/student/``. Partner A owns that portal; this repository only serves it.
A manual copy drifts silently, so the copy is recorded in
``static/student/PORTAL_SOURCE.json`` (source commit plus a sha256 per file) and
this tool is the only supported way to change it.

    python3 tools/sync_student_portal.py --check
        Verify the committed files still match the recorded manifest. Exits 1 on
        drift. Runs in the test suite and therefore in CI.

    python3 tools/sync_student_portal.py --source ../student-portal --write
        Copy ``app.js`` and ``styles.css`` verbatim, render ``index.html`` through
        the Django adapter below, and rewrite the manifest.

The adapter is deliberately small and explicit: it only rewrites asset references
to Django static paths and removes the CDN fallback, because the vendored
``html5-qrcode`` is always present in this repository. It never edits the portal's
markup or behaviour, so Partner A's implementation stays authoritative.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "static" / "student"
TEMPLATE = REPO / "templates" / "student" / "index.html"
MANIFEST = STATIC / "PORTAL_SOURCE.json"

VERBATIM = ("app.js", "styles.css")

# (pattern, replacement) applied in order to Partner A's index.html.
ADAPTER_RULES = (
    (re.compile(r'\A'), "{% load static %}\n", 1),
    (re.compile(r'<link rel="icon" href="favicon\.png" type="image/png">'),
     "<link rel=\"icon\" href=\"{% static 'student/assets/learn2earn-logo.svg' %}\" type=\"image/svg+xml\">", 1),
    (re.compile(r'<link rel="stylesheet" href="styles\.css">'),
     "<link rel=\"stylesheet\" href=\"{% static 'student/styles.css' %}\">", 1),
    (re.compile(r'<script src="vendor/html5-qrcode\.min\.js"></script>\s*'
                r'<script>\s*if \(!window\.Html5Qrcode\) \{.*?</script>\s*', re.S),
     "<script src=\"{% static 'student/vendor/html5-qrcode.min.js' %}\"></script>\n  ", 1),
    (re.compile(r'<script defer src="app\.js"></script>'),
     "<script defer src=\"{% static 'student/app.js' %}\"></script>", 1),
    (re.compile(r'src="assets/learn2earn-logo\.svg"'),
     "src=\"{% static 'student/assets/learn2earn-logo.svg' %}\"", 0),
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def adapt_index(source_html: str) -> str:
    """Turn Partner A's standalone index.html into a Django template."""
    rendered = source_html
    for pattern, replacement, count in ADAPTER_RULES:
        rendered = pattern.sub(replacement, rendered, count=count)
    if "{% static 'student/app.js' %}" not in rendered:
        raise SystemExit("adapter failed: app.js reference was not rewritten")
    if "document.write(" in rendered:
        raise SystemExit("adapter failed: the CDN fallback is still present")
    return rendered


def load_manifest() -> dict:
    if not MANIFEST.exists():
        raise SystemExit(f"missing manifest: {MANIFEST}")
    return json.loads(MANIFEST.read_text())


def current_hashes() -> dict:
    return {
        "app.js": digest(STATIC / "app.js"),
        "styles.css": digest(STATIC / "styles.css"),
        "index.html": digest(TEMPLATE),
    }


def check() -> int:
    manifest = load_manifest()
    recorded = manifest.get("files", {})
    actual = current_hashes()
    problems = []
    for name, path_hash in actual.items():
        if name not in recorded:
            problems.append(f"{name}: not recorded in the manifest")
        elif recorded[name] != path_hash:
            problems.append(
                f"{name}: sha256 {path_hash[:12]} does not match the recorded {recorded[name][:12]}")
    if problems:
        print("Student portal copies have drifted from the recorded source "
              f"({manifest.get('source_commit', 'unknown')}):")
        for problem in problems:
            print("  - " + problem)
        print("Re-sync with: python3 tools/sync_student_portal.py --source <partner-a-checkout> --write")
        return 1
    print(f"Student portal copies match the manifest (source {manifest.get('source_commit', 'unknown')}).")
    return 0


def write(source: Path, source_commit: str | None = None) -> int:
    missing = [name for name in ("app.js", "styles.css", "index.html") if not (source / name).exists()]
    if missing:
        raise SystemExit("source is missing: " + ", ".join(missing))

    for name in VERBATIM:
        (STATIC / name).write_bytes((source / name).read_bytes())
    TEMPLATE.write_text(adapt_index((source / "index.html").read_text()))

    commit = source_commit or "unknown"
    if not source_commit:
        try:
            commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                                    capture_output=True, text=True, check=True).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            commit = "unknown"

    manifest = {
        "source_repository": "super7abaga-crypto/Student_Attendance",
        "source_branch": "feat/django-student-integration",
        "source_commit": commit,
        "adapter": "tools/sync_student_portal.py (static paths and CDN fallback only)",
        "files": current_hashes(),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Synced from {commit}: " + ", ".join(manifest["files"]))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the copies against the manifest")
    parser.add_argument("--write", action="store_true", help="copy from --source and rewrite the manifest")
    parser.add_argument("--source", type=Path, help="path to Partner A's portal checkout")
    parser.add_argument("--source-commit", help="record this commit when --source is not a git checkout")
    args = parser.parse_args(argv)

    if args.check and args.write:
        parser.error("choose either --check or --write")
    if args.write:
        if not args.source:
            parser.error("--write requires --source")
        return write(args.source, args.source_commit)
    return check()


if __name__ == "__main__":
    sys.exit(main())
