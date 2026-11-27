"""P1 API corrections: campus timezone and unambiguous timestamp semantics.

The API must describe instants in UTC and campus-local wall clocks separately,
and every campus-local value must be rendered in that campus's own timezone
rather than the server's ``Africa/Lagos`` default.
"""

from datetime import datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import (AttendanceLog, Campus, MentorCampusAccess, SessionRun,
                              SessionSchedule, Student, User)
from apps.core.serializers import AttendanceSerializer
from apps.core.services import report_for

LAGOS = ZoneInfo("Africa/Lagos")
LOS_ANGELES = ZoneInfo("America/Los_Angeles")


@override_settings(QR_SIGNING_SECRET="timezone-test-secret-" + "x" * 48)
class CampusTimezoneContractTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.lagos = Campus.objects.create(name="Lagos campus", latitude=6.5244, longitude=3.3792, geofence_radius_m=500)
        self.la = Campus.objects.create(name="Los Angeles campus", latitude=34.0522, longitude=-118.2437,
                                        geofence_radius_m=500, timezone="America/Los_Angeles")

    def make_student(self, campus, username):
        user = User.objects.create_user(username=username, password="a-long-student-password",
                                        role=User.Role.STUDENT, assigned_campus=campus)
        return Student.objects.create(user=user, campus=campus)

    def make_log(self, student, scanned_at, campus=None):
        campus = campus or student.campus
        return AttendanceLog.objects.create(
            student=student, campus=campus, session_type="morning", attendance_action="check_in",
            attendance_date=timezone.localtime(scanned_at, ZoneInfo(campus.timezone)).date(),
            scanned_at=scanned_at, status=AttendanceLog.Status.PRESENT, source=AttendanceLog.Source.QR,
            location_verified=True, latitude=34.0522, longitude=-118.2437, location_accuracy_m=10,
            location_distance_m=5, location_checked_at=scanned_at, location_result="inside_geofence")

    def test_attendance_serializer_reports_campus_timezone_and_utc_instant(self):
        student = self.make_student(self.la, "la-student")
        scanned_at = datetime(2026, 3, 2, 14, 0, tzinfo=ZoneInfo("UTC"))
        payload = AttendanceSerializer(self.make_log(student, scanned_at)).data

        self.assertEqual(payload["campus_timezone"], "America/Los_Angeles")
        self.assertEqual(payload["scanned_at"], "2026-03-02T14:00:00Z")
        self.assertEqual(payload["scanned_at_local"], "2026-03-02T06:00:00-08:00")
        self.assertEqual(payload["scan_time_local"], "06:00:00")

    def test_legacy_scan_time_wat_now_follows_the_campus_clock(self):
        student = self.make_student(self.la, "la-legacy-student")
        scanned_at = datetime(2026, 3, 2, 14, 0, tzinfo=ZoneInfo("UTC"))
        log = self.make_log(student, scanned_at)

        # The legacy alias must not keep reporting Lagos wall-clock time for a
        # campus in another timezone.
        self.assertEqual(log.scan_time_wat, "06:00:00")
        self.assertEqual(log.scan_time_wat, log.scan_time_local)

    def test_lagos_campus_values_are_unchanged_for_existing_clients(self):
        student = self.make_student(self.lagos, "lagos-student")
        scanned_at = datetime(2026, 3, 2, 14, 0, tzinfo=ZoneInfo("UTC"))
        payload = AttendanceSerializer(self.make_log(student, scanned_at, campus=self.lagos)).data

        self.assertEqual(payload["campus_timezone"], "Africa/Lagos")
        self.assertEqual(payload["scanned_at"], "2026-03-02T14:00:00Z")
        self.assertEqual(payload["scanned_at_local"], "2026-03-02T15:00:00+01:00")
        self.assertEqual(payload["scan_time_wat"], "15:00:00")

    def test_student_profile_includes_campus_timezone(self):
        student = self.make_student(self.la, "la-profile-student")
        self.client.force_authenticate(user=student.user)

        response = self.client.get("/api/v1/student/profile/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["campus_timezone"], "America/Los_Angeles")
        self.assertEqual(response.data["campus_name"], "Los Angeles campus")

    def test_student_login_returns_campus_timezone(self):
        self.make_student(self.la, "la-login-student")

        response = self.client.post("/api/v1/auth/student/login/",
                                    {"username": "la-login-student", "password": "a-long-student-password"},
                                    format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["student"]["campus_timezone"], "America/Los_Angeles")

    def test_summary_exposes_offset_and_utc_generated_at(self):
        mentor = User.objects.create_user(username="tz-mentor", password="a-long-mentor-password",
                                          role=User.Role.MENTOR, assigned_campus=self.la)
        MentorCampusAccess.objects.create(user=mentor, campus=self.la)
        self.client.force_authenticate(user=mentor)
        now = datetime(2026, 3, 2, 14, 0, tzinfo=ZoneInfo("UTC"))

        with patch("django.utils.timezone.now", return_value=now):
            response = self.client.get(f"/api/v1/mentor/attendance/summary/?campus_id={self.la.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["timezone"], "America/Los_Angeles")
        self.assertEqual(response.data["timezone_offset"], "-08:00")
        self.assertEqual(response.data["generated_at"], "2026-03-02T14:00:00Z")
        self.assertEqual(response.data["date"].isoformat(), "2026-03-02")

    def test_qr_response_expiry_iso_matches_the_epoch_second(self):
        mentor = User.objects.create_user(username="qr-tz-mentor", password="a-long-mentor-password",
                                          role=User.Role.MENTOR, assigned_campus=self.lagos)
        MentorCampusAccess.objects.create(user=mentor, campus=self.lagos)
        student = self.make_student(self.lagos, "qr-tz-student")
        now = timezone.make_aware(datetime(2026, 3, 2, 9, 5), LAGOS)
        SessionSchedule.objects.create(campus=self.lagos, session_type="morning",
                                       start_time=time(9), late_after=time(9, 10), close_time=time(12))
        SessionRun.objects.create(campus=self.lagos, attendance_date=now.date(), session_type="morning",
                                  attendance_action="check_in", started_by=mentor)
        self.client.force_authenticate(user=mentor)

        with patch("apps.core.services.timezone.now", return_value=now):
            response = self.client.get(f"/api/v1/mentor/qr/current/?campus_id={self.lagos.pk}&session_type=morning")

        self.assertEqual(response.status_code, 200)
        expires_at = response.data["expires_at"]
        self.assertEqual(response.data["expires_in_seconds"], 30)
        self.assertEqual(response.data["expires_at_iso"],
                         datetime.fromtimestamp(expires_at, ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"))
        self.assertTrue(response.data["issued_at"].endswith("Z"))
        self.assertEqual(student.campus.timezone, "Africa/Lagos")

    def test_monthly_report_boundaries_follow_the_campus_timezone(self):
        student = self.make_student(self.la, "la-report-student")
        # 07:30 UTC on 1 March is 23:30 on 28 February in Los Angeles, so this row
        # belongs to the campus-local February report, not March.
        self.make_log(student, datetime(2026, 3, 1, 7, 30, tzinfo=ZoneInfo("UTC")))

        february, _ = report_for(self.la, 2026, 2)
        march, _ = report_for(self.la, 2026, 3)

        self.assertEqual(february.record_count, 1)
        self.assertEqual(march.record_count, 0)

    def test_mentor_roster_export_without_campus_param(self):
        mentor = User.objects.create_user(username="roster-mentor", password="a-long-mentor-password",
                                          role=User.Role.MENTOR, assigned_campus=self.lagos)
        MentorCampusAccess.objects.create(user=mentor, campus=self.lagos, can_export=True)
        self.make_student(self.lagos, "roster-student")
        self.client.force_authenticate(user=mentor)

        response = self.client.get("/api/v1/admin/students/export/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("roster-student", response.content.decode("utf-8"))

    def test_mentor_roster_export_without_export_permission_is_denied(self):
        mentor = User.objects.create_user(username="no-export-mentor", password="a-long-mentor-password",
                                          role=User.Role.MENTOR, assigned_campus=self.lagos)
        MentorCampusAccess.objects.create(user=mentor, campus=self.lagos, can_export=False)
        self.client.force_authenticate(user=mentor)

        response = self.client.get("/api/v1/admin/students/export/")

        self.assertEqual(response.status_code, 403)
