"""Búsquedas de colaboradores con su estado operativo actual."""

from django.db.models import OuterRef, Q, Subquery

from ..models import AttendanceRecord, PermisoSalida, VacationRecord
from .scoping import people_for_user


def search_detailed_people(user, search_term, today, limit=20):
    """Devuelve resultados detallados con cuatro consultas, sin una consulta por persona."""
    filters = (
        Q(first_name__icontains=search_term)
        | Q(last_name__icontains=search_term)
        | Q(id_number__icontains=search_term)
    )
    if user.user_type in ('admin_mina', 'admin_molino'):
        filters &= Q(area__icontains='mina' if user.user_type == 'admin_mina' else 'molino')

    latest_record_type = Subquery(
        AttendanceRecord.objects.filter(person_id=OuterRef('pk'))
        .order_by('-timestamp').values('record_type')[:1]
    )
    people = list(
        people_for_user(user).filter(filters).annotate(
            latest_record_type=latest_record_type,
        ).order_by('last_name', 'first_name')[:limit]
    )
    person_ids = [person.id for person in people]
    active_permissions = set(PermisoSalida.objects.filter(
        person_id__in=person_ids, fecha_inicio__lte=today, fecha_fin__gte=today,
    ).values_list('person_id', flat=True))
    active_vacations = set(VacationRecord.objects.filter(
        person_id__in=person_ids, start_date__lte=today, end_date__gte=today,
    ).values_list('person_id', flat=True))

    results = []
    for person in people:
        item = {
            'id': person.id,
            'nombre_completo': f'{person.first_name} {person.last_name}',
            'id_number': person.id_number,
            'cargo': person.cargo or '',
            'departamento': person.departamento or '',
            'area': person.area or '',
            'contacto': person.phone_number or '',
            'email': person.email or '',
            'fecha_ingreso': person.fecha_ingreso.strftime('%d/%m/%Y') if person.fecha_ingreso else '',
            'permiso_activo': person.id in active_permissions,
            'en_vacaciones': person.id in active_vacations,
            'esta_dentro': person.latest_record_type == 'entrada',
            'chequeo_medico': person.medical_checkup,
        }
        if person.foto:
            item['foto_url'] = person.foto.url
        results.append(item)
    return results
