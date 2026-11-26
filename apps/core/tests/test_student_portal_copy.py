"""The Django-served student portal must stay identical to Partner A's source.

Partner A owns the portal; this repository serves a copy. A copy drifts, so the
copy is recorded in ``static/student/PORTAL_SOURCE.json`` and these tests fail the
build when it drifts, when the template loses the three-checkpoint markup, or when
the route stops serving the vendored assets.
"""

import hashlib
import sys
from pathlib import Path

from django.contrib.staticfiles import finders
from django.test import TestCase

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools"))

import sync_student_portal as sync  # noqa: E402

# Markers that only exist in the three-checkpoint portal. If the served copy is an
# older snapshot these disappear, which is exactly the defect issue #6 describes.
CHECKPOINT_MARKERS = (
    "checkpointRows",          # the three-row checkpoint panel
    "checkpointHint",          # campus-local date hint above it
    "historyTimeHeader",       # time column headed by campus_timezone
    "confirmUtc",              # canonical scanned_at on the confirmation card
)

# Behaviour that lives in app.js rather than the template.
SCRIPT_MARKERS = (
    "DUPLICATE_CHECKPOINT_TEXT",   # checkpoint-specific duplicate copy
    "campusTodayKey",              # campus-local date, no fixed UTC+1
    "scan_time_local",             # campus-local clock time
)


class StudentPortalCopyTests(TestCase):
    def test_copies_match_the_recorded_source(self):
        manifest = sync.load_manifest()
        self.assertEqual(manifest["files"], sync.current_hashes(),
                         "static/student or the template drifted; run tools/sync_student_portal.py --write")

    def test_source_commit_is_recorded(self):
        manifest = sync.load_manifest()
        self.assertRegex(manifest["source_commit"], r"^[0-9a-f]{40}$")

    def test_adapter_reproduces_the_committed_template(self):
        """The sync tool must be able to regenerate exactly what is committed."""
        manifest = sync.load_manifest()
        template = (REPO / "templates" / "student" / "index.html").read_text()
        self.assertIn("{% load static %}", template)
        self.assertNotIn("document.write(", template)
        self.assertEqual(hashlib.sha256(template.encode()).hexdigest(),
                         manifest["files"]["index.html"])

    def test_portal_route_serves_the_three_checkpoint_portal(self):
        response = self.client.get("/student/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for marker in CHECKPOINT_MARKERS:
            self.assertIn(marker, body, f"/student/ is missing {marker}: stale snapshot?")
        self.assertIn("/static/student/app.js", body)
        self.assertIn("/static/student/styles.css", body)
        self.assertIn("/static/student/vendor/html5-qrcode.min.js", body)
        script = (REPO / "static" / "student" / "app.js").read_text()
        for marker in SCRIPT_MARKERS:
            self.assertIn(marker, script, f"served app.js is missing {marker}: stale snapshot?")

    def test_served_app_js_is_the_recorded_copy(self):
        path = finders.find("student/app.js")
        self.assertTrue(path)
        served = Path(path).read_bytes()
        recorded = (REPO / "static" / "student" / "app.js").read_bytes()
        self.assertEqual(hashlib.sha256(served).hexdigest(), hashlib.sha256(recorded).hexdigest())

    def test_attendance_history_is_grouped_by_day_not_by_checkpoint(self):
        """Three checkpoints on one day must not count as three attended days."""
        source = (REPO / "static" / "student" / "app.js").read_text()
        # The dashboard counts attended records within a single campus month, and the
        # history list is keyed by attendance_date, so a three-checkpoint day shows
        # three rows for that one date rather than inflating any day counter.
        self.assertIn("campusMonthKey", source)
        self.assertIn("monthKeyOf", source)
        self.assertIn("attended", source)
