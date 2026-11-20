from django.db import migrations, models
from django.db.models import Count


def validate_and_convert_daily_records(apps, schema_editor):
    AttendanceLog = apps.get_model("core", "AttendanceLog")
    duplicates = AttendanceLog.objects.values("student_id", "attendance_date").annotate(count=Count("id")).filter(count__gt=1)
    if duplicates.exists():
        raise RuntimeError(
            "Daily attendance migration stopped because legacy duplicate records exist. "
            "Run the documented preflight query, back up the database, and approve a data-cleanup plan before retrying."
        )
    AttendanceLog.objects.filter(status="on_time").update(status="present")


class Migration(migrations.Migration):
    dependencies = [("core", "0003_alter_mentorcampusaccess_id_alter_sessionschedule_id")]

    operations = [
        migrations.RemoveConstraint(model_name="attendancelog", name="uniq_student_date_session_attendance"),
        migrations.RunPython(validate_and_convert_daily_records, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="attendancelog",
            name="status",
            field=models.CharField(choices=[("present", "Present"), ("late", "Late"), ("absent", "Absent")], max_length=12),
        ),
        migrations.AlterField(
            model_name="attendanceadjustment",
            name="original_status",
            field=models.CharField(choices=[("present", "Present"), ("late", "Late"), ("absent", "Absent")], max_length=12),
        ),
        migrations.AlterField(
            model_name="attendanceadjustment",
            name="new_status",
            field=models.CharField(choices=[("present", "Present"), ("late", "Late"), ("absent", "Absent")], max_length=12),
        ),
        migrations.AddConstraint(
            model_name="attendancelog",
            constraint=models.UniqueConstraint(fields=("student", "attendance_date"), name="uniq_student_date_attendance"),
        ),
        migrations.RemoveIndex(model_name="attendancelog", name="core_attend_campus__345310_idx"),
        migrations.AddIndex(model_name="attendancelog", index=models.Index(fields=["campus", "attendance_date"], name="core_attend_campus__19d01d_idx")),
    ]
