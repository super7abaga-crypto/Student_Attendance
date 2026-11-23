from datetime import datetime, time
from zoneinfo import ZoneInfo
from hashlib import scrypt
from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from unittest.mock import patch
from apps.core.hashers import LegacyNodeScryptPasswordHasher
from apps.core.models import AttendanceLog, Campus, SessionRun, SessionSchedule, Student, User
from apps.core.services import DEFAULT_SCHEDULES, attended_sessions, mint_qr, record_scan, report_for, summary_for


@override_settings(QR_SIGNING_SECRET="test-secret-" + "x" * 48)
class AttendanceServiceTests(TestCase):
    def setUp(self):
        self.campus=Campus.objects.create(name="Lagos Campus",latitude=6.5244,longitude=3.3792,geofence_radius_m=500)
        self.student_user=User.objects.create_user(username="ada okafor",password="correct-horse-battery-staple",first_name="Ada",last_name="Okafor",role=User.Role.STUDENT,assigned_campus=self.campus)
        self.student=Student.objects.create(user=self.student_user,campus=self.campus)
        for kind,start,late,close in [("morning",time(9),time(9,10),time(12)),("afternoon",time(13),time(13,10),time(16)),("evening",time(17),time(17,10),time(20))]:
            SessionSchedule.objects.create(campus=self.campus,session_type=kind,start_time=start,late_after=late,close_time=close)

    def test_monthly_report_marks_generated_absence_and_system_source(self):
        day = timezone.localdate()
        AttendanceLog.objects.create(student=self.student, campus=self.campus, session_type="evening",
            attendance_action="check_in", attendance_date=day, status=AttendanceLog.Status.ABSENT,
            source=AttendanceLog.Source.SYSTEM, location_result="system_daily_absence")

        report, _ = report_for(self.campus, day.year, day.month)

        self.assertTrue(report.csv_content.startswith("full_name,username,student_id,campus,track,cohort,record_kind"))
        report_rows = report.json_content["attendance"]
        self.assertTrue(any(row["record_kind"] == "system_absence" and row["source"] == "Automated system" for row in report_rows))

    def token_at(self, session="morning", at=None):
        at=at or timezone.make_aware(datetime(2026,11,18,9,5),ZoneInfo("Africa/Lagos"))
        run,_=SessionRun.objects.get_or_create(campus=self.campus,attendance_date=at.astimezone(ZoneInfo("Africa/Lagos")).date(),session_type=session,defaults={"attendance_action":"check_in","started_by":self.student_user})
        with patch("apps.core.services.timezone.now",return_value=at):
            payload=mint_qr(run)
        return payload["token"],at

    def test_lateness_boundary_uses_exact_cutoff(self):
        for minute,expected in [(10,"present"),(11,"late")]:
            student_user=User.objects.create_user(username=f"student{minute}",password="correct-horse-battery-staple",first_name="Test",role=User.Role.STUDENT,assigned_campus=self.campus)
            student=Student.objects.create(user=student_user,campus=self.campus)
            at=timezone.make_aware(datetime(2026,11,18,9,minute),ZoneInfo("Africa/Lagos")); token,_=self.token_at(at=at)
            row=record_scan(student=student,token=token,latitude=6.5244,longitude=3.3792,accuracy=10,at=at)
            self.assertEqual(row.status,expected)

    def test_check_in_cutoffs_apply_to_morning_and_afternoon(self):
        for kind,hour in (("morning",9),("afternoon",13)):
            for minute,second,microsecond,expected in (
                (10,0,0,AttendanceLog.Status.PRESENT),
                (10,59,999999,AttendanceLog.Status.PRESENT),
                (11,0,0,AttendanceLog.Status.LATE),
            ):
                at=timezone.make_aware(datetime.combine(timezone.localdate(),time(hour,minute,second,microsecond)),ZoneInfo("Africa/Lagos"))
                token,_=self.token_at(kind,at)
                username=f"boundary-{kind}-{minute}-{second}-{microsecond}"
                extra_user=User.objects.create_user(username=username,password="correct-horse-battery-staple",first_name="Boundary",role=User.Role.STUDENT,assigned_campus=self.campus)
                extra_student=Student.objects.create(user=extra_user,campus=self.campus)
                row=record_scan(student=extra_student,token=token,latitude=6.5244,longitude=3.3792,accuracy=10,at=at)
                self.assertEqual(row.status,expected)
                self.assertEqual(row.attendance_action,"check_in")

    def test_evening_checkout_is_present_and_not_subject_to_checkin_lateness(self):
        for minute in (0, 10, 11, 59):
            at=timezone.make_aware(datetime.combine(timezone.localdate(),time(17,minute)),ZoneInfo("Africa/Lagos"))
            token,_=self.token_at("evening",at)
            user=User.objects.create_user(username=f"checkout-{minute}",password="correct-horse-battery-staple",first_name="Checkout",role=User.Role.STUDENT,assigned_campus=self.campus)
            student=Student.objects.create(user=user,campus=self.campus)
            row=record_scan(student=student,token=token,latitude=6.5244,longitude=3.3792,accuracy=10,at=at)
            self.assertEqual(row.attendance_action,"check_out")
            self.assertEqual(row.status,AttendanceLog.Status.PRESENT)

    def test_eleven_minutes_past_morning_and_afternoon_cutoffs_is_late(self):
        for kind,hour in (("morning",9),("afternoon",13)):
            at=timezone.make_aware(datetime.combine(timezone.localdate(),time(hour,11)),ZoneInfo("Africa/Lagos"))
            token,_=self.token_at(kind,at)
            user=User.objects.create_user(username=f"late-{kind}",password="correct-horse-battery-staple",first_name="Late",role=User.Role.STUDENT,assigned_campus=self.campus)
            student=Student.objects.create(user=user,campus=self.campus)
            self.assertEqual(record_scan(student=student,token=token,latitude=6.5244,longitude=3.3792,accuracy=10,at=at).status,AttendanceLog.Status.LATE)

    def test_each_checkpoint_is_allowed_once_per_student_and_campus_date(self):
        at=timezone.make_aware(datetime(2026,11,18,9,5),ZoneInfo("Africa/Lagos")); token,_=self.token_at(at=at)
        record_scan(student=self.student,token=token,latitude=6.5244,longitude=3.3792,accuracy=10,at=at)
        afternoon=at.replace(hour=13,minute=5)
        token2,_=self.token_at("afternoon",at=afternoon)
        afternoon_row=record_scan(student=self.student,token=token2,latitude=6.5244,longitude=3.3792,accuracy=10,at=afternoon)
        self.assertEqual(afternoon_row.attendance_action,"check_in")
        evening=at.replace(hour=17,minute=5)
        token3,_=self.token_at("evening",at=evening)
        evening_row=record_scan(student=self.student,token=token3,latitude=6.5244,longitude=3.3792,accuracy=10,at=evening)
        self.assertEqual(evening_row.attendance_action,"check_out")
        self.assertEqual(AttendanceLog.objects.filter(student=self.student,attendance_date=at.date()).count(),3)
        duplicate_token,_=self.token_at("afternoon",at=afternoon)
        with self.assertRaises(FileExistsError):
            record_scan(student=self.student,token=duplicate_token,latitude=6.5244,longitude=3.3792,accuracy=10,at=afternoon)

    def test_outside_campus_location_is_denied(self):
        at=timezone.make_aware(datetime(2026,11,18,9,5),ZoneInfo("Africa/Lagos")); token,_=self.token_at(at=at)
        with self.assertRaises(PermissionError): record_scan(student=self.student,token=token,latitude=7.5,longitude=4.5,accuracy=5,at=at)

    def test_exact_qr_expiration_and_closed_session_are_rejected(self):
        at=timezone.make_aware(datetime.combine(timezone.localdate(),time(9,5)),ZoneInfo("Africa/Lagos")); token,_=self.token_at(at=at)
        with self.assertRaises(ValueError):
            from apps.core.services import verify_qr
            verify_qr(token,at=at+timedelta(seconds=30))
        run=SessionRun.objects.get(campus=self.campus,attendance_date=at.date(),session_type="morning"); run.state=SessionRun.State.CLOSED; run.save(update_fields=["state"])
        with self.assertRaises(ValueError): verify_qr(token,at=at)

    def test_wrong_signature_and_wrong_campus_are_rejected(self):
        from apps.core.services import verify_qr
        at=timezone.make_aware(datetime.combine(timezone.localdate(),time(9,5)),ZoneInfo("Africa/Lagos")); token,_=self.token_at(at=at)
        with self.assertRaises(ValueError): verify_qr(token+"tampered",at=at)
        other=Campus.objects.create(name="Other Campus",latitude=6.5244,longitude=3.3792)
        with self.assertRaises(ValueError): verify_qr(token,campus=other,at=at)

    def test_low_accuracy_fix_fails_closed(self):
        at=timezone.make_aware(datetime.combine(timezone.localdate(),time(9,5)),ZoneInfo("Africa/Lagos")); token,_=self.token_at(at=at)
        with self.assertRaises(PermissionError): record_scan(student=self.student,token=token,latitude=6.5244,longitude=3.3792,accuracy=101,at=at)

    def test_student_is_not_absent_at_lateness_cutoff(self):
        at=timezone.make_aware(datetime(2026,11,18,9,10),ZoneInfo("Africa/Lagos"))
        self.assertEqual(summary_for(self.campus,at.date(),at)["absent"],0)

    def test_student_becomes_absent_after_configured_session_close(self):
        at=timezone.make_aware(datetime.combine(timezone.localdate(),time(20,1)),ZoneInfo("Africa/Lagos"))
        self.assertEqual(summary_for(self.campus,at.date(),at)["absent"],1)

    def test_completed_sessions_use_the_campuses_timezone(self):
        self.campus.timezone="America/Los_Angeles"
        self.campus.save(update_fields=["timezone"])
        now=timezone.make_aware(datetime(2026,11,18,12,1),ZoneInfo("UTC"))
        self.assertEqual(attended_sessions(self.campus,now.date(),now),[])

    def test_attendance_percentage_requires_all_three_checkpoints(self):
        day=timezone.localdate()
        for session,action in (("morning","check_in"),("afternoon","check_in"),("evening","check_out")):
            AttendanceLog.objects.create(student=self.student,campus=self.campus,session_type=session,
                attendance_action=action,attendance_date=day,
                scanned_at=timezone.make_aware(datetime.combine(day,DEFAULT_SCHEDULES[session][0]),ZoneInfo("Africa/Lagos")),status=AttendanceLog.Status.PRESENT)
        now=timezone.make_aware(datetime.combine(day,time(20,1)),ZoneInfo("Africa/Lagos"))
        self.assertEqual(summary_for(self.campus,day,now)["attendance_percentage"],100.0)

    def test_evening_check_out_is_separate_and_missing_day_is_not_absent_before_checkin_windows_close(self):
        at=timezone.make_aware(datetime(2026,11,18,17,5),ZoneInfo("Africa/Lagos")); token,_=self.token_at("evening",at)
        row=record_scan(student=self.student,token=token,latitude=6.5244,longitude=3.3792,accuracy=10,at=at)
        self.assertEqual(row.attendance_action,"check_out")
        self.assertEqual(summary_for(self.campus,at.date(),at)["not_checked_out"],0)

    def test_missed_checkpoint_is_recorded_without_erasing_other_checkins(self):
        day=timezone.localdate()
        AttendanceLog.objects.create(student=self.student,campus=self.campus,session_type="morning",
            attendance_action="check_in",attendance_date=day,scanned_at=timezone.make_aware(datetime.combine(day,time(9,5)),ZoneInfo("Africa/Lagos")),status=AttendanceLog.Status.PRESENT)
        after_afternoon=timezone.make_aware(datetime.combine(day,time(16,1)),ZoneInfo("Africa/Lagos"))

        summary=summary_for(self.campus,day,after_afternoon)

        missed=AttendanceLog.objects.get(student=self.student,attendance_date=day,session_type="afternoon")
        self.assertEqual(missed.status,AttendanceLog.Status.ABSENT)
        self.assertEqual(missed.source,AttendanceLog.Source.SYSTEM)
        self.assertEqual(self.student.attendance_logs.filter(attendance_date=day).count(),2)
        self.assertEqual(summary["incomplete"],1)
        self.assertEqual(summary["absent"],0)

    def test_wholly_absent_student_gets_one_absence_per_closed_checkpoint(self):
        day=timezone.localdate()
        now=timezone.make_aware(datetime.combine(day,time(20,1)),ZoneInfo("Africa/Lagos"))

        summary=summary_for(self.campus,day,now)

        rows=list(self.student.attendance_logs.filter(attendance_date=day).order_by("session_type"))
        self.assertEqual(len(rows),3)
        self.assertTrue(all(row.status==AttendanceLog.Status.ABSENT for row in rows))
        self.assertEqual({row.attendance_action for row in rows},{"check_in","check_out"})
        self.assertEqual(summary["absent"],1)
        self.assertEqual(summary["attendance_percentage"],0.0)


class LegacyHasherTests(TestCase):
    def test_node_scrypt_hash_verifies_and_is_marked_for_upgrade(self):
        salt="ab12cd34ef56ab78cd90ef12ab34cd56"
        digest=scrypt(b"mentor-password",salt=salt.encode(),n=16384,r=8,p=1,dklen=64).hex()
        encoded=f"legacy_node_scrypt$16384$8$1${salt}${digest}"
        hasher=LegacyNodeScryptPasswordHasher()
        self.assertTrue(hasher.verify("mentor-password",encoded))
        self.assertFalse(hasher.verify("wrong-password",encoded))
        self.assertTrue(hasher.must_update(encoded))
