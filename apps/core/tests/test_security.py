import json
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth import authenticate
from django.core.management import call_command
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings
from apps.core.models import Campus, User


class SecurityTests(TestCase):
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
            self.assertEqual((source.read_bytes(),profile.read_bytes()),before)
            with override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.Argon2PasswordHasher","django.contrib.auth.hashers.MD5PasswordHasher","apps.core.hashers.LegacyNodeScryptPasswordHasher"]):
                self.assertEqual(authenticate(username="legacy-mentor",password="a-real-old-password").pk,user.pk)
                user.refresh_from_db()
                self.assertTrue(user.password.startswith("argon2$"))
