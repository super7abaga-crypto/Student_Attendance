from celery import shared_task
from django.utils import timezone
from zoneinfo import ZoneInfo
from datetime import timedelta
from .models import Campus, QRToken
from .services import close_months_through, materialize_absences, schedule_for


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


@shared_task
def close_daily_attendance():
    """Close only campus-local dates whose final attendance window has ended.

    Beat invokes this every 15 minutes in UTC. Include the prior campus-local
    day as a bounded catch-up in case Beat was unavailable around midnight;
    today's date is eligible only after that campus's configured evening close.
    The database's student/date uniqueness constraint makes repeated runs safe.
    """
    now = timezone.now()
    recorded = 0
    for campus in Campus.objects.filter(active=True):
        local_now = timezone.localtime(now, ZoneInfo(campus.timezone))
        local_day = local_now.date()
        days_to_close = [local_day - timedelta(days=1)]
        evening_close = schedule_for(campus, "evening").close_time
        if local_now.timetz().replace(tzinfo=None) >= evening_close:
            days_to_close.append(local_day)
        for day in days_to_close:
            recorded += materialize_absences(campus, day, now)
    return {"absences_recorded": recorded}
