import csv
import hashlib
import io
import json
import math
import secrets
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.conf import settings
from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone
from .models import (AttendanceAdjustment, AttendanceLog, AuditLog, Campus, MonthlyReport,
                     QRToken, SessionRun, SessionSchedule, Student, User)

DEFAULT_SCHEDULES = {
    "morning": (time(9, 0), time(9, 10), time(12, 0), "check_in"),
    "afternoon": (time(13, 0), time(13, 10), time(16, 0), "check_in"),
    "evening": (time(17, 0), time(17, 10), time(20, 0), "check_in"),
}
LOCATION_DENIED = "Attendance denied. You must be physically present within your assigned Learn2Earn campus to scan."
QR_SALT = "learn2earn.attendance.qr.v1"


class QRValidationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ScanLocationError(PermissionError):
    def __init__(self, code, message=LOCATION_DENIED, *, result="", accuracy=None, distance=None, session_type=None):
        super().__init__(message)
        self.code = code
        self.result = result
        self.accuracy = accuracy
        self.distance = distance
        self.session_type = session_type


def audit(actor, action, *, campus=None, obj=None, details=None, reason="", request=None):
    ip = request.META.get("REMOTE_ADDR") if request else None
    return AuditLog.objects.create(actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action, campus=campus, object_type=obj.__class__.__name__ if obj else "",
        object_id=str(obj.pk) if obj else "", details=details or {}, reason=reason, ip_address=ip)


def schedule_for(campus, session_type):
    start, late, close, _action = DEFAULT_SCHEDULES[session_type]
    row, _ = SessionSchedule.objects.get_or_create(campus=campus, session_type=session_type,
        defaults={"start_time": start, "late_after": late, "close_time": close})
    return row


def status_for_attendance_time(schedule, local_now):
    """Keep the configured cutoff minute on time; lateness starts next minute.

    For example, a ``late_after`` value of 09:10 means scans through
    09:10:59.999999 are present and scans from 09:11:00 are late.
    """
    scan_time = local_now.replace(tzinfo=None)
    late_starts_at = datetime.combine(scan_time.date(), schedule.late_after) + timedelta(minutes=1)
    return AttendanceLog.Status.PRESENT if scan_time < late_starts_at else AttendanceLog.Status.LATE


def user_can_access(user, campus, *, manage=False, correct=False):
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or user.role == User.Role.SUPER_ADMIN:
        return True
    if user.assigned_campus_id == campus.pk and user.role == User.Role.CAMPUS_ADMIN:
        return True
    access = user.campus_access.filter(campus=campus)
    if manage:
        return access.filter(can_manage_students=True).exists()
    if correct:
        return access.filter(can_correct_attendance=True).exists()
    return access.exists()


def accessible_campuses(user):
    if user.is_superuser or user.role == User.Role.SUPER_ADMIN:
        return Campus.objects.filter(active=True)
    ids = set(user.campus_access.values_list("campus_id", flat=True))
    if user.assigned_campus_id:
        ids.add(user.assigned_campus_id)
    return Campus.objects.filter(active=True, pk__in=ids)


def user_can_export(user, campus):
    if not user_can_access(user,campus): return False
    if user.is_superuser or user.role in (User.Role.SUPER_ADMIN,User.Role.CAMPUS_ADMIN): return True
    return user.campus_access.filter(campus=campus,can_export=True).exists()


def haversine_m(lat1, lon1, lat2, lon2):
    radius = 6_371_000
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1)); dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def verify_location(campus, latitude, longitude, accuracy):
    if campus.latitude is None or campus.longitude is None:
        return False, None, "campus_location_unconfigured"
    try:
        lat, lon, acc = Decimal(str(latitude)), Decimal(str(longitude)), float(accuracy)
    except Exception:
        return False, None, "location_unavailable"
    if not (-90 <= lat <= 90 and -180 <= lon <= 180 and math.isfinite(acc) and acc >= 0):
        return False, None, "invalid_location"
    max_accuracy = float(getattr(settings, "MAX_LOCATION_ACCURACY_M", 100))
    if acc > max_accuracy:
        return False, None, "accuracy_too_low"
    distance = haversine_m(lat, lon, campus.latitude, campus.longitude)
    inside = distance + acc <= campus.geofence_radius_m
    return inside, distance, "inside_geofence" if inside else "outside_geofence"


def mint_qr(session_run):
    if not settings.QR_SIGNING_SECRET or len(settings.QR_SIGNING_SECRET) < 32:
        raise RuntimeError("Configure ATTENDANCE_SECRET with a random secret of at least 32 characters.")
    now = timezone.now(); expiry = now + timedelta(seconds=30)
    nonce = secrets.token_urlsafe(18); jti = str(uuid.uuid4())
    action = DEFAULT_SCHEDULES[session_run.session_type][3]
    payload = {"version": 1, "jti": jti, "campus_id": str(session_run.campus_id),
        "session_type": session_run.session_type, "attendance_action": action,
        "session_run_id": str(session_run.pk), "iat": int(now.timestamp()), "exp": int(expiry.timestamp()), "nonce": nonce}
    signed = signing.dumps(payload, key=settings.QR_SIGNING_SECRET, salt=QR_SALT, compress=True)
    QRToken.objects.create(id=jti, session_run=session_run,
        nonce_hash=hashlib.sha256((jti + nonce).encode()).hexdigest(), issued_at=now, expires_at=expiry)
    return {"version": 1, "token": signed, "expires_at": int(expiry.timestamp())}


def verify_qr(token, *, campus=None, session_type=None, attendance_action=None, at=None):
    now = at or timezone.now()
    try:
        payload = signing.loads(token, key=settings.QR_SIGNING_SECRET, salt=QR_SALT, max_age=30)
    except signing.SignatureExpired as exc:
        raise QRValidationError("qr_expired", "QR token has expired.") from exc
    except (signing.BadSignature, TypeError, ValueError) as exc:
        raise QRValidationError("invalid_qr", "QR token is invalid.") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise QRValidationError("invalid_qr", "QR token is invalid.")
    try:
        expires_at = int(payload.get("exp", 0))
    except (TypeError, ValueError) as exc:
        raise QRValidationError("invalid_qr", "QR token is invalid.") from exc
    if expires_at <= int(now.timestamp()):
        raise QRValidationError("qr_expired", "QR token has expired.")
    try:
        run = SessionRun.objects.select_related("campus").get(pk=payload["session_run_id"], campus_id=payload["campus_id"])
        qr = QRToken.objects.get(pk=payload["jti"], session_run=run)
    except (KeyError, SessionRun.DoesNotExist, QRToken.DoesNotExist, ValueError) as exc:
        raise QRValidationError("session_inactive", "QR session is invalid or inactive.") from exc
    if run.state != SessionRun.State.OPEN or qr.revoked_at:
        raise QRValidationError("session_inactive", "QR session has ended.")
    if qr.expires_at <= now:
        raise QRValidationError("qr_expired", "QR token has expired.")
    expected_nonce_hash = hashlib.sha256((str(payload.get("jti", "")) + str(payload.get("nonce", ""))).encode()).hexdigest()
    if not secrets.compare_digest(qr.nonce_hash, expected_nonce_hash):
        raise QRValidationError("invalid_qr", "QR token nonce is invalid.")
    if campus and run.campus_id != campus.pk:
        raise QRValidationError("wrong_campus", "QR code belongs to a different campus.")
    if session_type and run.session_type != session_type:
        raise QRValidationError("session_inactive", "QR code belongs to a different session.")
    expected_action = DEFAULT_SCHEDULES[run.session_type][3]
    if payload.get("attendance_action") != expected_action or (attendance_action and expected_action != attendance_action):
        raise QRValidationError("invalid_qr", "QR attendance action does not match the session.")
    if not run.campus.active:
        raise QRValidationError("session_inactive", "Campus is inactive.")
    schedule = schedule_for(run.campus, run.session_type)
    local_now = timezone.localtime(now, timezone=ZoneInfo(run.campus.timezone))
    local_time = local_now.timetz().replace(tzinfo=None)
    if local_time < schedule.start_time or local_time >= schedule.close_time:
        raise QRValidationError("session_inactive", "Attendance session is outside its scheduled time window.")
    return run, payload


@transaction.atomic
def record_scan(*, student, token, latitude, longitude, accuracy, at=None, request=None):
    now = at or timezone.now()
    if not student.active or not student.user.is_active or not student.user.active_student:
        raise PermissionError("This student account is inactive.")
    run, payload = verify_qr(token, campus=student.campus, at=now)
    inside, distance, location_result = verify_location(student.campus, latitude, longitude, accuracy)
    if not inside:
        code = {
            "accuracy_too_low": "gps_accuracy",
            "outside_geofence": "wrong_campus",
            "campus_location_unconfigured": "location_unconfigured",
        }.get(location_result, "gps_required")
        raise ScanLocationError(code,result=location_result,accuracy=accuracy,distance=distance,session_type=run.session_type)
    schedule = schedule_for(student.campus, run.session_type)
    local_now = timezone.localtime(now, timezone=ZoneInfo(student.campus.timezone))
    status = status_for_attendance_time(schedule, local_now)
    try:
        with transaction.atomic():
            log = AttendanceLog.objects.create(student=student, campus=student.campus,
                track_name=student.track.name if student.track_id else "", cohort_name=student.cohort.name if student.cohort_id else "",
                session_type=run.session_type, attendance_action=payload["attendance_action"], attendance_date=local_now.date(),
                scanned_at=now, status=status, source=AttendanceLog.Source.QR, location_verified=True,
                latitude=latitude, longitude=longitude, location_accuracy_m=accuracy, location_distance_m=distance,
                location_checked_at=now, location_result=location_result, session_run=run)
    except IntegrityError as exc:
        raise FileExistsError("Attendance has already been recorded for today.") from exc
    audit(student.user, "attendance.scan", campus=student.campus, obj=log,
          details={"status": status, "session_type": run.session_type, "source": "qr"}, request=request)
    return log


def attendance_day_closed(campus, day, now=None):
    """A daily absence becomes final after the last approved attendance window."""
    now = now or timezone.now()
    local_now = timezone.localtime(now, timezone=ZoneInfo(campus.timezone))
    final_close = schedule_for(campus, "evening").close_time
    return day < local_now.date() or (day == local_now.date() and local_now.timetz().replace(tzinfo=None) >= final_close)


def materialize_absences(campus, day, now=None):
    """Persist one Absent record for enrolled students with no daily attendance."""
    if not attendance_day_closed(campus, day, now):
        return 0
    # Serialize concurrent task/API materialization for this campus. The
    # database uniqueness constraint remains the final protection against a
    # concurrent scan or writer inserting the same student's daily row.
    with transaction.atomic():
        campus = Campus.objects.select_for_update().get(pk=campus.pk)
        if not attendance_day_closed(campus, day, now):
            return 0
        return _materialize_absences_locked(campus, day)


def _materialize_absences_locked(campus, day):
    students = Student.objects.filter(campus=campus, active=True, user__is_active=True, registration_date__lte=day)
    existing = set(AttendanceLog.objects.filter(campus=campus, attendance_date=day).values_list("student_id", flat=True))
    missing = [student for student in students if student.pk not in existing]
    if not missing:
        return 0
    AttendanceLog.objects.bulk_create([
        AttendanceLog(student=student, campus=campus,
            track_name=student.track.name if student.track_id else "",
            cohort_name=student.cohort.name if student.cohort_id else "",
            session_type="evening", attendance_action="check_in", attendance_date=day,
            status=AttendanceLog.Status.ABSENT, source=AttendanceLog.Source.MANUAL,
            location_verified=False, location_result="system_daily_absence")
        for student in missing
    ], ignore_conflicts=True)
    return len(missing)


def attended_sessions(campus, day, now=None):
    # Compatibility field for the mentor response. Daily attendance has one close point.
    return ["daily"] if attendance_day_closed(campus, day, now) else []


def summary_for(campus, day, now=None):
    now = now or timezone.now(); materialize_absences(campus, day, now)
    students = Student.objects.filter(campus=campus, active=True, user__is_active=True, registration_date__lte=day)
    total = students.count(); closed = attendance_day_closed(campus, day, now)
    logs = AttendanceLog.objects.filter(campus=campus, attendance_date=day)
    present = logs.filter(status__in=[AttendanceLog.Status.PRESENT, AttendanceLog.Status.LATE]).count()
    late = logs.filter(status=AttendanceLog.Status.LATE).count()
    missed = logs.filter(status=AttendanceLog.Status.ABSENT).count()
    expected = total if closed else 0
    return {"active_students": total, "present": present, "late": late,
        "on_time": logs.filter(status=AttendanceLog.Status.PRESENT).count(),
        "absent": missed, "not_checked_out": 0,
        "attendance_percentage": round((present / expected) * 100, 1) if expected else None,
        "completed_sessions": ["daily"] if closed else [], "morning_check_ins": logs.filter(session_type="morning").exclude(status="absent").count(),
        "afternoon_check_ins": logs.filter(session_type="afternoon").exclude(status="absent").count(), "evening_check_outs": logs.filter(session_type="evening").exclude(status="absent").count()}


def csv_safe(value):
    text = str(value if value is not None else "")
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def report_for(campus, year, month, actor=None):
    start = datetime(year, month, 1, tzinfo=timezone.get_current_timezone())
    end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.get_current_timezone())
    day = start.date()
    while day < end.date():
        materialize_absences(campus, day)
        day += timedelta(days=1)
    logs = AttendanceLog.objects.filter(campus=campus, attendance_date__gte=start.date(), attendance_date__lt=end.date()).select_related("student__user").order_by("attendance_date", "student__user__username")
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["full_name", "username", "student_id", "campus", "track", "cohort", "session_type", "attendance_action", "attendance_date", "scan_time_wat", "status", "source", "location_verified"])
    rows = []
    for a in logs:
        row = {"full_name": a.student.user.full_name, "username": a.student.user.username,
            "student_id": str(a.student_id), "campus": campus.name, "track": a.track_name,
            "cohort": a.cohort_name, "session_type": a.session_type, "attendance_action": a.attendance_action,
            "attendance_date": a.attendance_date.isoformat(), "scan_time_wat": a.scan_time_wat,
            "status": a.get_status_display(), "source": a.get_source_display(), "location_verified": a.location_verified}
        rows.append(row); writer.writerow([csv_safe(v) for v in row.values()])
    summary = {"campus": campus.name, "year": year, "month": month, "records": len(rows)}
    existing=MonthlyReport.objects.filter(campus=campus,year=year,month=month).first()
    if existing and existing.closed:
        return existing, False
    return MonthlyReport.objects.update_or_create(campus=campus, year=year, month=month,
        defaults={"generated_by": actor, "generated_at": timezone.now(), "record_count": len(rows), "summary": summary,
                  "csv_content": output.getvalue(), "json_content": {"summary": summary, "attendance": rows}, "closed": True})


def close_months_through(year, month, actor=None, campus_ids=None):
    """Idempotently generate every missing month since each campus was created."""
    reports = []
    campuses = Campus.objects.filter(active=True)
    if campus_ids is not None:
        campuses = campuses.filter(pk__in=campus_ids)
    for campus in campuses:
        earliest = AttendanceLog.objects.filter(campus=campus).order_by("attendance_date").values_list("attendance_date", flat=True).first()
        current = earliest or campus.created_at.astimezone(ZoneInfo(campus.timezone)).date()
        y, m = current.year, current.month
        while (y, m) <= (year, month):
            report, created = report_for(campus, y, m, actor)
            reports.append((report, created))
            m += 1
            if m == 13: y, m = y + 1, 1
    return reports


@transaction.atomic
def manual_adjustment(*, attendance, actor, new_status, reason, request=None):
    can_correct = actor.is_superuser or actor.role == User.Role.SUPER_ADMIN or (
        actor.role == User.Role.CAMPUS_ADMIN and actor.assigned_campus_id == attendance.campus_id
    ) or user_can_access(actor, attendance.campus, correct=True)
    if not can_correct or not user_can_access(actor, attendance.campus):
        raise PermissionError("You do not have access to this campus.")
    if MonthlyReport.objects.filter(campus=attendance.campus,year=attendance.attendance_date.year,month=attendance.attendance_date.month,closed=True).exists():
        raise ValueError("This month's report is closed. An administrator must reopen it before correcting historical attendance.")
    if new_status not in AttendanceLog.Status.values or not reason.strip():
        raise ValueError("Choose a valid status and enter a reason.")
    old = attendance.status
    adjustment = AttendanceAdjustment.objects.create(attendance=attendance, student=attendance.student,
        campus=attendance.campus, mentor=actor, original_status=old, new_status=new_status, reason=reason.strip())
    attendance.status = new_status; attendance.source = AttendanceLog.Source.MANUAL; attendance.save(update_fields=["status", "source"])
    audit(actor, "attendance.manual_adjustment", campus=attendance.campus, obj=attendance,
          details={"adjustment_id": str(adjustment.pk), "original_status": old, "new_status": new_status}, reason=reason, request=request)
    return adjustment
