"""Métricas operativas del panel principal de Recursos Humanos."""

from datetime import timedelta

from django.db.models import Count, Q

from ..models import (
    AttendanceRecord,
    HRInspection,
    MedicalLeaveCase,
    Room,
    RoomAssignment,
    SocialBenefitCase,
    UpcomingEntry,
    VacationRecord,
)
from .dates import local_day_bounds
from .scoping import people_for_user


def overview_metrics(user, today):
    """Obtiene los indicadores visibles en el dashboard sin duplicar consultas."""
    people = people_for_user(user)
    people_counts = people.aggregate(
        total=Count('id', distinct=True),
        active=Count('id', filter=Q(estado='activo'), distinct=True),
        inactive=Count('id', filter=Q(estado='pasivo'), distinct=True),
        without_photo=Count(
            'id',
            filter=Q(estado='activo') & (Q(foto='') | Q(foto__isnull=True)),
            distinct=True,
        ),
        without_room=Count('id', filter=Q(estado='activo', room_assignment__isnull=True), distinct=True),
        without_dining=Count('id', filter=Q(estado='activo', dining_hall__isnull=True), distinct=True),
        pending_medical=Count('id', filter=Q(estado='activo', medical_checkup=False), distinct=True),
    )
    day_start, day_end = local_day_bounds(today)
    room_counts = Room.objects.filter(organization=user.organization).aggregate(
        total=Count('id'),
        out_of_service=Count('id', filter=Q(service_status='out_of_service')),
    )

    return {
        'total_personas': people_counts['total'],
        'total_activos': people_counts['active'],
        'total_pasivos': people_counts['inactive'],
        'total_sin_foto': people_counts['without_photo'],
        'sin_alojamiento': people_counts['without_room'],
        'sin_comedor': people_counts['without_dining'],
        'pendientes_medicos': people_counts['pending_medical'],
        'asistencias_hoy': AttendanceRecord.objects.filter(
            person__in=people,
            timestamp__gte=day_start,
            timestamp__lt=day_end,
            record_type='entrada',
        ).values('person_id').distinct().count(),
        'habitaciones_total': room_counts['total'],
        'habitaciones_fuera_servicio': room_counts['out_of_service'],
        'ocupacion': RoomAssignment.objects.filter(
            room__organization=user.organization, status='occupied',
        ).count(),
        'vacaciones_actuales_count': VacationRecord.objects.filter(
            person__in=people,
            start_date__lte=today,
            end_date__gte=today,
        ).count(),
        'proximos_ingresos': UpcomingEntry.objects.filter(
            organization=user.organization,
            expected_entry_date__range=(today, today + timedelta(days=7)),
        ).exclude(status__in=('entered', 'cancelled')).count(),
        'descansos_activos': MedicalLeaveCase.objects.filter(
            organization=user.organization, status__in=('active', 'pending'),
        ).count(),
        'hallazgos_abiertos': HRInspection.objects.filter(
            organization=user.organization, status__in=('pending', 'in_progress'),
        ).count(),
        'tramites_sociales_pendientes': SocialBenefitCase.objects.filter(
            organization=user.organization,
            status__in=('not_started', 'processing', 'observed'),
        ).count(),
    }
