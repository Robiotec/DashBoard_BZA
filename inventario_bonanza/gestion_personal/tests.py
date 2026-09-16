from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from datetime import date, timedelta
from unittest.mock import patch
import subprocess
import pandas as pd

from django.core.management import call_command
from django.utils import timezone
from django.db import connection

from .forms import PermisoSalidaForm, RoomAssignmentForm, VacationRecordForm
from .models import (
    AccidentCase, AnnualActivity, AttendanceRecord, CustomUser, DiningAssignmentHistory,
    DiningHall, HRAuditLog, HRInspection, MedicalLeaveCase, Organization, Person, PlateLookupRecord, Room,
    PermisoSalida, RoomAssignment, RoomOccupancyMovement, SocialBenefitCase, UpcomingEntry, VisitaProgramada,
)
from .services.hr_analytics import management_dashboard_context
from .services.people_import import import_people_dataframe
from .services.detailed_people import search_detailed_people


@override_settings(SECURE_SSL_REDIRECT=False)
class AccommodationTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Campamento Norte', slug='norte')
        self.other_organization = Organization.objects.create(name='Campamento Sur', slug='sur')
        self.user = CustomUser.objects.create_user(
            username='rrhh', password='test-password', user_type='rh', organization=self.organization
        )
        self.person = Person.objects.create(
            first_name='Ana', last_name='Perez', id_number='0102030405',
            birth_date=date(1990, 1, 1), gender='F', estado='activo', organization=self.organization,
        )
        self.room = Room.objects.create(
            organization=self.organization, block='Bloque A', house='Casa 1', number='101', capacity=1
        )
        self.dining_hall = DiningHall.objects.create(organization=self.organization, name='Comedor Central')
        self.client.force_login(self.user)

    def test_room_rack_is_scoped_to_user_organization(self):
        Room.objects.create(
            organization=self.other_organization, block='Privado', number='999', capacity=2
        )
        response = self.client.get(reverse('accommodation_rack'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Habitación 101')
        self.assertNotContains(response, 'Habitación 999')

    def test_assignment_appears_in_people_list_with_room_and_dining_hall(self):
        RoomAssignment.objects.create(
            room=self.room, person=self.person, dining_hall=self.dining_hall,
            status='occupied', check_in_date=date.today()
        )
        response = self.client.get(reverse('person_list'))
        self.assertContains(response, 'Hab. 101')
        self.assertContains(response, 'Comedor Central')

    def test_assignment_form_rejects_room_over_capacity(self):
        RoomAssignment.objects.create(room=self.room, person=self.person, status='occupied')
        second_person = Person.objects.create(
            first_name='Luis', last_name='Vera', id_number='1111111111',
            birth_date=date(1992, 2, 2), gender='M', estado='activo', organization=self.organization,
        )
        form = RoomAssignmentForm(
            data={'person': second_person.id, 'status': 'occupied', 'check_in_date': date.today()},
            organization=self.organization, room=self.room,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('capacidad', str(form.errors).lower())

    def test_rh_can_filter_people_without_photo(self):
        response = self.client.get(reverse('person_list'), {'foto': 'sin'})
        self.assertContains(response, 'Ana Perez')

    def test_cannot_mark_occupied_room_out_of_service(self):
        RoomAssignment.objects.create(room=self.room, person=self.person, status='occupied')
        response = self.client.post(reverse('accommodation_room_update', args=[self.room.id]), {
            'block': self.room.block, 'house': self.room.house, 'number': self.room.number,
            'capacity': self.room.capacity, 'service_status': 'out_of_service', 'notes': '',
        }, follow=True)
        self.room.refresh_from_db()
        self.assertEqual(self.room.service_status, 'available')
        self.assertContains(response, 'Libere las asignaciones')

    def test_live_person_search_accepts_name_and_id_number(self):
        by_name = self.client.get(reverse('rh_person_search'), {'q': 'Ana', 'purpose': 'room'})
        by_id = self.client.get(reverse('rh_person_search'), {'q': '010203', 'purpose': 'room'})
        self.assertEqual(by_name.json()['results'][0]['id'], self.person.id)
        self.assertEqual(by_id.json()['results'][0]['id'], self.person.id)

    def test_dining_hall_can_be_assigned_without_room(self):
        response = self.client.post(reverse('person_dining_hall_update', args=[self.person.id]), {
            'dining_hall': self.dining_hall.id,
        }, follow=True)
        self.person.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.person.dining_hall, self.dining_hall)
        self.assertContains(response, 'Comedor Central')

    def test_dashboard_searches_people_by_name(self):
        response = self.client.get(reverse('dashboard_rrhh'), {'q': 'Ana'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['persona'], self.person)
        self.assertContains(response, 'id="personConsultationContent"')
        self.assertContains(response, 'id="personConsultationDestination"')
        self.assertContains(response, 'destination.appendChild(consultation)')

    def test_vacation_form_uses_searchable_person_picker(self):
        response = self.client.get(reverse('vacation_create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="person"')
        self.assertContains(response, 'Buscar por nombre o cédula')
        self.assertContains(response, self.person.id_number)
        today = timezone.localdate()
        self.assertContains(response, f'value="{today:%Y-%m-%d}"')
        self.assertContains(response, f'value="{today + timedelta(days=7):%Y-%m-%d}"')

    def test_date_period_forms_default_to_today_and_seven_days(self):
        today = timezone.localdate()
        vacation_form = VacationRecordForm(user=self.user)
        permission_form = PermisoSalidaForm()
        self.assertEqual(vacation_form.fields['start_date'].initial, today)
        self.assertEqual(vacation_form.fields['end_date'].initial, today + timedelta(days=7))
        self.assertEqual(permission_form.fields['fecha_inicio'].initial, today)
        self.assertEqual(permission_form.fields['fecha_fin'].initial, today + timedelta(days=7))

    def test_sanction_form_uses_person_selector_instead_of_cedula_only(self):
        response = self.client.get(reverse('registrar_sancion'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="person"')
        self.assertContains(response, 'Buscar por nombre o cédula')

    def test_rh_dashboard_contains_floating_assistant(self):
        response = self.client.get(reverse('dashboard_rrhh'))
        self.assertContains(response, 'id="rhAssistantToggle"')
        self.assertContains(response, 'id="rhAssistantPanel"')
        self.assertContains(response, 'id="personSearchModal"')
        self.assertContains(response, 'data-bs-target="#personSearchModal"')

    def test_empty_room_can_be_deleted_but_occupied_room_cannot(self):
        empty_room = Room.objects.create(
            organization=self.organization, block='Bloque B', number='202', capacity=2
        )
        self.client.post(reverse('accommodation_room_delete', args=[empty_room.id]))
        self.assertFalse(Room.objects.filter(pk=empty_room.id).exists())
        RoomAssignment.objects.create(room=self.room, person=self.person, status='occupied')
        response = self.client.post(
            reverse('accommodation_room_delete', args=[self.room.id]), follow=True
        )
        self.assertTrue(Room.objects.filter(pk=self.room.id).exists())
        self.assertContains(response, 'No se puede eliminar una habitación con personas asignadas')

    def test_dining_hall_can_be_updated_and_deleted(self):
        update_response = self.client.post(reverse('dining_hall_update', args=[self.dining_hall.id]), {
            'name': 'Comedor Principal', 'location': 'Bloque administrativo', 'is_active': 'on',
        }, follow=True)
        self.dining_hall.refresh_from_db()
        self.assertEqual(self.dining_hall.name, 'Comedor Principal')
        self.assertContains(update_response, 'Comedor actualizado correctamente')
        self.client.post(reverse('dining_hall_delete', args=[self.dining_hall.id]))
        self.assertFalse(DiningHall.objects.filter(pk=self.dining_hall.id).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class GlobalAdministratorTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Bonanza', slug='bonanza')
        self.global_admin = CustomUser.objects.create_superuser(
            username='mpiedra', password='test-password', user_type='global_admin'
        )
        self.rh_user = CustomUser.objects.create_user(
            username='rh-bonanza', password='test-password', user_type='rh', organization=self.organization
        )
        self.person = Person.objects.create(
            first_name='Carlos', last_name='Mendoza', id_number='0999999999',
            birth_date=date(1988, 3, 3), gender='M', estado='activo', organization=self.organization,
        )
        self.client.force_login(self.global_admin)

    def test_global_admin_sees_visits_created_by_other_users(self):
        VisitaProgramada.objects.create(
            nombre='Visita Externa', identificacion='1234567890', motivo='Reunión',
            fecha_programada=date.today(), hora_programada='10:00', area_visita='Mina',
            autorizado_por='Gerencia', programado_por=self.rh_user,
        )
        response = self.client.get(reverse('visitas_programadas'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Visita Externa')

    def test_global_records_searches_by_person_name(self):
        AttendanceRecord.objects.create(
            person=self.person, record_type='entrada', recorded_by=self.rh_user
        )
        response = self.client.get(reverse('global_records'), {'q': 'Carlos'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Carlos Mendoza')

    def test_organization_scoped_admin_cannot_see_other_organizations(self):
        other_org = Organization.objects.create(name='Otra Empresa', slug='otra')
        outsider = Person.objects.create(
            first_name='Persona', last_name='Externa', id_number='0888888888',
            birth_date=date(1985, 4, 4), gender='F', estado='activo', organization=other_org,
        )
        self.global_admin.organization = self.organization
        self.global_admin.is_superuser = False
        self.global_admin.is_staff = False
        self.global_admin.save()
        response = self.client.get(reverse('global_person_list'))
        self.assertContains(response, 'Carlos Mendoza')
        self.assertNotContains(response, outsider.id_number)

    def test_organization_scoped_admin_has_no_system_tools(self):
        self.global_admin.organization = self.organization
        self.global_admin.is_superuser = False
        self.global_admin.is_staff = False
        self.global_admin.save()
        dashboard = self.client.get(reverse('dashboard_global_admin'))
        self.assertNotContains(dashboard, 'Consulta Placas')
        self.assertNotContains(dashboard, 'Consulta Personas')
        self.assertNotContains(dashboard, 'Servidor')
        self.assertNotContains(dashboard, reverse('global_user_list'))
        self.assertEqual(self.client.get(reverse('server_status_page')).status_code, 302)
        self.assertEqual(self.client.get(reverse('global_user_list')).status_code, 302)

    def test_organization_scoped_admin_can_use_integral_hr_management(self):
        self.global_admin.organization = self.organization
        self.global_admin.is_superuser = False
        self.global_admin.is_staff = False
        self.global_admin.save()
        self.assertEqual(self.client.get(reverse('hr_management_dashboard')).status_code, 200)
        self.assertEqual(self.client.get(reverse('hr_module', args=['ingresos'])).status_code, 200)
        self.assertEqual(self.client.get(reverse('accommodation_rack')).status_code, 200)


@override_settings(SECURE_SSL_REDIRECT=False)
class HRManagementRequirementsTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Bonanza Operaciones', slug='bonanza-operaciones')
        self.other_organization = Organization.objects.create(name='Otra Operación', slug='otra-operacion')
        self.user = CustomUser.objects.create_user(
            username='rrhh-integral', password='test-password', user_type='rh', organization=self.organization
        )
        self.person = Person.objects.create(
            first_name='Maria', last_name='Velez', id_number='0701234567', birth_date=date(1991, 5, 5),
            gender='F', organization=self.organization, estado='activo', departamento='Operaciones', area='Mina',
        )
        self.room = Room.objects.create(
            organization=self.organization, camp='Bonanza', block='B1', house='Casa 1', number='12', capacity=2
        )
        self.hall = DiningHall.objects.filter(organization=self.organization).first()
        self.client.force_login(self.user)

    def test_integral_dashboard_and_all_modules_render(self):
        response = self.client.get(reverse('hr_management_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Gestión integral')
        for module in ('ingresos', 'cronograma', 'subsidios', 'descansos', 'accidentes', 'inspecciones'):
            self.assertEqual(self.client.get(reverse('hr_module', args=[module])).status_code, 200)

    def test_upcoming_entry_creates_audit_and_can_be_found_by_name_or_id(self):
        response = self.client.post(reverse('hr_module', args=['ingresos']), {
            'first_name': 'Pedro', 'last_name': 'Mora', 'id_number': '0101010101',
            'destination_camp': 'Bonanza', 'expected_entry_date': date.today(),
            'status': 'pending', 'room': self.room.pk, 'dining_hall': self.hall.pk,
        })
        self.assertEqual(response.status_code, 302)
        entry = UpcomingEntry.objects.get(id_number='0101010101')
        self.assertEqual(entry.organization, self.organization)
        self.assertTrue(HRAuditLog.objects.filter(module='ingresos', object_id=entry.pk, action='created').exists())
        self.assertContains(self.client.get(reverse('hr_module', args=['ingresos']), {'q': 'Pedro'}), '0101010101')
        self.assertContains(self.client.get(reverse('hr_module', args=['ingresos']), {'q': '010101'}), 'Pedro Mora')

    def test_person_backed_module_searches_name_and_cedula(self):
        SocialBenefitCase.objects.create(
            organization=self.organization, person=self.person, management_type='Subsidio IESS',
            responsible='Analista RRHH',
        )
        by_name = self.client.get(reverse('hr_module', args=['subsidios']), {'q': 'Maria'})
        by_id = self.client.get(reverse('hr_module', args=['subsidios']), {'q': '070123'})
        self.assertContains(by_name, self.person.id_number)
        self.assertContains(by_id, 'Maria Velez')

    def test_medical_leave_calculates_days_and_rejects_invalid_dates(self):
        url = reverse('hr_module', args=['descansos'])
        valid = self.client.post(url, {
            'person': self.person.pk, 'start_date': '2026-08-22', 'end_date': '2026-08-28',
            'expected_return_date': '2026-08-29', 'reason': 'general_illness', 'days': 1,
            'responsible': 'RRHH', 'status': 'active',
        })
        self.assertEqual(valid.status_code, 302)
        self.assertEqual(MedicalLeaveCase.objects.get().days, 7)
        invalid = self.client.post(url, {
            'person': self.person.pk, 'start_date': '2026-09-10', 'end_date': '2026-09-01',
            'expected_return_date': '2026-09-11', 'reason': 'general_illness', 'days': 1,
            'responsible': 'RRHH', 'status': 'active',
        })
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, 'no puede ser anterior', status_code=200)

    def test_accident_rejects_coverage_above_leave_total(self):
        response = self.client.post(reverse('hr_module', args=['accidentes']), {
            'person': self.person.pk, 'event_type': 'Accidente laboral', 'event_date': '2026-08-22',
            'event_place': 'Mina', 'leave_start_date': '2026-08-22', 'leave_end_date': '2026-08-24',
            'total_leave_days': 3, 'company_days': 2, 'iess_days': 2, 'procedure_status': 'notice_pending',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AccidentCase.objects.exists())
        self.assertContains(response, 'no pueden superar el total')

    def test_room_and_dining_changes_create_history(self):
        self.client.post(reverse('room_assignment_save', args=[self.room.pk]), {
            'person': self.person.pk, 'dining_hall': self.hall.pk, 'status': 'occupied',
            'check_in_date': date.today(), 'bed_label': 'Litera 2', 'notes': '',
        })
        assignment = RoomAssignment.objects.get(person=self.person)
        movement = RoomOccupancyMovement.objects.get(person=self.person, movement_type='assigned')
        self.assertEqual(movement.bed_label, 'Litera 2')
        self.client.post(reverse('room_assignment_delete', args=[assignment.pk]))
        self.assertTrue(RoomOccupancyMovement.objects.filter(person=self.person, movement_type='released').exists())
        self.assertTrue(DiningAssignmentHistory.objects.filter(person=self.person, dining_hall=self.hall).exists())

    def test_upcoming_room_reservation_reduces_real_availability(self):
        UpcomingEntry.objects.create(
            organization=self.organization, first_name='Luis', last_name='Diaz', id_number='9999999999',
            destination_camp='Bonanza', expected_entry_date=date.today() + timedelta(days=2), room=self.room,
        )
        response = self.client.get(reverse('accommodation_rack'))
        self.assertContains(response, 'Reserva por próximo ingreso')
        self.assertContains(response, '1 disponibles')

    def test_exports_xlsx_pdf_and_csv(self):
        HRInspection.objects.create(
            organization=self.organization, inspection_type='Alojamiento', camp='Bonanza', location='Casa 1',
            finding='Luminaria dañada', corrective_action='Cambiar luminaria', responsible='Mantenimiento',
            due_date=date.today() + timedelta(days=2),
        )
        expected_types = {'xlsx': 'spreadsheetml', 'pdf': 'application/pdf', 'csv': 'text/csv'}
        for output_format, content_type in expected_types.items():
            response = self.client.get(reverse('hr_module_export', args=['inspecciones', output_format]))
            self.assertEqual(response.status_code, 200)
            self.assertIn(content_type, response['Content-Type'])

    def test_records_are_strictly_scoped_to_organization(self):
        outsider = HRInspection.objects.create(
            organization=self.other_organization, inspection_type='Privada', location='Otro campamento',
            finding='No visible', corrective_action='Ninguna', responsible='Externo', due_date=date.today(),
        )
        listing = self.client.get(reverse('hr_module', args=['inspecciones']))
        self.assertNotContains(listing, 'No visible')
        edit = self.client.get(reverse('hr_module', args=['inspecciones']), {'edit': outsider.pk})
        self.assertEqual(edit.status_code, 404)


class HRAnalyticsTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Analítica', slug='analitica')
        self.person = Person.objects.create(
            first_name='Elena', last_name='Paz', id_number='0102030405',
            birth_date=date(1990, 1, 1), gender='F', estado='activo',
            organization=self.organization, departamento='Operaciones', dias_jornada=20,
        )

    def test_management_dashboard_aggregates_metrics_and_limits_queries(self):
        month_start = date(2026, 9, 1)
        month_end = date(2026, 9, 30)
        MedicalLeaveCase.objects.create(
            organization=self.organization, person=self.person, start_date=date(2026, 8, 30),
            end_date=date(2026, 9, 3), expected_return_date=date(2026, 9, 4),
            reason='general_illness', days=5, responsible='RRHH', status='active',
        )
        AccidentCase.objects.create(
            organization=self.organization, person=self.person, event_type='Caída',
            event_date=date(2026, 9, 10), event_place='Mina',
            leave_start_date=date(2026, 9, 10), leave_end_date=date(2026, 9, 11),
            total_leave_days=2, company_days=2, procedure_status='notice_pending',
        )
        AnnualActivity.objects.create(
            organization=self.organization, action_line='Capacitación', activity='Inducción',
            responsible='RRHH', execution_months=[9], status='completed',
        )

        with CaptureQueriesContext(connection) as queries:
            context = management_dashboard_context(
                self.organization, month_start, month_end, month_start, str,
            )

        self.assertEqual(context['medical_cases'], 1)
        self.assertEqual(context['medical_days'], 5)
        self.assertEqual(context['accident_count'], 1)
        self.assertEqual(context['completed_activities'], 1)
        self.assertEqual(len(context['comparison']), 6)
        self.assertLessEqual(len(queries), 23)


class PeopleImportTests(TestCase):
    def test_import_updates_and_creates_people_in_batches(self):
        organization = Organization.objects.create(name='Importación', slug='importacion')
        existing = Person.objects.create(
            first_name='Nombre anterior', last_name='Apellido anterior', id_number='0101010101',
            birth_date=date(1990, 1, 1), gender='O', organization=organization,
        )
        dataframe = pd.DataFrame([
            {'cedula': '0101010101', 'nombre': 'Elena', 'apellido': 'Vega', 'genero': 'F'},
            {'cedula': '0202020202', 'nombre': 'Luis', 'apellido': 'Mora', 'departamento': 'Mina'},
            {'cedula': '', 'nombre': 'Sin', 'apellido': 'Documento'},
        ])

        with CaptureQueriesContext(connection) as queries:
            created, updated, errors = import_people_dataframe(dataframe, organization)

        existing.refresh_from_db()
        created_person = Person.objects.get(organization=organization, id_number='0202020202')
        self.assertEqual((created, updated, errors), (1, 1, 1))
        self.assertEqual((existing.first_name, existing.gender), ('Elena', 'F'))
        self.assertEqual(created_person.departamento, 'Mina')
        self.assertLessEqual(len(queries), 6)


class DetailedPeopleSearchTests(TestCase):
    def test_search_is_organization_scoped_and_uses_batched_status_queries(self):
        organization = Organization.objects.create(name='Búsqueda', slug='busqueda')
        other_organization = Organization.objects.create(name='No visible', slug='no-visible')
        user = CustomUser.objects.create_user(
            username='operador-busqueda', password='test-password', user_type='operador', organization=organization,
        )
        visible = Person.objects.create(
            first_name='Carla', last_name='Mora', id_number='0101010101',
            birth_date=date(1990, 1, 1), gender='F', organization=organization,
        )
        Person.objects.create(
            first_name='Carla', last_name='Externa', id_number='0202020202',
            birth_date=date(1990, 1, 1), gender='F', organization=other_organization,
        )
        PermisoSalida.objects.create(
            person=visible, motivo='Trámite', fecha_inicio=date.today(), fecha_fin=date.today(), creado_por=user,
        )
        AttendanceRecord.objects.create(person=visible, record_type='entrada', recorded_by=user)

        with CaptureQueriesContext(connection) as queries:
            results = search_detailed_people(user, 'Carla', date.today())

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]['permiso_activo'])
        self.assertTrue(results[0]['esta_dentro'])
        self.assertLessEqual(len(queries), 3)


class PlateLookupQueueTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='consulta-placas', password='test-password', user_type='global_admin'
        )

    @patch('gestion_personal.management.commands.lookup_plate.consultar_placa_completa')
    def test_lookup_without_user_id_preserves_requesting_user(self, consultar):
        consultar.return_value = {
            'placa': 'ABC1234', 'placa_aliases': ['ABC1234'], 'normalized': {'tramites': []},
            'sources': {}, 'source_attempts': {}, 'errors': {},
        }
        PlateLookupRecord.objects.create(
            placa='ABC1234', lookup_status='pending', consultado_por=self.user,
            requested_at=timezone.now(),
        )
        call_command('lookup_plate', 'ABC1234', timeout_seconds=30)
        record = PlateLookupRecord.objects.get(placa='ABC1234')
        self.assertEqual(record.lookup_status, 'completed')
        self.assertEqual(record.consultado_por, self.user)

    @patch('gestion_personal.management.commands.drain_plate_lookups.fcntl.flock')
    @patch('gestion_personal.management.commands.drain_plate_lookups.subprocess.run')
    def test_drain_processes_pending_and_recovers_stale_running_records(self, run, flock):
        pending = PlateLookupRecord.objects.create(
            placa='AAA0001', lookup_status='pending', requested_at=timezone.now() - timedelta(days=2)
        )
        stale = PlateLookupRecord.objects.create(
            placa='BBB0002', lookup_status='running', requested_at=timezone.now() - timedelta(days=1),
            started_at=timezone.now() - timedelta(hours=2),
        )
        PlateLookupRecord.objects.filter(pk=stale.pk).update(updated_at=timezone.now() - timedelta(hours=2))

        def complete(command, **kwargs):
            PlateLookupRecord.objects.filter(placa=command[3]).update(lookup_status='completed')
            return subprocess.CompletedProcess(command, 0)

        run.side_effect = complete
        call_command('drain_plate_lookups', limit=0, stale_minutes=10, timeout_seconds=30, sleep=0)
        pending.refresh_from_db()
        stale.refresh_from_db()
        self.assertEqual(pending.lookup_status, 'completed')
        self.assertEqual(stale.lookup_status, 'completed')
        self.assertIn('huérfana', stale.last_error)
