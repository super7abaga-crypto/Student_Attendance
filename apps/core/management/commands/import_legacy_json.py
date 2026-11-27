import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from apps.core.models import AttendanceLog, Campus, Student, Track


class Command(BaseCommand):
    help = "Validate and import legacy data/attendance.json into Django. Source files are never changed or deleted."

    def add_arguments(self, parser):
        parser.add_argument("--source", default="data/attendance.json")
        parser.add_argument("--mentor-profile", default="data/mentor_profile.json")
        parser.add_argument("--campus-id", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        source=Path(options["source"]).resolve()
        try: data=json.loads(source.read_text(encoding="utf-8"))
        except Exception as exc: raise CommandError(f"Could not parse legacy JSON: {exc}")
        if not isinstance(data,dict) or not isinstance(data.get("students",[]),list) or not isinstance(data.get("attendance_logs",[]),list):
            raise CommandError("Expected object containing students and attendance_logs arrays.")
        try: campus=Campus.objects.get(pk=options["campus_id"])
        except Campus.DoesNotExist: raise CommandError("Campus was not found. Create it before importing legacy records.")
        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"Validated {len(data.get('students',[]))} students and {len(data.get('attendance_logs',[]))} attendance rows from {source}; no changes written.")); return
        User=get_user_model(); users_created=logs_created=duplicates=warnings=0
        with transaction.atomic():
            for item in data.get("students",[]):
                try:
                    username="".join(str(item["username"]).lower().split())
                    if not username or not str(item.get("full_name", "")).strip(): raise ValueError("username/full_name missing")
                    user,created=User.objects.get_or_create(username=username,defaults={"first_name":str(item["full_name"]).strip()[:150],"role":User.Role.STUDENT,"assigned_campus":campus,"active_student":True})
                    if created:
                        user.set_unusable_password(); user.save(update_fields=["password"]); users_created+=1
                        Student.objects.create(user=user,campus=campus,student_code=str(item.get("student_id", ""))[:32])
                    elif not hasattr(user,"student_profile"):
                        warnings+=1; self.stderr.write(f"Skipped roster username {username}: it is already used by a non-student account.")
                    track_name=str(item.get("track", "")).strip()
                    if track_name and hasattr(user,"student_profile") and not user.student_profile.track_id:
                        track,_=Track.objects.get_or_create(campus=campus,name=track_name)
                        user.student_profile.track=track; user.student_profile.save(update_fields=["track"])
                except Exception as exc:
                    warnings+=1; self.stderr.write(f"Skipped invalid student row: {exc}")
            for item in data.get("attendance_logs",[]):
                try:
                    username="".join(str(item["username"]).lower().split()); name=str(item.get("full_name", "")).strip()
                    if not username or not name: raise ValueError("username/full_name missing")
                    user,created=User.objects.get_or_create(username=username,defaults={"first_name":name[:150],"role":User.Role.STUDENT,"assigned_campus":campus,"active_student":False,"is_active":False})
                    if created:
                        user.set_unusable_password(); user.save(update_fields=["password"]); users_created+=1
                        student=Student.objects.create(user=user,campus=campus,active=False)
                    else:
                        student,created=Student.objects.get_or_create(user=user,defaults={"campus":campus,"active":False})
                    track_name=str(item.get("track", "")).strip(); track=None
                    if track_name: track,_=Track.objects.get_or_create(campus=campus,name=track_name)
                    day=datetime.strptime(item["scan_date"],"%Y-%m-%d").date()
                    scan_time=str(item.get("scan_time_wat", "00:00:00"))
                    try: naive=datetime.strptime(f"{day.isoformat()} {scan_time}","%Y-%m-%d %H:%M:%S")
                    except ValueError: naive=datetime.strptime(f"{day.isoformat()} {scan_time}","%Y-%m-%d %H:%M")
                    scanned=timezone.make_aware(naive,ZoneInfo(campus.timezone))
                    session=str(item.get("session_type", "" )).lower()
                    if session not in ("morning","afternoon","evening"): raise ValueError("invalid session_type")
                    status_map={"on time":AttendanceLog.Status.PRESENT,"on_time":AttendanceLog.Status.PRESENT,"present":AttendanceLog.Status.PRESENT,"late":AttendanceLog.Status.LATE,"absent":AttendanceLog.Status.ABSENT}
                    attendance_status=status_map.get(str(item.get("status","")).lower())
                    if not attendance_status: raise ValueError("invalid status")
                    if AttendanceLog.objects.filter(student=student,attendance_date=day,session_type=session).exists(): duplicates+=1; continue
                    AttendanceLog.objects.create(student=student,campus=campus,track_name=track.name if track else "",cohort_name="",session_type=session,attendance_action="check_in",attendance_date=day,scanned_at=scanned,status=attendance_status,source=AttendanceLog.Source.QR,location_verified=False,location_result="legacy_unverified")
                    logs_created+=1
                except Exception as exc:
                    warnings+=1; self.stderr.write(f"Skipped invalid attendance row: {exc}")
            profile_path=Path(options["mentor_profile"]).resolve()
            if profile_path.exists():
                try:
                    legacy=json.loads(profile_path.read_text(encoding="utf-8"))
                    username="legacy-mentor"
                    if not User.objects.filter(username=username).exists() and legacy.get("salt") and legacy.get("password_hash"):
                        user=User(username=username,first_name=str(legacy.get("display_name","Mentor"))[:150],display_name=str(legacy.get("display_name","Mentor"))[:120],role=User.Role.MENTOR,assigned_campus=campus,is_active=True)
                        user.password=f"legacy_node_scrypt$16384$8$1${legacy['salt']}${legacy['password_hash']}"; user.save()
                        from apps.core.models import MentorCampusAccess
                        MentorCampusAccess.objects.create(user=user,campus=campus,can_manage_students=False,can_correct_attendance=True,can_export=True)
                        self.stdout.write("Migrated the legacy mentor hash to a one-time Django-compatible verifier; first successful login upgrades it to Argon2.")
                except Exception as exc:
                    warnings+=1; self.stderr.write(f"Legacy mentor profile was preserved but could not be imported: {exc}")
        self.stdout.write(self.style.SUCCESS(f"Imported {users_created} student accounts and {logs_created} attendance rows; {duplicates} duplicates skipped; {warnings} invalid/colliding rows reported. Original JSON was preserved."))
