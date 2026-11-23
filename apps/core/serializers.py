from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import AttendanceLog, Campus, Cohort, SessionSchedule, Student, Track, User


class APIResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(required=False)
    code = serializers.CharField(required=False)
    message = serializers.CharField(required=False)
    data = serializers.JSONField(required=False)


class CampusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campus
        fields = ["id", "name", "address", "latitude", "longitude", "geofence_radius_m", "timezone", "contact_email", "contact_phone", "active", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_geofence_radius_m(self,value):
        if not 20<=value<=2000: raise serializers.ValidationError("Geofence radius must be between 20 and 2,000 metres.")
        return value

    def validate_timezone(self,value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try: ZoneInfo(value)
        except ZoneInfoNotFoundError: raise serializers.ValidationError("Use a valid IANA timezone, such as Africa/Lagos.")
        return value

    def validate(self, attrs):
        latitude = attrs.get("latitude", getattr(self.instance, "latitude", None))
        longitude = attrs.get("longitude", getattr(self.instance, "longitude", None))
        if (latitude is None) != (longitude is None):
            raise serializers.ValidationError({"latitude": "Set both latitude and longitude, or leave both blank."})
        if latitude is not None and not -90 <= latitude <= 90:
            raise serializers.ValidationError({"latitude": "Latitude must be between -90 and 90."})
        if longitude is not None and not -180 <= longitude <= 180:
            raise serializers.ValidationError({"longitude": "Longitude must be between -180 and 180."})
        return attrs


class ScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionSchedule
        fields = ["id", "campus", "session_type", "start_time", "late_after", "close_time", "active"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        start = attrs.get("start_time", getattr(self.instance, "start_time", None))
        last_on_time = attrs.get("late_after", getattr(self.instance, "late_after", None))
        close = attrs.get("close_time", getattr(self.instance, "close_time", None))
        if start is not None and last_on_time is not None and close is not None:
            if start >= close:
                raise serializers.ValidationError({"close_time": "Session close must be later than its start."})
            if not start <= last_on_time < close:
                raise serializers.ValidationError({"late_after": "The last on-time minute must be within the session window."})
        return attrs


class StudentSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    track_name = serializers.CharField(source="track.name", read_only=True)
    cohort_name = serializers.CharField(source="cohort.name", read_only=True)

    class Meta:
        model = Student
        fields = ["id", "student_code", "username", "full_name", "email", "campus", "track", "track_name", "cohort", "cohort_name", "registration_date", "active", "profile"]
        read_only_fields = ["id", "registration_date", "campus", "active", "username", "full_name", "email"]

    def validate(self, attrs):
        campus=self.instance.campus if self.instance else attrs.get("campus")
        if attrs.get("track") and attrs["track"].campus_id != campus.pk:
            raise serializers.ValidationError({"track":"Track must belong to the student's campus."})
        if attrs.get("cohort") and attrs["cohort"].campus_id != campus.pk:
            raise serializers.ValidationError({"cohort":"Cohort must belong to the student's campus."})
        return attrs


class AttendanceSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="student.user.username", read_only=True)
    full_name = serializers.CharField(source="student.user.full_name", read_only=True)
    student_id = serializers.UUIDField(source="student.id", read_only=True)
    campus_name = serializers.CharField(source="campus.name", read_only=True)
    scan_time_wat = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    record_kind = serializers.SerializerMethodField()

    def get_record_kind(self, obj) -> str:
        if obj.status == AttendanceLog.Status.ABSENT:
            if obj.location_result == "system_daily_absence":
                return "system_absence"
            return "manual_absence"
        return "attendance"

    class Meta:
        model = AttendanceLog
        fields = ["id", "full_name", "username", "student_id", "campus", "campus_name", "track_name", "cohort_name", "record_kind", "session_type", "attendance_action", "attendance_date", "scanned_at", "scan_time_wat", "status", "status_label", "source", "source_label", "location_verified", "location_accuracy_m", "location_distance_m"]


class StudentCreateSerializer(serializers.Serializer):
    username = serializers.CharField(min_length=2, max_length=64)
    password = serializers.CharField(min_length=12, write_only=True)
    full_name = serializers.CharField(min_length=2, max_length=120)
    email = serializers.EmailField(required=False, allow_blank=True)
    campus = serializers.UUIDField()
    track = serializers.UUIDField(required=False, allow_null=True)
    cohort = serializers.UUIDField(required=False, allow_null=True)
    student_code = serializers.CharField(required=False, allow_blank=True, max_length=32)

    def validate_username(self, value):
        normalized="".join(value.lower().split())
        if len(normalized)<2 or len(normalized)>40 or not __import__("re").fullmatch(r"[a-z0-9._-]+",normalized):
            raise serializers.ValidationError("Use 2–40 letters, numbers, dots, underscores or hyphens.")
        return normalized

    def validate(self, attrs):
        normalized=self.validate_username(attrs["username"])
        user=User(username=normalized,first_name=attrs["full_name"].strip().split(" ",1)[0])
        try: validate_password(attrs["password"],user=user)
        except DjangoValidationError as exc: raise serializers.ValidationError({"password":exc.messages})
        attrs["username"]=normalized
        return attrs
