from django.urls import include, path
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from .views import (AdminReportView, AttendanceManualView, AttendanceScanView,
                    AttendanceSummaryView, CampusViewSet, LogoutView, MentorAttendanceView, LocationOverrideView,
                    MentorLoginView, MentorProfileView, QRImageView, MonthlyCloseView, MonthlyReportCsvView, MonthlyReportJsonView, MonthlyReportsView, MonthlyReopenView, TrackListView,
                    SessionCurrentQRView, SessionEndView, SessionStartView,
                    StudentHistoryView, StudentLoginView, StudentProfileView, StudentRegisterView,
                    StudentViewSet)

router = DefaultRouter()
router.register("admin/campuses", CampusViewSet, basename="campus")
router.register("admin/students", StudentViewSet, basename="student-admin")

urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(), name="openapi-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="openapi-schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="openapi-schema"), name="redoc"),
    path("auth/student/login/", StudentLoginView.as_view(), name="student-login"),
    path("auth/student/register/", StudentRegisterView.as_view(), name="student-register"),
    path("auth/mentor/login/", MentorLoginView.as_view(), name="mentor-login"),
    path("auth/mentor/profile/", MentorProfileView.as_view(), name="mentor-profile"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("student/profile/", StudentProfileView.as_view(), name="student-profile"),
    path("student/attendance-history/", StudentHistoryView.as_view(), name="student-history"),
    path("attendance/scan/", AttendanceScanView.as_view(), name="attendance-scan"),
    path("mentor/qr/start/", SessionStartView.as_view(), name="qr-start"),
    path("mentor/qr/current/", SessionCurrentQRView.as_view(), name="qr-current"),
    path("mentor/qr/image/", QRImageView.as_view(), name="qr-image"),
    path("mentor/qr/end/", SessionEndView.as_view(), name="qr-end"),
    path("mentor/attendance/", MentorAttendanceView.as_view(), name="mentor-attendance"),
    path("mentor/attendance/summary/", AttendanceSummaryView.as_view(), name="attendance-summary"),
    path("mentor/attendance/manual/", AttendanceManualView.as_view(), name="attendance-manual"),
    path("mentor/attendance/location-override/", LocationOverrideView.as_view(), name="attendance-location-override"),
    path("admin/reports/", AdminReportView.as_view(), name="admin-reports"),
    path("admin/monthly-reports/", MonthlyReportsView.as_view(), name="monthly-reports"),
    path("admin/monthly-close/", MonthlyCloseView.as_view(), name="monthly-close"),
    path("admin/monthly-reports/<uuid:report_id>/reopen/", MonthlyReopenView.as_view(), name="monthly-reopen"),
    path("admin/reports/<uuid:report_id>/csv/", MonthlyReportCsvView.as_view(), name="monthly-report-csv"),
    path("admin/reports/<uuid:report_id>/json/", MonthlyReportJsonView.as_view(), name="monthly-report-json"),
    path("admin/tracks/", TrackListView.as_view(), name="tracks"),
    path("", include(router.urls)),
]
