import uuid
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Campus(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    address = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    geofence_radius_m = models.PositiveIntegerField(default=150)
    timezone = models.CharField(max_length=64, default="Africa/Lagos")
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, TypeError):
            raise ValidationError({"timezone": "Use a valid IANA timezone, such as Africa/Lagos."})
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError({"latitude": "Set both latitude and longitude, or leave both blank."})
        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise ValidationError({"latitude": "Latitude must be between -90 and 90."})
        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValidationError({"longitude": "Longitude must be between -180 and 180."})
        if self.geofence_radius_m is not None and not 20 <= self.geofence_radius_m <= 2000:
            raise ValidationError({"geofence_radius_m": "Geofence radius must be between 20 and 2,000 metres."})

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["active", "name"])]

    def __str__(self):
        return self.name


class Track(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campus = models.ForeignKey(Campus, on_delete=models.PROTECT, related_name="tracks")
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campus", "name"], name="uniq_track_per_campus")]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Cohort(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campus = models.ForeignKey(Campus, on_delete=models.PROTECT, related_name="cohorts")
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campus", "name"], name="uniq_cohort_per_campus")]
        ordering = ["name"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Administrator"
        CAMPUS_ADMIN = "campus_admin", "Campus Administrator"
        MENTOR = "mentor", "Mentor"
        OFFICER = "attendance_officer", "Attendance Officer"
        STUDENT = "student", "Student"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(blank=True, db_index=True)
    display_name = models.CharField(max_length=120, blank=True)
    role = models.CharField(max_length=24, choices=Role.choices, default=Role.MENTOR, db_index=True)
    assigned_campus = models.ForeignKey(Campus, null=True, blank=True, on_delete=models.PROTECT, related_name="assigned_users")
    active_student = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        self.username = "".join((self.username or "").lower().split())
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        return self.get_full_name() or self.display_name or self.username


class Student(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.PROTECT, related_name="student_profile")
    campus = models.ForeignKey(Campus, on_delete=models.PROTECT, related_name="students")
    track = models.ForeignKey(Track, null=True, blank=True, on_delete=models.PROTECT, related_name="students")
    cohort = models.ForeignKey(Cohort, null=True, blank=True, on_delete=models.PROTECT, related_name="students")
    registration_date = models.DateField(default=timezone.localdate)
    active = models.BooleanField(default=True)
    student_code = models.CharField(max_length=32, blank=True, db_index=True)
    profile = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["campus", "active"])]

    def __str__(self):
        return self.user.full_name


class MentorCampusAccess(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="campus_access")
    campus = models.ForeignKey(Campus, on_delete=models.CASCADE, related_name="user_access")
    can_manage_students = models.BooleanField(default=False)
    can_correct_attendance = models.BooleanField(default=False)
    can_export = models.BooleanField(default=True)
    granted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="granted_access")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "campus"], name="uniq_user_campus_access")]


class CampusTransfer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="transfers")
    from_campus = models.ForeignKey(Campus, null=True, on_delete=models.PROTECT, related_name="transfers_from")
    to_campus = models.ForeignKey(Campus, on_delete=models.PROTECT, related_name="transfers_to")
    approved_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="approved_transfers")
    reason = models.TextField()
    effective_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)


class SessionSchedule(models.Model):
    class SessionType(models.TextChoices):
        MORNING = "morning", "Morning"
        AFTERNOON = "afternoon", "Afternoon"
        EVENING = "evening", "Evening"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campus = models.ForeignKey(Campus, on_delete=models.CASCADE, related_name="schedules")
    session_type = models.CharField(max_length=12, choices=SessionType.choices)
    start_time = models.TimeField()
    late_after = models.TimeField()
    close_time = models.TimeField()
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campus", "session_type"], name="uniq_schedule_campus_session")]

    def clean(self):
        super().clean()
        if self.start_time is None or self.late_after is None or self.close_time is None:
            return
        if self.start_time >= self.close_time:
            raise ValidationError({"close_time": "Session close must be later than its start."})
        if not self.start_time <= self.late_after < self.close_time:
            raise ValidationError({"late_after": "The last on-time minute must be within the session window."})


class SessionRun(models.Model):
    class State(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campus = models.ForeignKey(Campus, on_delete=models.PROTECT, related_name="session_runs")
    attendance_date = models.DateField(default=timezone.localdate)
    session_type = models.CharField(max_length=12, choices=SessionSchedule.SessionType.choices)
    attendance_action = models.CharField(max_length=12, choices=[("check_in", "Check-in"), ("check_out", "Check-out")])
    state = models.CharField(max_length=8, choices=State.choices, default=State.OPEN)
    started_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="started_sessions")
    started_at = models.DateTimeField(default=timezone.now)
    ended_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="ended_sessions")
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campus", "attendance_date", "session_type"], name="uniq_campus_day_session")]
        indexes = [models.Index(fields=["campus", "attendance_date", "state"])]


class QRToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_run = models.ForeignKey(SessionRun, on_delete=models.CASCADE, related_name="qr_tokens")
    nonce_hash = models.CharField(max_length=64, unique=True)
    issued_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class AttendanceLog(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        LATE = "late", "Late"
        ABSENT = "absent", "Absent"

    class Source(models.TextChoices):
        QR = "qr", "QR Scan"
        MANUAL = "manual", "Manual"
        SYSTEM = "system", "Automated system"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="attendance_logs")
    campus = models.ForeignKey(Campus, on_delete=models.PROTECT, related_name="attendance_logs")
    track_name = models.CharField(max_length=100, blank=True)
    cohort_name = models.CharField(max_length=100, blank=True)
    session_type = models.CharField(max_length=12, choices=SessionSchedule.SessionType.choices)
    attendance_action = models.CharField(max_length=12, choices=[("check_in", "Check-in"), ("check_out", "Check-out")])
    attendance_date = models.DateField()
    scanned_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.QR)
    location_verified = models.BooleanField(default=False)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_accuracy_m = models.FloatField(null=True, blank=True)
    location_distance_m = models.FloatField(null=True, blank=True)
    location_checked_at = models.DateTimeField(null=True, blank=True)
    location_result = models.CharField(max_length=32, blank=True)
    session_run = models.ForeignKey(SessionRun, null=True, blank=True, on_delete=models.PROTECT, related_name="attendance")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["student", "attendance_date", "session_type"], name="uniq_student_date_session_attendance")]
        indexes = [models.Index(fields=["campus", "attendance_date"]), models.Index(fields=["campus", "status", "attendance_date"])]
        ordering = ["-scanned_at", "student__user__username"]

    @property
    def scan_time_wat(self):
        return timezone.localtime(self.scanned_at).strftime("%H:%M:%S") if self.scanned_at else "—"


class AttendanceAdjustment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attendance = models.ForeignKey(AttendanceLog, on_delete=models.PROTECT, related_name="adjustments")
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="attendance_adjustments")
    campus = models.ForeignKey(Campus, on_delete=models.PROTECT, related_name="attendance_adjustments")
    mentor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="attendance_adjustments")
    original_status = models.CharField(max_length=12, choices=AttendanceLog.Status.choices)
    new_status = models.CharField(max_length=12, choices=AttendanceLog.Status.choices)
    reason = models.TextField()
    location_override = models.BooleanField(default=False)
    original_location_result = models.CharField(max_length=64, blank=True)
    override_result = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class MonthlyReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campus = models.ForeignKey(Campus, on_delete=models.PROTECT, related_name="monthly_reports")
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    generated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="generated_reports")
    generated_at = models.DateTimeField(default=timezone.now)
    record_count = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict)
    csv_content = models.TextField(blank=True)
    json_content = models.JSONField(default=dict)
    closed = models.BooleanField(default=True)
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="reopened_reports")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campus", "year", "month"], name="uniq_monthly_report_campus_period")]
        ordering = ["-year", "-month"]


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events")
    action = models.CharField(max_length=64, db_index=True)
    object_type = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    campus = models.ForeignKey(Campus, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events")
    details = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
