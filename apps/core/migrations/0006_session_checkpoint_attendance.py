from django.db import migrations, models
from django.utils import timezone


def set_evening_checkout(apps, schema_editor):
    SessionRun = apps.get_model("core", "SessionRun")
    QRToken = apps.get_model("core", "QRToken")
    db = schema_editor.connection.alias

    # Existing signed QR payloads encode check_in. Revoke outstanding evening
    # QR tokens before changing the run action, then mentors can mint checkout QR.
    QRToken.objects.using(db).filter(
        session_run__session_type="evening", session_run__state="open", revoked_at__isnull=True
    ).update(revoked_at=timezone.now())
    SessionRun.objects.using(db).filter(
        session_type="evening", state="open", attendance_action="check_in"
    ).update(attendance_action="check_out")


class Migration(migrations.Migration):
    dependencies = [("core", "0005_automated_absence_source")]

    operations = [
        migrations.RunPython(set_evening_checkout, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="attendancelog",
            name="uniq_student_date_attendance",
        ),
        migrations.AddConstraint(
            model_name="attendancelog",
            constraint=models.UniqueConstraint(
                fields=("student", "attendance_date", "session_type"),
                name="uniq_student_date_session_attendance",
            ),
        ),
    ]
