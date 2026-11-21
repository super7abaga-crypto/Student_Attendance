from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class DailyAttendanceMigrationTests(TransactionTestCase):
    """Exercise core.0004 against historical models and actual legacy rows."""

    migrate_from = ("core", "0003_alter_mentorcampusaccess_id_alter_sessionschedule_id")
    migrate_to = ("core", "0004_daily_attendance_policy")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        self.old_apps = executor.loader.project_state([self.migrate_from]).apps

    def tearDown(self):
        # Leave the test database at its normal leaf migration state for the
        # remaining test cases and Django's final database teardown.
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def create_legacy_rows(self, *, duplicate=False):
        Campus = self.old_apps.get_model("core", "Campus")
        User = self.old_apps.get_model("core", "User")
        Student = self.old_apps.get_model("core", "Student")
        AttendanceLog = self.old_apps.get_model("core", "AttendanceLog")
        AttendanceAdjustment = self.old_apps.get_model("core", "AttendanceAdjustment")

        campus = Campus.objects.create(name="Migration Test Campus")
        mentor = User.objects.create(username="migrationmentor", password="unused", role="mentor")
        user = User.objects.create(username="migrationstudent", password="unused", role="student")
        student = Student.objects.create(user=user, campus=campus)
        first = AttendanceLog.objects.create(
            student=student, campus=campus, session_type="morning",
            attendance_action="check_in", attendance_date=date(2026, 11, 20), status="on_time",
        )
        AttendanceAdjustment.objects.create(
            attendance=first, student=student, campus=campus, mentor=mentor,
            original_status="on_time", new_status="on_time", reason="legacy status fixture",
        )
        if duplicate:
            AttendanceLog.objects.create(
                student=student, campus=campus, session_type="afternoon",
                attendance_action="check_in", attendance_date=date(2026, 11, 20), status="late",
            )
        return student.pk

    def test_converts_all_historical_on_time_status_fields_and_retains_rows(self):
        student_id = self.create_legacy_rows()

        MigrationExecutor(connection).migrate([self.migrate_to])
        new_apps = MigrationExecutor(connection).loader.project_state([self.migrate_to]).apps
        AttendanceLog = new_apps.get_model("core", "AttendanceLog")
        AttendanceAdjustment = new_apps.get_model("core", "AttendanceAdjustment")

        row = AttendanceLog.objects.get(student_id=student_id)
        adjustment = AttendanceAdjustment.objects.get(student_id=student_id)
        self.assertEqual(AttendanceLog.objects.filter(student_id=student_id).count(), 1)
        self.assertEqual(row.status, "present")
        self.assertEqual(row.session_type, "morning")
        self.assertEqual(adjustment.original_status, "present")
        self.assertEqual(adjustment.new_status, "present")

    def test_duplicate_student_date_aborts_without_deleting_rows(self):
        student_id = self.create_legacy_rows(duplicate=True)
        AttendanceLog = self.old_apps.get_model("core", "AttendanceLog")

        with self.assertRaisesRegex(RuntimeError, "legacy duplicate records exist"):
            MigrationExecutor(connection).migrate([self.migrate_to])

        self.assertEqual(AttendanceLog.objects.filter(student_id=student_id).count(), 2)
        # Remove only the test fixture conflict after asserting preservation so
        # tearDown can restore the database's latest migration state.
        AttendanceLog.objects.filter(student_id=student_id, session_type="afternoon").delete()
