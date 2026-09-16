"""Conteos agregados para listados de registros operativos."""

from django.db.models import Count, Q


def attendance_counts(queryset):
    return queryset.aggregate(
        total=Count('id'),
        entries=Count('id', filter=Q(record_type='entrada')),
        exits=Count('id', filter=Q(record_type='salida')),
    )


def vehicle_counts(queryset):
    return queryset.aggregate(
        total=Count('id'),
        inside=Count('id', filter=Q(fecha_salida__isnull=True)),
    )
