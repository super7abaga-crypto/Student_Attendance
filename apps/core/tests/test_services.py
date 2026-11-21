from datetime import datetime, time
from zoneinfo import ZoneInfo
from hashlib import scrypt
from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from unittest.mock import patch
from apps.core.hashers import LegacyNodeScryptPasswordHasher
from apps.core.models import AttendanceLog, Campus, SessionRun, SessionSchedule, Student, User
from apps.core.services import attended_sessions, mint_qr, record_scan, summary_for


@override_settings(QR_SIGNING_SECRET="test-secret-" + "x" * 48)
class AttendanceServiceTests(TestCase):
    def setUp(self):
        self.campus=Campus.objects.create(name="Lagos Campus",latitude=6.5244,longitude=3.3792,geofence_radius_m=500)
        self.student_user=User.objects.create_user(username="ada okafor",password="correct-horse-battery-staple",first_name="Ada",last_name="Okafor",role=User.Role.STUDENT,assigned_campus=self.campus)
        self.student=Student.objects.create(user=self.student_user,campus=self.campus)
        for kind,start,late,close in [("morning",time(9),time(9,10),time(12)),("afternoon",time(13),time(13,10),time(16)),("evening",time(17),time(17,10),time(20))]:
            SessionSchedule.objects.create(campus=self.campus,session_type=kind,start_time=start,late_after=late,close_time=close)

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

    def test_cutoffs_apply_to_all_three_sessions(self):
        for kind,hour in (("morning",9),("afternoon",13),("evening",17)):
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

    def test_eleven_minutes_past_each_cutoff_is_late(self):
        for kind,hour in (("morning",9),("afternoon",13),("evening",17)):
            at=timezone.make_aware(datetime.combine(timezone.localdate(),time(hour,11)),ZoneInfo("Africa/Lagos"))
            token,_=self.token_at(kind,at)
            user=User.objects.create_user(username=f"late-{kind}",password="correct-horse-battery-staple",first_name="Late",role=User.Role.STUDENT,assigned_campus=self.campus)
            student=Student.objects.create(user=user,campus=self.campus)
            self.assertEqual(record_scan(student=student,token=token,latitude=6.5244,longitude=3.3792,accuracy=10,at=at).status,AttendanceLog.Status.LATE)

    def test_duplicate_has_database_level_conflict(self):
        at=timezone.make_aware(datetime(2026,11,18,9,5),ZoneInfo("Africa/Lagos")); token,_=self.token_at(at=at)
        record_scan(student=self.student,token=token,latitude=6.5244,longitude=3.3792,accuracy=10,at=at)
        token2,_=self.token_at("afternoon",at=at.replace(hour=13,minute=5))
        with self.assertRaises(FileExistsError): record_scan(student=self.student,token=token2,latitude=6.5244,longitude=3.3792,accuracy=10,at=at.replace(hour=13,minute=5))

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

    def test_attendance_percentage_uses_one_daily_record(self):
        day=timezone.localdate()
        AttendanceLog.objects.create(student=self.student,campus=self.campus,session_type="morning",
            attendance_action="check_in",attendance_date=day,
            scanned_at=timezone.make_aware(datetime.combine(day,time(9,5)),ZoneInfo("Africa/Lagos")),status=AttendanceLog.Status.PRESENT)
        now=timezone.make_aware(datetime.combine(day,time(20,1)),ZoneInfo("Africa/Lagos"))
        self.assertEqual(summary_for(self.campus,day,now)["attendance_percentage"],100.0)

    def test_evening_check_in_is_daily_attendance_and_missing_attendance_is_not_absence_before_close(self):
        at=timezone.make_aware(datetime(2026,11,18,17,5),ZoneInfo("Africa/Lagos")); token,_=self.token_at("evening",at)
        row=record_scan(student=self.student,token=token,latitude=6.5244,longitude=3.3792,accuracy=10,at=at)
        self.assertEqual(row.attendance_action,"check_in")
        self.assertEqual(summary_for(self.campus,at.date(),at)["not_checked_out"],0)


class LegacyHasherTests(TestCase):
    def test_node_scrypt_hash_verifies_and_is_marked_for_upgrade(self):
        salt="ab12cd34ef56ab78cd90ef12ab34cd56"
        digest=scrypt(b"mentor-password",salt=salt.encode(),n=16384,r=8,p=1,dklen=64).hex()
        encoded=f"legacy_node_scrypt$16384$8$1${salt}${digest}"
        hasher=LegacyNodeScryptPasswordHasher()
        self.assertTrue(hasher.verify("mentor-password",encoded))
        self.assertFalse(hasher.verify("wrong-password",encoded))
        self.assertTrue(hasher.must_update(encoded))
