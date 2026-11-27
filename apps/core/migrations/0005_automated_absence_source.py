from django.db import migrations, models


def mark_system_absences(apps, schema_editor):
    AttendanceLog = apps.get_model("core", "AttendanceLog")
    AttendanceLog.objects.filter(
        location_result="system_daily_absence", status="absent"
    ).update(source="system")


class Migration(migrations.Migration):
    dependencies = [("core", "0004_daily_attendance_policy")]

    operations = [
        migrations.RunPython(mark_system_absences, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="attendancelog",
            name="source",
            field=models.CharField(
                choices=[("qr", "QR Scan"), ("manual", "Manual"), ("system", "Automated system")],
                default="qr",
                max_length=8,
            ),
        ),
    ]
