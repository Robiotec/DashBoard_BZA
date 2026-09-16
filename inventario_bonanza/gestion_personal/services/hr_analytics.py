"""Consultas agregadas para los tableros de Recursos Humanos."""

import calendar
from datetime import date, timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth

from ..models import (
    AccidentCase,
    AnnualActivity,
    DiningHall,
    HRAuditLog,
    HRInspection,
    MedicalLeaveCase,
    Person,
    Room,
    RoomAssignment,
    SocialBenefitCase,
    UpcomingEntry,
)


def _six_month_window(month_start):
    total_months = month_start.year * 12 + month_start.month - 1 - 5
    year, month = divmod(total_months, 12)
    return date(year, month + 1, 1)


def _month_end(value):
    return value.replace(day=calendar.monthrange(value.year, value.month)[1])


def _as_date(value):
    return value.date() if hasattr(value, 'date') else value


def _trend(month_start, month_end, organization):
    """Genera seis meses con tres consultas agregadas, en lugar de dieciocho."""
    first_month = _six_month_window(month_start)
    months = []
    cursor = first_month
    while cursor <= month_start:
        months.append(cursor)
        next_month = cursor.month % 12 + 1
        cursor = date(cursor.year + (cursor.month == 12), next_month, 1)

    medical = {month: 0 for month in months}
    leaves = MedicalLeaveCase.objects.filter(
        organization=organization,
        start_date__lte=month_end,
        end_date__gte=first_month,
    ).values_list('start_date', 'end_date')
    for start, end in leaves:
        for month in months:
            if start <= _month_end(month) and end >= month:
                medical[month] += 1

    accidents = {
        _as_date(item['month']): item['total']
        for item in AccidentCase.objects.filter(
            organization=organization,
            event_date__range=(first_month, month_end),
        ).annotate(month=TruncMonth('event_date')).values('month').annotate(total=Count('id'))
    }
    inspections = {
        _as_date(item['month']): item['total']
        for item in HRInspection.objects.filter(
            organization=organization,
            inspection_date__range=(first_month, month_end),
        ).annotate(month=TruncMonth('inspection_date')).values('month').annotate(total=Count('id'))
    }

    comparison = [
        {
            'label': calendar.month_abbr[month.month].title(),
            'medical': medical[month],
            'accidents': accidents.get(month, 0),
            'inspections': inspections.get(month, 0),
        }
        for month in months
    ]
    chart_max = max(
        (value for item in comparison for value in (item['medical'], item['accidents'], item['inspections'])),
        default=1,
    )
    for item in comparison:
        for key in ('medical', 'accidents', 'inspections'):
            item[f'{key}_pct'] = max(item[key] * 100 / chart_max, 3) if item[key] else 0
    return comparison


def management_dashboard_context(organization, month_start, month_end, today, label_for):
    """Construye las métricas del tablero con conjuntos y agregados reutilizables."""
    room_metrics = Room.objects.filter(organization=organization).aggregate(
        capacity=Sum('capacity', filter=Q(service_status='available')),
    )
    assignment_metrics = RoomAssignment.objects.filter(room__organization=organization).aggregate(
        occupied=Count('id', filter=Q(status='occupied')),
        reserved=Count('id', filter=Q(status='reserved')),
    )
    capacity = room_metrics['capacity'] or 0
    occupied = assignment_metrics['occupied'] or 0
    reserved = (assignment_metrics['reserved'] or 0) + UpcomingEntry.objects.filter(
        organization=organization, room__isnull=False,
    ).exclude(status__in=('entered', 'cancelled')).count()

    people_metrics = Person.objects.filter(organization=organization, estado='activo').aggregate(
        planned_workdays=Sum('dias_jornada'),
        without_dining=Count('id', filter=Q(dining_hall__isnull=True)),
    )
    planned_workdays = people_metrics['planned_workdays'] or 0

    upcoming_month = UpcomingEntry.objects.filter(
        organization=organization, expected_entry_date__range=(month_start, month_end),
    )
    upcoming_metrics = upcoming_month.aggregate(
        total=Count('id'), without_room=Count('id', filter=Q(room__isnull=True)),
    )

    activity_ids = [
        activity.pk
        for activity in AnnualActivity.objects.filter(organization=organization).only(
            'pk', 'execution_months', 'planned_date',
        )
        if month_start.month in activity.execution_months
        or activity.planned_date and month_start <= activity.planned_date <= month_end
    ]
    activity_metrics = AnnualActivity.objects.filter(pk__in=activity_ids).aggregate(
        total=Count('id'),
        completed=Count('id', filter=Q(status='completed')),
        rescheduled=Count('id', filter=Q(status='rescheduled')),
        evidence_pending=Count('id', filter=Q(status='completed', evidence='', evidence_link='')),
    )
    activity_total = activity_metrics['total'] or 0

    overlap = Q(start_date__lte=month_end, end_date__gte=month_start)
    leave_metrics = MedicalLeaveCase.objects.filter(organization=organization).aggregate(
        cases=Count('id', filter=overlap),
        days=Sum('days', filter=overlap),
        active=Count('id', filter=Q(status__in=('active', 'pending'))),
        returns=Count(
            'id',
            filter=Q(
                status__in=('returned', 'relocated', 'closed'),
                expected_return_date__range=(month_start, month_end),
            ),
        ),
    )
    medical_days = leave_metrics['days'] or 0

    inspection_metrics = HRInspection.objects.filter(organization=organization).aggregate(
        month_total=Count('id', filter=Q(inspection_date__range=(month_start, month_end))),
        open_total=Count('id', filter=Q(status__in=('pending', 'in_progress'))),
        closed_actions=Count(
            'id',
            filter=Q(
                inspection_date__range=(month_start, month_end),
                status__in=('verified', 'closed'),
            ),
        ),
    )
    accident_metrics = AccidentCase.objects.filter(organization=organization).aggregate(
        total=Count('id', filter=Q(event_date__range=(month_start, month_end))),
        company_days=Sum('company_days', filter=Q(event_date__range=(month_start, month_end))),
        iess_days=Sum('iess_days', filter=Q(event_date__range=(month_start, month_end))),
    )
    benefit_counts = dict(
        SocialBenefitCase.objects.filter(organization=organization)
        .values_list('status').annotate(total=Count('id'))
    )

    alerts = []
    for entry in UpcomingEntry.objects.filter(
        organization=organization, expected_entry_date__range=(today, today + timedelta(days=7)),
    ).exclude(status__in=('entered', 'cancelled')).only(
        'id', 'first_name', 'last_name', 'id_number', 'expected_entry_date',
        'documentation_complete', 'medical_exam_complete', 'induction_complete',
        'accreditation_complete', 'final_approval', 'room_id', 'dining_hall_id',
    ):
        pending = []
        if not entry.requirements_complete:
            pending.append('requisitos')
        if not entry.room_id:
            pending.append('alojamiento')
        if not entry.dining_hall_id:
            pending.append('comedor')
        if pending:
            alerts.append({
                'level': 'danger', 'module': 'ingresos',
                'text': f'{label_for(entry)} ingresa el {entry.expected_entry_date:%d/%m}: falta {", ".join(pending)}.',
            })
    for leave in MedicalLeaveCase.objects.filter(
        organization=organization,
        end_date__range=(today, today + timedelta(days=3)),
        status__in=('active', 'pending'),
    ).select_related('person'):
        alerts.append({
            'level': 'warning', 'module': 'descansos',
            'text': f'El descanso de {label_for(leave)} finaliza el {leave.end_date:%d/%m/%Y}.',
        })
    for activity in AnnualActivity.objects.filter(
        organization=organization, due_date__lt=today,
    ).exclude(status__in=('completed', 'cancelled')).only('action_line'):
        alerts.append({'level': 'warning', 'module': 'cronograma', 'text': f'Actividad vencida: {activity.action_line}.'})
    for inspection in HRInspection.objects.filter(
        organization=organization, due_date__lt=today,
    ).exclude(status__in=('verified', 'closed')).only('location'):
        alerts.append({
            'level': 'danger', 'module': 'inspecciones',
            'text': f'Acción de inspección vencida en {inspection.location}.',
        })

    return {
        'alerts': alerts[:12],
        'dining_counts': list(DiningHall.objects.filter(organization=organization).annotate(
            assigned=Count('diners', filter=Q(diners__estado='activo')),
        ).values('name', 'assigned').order_by('name')),
        'capacity': capacity,
        'occupied': occupied,
        'reserved': reserved,
        'available': max(capacity - occupied - reserved, 0),
        'occupation_pct': round(occupied * 100 / capacity, 1) if capacity else 0,
        'without_dining': people_metrics['without_dining'] or 0,
        'upcoming_count': upcoming_metrics['total'] or 0,
        'upcoming_without_room': upcoming_metrics['without_room'] or 0,
        'activity_total': activity_total,
        'completed_activities': activity_metrics['completed'] or 0,
        'activity_compliance': round((activity_metrics['completed'] or 0) * 100 / activity_total, 1) if activity_total else 0,
        'rescheduled_activities': activity_metrics['rescheduled'] or 0,
        'activity_evidence_pending': activity_metrics['evidence_pending'] or 0,
        'inspections_count': inspection_metrics['month_total'] or 0,
        'open_findings': inspection_metrics['open_total'] or 0,
        'closed_actions': inspection_metrics['closed_actions'] or 0,
        'medical_cases': leave_metrics['cases'] or 0,
        'medical_days': medical_days,
        'medical_absenteeism': round(medical_days * 100 / planned_workdays, 2) if planned_workdays else 0,
        'planned_workdays': planned_workdays,
        'incidence_areas': list(MedicalLeaveCase.objects.filter(organization=organization).filter(overlap).values(
            'person__departamento',
        ).annotate(cases=Count('id'), days=Sum('days')).order_by('-cases', '-days')[:5]),
        'medical_active': leave_metrics['active'] or 0,
        'returns': leave_metrics['returns'] or 0,
        'accident_count': accident_metrics['total'] or 0,
        'company_days': accident_metrics['company_days'] or 0,
        'iess_days': accident_metrics['iess_days'] or 0,
        'benefits_pending': sum(benefit_counts.get(status, 0) for status in ('not_started', 'processing', 'observed')),
        'documents_pending': SocialBenefitCase.objects.filter(organization=organization).exclude(
            pending_documents='',
        ).exclude(status__in=('closed', 'not_applicable')).count(),
        'benefit_statuses': [
            {'label': label, 'count': benefit_counts.get(status, 0)}
            for status, label in SocialBenefitCase.STATUS_CHOICES
        ],
        'comparison': _trend(month_start, month_end, organization),
        'audit_logs': HRAuditLog.objects.filter(organization=organization).select_related('user')[:12],
    }
