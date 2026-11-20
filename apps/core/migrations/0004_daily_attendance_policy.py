from django.db import migrations, models


def convert_daily_records(apps, schema_editor):
    AttendanceLog = apps.get_model("core", "AttendanceLog")
    # The earliest check-in is retained where a legacy system stored several
    # session records for one student/day. Deployments should back up first.
    seen = set()
    for row in AttendanceLog.objects.order_by("student_id", "attendance_date", "scanned_at", "created_at", "id"):
        key = (row.student_id, row.attendance_date)
        if key in seen:
            row.delete()
            continue
        seen.add(key)
        if row.status == "on_time":
            row.status = "present"
            row.save(update_fields=["status"])


class Migration(migrations.Migration):
    dependencies = [("core", "0003_alter_mentorcampusaccess_id_alter_sessionschedule_id")]

    operations = [
        migrations.RemoveConstraint(model_name="attendancelog", name="uniq_student_date_session_attendance"),
        migrations.RunPython(convert_daily_records, migrations.RunPython.noop),
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
