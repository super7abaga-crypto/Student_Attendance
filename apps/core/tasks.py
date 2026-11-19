from celery import shared_task
from django.utils import timezone
from zoneinfo import ZoneInfo
from .models import Campus, QRToken
from .services import close_months_through


@shared_task
def close_missed_months():
    now = timezone.now()
    campuses = list(Campus.objects.filter(active=True))
    reports = []
    for campus in campuses:
        today = timezone.localtime(now, ZoneInfo(campus.timezone)).date()
        year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        reports.extend(close_months_through(year, month, campus_ids=[campus.pk]))
    QRToken.objects.filter(expires_at__lt=timezone.now() - timezone.timedelta(days=90)).delete()
    return {"reports_processed": len(reports), "campuses": len(campuses)}
