from datetime import datetime, time, timedelta
import csv
import json
from unittest.mock import patch
from zoneinfo import ZoneInfo
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.authtoken.models import Token
from apps.core.models import AttendanceLog, AuditLog, Campus, MentorCampusAccess, MonthlyReport, SessionRun, SessionSchedule, Student, User
from apps.core.serializers import AttendanceSerializer, CampusSerializer, ScheduleSerializer
from apps.core.services import mint_qr


@override_settings(QR_SIGNING_SECRET="api-test-secret-"+"x"*48)
class AttendanceAPITests(TestCase):
    def setUp(self):
        self.client=APIClient()
        self.campus=Campus.objects.create(name="API Campus",latitude=6.5244,longitude=3.3792,geofence_radius_m=500)
        self.user=User.objects.create_user(username="ada",password="long-password-for-tests",first_name="Ada",last_name="Okafor",role=User.Role.STUDENT,assigned_campus=self.campus)
        self.student=Student.objects.create(user=self.user,campus=self.campus)
        SessionSchedule.objects.create(campus=self.campus,session_type="morning",start_time=time(9),late_after=time(9,10),close_time=time(12))

    def make_token(self,at,session="morning"):
        action="check_out" if session=="evening" else "check_in"
        run,_=SessionRun.objects.get_or_create(campus=self.campus,attendance_date=at.date(),session_type=session,defaults={"attendance_action":action,"started_by":self.user})
        with patch("apps.core.services.timezone.now",return_value=at): return mint_qr(run)["token"]

    def test_scan_uses_authenticated_student_not_submitted_username(self):
        at=timezone.make_aware(datetime.combine(timezone.localdate(),time(9,5)),ZoneInfo("Africa/Lagos")); token=self.make_token(at)
        self.client.force_authenticate(user=self.user)
        qr_payload=json.dumps({"version":1,"token":token,"expires_at":int(at.timestamp())+30})
        with patch("django.utils.timezone.now",return_value=at):
            response=self.client.post("/api/v1/attendance/scan/",{"username":"someone-else","qr_payload":qr_payload,"latitude":6.5244,"longitude":3.3792,"accuracy":10},format="json")
        self.assertEqual(response.status_code,201)
        self.assertEqual(response.data["attendance"]["username"],"ada")
        self.assertEqual(response.data["attendance"]["status"],"present")

    def test_scan_errors_have_stable_codes_for_the_student_portal(self):
        at=timezone.make_aware(datetime.combine(timezone.localdate(),time(9,5)),ZoneInfo("Africa/Lagos"))
        token=self.make_token(at)
        self.client.force_authenticate(user=self.user)
        missing_gps=self.client.post("/api/v1/attendance/scan/",{"qr_payload":token},format="json")
        self.assertEqual(missing_gps.status_code,400)
        self.assertEqual(missing_gps.data["code"],"gps_required")
        with patch("django.utils.timezone.now",return_value=at):
            low_accuracy=self.client.post("/api/v1/attendance/scan/",{"qr_payload":token,"latitude":6.5244,"longitude":3.3792,"accuracy":101},format="json")
        self.assertEqual(low_accuracy.status_code,403)
        self.assertEqual(low_accuracy.data["code"],"gps_accuracy")
        self.assertTrue(AuditLog.objects.filter(action="attendance.location_rejected",actor=self.user).exists())

    def test_expired_qr_returns_a_distinct_code(self):
        at=timezone.make_aware(datetime.combine(timezone.localdate(),time(9,5)),ZoneInfo("Africa/Lagos"))
        token=self.make_token(at)
        self.client.force_authenticate(user=self.user)
        with patch("django.utils.timezone.now",return_value=at+timedelta(seconds=30)):
            response=self.client.post("/api/v1/attendance/scan/",{"qr_payload":token,"latitude":6.5244,"longitude":3.3792,"accuracy":10},format="json")
        self.assertEqual(response.status_code,403)
        self.assertEqual(response.data["code"],"qr_expired")

    def test_geofence_rejection_returns_wrong_campus_code(self):
        at=timezone.make_aware(datetime.combine(timezone.localdate(),time(9,5)),ZoneInfo("Africa/Lagos"))
        token=self.make_token(at)
        self.client.force_authenticate(user=self.user)
        with patch("django.utils.timezone.now",return_value=at):
            response=self.client.post("/api/v1/attendance/scan/",{"qr_payload":token,"latitude":7.5,"longitude":4.5,"accuracy":5},format="json")
        self.assertEqual(response.status_code,403)
        self.assertEqual(response.data["code"],"wrong_campus")

    def test_duplicate_scan_is_audited_after_the_failed_insert_transaction(self):
        at=timezone.make_aware(datetime.combine(timezone.localdate(),time(9,5)),ZoneInfo("Africa/Lagos"))
        token=self.make_token(at)
        self.client.force_authenticate(user=self.user)
        body={"qr_payload":token,"latitude":6.5244,"longitude":3.3792,"accuracy":10}
        with patch("django.utils.timezone.now",return_value=at):
            first=self.client.post("/api/v1/attendance/scan/",body,format="json")
            duplicate=self.client.post("/api/v1/attendance/scan/",body,format="json")
        self.assertEqual(first.status_code,201)
        self.assertEqual(duplicate.status_code,409)
        self.assertEqual(duplicate.data["attendance"]["session_type"],"morning")
        self.assertTrue(AuditLog.objects.filter(action="attendance.duplicate_scan",actor=self.user).exists())

    def test_same_day_scans_in_other_checkpoints_are_allowed_and_evening_checks_out(self):
        self.client.force_authenticate(user=self.user)
        for session,at,expected_action in (
            ("morning",time(9,5),"check_in"),
            ("afternoon",time(13,5),"check_in"),
            ("evening",time(17,5),"check_out"),
        ):
            moment=timezone.make_aware(datetime.combine(timezone.localdate(),at),ZoneInfo("Africa/Lagos"))
            token=self.make_token(moment,session)
            body={"qr_payload":token,"latitude":6.5244,"longitude":3.3792,"accuracy":10}
            with patch("django.utils.timezone.now",return_value=moment):
                response=self.client.post("/api/v1/attendance/scan/",body,format="json")
            self.assertEqual(response.status_code,201,response.data)
            self.assertEqual(response.data["attendance"]["attendance_action"],expected_action)
        self.assertEqual(self.student.attendance_logs.filter(attendance_date=timezone.localdate()).count(),3)

    def test_absence_cannot_be_manually_created_before_session_close(self):
        mentor=User.objects.create_user(username="admin",password="a-very-long-mentor-password",role=User.Role.CAMPUS_ADMIN,assigned_campus=self.campus,is_staff=True)
        self.client.force_authenticate(user=mentor)
        at=timezone.make_aware(datetime.combine(timezone.localdate(),time(11,59)),ZoneInfo("Africa/Lagos"))
        with patch("apps.core.views.timezone.now",return_value=at):
            response=self.client.post("/api/v1/mentor/attendance/manual/",{"student_id":str(self.student.pk),"session_type":"morning","status":"absent","reason":"No scan observed"},format="json")
        self.assertEqual(response.status_code,400)
        self.assertFalse(self.student.attendance_logs.exists())

    def test_monthly_close_defaults_to_previous_december_when_current_month_is_january(self):
        admin=User.objects.create_user(username="reportadmin",password="a-very-long-mentor-password",role=User.Role.CAMPUS_ADMIN,assigned_campus=self.campus,is_staff=True)
        self.client.force_authenticate(user=admin)
        now=timezone.make_aware(datetime(2027,1,2,0,30),ZoneInfo("UTC"))
        with patch("apps.core.views.timezone.now",return_value=now):
            response=self.client.post("/api/v1/admin/monthly-close/",{"campus_id":str(self.campus.pk)},format="json")
        self.assertEqual(response.status_code,201)
        report=MonthlyReport.objects.get(campus=self.campus)
        self.assertEqual((report.year,report.month),(2026,12))

    def test_mentor_qr_image_returns_a_png_with_a_live_signed_payload(self):
        at=timezone.make_aware(datetime.combine(timezone.localdate(),time(9,5)),ZoneInfo("Africa/Lagos"))
        mentor=User.objects.create_user(username="qrmentor",password="long-password-for-tests",role=User.Role.CAMPUS_ADMIN,assigned_campus=self.campus,is_staff=True)
        run=SessionRun.objects.create(campus=self.campus,attendance_date=at.date(),session_type="morning",attendance_action="check_in",started_by=mentor)
        with patch("apps.core.services.timezone.now",return_value=at): qr=mint_qr(run)
        self.client.force_authenticate(user=mentor)
        with patch("apps.core.services.timezone.now",return_value=at):
            response=self.client.get("/api/v1/mentor/qr/image/",{"token":qr["token"]})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response["Content-Type"],"image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_student_scan_requires_authenticated_identity(self):
        at=timezone.make_aware(datetime.combine(timezone.localdate(),time(9,5)),ZoneInfo("Africa/Lagos")); token=self.make_token(at)
        response=self.client.post("/api/v1/attendance/scan/",{"username":"ada","qr_token":token,"latitude":6.5244,"longitude":3.3792,"accuracy":10},format="json")
        self.assertEqual(response.status_code,401)

    def test_student_tokens_expire_and_are_renewed_by_login(self):
        token=Token.objects.create(user=self.user)
        Token.objects.filter(pk=token.pk).update(created=timezone.now()-timedelta(hours=13))
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.assertEqual(self.client.get("/api/v1/student/profile/").status_code,401)
        self.client.credentials()
        response=self.client.post("/api/v1/auth/student/login/",{"username":"ada","password":"long-password-for-tests"},format="json")
        self.assertEqual(response.status_code,200)
        self.assertNotEqual(response.data["token"],token.key)

    def test_campus_location_requires_a_valid_coordinate_pair(self):
        partial=CampusSerializer(data={"name":"Partial Campus","latitude":"6.500000"})
        self.assertFalse(partial.is_valid())
        out_of_range=CampusSerializer(data={"name":"Invalid Campus","latitude":"91.000000","longitude":"0.000000"})
        self.assertFalse(out_of_range.is_valid())

    def test_schedule_rejects_a_cutoff_outside_the_open_window(self):
        serializer=ScheduleSerializer(data={
            "campus":str(self.campus.pk),"session_type":"morning",
            "start_time":"09:00","late_after":"12:00","close_time":"12:00",
        })
        self.assertFalse(serializer.is_valid())

    def test_mentor_with_manage_permission_can_deactivate_roster_student(self):
        mentor=User.objects.create_user(username="roster-manager",password="a-very-long-mentor-password",role=User.Role.MENTOR)
        MentorCampusAccess.objects.create(user=mentor,campus=self.campus,can_manage_students=True)
        self.client.force_authenticate(user=mentor)
        response=self.client.post(f"/api/v1/admin/students/{self.student.pk}/deactivate/",{},format="json")
        self.assertEqual(response.status_code,200)
        self.student.refresh_from_db()
        self.assertFalse(self.student.active)

    def test_mentor_without_manage_permission_cannot_deactivate_roster_student(self):
        mentor=User.objects.create_user(username="roster-reader",password="a-very-long-mentor-password",role=User.Role.MENTOR)
        MentorCampusAccess.objects.create(user=mentor,campus=self.campus,can_manage_students=False)
        self.client.force_authenticate(user=mentor)
        response=self.client.post(f"/api/v1/admin/students/{self.student.pk}/deactivate/",{},format="json")
        self.assertEqual(response.status_code,403)

    def test_location_override_rejects_non_today_attendance_date(self):
        mentor=User.objects.create_user(username="location-mentor",password="a-very-long-mentor-password",role=User.Role.MENTOR)
        MentorCampusAccess.objects.create(user=mentor,campus=self.campus,can_correct_attendance=True)
        self.client.force_authenticate(user=mentor)
        today=timezone.localtime(timezone.now(),ZoneInfo(self.campus.timezone)).date()
        response=self.client.post("/api/v1/mentor/attendance/location-override/",{
            "student_id":str(self.student.pk),"campus_id":str(self.campus.pk),"session_type":"morning",
            "attendance_date":(today+timedelta(days=1)).isoformat(),"original_location_result":"outside_geofence","reason":"Approved review",
        },format="json")
        self.assertEqual(response.status_code,400)
        self.assertIn("Location overrides can only record attendance for today.",str(response.data["attendance_date"]))

    def test_location_override_cannot_change_a_closed_month(self):
        mentor=User.objects.create_user(username="location-archived-mentor",password="a-very-long-mentor-password",role=User.Role.MENTOR)
        MentorCampusAccess.objects.create(user=mentor,campus=self.campus,can_correct_attendance=True)
        self.client.force_authenticate(user=mentor)
        today=timezone.localtime(timezone.now(),ZoneInfo(self.campus.timezone)).date()
        MonthlyReport.objects.create(campus=self.campus,year=today.year,month=today.month,closed=True)
        response=self.client.post("/api/v1/mentor/attendance/location-override/",{
            "student_id":str(self.student.pk),"campus_id":str(self.campus.pk),"session_type":"morning",
            "attendance_date":today.isoformat(),"original_location_result":"outside_geofence","reason":"Approved review",
        },format="json")
        self.assertEqual(response.status_code,400)
        self.assertIn("report is closed",str(response.data["attendance_date"]))

    def test_location_override_cannot_reuse_a_failure_from_another_session(self):
        mentor=User.objects.create_user(username="location-mentor2",password="a-very-long-mentor-password",role=User.Role.MENTOR)
        MentorCampusAccess.objects.create(user=mentor,campus=self.campus,can_correct_attendance=True)
        self.client.force_authenticate(user=mentor)
        now=timezone.make_aware(datetime.combine(timezone.localdate(),time(9,5)),ZoneInfo(self.campus.timezone))
        AuditLog.objects.create(actor=self.user,campus=self.campus,action="attendance.location_rejected",
            details={"result":"outside_geofence","session_type":"afternoon"})
        AuditLog.objects.filter(actor=self.user,action="attendance.location_rejected").update(created_at=now)
        with patch("apps.core.views.timezone.now",return_value=now):
            response=self.client.post("/api/v1/mentor/attendance/location-override/",{
                "student_id":str(self.student.pk),"campus_id":str(self.campus.pk),"session_type":"morning",
                "attendance_date":now.date().isoformat(),"original_location_result":"outside_geofence","reason":"Approved review",
            },format="json")
        self.assertEqual(response.status_code,400)
        self.assertIn("campus and session",str(response.data["original_location_result"]))

    def test_mentor_session_is_individual_and_csrf_protected(self):
        mentor=User.objects.create_user(username="mentor1",password="a-very-long-mentor-password",role=User.Role.CAMPUS_ADMIN,assigned_campus=self.campus,display_name="Mentor One")
        client=APIClient(enforce_csrf_checks=True)
        response=client.post("/api/v1/auth/mentor/login/",{"username":"mentor1","password":"a-very-long-mentor-password"},format="json")
        self.assertEqual(response.status_code,200)
        self.assertIn("sessionid",client.cookies)
        csrf=client.cookies["csrftoken"].value
        protected=client.patch("/api/v1/auth/mentor/profile/",{"display_name":"Updated Mentor"},format="json")
        self.assertEqual(protected.status_code,403)
        changed=client.patch("/api/v1/auth/mentor/profile/",{"display_name":"Updated Mentor"},format="json",HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(changed.status_code,200)
        self.assertEqual(mentor.pk,User.objects.get(username="mentor1").pk)

    def test_login_endpoint_enforces_its_rate_limit(self):
        from unittest.mock import patch
        rates = {**settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "login": "2/min"}
        with patch("apps.core.views.LoginThrottle.THROTTLE_RATES", rates):
            cache.clear()
            first = self.client.post("/api/v1/auth/student/login/", {"username": "missing", "password": "wrong"}, format="json")
            second = self.client.post("/api/v1/auth/student/login/", {"username": "missing", "password": "wrong"}, format="json")
            limited = self.client.post("/api/v1/auth/student/login/", {"username": "missing", "password": "wrong"}, format="json")
        self.assertEqual(first.status_code, 401)
        self.assertEqual(second.status_code, 401)
        self.assertEqual(limited.status_code, 429)

    def test_scan_endpoint_enforces_authenticated_scan_rate_limit(self):
        from unittest.mock import patch
        rates = {**settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "scan": "2/min"}
        with patch("apps.core.views.ScanThrottle.THROTTLE_RATES", rates):
            cache.clear()
            self.client.force_authenticate(user=self.user)
            first = self.client.post("/api/v1/attendance/scan/", {}, format="json")
            second = self.client.post("/api/v1/attendance/scan/", {}, format="json")
            limited = self.client.post("/api/v1/attendance/scan/", {}, format="json")
        self.assertEqual(first.status_code, 400)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(limited.status_code, 429)

    def test_mentor_csv_export_contains_headers_and_escapes_formulas(self):
        mentor = User.objects.create_user(username="csv-mentor", password="a-very-long-mentor-password", role=User.Role.MENTOR)
        MentorCampusAccess.objects.create(user=mentor, campus=self.campus, can_export=True)
        formula_user = User.objects.create_user(username="=HYPERLINK(1)", password="a-very-long-student-password",
            first_name="=1+1", last_name="Student", role=User.Role.STUDENT, assigned_campus=self.campus)
        formula_student = Student.objects.create(user=formula_user, campus=self.campus)
        AttendanceLog.objects.create(student=formula_student, campus=self.campus, session_type="morning",
            attendance_action="check_in", attendance_date=timezone.localdate(), status=AttendanceLog.Status.PRESENT)
        self.client.force_authenticate(user=mentor)

        response = self.client.get(f"/api/v1/mentor/attendance/?campus_id={self.campus.pk}&format=csv")

        self.assertEqual(response.status_code, 200, response.content.decode("utf-8", errors="replace"))
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        rows = list(csv.reader(response.content.decode("utf-8").splitlines()))
        self.assertIn("record_kind", rows[0])
        self.assertEqual(rows[0][:4], ["full_name", "username", "student_id", "campus"])
        self.assertEqual(rows[1][0], "'=1+1 Student")
        self.assertEqual(rows[1][1], "'=hyperlink(1)")
        self.assertEqual(rows[1][6], "attendance")

    def test_system_absence_csv_is_identified_as_automated(self):
        mentor = User.objects.create_user(username="absence-csv-mentor", password="a-very-long-mentor-password", role=User.Role.MENTOR)
        MentorCampusAccess.objects.create(user=mentor, campus=self.campus, can_export=True)
        AttendanceLog.objects.create(student=self.student, campus=self.campus, session_type="evening",
            attendance_action="check_in", attendance_date=timezone.localdate(), status=AttendanceLog.Status.ABSENT,
            source=AttendanceLog.Source.SYSTEM, location_result="system_daily_absence")
        self.client.force_authenticate(user=mentor)

        response = self.client.get(f"/api/v1/mentor/attendance/?campus_id={self.campus.pk}&format=csv")

        rows = list(csv.reader(response.content.decode("utf-8").splitlines()))
        self.assertEqual(rows[1][6], "system_absence")
        self.assertEqual(rows[1][12], "Automated system")

    def test_absence_serializer_adds_kind_without_removing_legacy_fields(self):
        absent = AttendanceLog.objects.create(student=self.student, campus=self.campus,
            session_type="evening", attendance_action="check_in", attendance_date=timezone.localdate(),
            status=AttendanceLog.Status.ABSENT, source=AttendanceLog.Source.MANUAL,
            location_result="system_daily_absence")
        payload = AttendanceSerializer(absent).data
        self.assertEqual(payload["record_kind"], "system_absence")
        self.assertEqual(payload["session_type"], "evening")
        self.assertEqual(payload["attendance_action"], "check_in")
