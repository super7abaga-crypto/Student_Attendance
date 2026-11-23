import csv
import json
import io
import qrcode
from datetime import date, datetime, timedelta
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.middleware.csrf import get_token
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status, viewsets
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied, ValidationError
from rest_framework.generics import ListCreateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated, SAFE_METHODS, BasePermission
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from .models import (AttendanceAdjustment, AttendanceLog, AuditLog, Campus, CampusTransfer,
                     Cohort, MonthlyReport, SessionRun, SessionSchedule, Student, Track, User, QRToken)
from .permissions import StaffRolePermission
from .serializers import (AttendanceSerializer, CampusSerializer, ScheduleSerializer,
                          StudentCreateSerializer, StudentSerializer, APIResponseSerializer)
from .services import (DEFAULT_SCHEDULES, accessible_campuses, attended_sessions, audit, csv_safe, manual_adjustment,
                       mint_qr, report_for, schedule_for, summary_for, user_can_access, user_can_export,
                       verify_qr, record_scan, QRValidationError, ScanLocationError, status_for_attendance_time)


def scoped_campus(user, campus_id, *, manage=False, correct=False):
    try:
        campus = Campus.objects.get(pk=campus_id, active=True)
    except (Campus.DoesNotExist, ValueError, TypeError):
        raise ValidationError({"campus_id": "Campus not found."})
    if not user_can_access(user, campus, manage=manage, correct=correct):
        raise PermissionDenied("You are not authorised for this campus.")
    return campus


class LoginThrottle(AnonRateThrottle):
    scope = "login"


class ScanThrottle(UserRateThrottle):
    scope = "scan"


class StudentLoginView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes = [AllowAny]; throttle_classes = [LoginThrottle]
    @extend_schema(request={"application/json": {"type": "object", "properties": {"username": {"type": "string"}, "password": {"type": "string"}}, "required": ["username", "password"]}})
    def post(self, request):
        username = "".join(str(request.data.get("username", "")).lower().split())
        user = authenticate(request=request, username=username, password=request.data.get("password", ""))
        if not user or not user.is_active or user.role != User.Role.STUDENT:
            return Response({"success": False, "code": "invalid_credentials", "message": "Username or password is incorrect."}, status=401)
        profile = getattr(user, "student_profile", None)
        if not profile or not profile.active:
            return Response({"success": False, "code": "student_inactive", "message": "Student account is inactive."}, status=403)
        token=Token.objects.filter(user=user).first()
        if token and token.created <= timezone.now()-timedelta(hours=12): token.delete(); token=None
        if token is None: token=Token.objects.create(user=user)
        audit(user, "student.login", campus=profile.campus, request=request)
        return Response({"success": True, "token": token.key, "student": {"id": str(profile.pk), "full_name": user.full_name, "username": user.username, "campus": str(profile.campus_id), "campus_name": profile.campus.name}})


class MentorLoginView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes = [AllowAny]; throttle_classes = [LoginThrottle]
    def post(self, request):
        username = "".join(str(request.data.get("username", "")).lower().split())
        user = authenticate(request=request, username=username, password=request.data.get("password", ""))
        allowed = {User.Role.SUPER_ADMIN, User.Role.CAMPUS_ADMIN, User.Role.MENTOR, User.Role.OFFICER}
        if not user or not user.is_active or (not user.is_superuser and user.role not in allowed):
            return Response({"success":False,"code":"invalid_credentials","message":"Username or password is incorrect."},status=401)
        request.session.cycle_key()
        login(request,user)
        audit(user,"mentor.login",campus=user.assigned_campus,request=request)
        return Response({"success":True,"csrf_token":get_token(request),"display_name":user.display_name or user.full_name,"role":user.role})


class LogoutView(APIView):
    serializer_class=APIResponseSerializer
    def post(self,request):
        if getattr(request,"auth",None) and isinstance(request.auth,Token):
            request.auth.delete()
        audit(request.user,"user.logout",campus=request.user.assigned_campus,request=request)
        logout(request)
        return Response({"success":True})


class MentorProfileView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def get(self,request):
        memberships=list(request.user.campus_access.values("campus_id","can_correct_attendance","can_manage_students","can_export"))
        return Response({"id":str(request.user.pk),"username":request.user.username,"display_name":request.user.display_name or request.user.full_name,"role":request.user.role,"email":request.user.email,"assigned_campus":str(request.user.assigned_campus_id) if request.user.assigned_campus_id else None,"campus_access":memberships})
    def patch(self,request):
        name=str(request.data.get("display_name",request.user.display_name)).strip()
        if len(name)<2 or len(name)>120: raise ValidationError({"display_name":"Enter a display name from 2 to 120 characters."})
        request.user.display_name=name
        if request.data.get("password"):
            password=str(request.data["password"])
            if len(password)<12: raise ValidationError({"password":"Password must contain at least 12 characters."})
            from django.contrib.auth.password_validation import validate_password
            from django.core.exceptions import ValidationError as DjangoValidationError
            try: validate_password(password,user=request.user)
            except DjangoValidationError as exc: raise ValidationError({"password":exc.messages})
            request.user.set_password(password)
        request.user.save()
        if request.data.get("password"):
            update_session_auth_hash(request,request.user)
        audit(request.user,"mentor.profile.update",campus=request.user.assigned_campus,request=request)
        return Response({"display_name":name})


class QRImageView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def get(self,request):
        token=request.query_params.get("token","")
        try:
            run,payload=verify_qr(token)
        except ValueError as exc:
            return Response({"success":False,"code":"invalid_qr","message":str(exc)},status=403)
        if not user_can_access(request.user,run.campus): raise PermissionDenied("You are not authorised for this campus.")
        outer={"version":1,"token":token,"expires_at":payload["exp"]}
        img=qrcode.make(json.dumps(outer,separators=(",",":")))
        stream=io.BytesIO(); img.save(stream,format="PNG")
        response=HttpResponse(stream.getvalue(),content_type="image/png"); response["Cache-Control"]="no-store"; response["X-Content-Type-Options"]="nosniff"
        return response


class StudentRegisterView(APIView):
    serializer_class=StudentCreateSerializer
    permission_classes = [IsAuthenticated, StaffRolePermission]
    def post(self, request):
        serializer = StudentCreateSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        data = serializer.validated_data; campus = scoped_campus(request.user, data["campus"])
        if not user_can_access(request.user, campus, manage=True):
            raise PermissionDenied("Student registration is not permitted.")
        username = data["username"]
        if User.objects.filter(username__iexact=username).exists():
            return Response({"success": False, "code": "username_taken", "message": "Attendance username is already registered."}, status=409)
        track = Track.objects.filter(pk=data.get("track"), campus=campus).first() if data.get("track") else None
        cohort = Cohort.objects.filter(pk=data.get("cohort"), campus=campus).first() if data.get("cohort") else None
        if data.get("track") and not track or data.get("cohort") and not cohort:
            raise ValidationError("Track or cohort does not belong to this campus.")
        names = data["full_name"].strip().split(" ", 1)
        try:
            with transaction.atomic():
                user = User.objects.create_user(username=username, password=data["password"], email=data.get("email", ""), first_name=names[0], last_name=names[1] if len(names)>1 else "", role=User.Role.STUDENT, assigned_campus=campus)
                student = Student.objects.create(user=user, campus=campus, track=track, cohort=cohort, student_code=data.get("student_code", ""))
                audit(request.user, "student.register", campus=campus, obj=student, request=request)
        except IntegrityError:
            return Response({"success": False, "code": "username_taken", "message": "Attendance username is already registered."}, status=409)
        return Response(StudentSerializer(student).data, status=201)


class StudentProfileView(APIView):
    serializer_class=StudentSerializer
    def get(self, request):
        try: student = request.user.student_profile
        except Student.DoesNotExist: raise PermissionDenied("Student account required.")
        if not student.active: raise PermissionDenied("Student account is inactive.")
        return Response(StudentSerializer(student).data)


class StudentHistoryView(APIView):
    serializer_class=AttendanceSerializer
    def get(self, request):
        try: student = request.user.student_profile
        except Student.DoesNotExist: raise PermissionDenied("Student account required.")
        rows = AttendanceLog.objects.filter(student=student).select_related("campus").order_by("-attendance_date", "-scanned_at")
        return Response(AttendanceSerializer(rows[:500], many=True).data)


class AttendanceScanView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes = [IsAuthenticated]; throttle_classes = [ScanThrottle]
    @extend_schema(request={"application/json": {"type":"object", "properties": {"qr_token":{"type":"string"},"qr_payload":{"type":"string"},"latitude":{"type":"number"},"longitude":{"type":"number"},"accuracy":{"type":"number"}}, "required":["latitude","longitude","accuracy"]}})
    def post(self, request):
        if request.user.role != User.Role.STUDENT:
            return Response({"success": False, "code": "student_auth_required", "message": "Student authentication required."}, status=403)
        try: student = request.user.student_profile
        except Student.DoesNotExist: return Response({"success": False,"code":"student_not_found","message":"Student profile not found."},status=404)
        raw_qr = request.data.get("qr_token", request.data.get("qr_payload"))
        if not raw_qr:
            return Response({"success":False,"code":"invalid_qr","message":"QR payload is required."},status=400)
        if not all(k in request.data for k in ("latitude", "longitude", "accuracy")):
            return Response({"success":False,"code":"gps_required","message":"A fresh location and accuracy are required to scan."},status=400)
        token = raw_qr
        if isinstance(raw_qr, dict):
            token = raw_qr.get("token")
        elif isinstance(raw_qr, str) and raw_qr.lstrip().startswith("{"):
            try:
                envelope = json.loads(raw_qr)
                token = envelope.get("token") if isinstance(envelope, dict) and envelope.get("version") == 1 else None
            except (TypeError, ValueError):
                token = None
        if not isinstance(token, str) or not token:
            return Response({"success":False,"code":"invalid_qr","message":"QR payload is malformed or unsupported."},status=400)
        try:
            log = record_scan(student=student, token=token, latitude=request.data["latitude"], longitude=request.data["longitude"], accuracy=request.data["accuracy"], request=request)
        except FileExistsError as exc:
            audit(request.user, "attendance.duplicate_scan", campus=student.campus, obj=student, request=request)
            existing=AttendanceLog.objects.filter(student=student,attendance_date=getattr(exc,"attendance_date",None),session_type=getattr(exc,"session_type",None)).first()
            body={"success":False,"code":"duplicate_attendance","message":str(exc)}
            if existing: body["attendance"]=AttendanceSerializer(existing).data
            return Response(body,status=409)
        except ScanLocationError as exc:
            audit(request.user, "attendance.location_rejected", campus=student.campus, obj=student,
                  details={"result":exc.result,"accuracy_m":exc.accuracy,"distance_m":exc.distance,"session_type":exc.session_type},request=request)
            return Response({"success":False,"code":exc.code,"message":str(exc)},status=403)
        except PermissionError as exc:
            return Response({"success":False,"code":"student_inactive","message":str(exc)},status=403)
        except QRValidationError as exc:
            audit(request.user, "qr.validation_failed", campus=student.campus, obj=student, details={"error":str(exc), "code":exc.code}, request=request)
            return Response({"success":False,"code":exc.code,"message":str(exc)},status=403)
        except ValueError as exc:
            audit(request.user, "qr.validation_failed", campus=student.campus, obj=student, details={"error":str(exc)}, request=request)
            return Response({"success":False,"code":"invalid_qr","message":str(exc)},status=403)
        payload = AttendanceSerializer(log).data
        return Response({"success":True,"attendance":payload},status=201)


class CampusViewSet(viewsets.ModelViewSet):
    serializer_class = CampusSerializer
    queryset = Campus.objects.none()
    permission_classes = [IsAuthenticated, StaffRolePermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    def get_permissions(self):
        if self.action in ("list", "retrieve", "schedules") and self.request.method == "GET":
            return [IsAuthenticated(), StaffRolePermission()]
        return [IsAuthenticated(), StaffRolePermission()]
    def get_queryset(self):
        if getattr(self,"swagger_fake_view",False): return Campus.objects.none()
        return accessible_campuses(self.request.user)
    def create(self, request, *args, **kwargs):
        if not (request.user.is_superuser or request.user.role == User.Role.SUPER_ADMIN): raise PermissionDenied("Only a super administrator may create campuses.")
        return super().create(request, *args, **kwargs)
    @action(detail=False, methods=["post"], url_path="add-directory-campus")
    def add_directory_campus(self, request):
        if not (request.user.is_superuser or request.user.role == User.Role.SUPER_ADMIN):
            raise PermissionDenied("Only a super administrator may add directory campuses.")
        from .management.commands.seed_campuses import CAMPUS_DIRECTORY
        name = str(request.data.get("name", ""))
        selected = next((item for item in CAMPUS_DIRECTORY if item[0] == name), None)
        if not selected:
            raise ValidationError({"name": "Choose a campus from the official directory."})
        campus_name, region, address = selected
        campus, created = Campus.objects.get_or_create(
            name=campus_name,
            defaults={"address": f"{address}, {region}", "timezone": "Africa/Lagos", "active": True},
        )
        if not created and not campus.address:
            campus.address = f"{address}, {region}"
            campus.save(update_fields=["address"])
        if created:
            audit(request.user, "campus.create_from_directory", campus=campus, obj=campus, request=request)
        return Response({"campus": CampusSerializer(campus).data, "created": created}, status=201 if created else 200)
    def perform_create(self, serializer):
        campus=serializer.save(); audit(self.request.user,"campus.create",campus=campus,obj=campus,request=self.request)
    def perform_update(self, serializer):
        if self.request.user.role != User.Role.SUPER_ADMIN and not self.request.user.is_superuser:
            campus=self.get_object()
            if self.request.user.role != User.Role.CAMPUS_ADMIN or self.request.user.assigned_campus_id != campus.pk:
                raise PermissionDenied("Only a campus administrator or super administrator may edit this campus.")
        campus=serializer.save(); audit(self.request.user,"campus.update",campus=campus,obj=campus,request=self.request)
    @action(detail=True, methods=["get","post"], url_path="schedules")
    def schedules(self, request, pk=None):
        campus=self.get_object()
        if request.method == "GET":
            rows=[schedule_for(campus,s) for s in DEFAULT_SCHEDULES]
            return Response(ScheduleSerializer(rows,many=True).data)
        if request.user.role not in (User.Role.CAMPUS_ADMIN,User.Role.SUPER_ADMIN) and not request.user.is_superuser: raise PermissionDenied("Only campus administrators may change session schedules.")
        if request.user.role == User.Role.CAMPUS_ADMIN and request.user.assigned_campus_id != campus.pk:
            raise PermissionDenied("Campus administrators may only change schedules for their assigned campus.")
        serializer=ScheduleSerializer(data={**request.data,"campus":campus.pk}); serializer.is_valid(raise_exception=True)
        row,_=SessionSchedule.objects.update_or_create(campus=campus,session_type=serializer.validated_data["session_type"],defaults={k:v for k,v in serializer.validated_data.items() if k not in ("campus","session_type")})
        audit(request.user,"campus.schedule.update",campus=campus,obj=row,request=request)
        return Response(ScheduleSerializer(row).data)


class TrackListView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def get(self,request):
        campus=scoped_campus(request.user,request.query_params.get("campus_id"))
        return Response({"results":[{"id":str(t.pk),"name":t.name} for t in Track.objects.filter(campus=campus,active=True).order_by("name")]})


class MonthlyReportsView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def get(self,request):
        reports=MonthlyReport.objects.filter(campus__in=accessible_campuses(request.user)).select_related("campus")
        campus_id=request.query_params.get("campus_id")
        if campus_id: reports=reports.filter(campus_id=campus_id)
        return Response({"results":[{"id":str(r.pk),"campus":r.campus.name,"campus_id":str(r.campus_id),"year":r.year,"month":r.month,"record_count":r.record_count,"generated_at":r.generated_at,"closed":r.closed,"csv_url":f"/api/v1/admin/reports/{r.pk}/csv/"} for r in reports]})


class MonthlyReopenView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def post(self,request,report_id):
        try: report=MonthlyReport.objects.select_related("campus").get(pk=report_id)
        except MonthlyReport.DoesNotExist: return Response({"success":False,"code":"report_not_found","message":"Report not found."},status=404)
        if request.user.role not in (User.Role.CAMPUS_ADMIN,User.Role.SUPER_ADMIN) and not request.user.is_superuser: raise PermissionDenied("Only an administrator can reopen reports.")
        if request.user.role == User.Role.CAMPUS_ADMIN and request.user.assigned_campus_id != report.campus_id:
            raise PermissionDenied("Campus administrators may only reopen reports for their assigned campus.")
        if not user_can_access(request.user,report.campus): raise PermissionDenied("You are not authorised for this campus.")
        report.closed=False; report.reopened_at=timezone.now(); report.reopened_by=request.user; report.save(update_fields=["closed","reopened_at","reopened_by"])
        audit(request.user,"report.month.reopen",campus=report.campus,obj=report,reason=str(request.data.get("reason", "")),request=request)
        return Response({"success":True,"closed":False})


class StudentViewSet(viewsets.ModelViewSet):
    serializer_class = StudentSerializer
    queryset = Student.objects.none()
    permission_classes = [IsAuthenticated, StaffRolePermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    search_fields = ["user__username", "user__first_name", "user__last_name", "student_code"]
    filterset_fields = ["campus", "track", "cohort", "active"]
    ordering_fields = ["registration_date", "user__username"]
    def create(self,request,*args,**kwargs):
        raise MethodNotAllowed("POST",detail="Use the staff student registration endpoint.")
    def get_queryset(self):
        if getattr(self,"swagger_fake_view",False): return Student.objects.none()
        return Student.objects.filter(campus__in=accessible_campuses(self.request.user)).select_related("user","campus","track","cohort")
    def perform_update(self, serializer):
        student=self.get_object()
        if not user_can_access(self.request.user,student.campus,manage=True):
            raise PermissionDenied("Student management is not permitted for this campus.")
        student=serializer.save(); audit(self.request.user,"student.update",campus=student.campus,obj=student,request=self.request)
    @action(detail=True,methods=["post"])
    def deactivate(self,request,pk=None):
        student=self.get_object()
        if not user_can_access(request.user,student.campus,manage=True): raise PermissionDenied("Student management is not permitted for this campus.")
        student.active=False; student.user.active_student=False; student.user.is_active=False
        student.save(update_fields=["active"]); student.user.save(update_fields=["active_student","is_active"])
        audit(request.user,"student.deactivate",campus=student.campus,obj=student,request=request)
        return Response({"success":True})
    @action(detail=True,methods=["post"])
    def reactivate(self,request,pk=None):
        student=self.get_object()
        if not user_can_access(request.user,student.campus,manage=True): raise PermissionDenied("Student management is not permitted for this campus.")
        student.active=True; student.user.active_student=True; student.user.is_active=True
        student.save(update_fields=["active"]); student.user.save(update_fields=["active_student","is_active"])
        audit(request.user,"student.reactivate",campus=student.campus,obj=student,request=request)
        return Response({"success":True})
    @action(detail=True,methods=["post"])
    def transfer(self,request,pk=None):
        student=self.get_object()
        if not user_can_access(request.user,student.campus,manage=True): raise PermissionDenied("Student transfer is not permitted for the student's current campus.")
        destination=scoped_campus(request.user,request.data.get("campus_id"),manage=True)
        reason=str(request.data.get("reason","")).strip()
        if not reason: raise ValidationError({"reason":"A transfer reason is required."})
        old=student.campus
        with transaction.atomic():
            transfer=CampusTransfer.objects.create(student=student,from_campus=old,to_campus=destination,approved_by=request.user,reason=reason)
            student.campus=destination; student.user.assigned_campus=destination
            student.save(update_fields=["campus"]); student.user.save(update_fields=["assigned_campus"])
            audit(request.user,"student.campus.transfer",campus=destination,obj=transfer,reason=reason,details={"from":str(old.pk),"to":str(destination.pk)},request=request)
        return Response({"success":True,"transfer_id":str(transfer.pk),"campus":CampusSerializer(destination).data})
    @action(detail=False,methods=["get"])
    def export(self,request):
        campus_id=request.query_params.get("campus")
        if campus_id:
            campus=scoped_campus(request.user,campus_id)
            if not user_can_export(request.user,campus): raise PermissionDenied("Student CSV export is not permitted for this campus.")
        elif request.user.role==User.Role.OFFICER:
            raise PermissionDenied("Select a campus where CSV export is permitted.")
        elif request.user.role==User.Role.MENTOR:
            allowed_ids=list(MentorCampusAccess.objects.filter(user=request.user,can_export=True).values_list("campus_id",flat=True))
            if not allowed_ids: raise PermissionDenied("CSV export is not permitted for your campus assignments.")
            request._export_campus_ids=allowed_ids
        output=csv.writer(__import__("io").StringIO())
        import io
        buf=io.StringIO(); writer=csv.writer(buf); writer.writerow(["username","full_name","email","campus","track","cohort","student_code","active"])
        queryset=self.filter_queryset(self.get_queryset())
        if hasattr(request,"_export_campus_ids"):
            queryset=queryset.filter(campus_id__in=request._export_campus_ids)
        for student in queryset:
            writer.writerow([csv_safe(student.user.username),csv_safe(student.user.full_name),csv_safe(student.user.email),csv_safe(student.campus.name),csv_safe(student.track.name if student.track_id else ""),csv_safe(student.cohort.name if student.cohort_id else ""),csv_safe(student.student_code),student.active])
        response=HttpResponse(buf.getvalue(),content_type="text/csv; charset=utf-8"); response["Content-Disposition"]='attachment; filename="learn2earn-students.csv"'; response["X-Content-Type-Options"]="nosniff"
        audit(request.user,"student.csv.export",request=request); return response
    @action(detail=False,methods=["post"])
    def bulk_import(self,request):
        import io
        file=request.FILES.get("file")
        if not file or file.size>2*1024*1024: raise ValidationError({"file":"Upload a CSV file up to 2 MB."})
        try: rows=list(csv.DictReader(io.TextIOWrapper(file.file,encoding="utf-8-sig")))
        except Exception: raise ValidationError({"file":"CSV file could not be read as UTF-8."})
        if len(rows)>5000: raise ValidationError({"file":"Maximum import is 5,000 students per file."})
        created=[]; errors=[]
        for line,row in enumerate(rows,start=2):
            try:
                data={"username":row.get("username",""),"password":row.get("password",""),"full_name":row.get("full_name", ""),"email":row.get("email", ""),"campus":request.query_params.get("campus_id") or row.get("campus_id","")}
                serializer=StudentCreateSerializer(data=data); serializer.is_valid(raise_exception=True); val=serializer.validated_data
                campus=scoped_campus(request.user,val["campus"],manage=True); username="".join(val["username"].lower().split())
                if User.objects.filter(username__iexact=username).exists(): raise ValueError("username already exists")
                names=val["full_name"].strip().split(" ",1)
                with transaction.atomic():
                    user=User.objects.create_user(username=username,password=val["password"],email=val.get("email",""),first_name=names[0],last_name=names[1] if len(names)>1 else "",role=User.Role.STUDENT,assigned_campus=campus)
                    Student.objects.create(user=user,campus=campus,student_code=row.get("student_code", ""))
                created.append(username)
            except Exception as exc: errors.append({"line":line,"error":str(exc)[:250]})
        audit(request.user,"student.csv.import",details={"created":len(created),"errors":len(errors)},request=request)
        return Response({"created":len(created),"errors":errors})


class SessionStartView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def post(self,request):
        if request.user.role not in (User.Role.MENTOR,User.Role.CAMPUS_ADMIN,User.Role.SUPER_ADMIN) and not request.user.is_superuser: raise PermissionDenied("Only mentors and administrators can start sessions.")
        campus=scoped_campus(request.user,request.data.get("campus_id")); session=request.data.get("session_type")
        if session not in DEFAULT_SCHEDULES: raise ValidationError({"session_type":"Choose morning, afternoon or evening."})
        from zoneinfo import ZoneInfo
        schedule=schedule_for(campus,session); local_now=timezone.localtime(timezone.now(),timezone=ZoneInfo(campus.timezone))
        if not schedule.active or local_now.timetz().replace(tzinfo=None) < schedule.start_time or local_now.timetz().replace(tzinfo=None) >= schedule.close_time:
            raise ValidationError({"code":"outside_session_window","detail":"This attendance session is outside its configured open window."})
        run,created=SessionRun.objects.get_or_create(campus=campus,attendance_date=local_now.date(),session_type=session,
            defaults={"attendance_action":DEFAULT_SCHEDULES[session][3],"started_by":request.user})
        if not created and run.state == SessionRun.State.CLOSED: raise ValidationError({"code":"session_closed","detail":"This session has already been closed."})
        audit(request.user,"qr.session.start",campus=campus,obj=run,request=request)
        return Response({"session_id":str(run.pk),"campus":campus.name,"session_type":session,"attendance_action":run.attendance_action,"state":run.state},status=201 if created else 200)


class SessionCurrentQRView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def get(self,request):
        if request.user.role not in (User.Role.MENTOR,User.Role.CAMPUS_ADMIN,User.Role.SUPER_ADMIN) and not request.user.is_superuser: raise PermissionDenied("QR kiosk access is not permitted.")
        campus=scoped_campus(request.user,request.query_params.get("campus_id")); session=request.query_params.get("session_type")
        from zoneinfo import ZoneInfo
        local_now=timezone.localtime(timezone.now(),ZoneInfo(campus.timezone))
        run=SessionRun.objects.filter(campus=campus,attendance_date=local_now.date(),session_type=session,state=SessionRun.State.OPEN).first()
        if not run: return Response({"success":False,"code":"session_closed","message":"No active session."},status=409)
        schedule=schedule_for(campus,session); local=local_now.timetz().replace(tzinfo=None)
        if not schedule.active or local<schedule.start_time or local>=schedule.close_time:
            return Response({"success":False,"code":"outside_session_window","message":"This session is outside its configured open window."},status=409)
        qr=mint_qr(run); audit(request.user,"qr.generated",campus=campus,obj=run,request=request)
        return Response({**qr,"qr_payload":qr,"qr_image_url":f"/api/v1/mentor/qr/image/?token={qr['token']}","session_id":str(run.pk),"campus":campus.name,"campus_id":str(campus.pk),"session_type":session,"attendance_action":run.attendance_action,"state":"open","expires_in_seconds":30})


class SessionEndView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def post(self,request):
        if request.user.role not in (User.Role.MENTOR,User.Role.CAMPUS_ADMIN,User.Role.SUPER_ADMIN) and not request.user.is_superuser: raise PermissionDenied("Only mentors and administrators can end sessions.")
        with transaction.atomic():
            try: run=SessionRun.objects.select_for_update().select_related("campus").get(pk=request.data.get("session_id"))
            except (SessionRun.DoesNotExist,ValueError,TypeError): return Response({"success":False,"code":"session_not_found","message":"Session not found."},status=404)
            if not user_can_access(request.user,run.campus): raise PermissionDenied("You are not authorised for this campus.")
            run.state=SessionRun.State.CLOSED; run.ended_by=request.user; run.ended_at=timezone.now(); run.save()
            QRToken.objects.filter(session_run=run,revoked_at__isnull=True).update(revoked_at=timezone.now())
        audit(request.user,"qr.session.end",campus=run.campus,obj=run,request=request)
        return Response({"success":True,"state":run.state,"ended_at":run.ended_at})


class MentorAttendanceView(APIView):
    serializer_class=AttendanceSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def get(self,request):
        campus=scoped_campus(request.user,request.query_params.get("campus_id")); qs=AttendanceLog.objects.filter(campus=campus).select_related("student__user")
        day=parse_date(request.query_params.get("date", ""))
        if day: qs=qs.filter(attendance_date=day)
        if request.query_params.get("date_from"): qs=qs.filter(attendance_date__gte=request.query_params["date_from"])
        if request.query_params.get("date_to"): qs=qs.filter(attendance_date__lte=request.query_params["date_to"])
        for field in ("session_type","status","source","track_name","cohort_name"):
            value=request.query_params.get(field)
            if value: qs=qs.filter(**{field:value})
        term=request.query_params.get("search", "").strip()
        if term: qs=qs.filter(Q(student__user__username__icontains=term)|Q(student__user__first_name__icontains=term)|Q(student__user__last_name__icontains=term)|Q(student__student_code__icontains=term))
        from rest_framework.pagination import PageNumberPagination
        items=list(qs)
        if day:
            # This materializes any closed missing checkpoints, so
            # the API and CSV export always return the same persisted records.
            summary_for(campus, day, timezone.now())
            items=list(qs)
        if request.query_params.get("format")=="csv":
            if not user_can_export(request.user,campus): raise PermissionDenied("CSV export is not permitted for this campus.")
            out=io.StringIO(); writer=csv.writer(out); writer.writerow(["full_name","username","student_id","campus","track","cohort","record_kind","session_type","attendance_action","attendance_date","scan_time_wat","status","source","location_verified"])
            for item in items:
                if isinstance(item,dict): row=item
                else: row={"full_name":item.student.user.full_name,"username":item.student.user.username,"student_id":item.student_id,"campus":item.campus.name,"track":item.track_name,"cohort":item.cohort_name,"record_kind":"system_absence" if item.source == AttendanceLog.Source.SYSTEM or item.location_result == "system_daily_absence" else "manual_absence" if item.status == AttendanceLog.Status.ABSENT else "attendance","session_type":item.session_type,"attendance_action":item.attendance_action,"attendance_date":item.attendance_date,"scan_time_wat":item.scan_time_wat,"status":item.get_status_display(),"source":item.get_source_display(),"location_verified":item.location_verified}
                writer.writerow([csv_safe(row.get(k,"")) for k in ("full_name","username","student_id","campus","track","cohort","record_kind","session_type","attendance_action","attendance_date","scan_time_wat","status","source","location_verified")])
            audit(request.user,"attendance.csv.export",campus=campus,details={"rows":len(items)},request=request)
            response=HttpResponse(out.getvalue(),content_type="text/csv; charset=utf-8"); response["Content-Disposition"]='attachment; filename="learn2earn-attendance.csv"'; response["X-Content-Type-Options"]="nosniff"; return response
        paginator=PageNumberPagination(); paginator.page_size=50
        if request.query_params.get("status")=="absent": items=[x for x in items if (x.get("status") if isinstance(x,dict) else x.status)=="absent"]
        status_filter=request.query_params.get("status")
        if status_filter and status_filter!="absent": items=[x for x in items if (x.get("status") if isinstance(x,dict) else x.status)==status_filter]
        if request.query_params.get("session_type"): items=[x for x in items if (x.get("session_type") if isinstance(x,dict) else x.session_type)==request.query_params["session_type"]]
        if request.query_params.get("source"): items=[x for x in items if (x.get("source") if isinstance(x,dict) else x.source)==request.query_params["source"]]
        if request.query_params.get("track_name"): items=[x for x in items if (x.get("track_name") if isinstance(x,dict) else x.track_name)==request.query_params["track_name"]]
        items.sort(key=lambda x: ((x.get("scan_time_wat", "—") if isinstance(x,dict) else x.scan_time_wat),x.get("username","") if isinstance(x,dict) else x.student.user.username))
        data=[]
        for item in paginator.paginate_queryset(items,request): data.append(item if isinstance(item,dict) else AttendanceSerializer(item).data)
        return paginator.get_paginated_response(data)


class AttendanceSummaryView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def get(self,request):
        campus=scoped_campus(request.user,request.query_params.get("campus_id"))
        from zoneinfo import ZoneInfo
        now=timezone.now()
        day=parse_date(request.query_params.get("date", "")) or timezone.localtime(now,ZoneInfo(campus.timezone)).date()
        return Response({"campus":CampusSerializer(campus).data,"date":day,"timezone":campus.timezone,"summary":summary_for(campus,day,now)})


class AttendanceManualView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def post(self,request):
        reason=str(request.data.get("reason", "")).strip(); new_status=request.data.get("status")
        if not reason: raise ValidationError({"reason":"A reason is required for every manual attendance action."})
        if request.data.get("attendance_id"):
            try: attendance=AttendanceLog.objects.select_related("campus","student").get(pk=request.data.get("attendance_id"))
            except (AttendanceLog.DoesNotExist,ValueError,TypeError): return Response({"success":False,"code":"attendance_not_found","message":"Attendance record not found."},status=404)
            try: adjustment=manual_adjustment(attendance=attendance,actor=request.user,new_status=new_status,reason=reason,request=request)
            except PermissionError as exc: raise PermissionDenied(str(exc))
            except ValueError as exc: raise ValidationError({"detail":str(exc)})
            return Response({"success":True,"adjustment_id":str(adjustment.pk),"attendance":AttendanceSerializer(attendance).data},status=201)
        try:
            student=Student.objects.select_related("campus","track","cohort","user").get(pk=request.data.get("student_id"),active=True)
        except (Student.DoesNotExist,ValueError,TypeError): return Response({"success":False,"code":"student_not_found","message":"Active student not found."},status=404)
        if not user_can_access(request.user,student.campus,correct=True):
            raise PermissionDenied("Attendance corrections are not authorised for this campus.")
        from zoneinfo import ZoneInfo
        session=request.data.get("session_type")
        raw_day=request.data.get("attendance_date", "")
        day=parse_date(raw_day) if raw_day else None
        if raw_day and day is None: raise ValidationError({"attendance_date":"Use YYYY-MM-DD."})
        day=day or timezone.localtime(timezone.now(),ZoneInfo(student.campus.timezone)).date()
        if day > timezone.localtime(timezone.now(),ZoneInfo(student.campus.timezone)).date(): raise ValidationError({"attendance_date":"Future attendance dates are not allowed."})
        if session not in DEFAULT_SCHEDULES or new_status not in AttendanceLog.Status.values: raise ValidationError("Choose a valid session and status.")
        if session == "evening" and new_status == AttendanceLog.Status.LATE:
            raise ValidationError({"status":"Evening checkout cannot be marked late; record it as present or absent."})
        schedule=schedule_for(student.campus,session)
        local_now=timezone.localtime(timezone.now(),ZoneInfo(student.campus.timezone))
        if new_status==AttendanceLog.Status.ABSENT and day==local_now.date() and local_now.timetz().replace(tzinfo=None)<schedule.close_time:
            raise ValidationError({"status":"A student cannot be marked absent until this checkpoint has closed."})
        if MonthlyReport.objects.filter(campus=student.campus,year=day.year,month=day.month,closed=True).exists():
            raise ValidationError({"detail":"This month's report is closed. An administrator must reopen it before correcting historical attendance."})
        try:
            with transaction.atomic():
                log=AttendanceLog.objects.create(student=student,campus=student.campus,track_name=student.track.name if student.track_id else "",cohort_name=student.cohort.name if student.cohort_id else "",session_type=session,attendance_action=DEFAULT_SCHEDULES[session][3],attendance_date=day,scanned_at=None if new_status==AttendanceLog.Status.ABSENT else timezone.now(),status=new_status,source=AttendanceLog.Source.MANUAL,location_verified=False,location_result="manual_override")
                adjustment=AttendanceAdjustment.objects.create(attendance=log,student=student,campus=student.campus,mentor=request.user,original_status=AttendanceLog.Status.ABSENT,new_status=new_status,reason=reason)
                audit(request.user,"attendance.manual_create",campus=student.campus,obj=log,reason=reason,details={"adjustment_id":str(adjustment.pk),"status":new_status},request=request)
        except IntegrityError:
            return Response({"success":False,"code":"duplicate_attendance","message":"An attendance record already exists for this student and session."},status=409)
        return Response({"success":True,"adjustment_id":str(adjustment.pk),"attendance":AttendanceSerializer(log).data},status=201)


class LocationOverrideView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def post(self,request):
        if request.user.role not in (User.Role.MENTOR,User.Role.CAMPUS_ADMIN,User.Role.SUPER_ADMIN) and not request.user.is_superuser: raise PermissionDenied("Location overrides are restricted to mentors and administrators.")
        reason=str(request.data.get("reason", "")).strip(); original=str(request.data.get("original_location_result", "")).strip()
        if not reason or not original: raise ValidationError({"reason":"A reason and the original failed location result are required."})
        try: student=Student.objects.select_related("campus","track","cohort","user").get(pk=request.data.get("student_id"),active=True)
        except (Student.DoesNotExist,ValueError,TypeError): return Response({"success":False,"code":"student_not_found","message":"Active student not found."},status=404)
        campus=scoped_campus(request.user,request.data.get("campus_id"),correct=True)
        if campus.pk!=student.campus_id: raise PermissionDenied("Students may only be checked in at their assigned campus.")
        from zoneinfo import ZoneInfo
        session=request.data.get("session_type")
        if session not in DEFAULT_SCHEDULES: raise ValidationError({"session_type":"Choose morning, afternoon or evening."})
        schedule=schedule_for(campus,session)
        now=timezone.now(); local=timezone.localtime(now,ZoneInfo(campus.timezone))
        raw_day=request.data.get("attendance_date", "")
        day=parse_date(raw_day) if raw_day else None
        if raw_day and day is None: raise ValidationError({"attendance_date":"Use YYYY-MM-DD."})
        day=day or local.date()
        if day != local.date(): raise ValidationError({"attendance_date":"Location overrides can only record attendance for today."})
        if MonthlyReport.objects.filter(campus=campus,year=day.year,month=day.month,closed=True).exists():
            raise ValidationError({"attendance_date":"This month's report is closed. An administrator must reopen it before a correction."})
        failed=AuditLog.objects.filter(actor=student.user,campus=campus,action="attendance.location_rejected",created_at__gte=now-timedelta(minutes=15),details__result=original,details__session_type=session).exists()
        if not failed: raise ValidationError({"original_location_result":"No matching recent location failure was found for this student, campus and session."})
        if local.timetz().replace(tzinfo=None)<schedule.start_time or local.timetz().replace(tzinfo=None)>=schedule.close_time: raise ValidationError({"code":"outside_session_window","detail":"Session is outside its configured attendance window."})
        action=DEFAULT_SCHEDULES[session][3]
        status_value=AttendanceLog.Status.PRESENT if action=="check_out" else status_for_attendance_time(schedule,local)
        try:
            with transaction.atomic():
                log=AttendanceLog.objects.create(student=student,campus=campus,track_name=student.track.name if student.track_id else "",cohort_name=student.cohort.name if student.cohort_id else "",session_type=session,attendance_action=action,attendance_date=day,scanned_at=now,status=status_value,source=AttendanceLog.Source.MANUAL,location_verified=False,location_result="manual_override")
                adjustment=AttendanceAdjustment.objects.create(attendance=log,student=student,campus=campus,mentor=request.user,original_status=AttendanceLog.Status.ABSENT,new_status=status_value,reason=reason,location_override=True,original_location_result=original,override_result="approved_by_mentor")
                audit(request.user,"attendance.location_override",campus=campus,obj=log,reason=reason,details={"adjustment_id":str(adjustment.pk),"original_location_result":original,"override_result":"approved_by_mentor","student_id":str(student.pk)},request=request)
        except IntegrityError: return Response({"success":False,"code":"duplicate_attendance","message":"An attendance record already exists for this session."},status=409)
        return Response({"success":True,"adjustment_id":str(adjustment.pk),"attendance":AttendanceSerializer(log).data},status=201)


class AdminReportView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def get(self,request):
        campus_id=request.query_params.get("campus_id")
        campuses=accessible_campuses(request.user)
        if campus_id: campuses=campuses.filter(pk=campus_id)
        rows=[]
        for campus in campuses:
            if not user_can_access(request.user,campus): continue
            qs=AttendanceLog.objects.filter(campus=campus)
            start=parse_date(request.query_params.get("date_from", "")); end=parse_date(request.query_params.get("date_to", ""))
            if start: qs=qs.filter(attendance_date__gte=start)
            if end: qs=qs.filter(attendance_date__lte=end)
            rows.append({"campus":CampusSerializer(campus).data,"records":qs.count(),"present":qs.filter(status="present").count(),"late":qs.filter(status="late").count(),"absent":qs.filter(status="absent").count(),"by_session":{s:qs.filter(session_type=s).count() for s in DEFAULT_SCHEDULES}})
        return Response({"results":rows})


class MonthlyCloseView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def post(self,request):
        campus=scoped_campus(request.user,request.data.get("campus_id"))
        if request.user.role not in (User.Role.SUPER_ADMIN,User.Role.CAMPUS_ADMIN) and not request.user.is_superuser: raise PermissionDenied("Monthly report closure requires administrator access.")
        if request.user.role == User.Role.CAMPUS_ADMIN and request.user.assigned_campus_id != campus.pk:
            raise PermissionDenied("Campus administrators may only close reports for their assigned campus.")
        from zoneinfo import ZoneInfo
        today=timezone.localtime(timezone.now(),ZoneInfo(campus.timezone)).date()
        latest_year,latest_month=(today.year,today.month-1) if today.month>1 else (today.year-1,12)
        try:
            year=int(request.data.get("year",latest_year)); month=int(request.data.get("month",latest_month))
        except (TypeError,ValueError):
            raise ValidationError("Year and month must be integers.")
        if not 2000<=year<=latest_year or not 1<=month<=12 or (year,month)>(latest_year,latest_month): raise ValidationError("Only completed reporting months can be closed.")
        report,_=report_for(campus,year,month,request.user); audit(request.user,"report.month.close",campus=campus,obj=report,request=request)
        return Response({"id":str(report.pk),"campus":campus.name,"year":year,"month":month,"record_count":report.record_count,"generated_at":report.generated_at,"csv_url":f"/api/v1/admin/reports/{report.pk}/csv/"},status=201)


class MonthlyReportCsvView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def get(self,request,report_id):
        try: report=MonthlyReport.objects.select_related("campus").get(pk=report_id)
        except MonthlyReport.DoesNotExist: return Response({"success":False,"code":"report_not_found","message":"Report not found."},status=404)
        if not user_can_access(request.user,report.campus): raise PermissionDenied("You are not authorised for this campus.")
        if not user_can_export(request.user,report.campus): raise PermissionDenied("CSV export is not permitted for this campus.")
        audit(request.user,"report.csv.export",campus=report.campus,obj=report,request=request)
        response=HttpResponse(report.csv_content,content_type="text/csv; charset=utf-8")
        response["Content-Disposition"]=f'attachment; filename="{report.year}-{report.month:02d}-{report.campus_id}-attendance.csv"'
        response["X-Content-Type-Options"]="nosniff"; return response


class MonthlyReportJsonView(APIView):
    serializer_class=APIResponseSerializer
    permission_classes=[IsAuthenticated,StaffRolePermission]
    def get(self,request,report_id):
        try: report=MonthlyReport.objects.select_related("campus").get(pk=report_id)
        except MonthlyReport.DoesNotExist: return Response({"success":False,"code":"report_not_found","message":"Report not found."},status=404)
        if not user_can_export(request.user,report.campus): raise PermissionDenied("JSON export is not permitted for this campus.")
        audit(request.user,"report.json.export",campus=report.campus,obj=report,request=request)
        response=HttpResponse(json.dumps(report.json_content,ensure_ascii=False),content_type="application/json; charset=utf-8")
        response["Content-Disposition"]=f'attachment; filename="{report.year}-{report.month:02d}-{report.campus_id}-attendance.json"'; response["X-Content-Type-Options"]="nosniff"
        return response
