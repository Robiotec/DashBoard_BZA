"""Persistencia masiva de la planificación mensual de jornadas."""

from django.db import transaction

from ..models import MonthlyWorkDay


def save_monthly_workdays(post_data, people, days, allowed_statuses, user):
    """Aplica una cuadrícula mensual con operaciones por lote.

    El formulario puede contener cientos de celdas; se consulta el estado actual
    una vez y se persisten todas las diferencias en una sola transacción.
    """
    person_ids = [person.id for person in people]
    existing = {
        (record.person_id, record.date): record
        for record in MonthlyWorkDay.objects.filter(person_id__in=person_ids, date__in=days)
    }
    to_create, to_update, to_delete = [], [], []
    saved = deleted = 0

    for person in people:
        for day in days:
            field_name = f'status_{person.id}_{day.isoformat()}'
            if field_name not in post_data:
                continue
            status = post_data.get(field_name, '').strip()
            if status and status not in allowed_statuses:
                continue
            record = existing.get((person.id, day))
            if not status:
                if record:
                    to_delete.append(record.pk)
                    deleted += 1
                continue
            saved += 1
            if record:
                record.status = status
                record.recorded_by = user
                to_update.append(record)
            else:
                to_create.append(MonthlyWorkDay(
                    person_id=person.id, date=day, status=status, recorded_by=user,
                ))

    with transaction.atomic():
        if to_delete:
            MonthlyWorkDay.objects.filter(pk__in=to_delete).delete()
        if to_create:
            MonthlyWorkDay.objects.bulk_create(to_create, batch_size=500)
        if to_update:
            MonthlyWorkDay.objects.bulk_update(to_update, ('status', 'recorded_by'), batch_size=500)
    return saved, deleted
