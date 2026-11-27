import json
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth import authenticate
from django.core.management import call_command
from django.db import OperationalError
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings
from apps.core.models import Campus, User


class SecurityTests(TestCase):
    def test_health_reports_database_readiness(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "service": "learn2earn-attendance", "database": "ok"})

    def test_health_returns_503_when_database_is_unavailable(self):
        with patch("config.urls.connection.cursor", side_effect=OperationalError("unavailable")):
            response = self.client.get("/health/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["database"], "unavailable")

    def test_student_portal_has_a_separate_django_route_and_vendored_assets(self):
        response=self.client.get("/student/")
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"/static/student/app.js")
        self.assertContains(response,"/static/student/vendor/html5-qrcode.min.js")
        self.assertNotContains(response,"document.write(")
        self.assertTrue(finders.find("student/app.js"))
        self.assertTrue(finders.find("student/styles.css"))
        self.assertTrue(finders.find("student/vendor/html5-qrcode.min.js"))

    def test_old_json_files_and_backend_source_are_not_served(self):
        for path in ("/data/attendance.json", "/data/mentor_profile.json", "/server.js", "/legacy/server.js.disabled"):
            self.assertEqual(self.client.get(path).status_code,404)

    def test_campus_api_requires_authentication(self):
        self.assertEqual(self.client.get("/api/v1/admin/campuses/").status_code,401)

    def test_legacy_import_preserves_sources_and_upgrades_legacy_mentor_hash(self):
        campus=Campus.objects.create(name="Legacy Import Campus")
        salt="test-salt-0123456789"
        digest=hashlib.scrypt(b"a-real-old-password",salt=salt.encode(),n=16384,r=8,p=1,dklen=64).hex()
        with TemporaryDirectory() as folder:
            source=Path(folder)/"attendance.json"; profile=Path(folder)/"mentor.json"
            source.write_text(json.dumps({"students":[],"attendance_logs":[]}),encoding="utf-8")
            profile.write_text(json.dumps({"display_name":"Old Mentor","salt":salt,"password_hash":digest,"session_id":"legacy-session"}),encoding="utf-8")
            before=(source.read_bytes(),profile.read_bytes())
            call_command("import_legacy_json",source=str(source),mentor_profile=str(profile),campus_id=str(campus.pk),verbosity=0)
            user=User.objects.get(username="legacy-mentor")
            self.assertEqual(user.password.split("$")[0],"legacy_node_scrypt")
            self.assertGreater(len(user.password), 128)
            self.assertEqual((source.read_bytes(),profile.read_bytes()),before)
            with override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.Argon2PasswordHasher","django.contrib.auth.hashers.MD5PasswordHasher","apps.core.hashers.LegacyNodeScryptPasswordHasher"]):
                self.assertEqual(authenticate(username="legacy-mentor",password="a-real-old-password").pk,user.pk)
                user.refresh_from_db()
                self.assertTrue(user.password.startswith("argon2$"))

    def test_legacy_import_keeps_distinct_checkpoints_and_skips_same_checkpoint_duplicates(self):
        campus = Campus.objects.create(name="Checkpoint Import Campus")
        base = {
            "username": "ada.student",
            "full_name": "Ada Student",
            "scan_date": "2026-11-20",
            "scan_time_wat": "09:05:00",
            "status": "present",
        }
        records = [
            {**base, "session_type": "morning"},
            {**base, "session_type": "afternoon", "scan_time_wat": "13:05:00"},
            {**base, "session_type": "evening", "scan_time_wat": "17:05:00"},
            {**base, "session_type": "morning", "scan_time_wat": "09:06:00"},
        ]
        with TemporaryDirectory() as folder:
            source = Path(folder) / "attendance.json"
            source.write_text(json.dumps({"students": [], "attendance_logs": records}), encoding="utf-8")
            call_command(
                "import_legacy_json",
                source=str(source),
                mentor_profile=str(Path(folder) / "missing-mentor.json"),
                campus_id=str(campus.pk),
                verbosity=0,
            )

        user = User.objects.get(username="ada.student")
        rows = user.student_profile.attendance_logs.filter(attendance_date="2026-11-20")
        self.assertEqual(rows.count(), 3)
        self.assertSetEqual(set(rows.values_list("session_type", flat=True)), {"morning", "afternoon", "evening"})
