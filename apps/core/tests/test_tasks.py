from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from celery.schedules import crontab
from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from apps.core.models import AttendanceLog, Campus, Student, User
from apps.core.tasks import close_daily_attendance


class DailyAbsenceTaskTests(TestCase):
    def setUp(self):
        self.lagos = Campus.objects.create(name="Lagos task campus", timezone="Africa/Lagos")
        self.los_angeles = Campus.objects.create(name="Los Angeles task campus", timezone="America/Los_Angeles")
        self.lagos_student = self.make_student("lagos-task-student", self.lagos)
        self.la_student = self.make_student("la-task-student", self.los_angeles)

    def make_student(self, username, campus):
        user = User.objects.create_user(username=username, password="a-long-test-password", role=User.Role.STUDENT)
        return Student.objects.create(user=user, campus=campus, registration_date=date(2026, 1, 1))

    def test_task_uses_each_campus_local_date_and_evening_close(self):
        # At 03:00 UTC Lagos is already on Nov 23, but Los Angeles is still
        # Nov 22 at 19:00, before its 20:00 evening close.
        now = timezone.make_aware(datetime(2026, 11, 23, 3, 0), ZoneInfo("UTC"))
        with patch("apps.core.tasks.timezone.now", return_value=now):
            result = close_daily_attendance.run()
            self.assertEqual(result["absences_recorded"], 2)
            self.assertEqual(
                list(AttendanceLog.objects.filter(campus=self.los_angeles).order_by("attendance_date").values_list("attendance_date", flat=True)),
                [date(2026, 11, 21)],
            )
            self.assertEqual(
                list(AttendanceLog.objects.filter(campus=self.lagos).order_by("attendance_date").values_list("attendance_date", flat=True)),
                [date(2026, 11, 22)],
            )

        # At 05:00 UTC Los Angeles is past its own close, while Lagos is not.
        now = timezone.make_aware(datetime(2026, 11, 23, 5, 0), ZoneInfo("UTC"))
        with patch("apps.core.tasks.timezone.now", return_value=now):
            result = close_daily_attendance.run()
        self.assertEqual(result["absences_recorded"], 1)
        self.assertEqual(
            list(AttendanceLog.objects.filter(campus=self.los_angeles).order_by("attendance_date").values_list("attendance_date", flat=True)),
            [date(2026, 11, 21), date(2026, 11, 22)],
        )
        self.assertFalse(AttendanceLog.objects.filter(campus=self.lagos, attendance_date=date(2026, 11, 23)).exists())

        # Re-running the task is idempotent; the unique student/date key keeps
        # the one daily record even when Beat invokes the task again.
        with patch("apps.core.tasks.timezone.now", return_value=now):
            self.assertEqual(close_daily_attendance.run()["absences_recorded"], 0)
        self.assertEqual(AttendanceLog.objects.count(), 3)

    def test_beat_runs_absence_checks_in_utc_and_month_close_daily(self):
        self.assertEqual(settings.CELERY_TIMEZONE, "UTC")
        daily = settings.CELERY_BEAT_SCHEDULE["daily-attendance-close"]
        monthly = settings.CELERY_BEAT_SCHEDULE["monthly-attendance-close"]
        self.assertEqual(daily["task"], "apps.core.tasks.close_daily_attendance")
        self.assertEqual(daily["schedule"].minute, {0, 15, 30, 45})
        self.assertEqual(monthly["task"], "apps.core.tasks.close_missed_months")
        self.assertIsInstance(monthly["schedule"], crontab)
        self.assertEqual(monthly["schedule"].hour, {1})
        self.assertEqual(monthly["schedule"].minute, {15})
