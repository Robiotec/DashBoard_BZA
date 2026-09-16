"""Importación masiva de personas desde archivos tabulares."""

import logging

import pandas as pd
from django.db import transaction
from django.utils import timezone

from ..models import Person


logger = logging.getLogger(__name__)
REQUIRED_COLUMNS = {'cedula', 'nombre', 'apellido'}
OPTIONAL_FIELDS = {
    'cargo': 'cargo', 'departamento': 'departamento', 'area': 'area',
    'email': 'email', 'telefono': 'phone_number',
    'contacto_emergencia': 'contacto_emergencia', 'direccion': 'address',
    'anotaciones': 'anotaciones_rrhh',
}
DATE_FIELDS = {'fecha_nacimiento': 'birth_date', 'fecha_ingreso': 'fecha_ingreso', 'fecha_egreso': 'fecha_egreso'}
UPDATE_FIELDS = [
    'first_name', 'last_name', *OPTIONAL_FIELDS.values(), *DATE_FIELDS.values(),
    'gender', 'estado', 'updated_at',
]


def _text(value):
    return '' if pd.isna(value) else str(value).strip()


def _date(value):
    if pd.isna(value):
        return None
    try:
        return pd.to_datetime(value).date()
    except (TypeError, ValueError):
        return None


def _gender(value):
    normalized = _text(value).upper()
    if normalized in ('M', 'MASCULINO', 'HOMBRE'):
        return 'M'
    if normalized in ('F', 'FEMENINO', 'MUJER'):
        return 'F'
    return 'O'


def import_people_dataframe(dataframe, organization):
    """Crea o actualiza personas en lotes, evitando una consulta por cada fila."""
    columns = set(dataframe.columns)
    if not REQUIRED_COLUMNS.issubset(columns):
        return 0, 0, len(dataframe)

    rows = dataframe.to_dict('records')
    id_numbers = {_text(row['cedula']) for row in rows if _text(row['cedula'])}
    existing = {
        person.id_number: person
        for person in Person.objects.filter(organization=organization, id_number__in=id_numbers)
    }
    to_create, to_update = [], {}
    created_count = updated_count = error_count = 0

    with transaction.atomic():
        for row in rows:
            id_number = _text(row.get('cedula'))
            first_name = _text(row.get('nombre'))
            last_name = _text(row.get('apellido'))
            if not all((id_number, first_name, last_name)):
                error_count += 1
                continue

            person = existing.get(id_number)
            is_new = person is None
            if is_new:
                person = Person(
                    organization=organization, id_number=id_number, birth_date=timezone.localdate(),
                    gender='O', estado='activo',
                )
                existing[id_number] = person

            person.first_name = first_name
            person.last_name = last_name
            for column, field in OPTIONAL_FIELDS.items():
                value = row.get(column)
                if not pd.isna(value):
                    setattr(person, field, str(value).strip())
            for column, field in DATE_FIELDS.items():
                parsed = _date(row.get(column))
                if parsed:
                    setattr(person, field, parsed)
            if not pd.isna(row.get('genero')):
                person.gender = _gender(row['genero'])
            if not pd.isna(row.get('estado')):
                person.estado = 'pasivo' if _text(row['estado']).lower() in {
                    'pasivo', 'inactivo', 'retirado', 'egresado',
                } else 'activo'

            if is_new:
                to_create.append(person)
                created_count += 1
            elif person.pk:
                to_update[person.pk] = person
                updated_count += 1
            else:
                updated_count += 1

        Person.objects.bulk_create(to_create, batch_size=500)
        Person.objects.bulk_update(list(to_update.values()), UPDATE_FIELDS, batch_size=500)

    return created_count, updated_count, error_count
