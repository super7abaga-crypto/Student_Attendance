from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time
from threading import Barrier
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.core.models import AttendanceLog, Campus, SessionRun, SessionSchedule, Student, User
from apps.core.services import mint_qr, record_scan


@override_settings(QR_SIGNING_SECRET="concurrency-test-secret-" + "x" * 48)
class ConcurrentAttendanceScanTests(TransactionTestCase):
    """Exercise per-checkpoint uniqueness with genuinely separate DB sessions."""

    def test_simultaneous_scans_create_one_row_for_the_same_checkpoint(self):
        if connection.vendor != "postgresql":
            self.skipTest("Concurrent insert behavior is exercised on PostgreSQL; SQLite locking differs.")

        campus = Campus.objects.create(name="Concurrent campus", latitude=6.5244, longitude=3.3792)
        SessionSchedule.objects.create(campus=campus, session_type="morning", start_time=time(9), late_after=time(9, 10), close_time=time(12))
        user = User.objects.create_user(username="concurrent-student", password="a-long-test-password",
            role=User.Role.STUDENT, assigned_campus=campus)
        student = Student.objects.create(user=user, campus=campus, registration_date=date(2026, 1, 1))
        at = timezone.make_aware(datetime(2026, 11, 18, 9, 5), ZoneInfo("Africa/Lagos"))
        run = SessionRun.objects.create(campus=campus, attendance_date=at.date(), session_type="morning",
            attendance_action="check_in", started_by=user)
        with patch("apps.core.services.timezone.now", return_value=at):
            token = mint_qr(run)["token"]

        barrier = Barrier(2)

        def scan_once():
            close_old_connections()
            try:
                student_row = Student.objects.get(pk=student.pk)
                barrier.wait(timeout=10)
                try:
                    record_scan(student=student_row, token=token, latitude=6.5244, longitude=3.3792, accuracy=10, at=at)
                    return "created"
                except FileExistsError:
                    return "duplicate"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _index: scan_once(), range(2)))

        self.assertCountEqual(outcomes, ["created", "duplicate"])
        self.assertEqual(AttendanceLog.objects.filter(student=student, attendance_date=at.date(), session_type="morning").count(), 1)
