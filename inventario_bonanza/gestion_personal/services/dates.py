"""Límites de fechas para filtros indexables sobre DateTimeField."""

from datetime import datetime, time, timedelta

from django.utils import timezone


def local_day_bounds(day):
    """Devuelve [inicio, siguiente inicio) en la zona horaria activa."""
    start = timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())
    return start, start + timedelta(days=1)


def local_date_range_bounds(start_date, end_date):
    """Devuelve límites inclusivos por día usando el extremo superior exclusivo."""
    start, _ = local_day_bounds(start_date)
    _, end = local_day_bounds(end_date)
    return start, end
