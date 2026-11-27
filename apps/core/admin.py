from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (AttendanceAdjustment, AttendanceLog, AuditLog, Campus, CampusTransfer,
                     Cohort, MentorCampusAccess, MonthlyReport, QRToken, SessionRun,
                     SessionSchedule, Student, Track, User)


@admin.register(User)
class AttendanceUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Learn2Earn access", {"fields": ("display_name", "role", "assigned_campus", "active_student")}),)
    list_display = ("username", "email", "role", "assigned_campus", "is_active")
    list_filter = ("role", "assigned_campus", "is_active")


for model in (Campus, Track, Cohort, Student, MentorCampusAccess, CampusTransfer,
              SessionSchedule, SessionRun, QRToken, AttendanceLog,
              AttendanceAdjustment, MonthlyReport):
    admin.site.register(model)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "campus", "object_type", "object_id")
    list_filter = ("action", "campus", "created_at")
    readonly_fields = tuple(f.name for f in AuditLog._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
