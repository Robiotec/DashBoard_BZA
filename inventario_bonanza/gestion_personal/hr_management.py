import calendar
import csv
from datetime import date, datetime
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .forms import (
    AccidentCaseForm,
    AnnualActivityForm,
    HRInspectionForm,
    MedicalLeaveCaseForm,
    SocialBenefitCaseForm,
    UpcomingEntryForm,
)
from .models import (
    AccidentCase,
    AnnualActivity,
    HRAuditLog,
    HRInspection,
    MedicalLeaveCase,
    Person,
    SocialBenefitCase,
    UpcomingEntry,
)
from .services.hr_analytics import management_dashboard_context


def is_rh_manager(user):
    return user.is_authenticated and user.organization_id and user.user_type in ('rh', 'global_admin')


MODULES = {
    'ingresos': {
        'title': 'Próximos ingresos', 'singular': 'próximo ingreso', 'icon': 'fa-person-walking-arrow-right',
        'model': UpcomingEntry, 'form': UpcomingEntryForm, 'date_field': 'expected_entry_date', 'status_field': 'status',
        'search': ('first_name', 'last_name', 'id_number', 'company', 'department', 'destination_camp'),
        'select': ('room', 'dining_hall'),
        'export': (
            ('expected_entry_date', 'Fecha ingreso'), ('first_name', 'Nombres'), ('last_name', 'Apellidos'),
            ('id_number', 'Cédula'), ('company', 'Empresa'), ('position', 'Cargo'), ('department', 'Departamento'),
            ('shift_group', 'Grupo'), ('destination_camp', 'Campamento'), ('status_display', 'Estado'),
            ('requirements', 'Requisitos'), ('room', 'Habitación'), ('dining_hall', 'Comedor'),
        ),
    },
    'cronograma': {
        'title': 'Cronograma anual', 'singular': 'actividad', 'icon': 'fa-calendar-check',
        'model': AnnualActivity, 'form': AnnualActivityForm, 'date_field': 'planned_date', 'status_field': 'status',
        'search': ('action_line', 'activity', 'target_population', 'responsible'), 'select': (),
        'export': (
            ('action_line', 'Línea de acción'), ('activity', 'Actividad'), ('target_population', 'Población'),
            ('responsible', 'Responsable'), ('months', 'Meses'), ('planned_date', 'Fecha planificada'),
            ('due_date', 'Fecha límite'), ('status_display', 'Estado'), ('progress', 'Avance %'), ('evidence_state', 'Evidencia'),
        ),
    },
    'subsidios': {
        'title': 'Subsidios y prestaciones', 'singular': 'caso', 'icon': 'fa-hand-holding-medical',
        'model': SocialBenefitCase, 'form': SocialBenefitCaseForm, 'date_field': 'case_date', 'status_field': 'status',
        'search': ('person__first_name', 'person__last_name', 'person__id_number', 'management_type', 'responsible', 'pending_documents'),
        'select': ('person',),
        'export': (
            ('case_date', 'Fecha'), ('person', 'Colaborador'), ('person_id_number', 'Cédula'),
            ('management_type', 'Tipo'), ('status_display', 'Estado'), ('pending_documents', 'Documentos pendientes'),
            ('pending_action', 'Acción pendiente'), ('responsible', 'Responsable'), ('close_date', 'Cierre'),
        ),
    },
    'descansos': {
        'title': 'Descansos y reincorporación', 'singular': 'descanso médico', 'icon': 'fa-briefcase-medical',
        'model': MedicalLeaveCase, 'form': MedicalLeaveCaseForm, 'date_field': 'start_date', 'status_field': 'status',
        'search': ('person__first_name', 'person__last_name', 'person__id_number', 'person__area', 'person__departamento', 'responsible'),
        'select': ('person',),
        'export': (
            ('start_date', 'Inicio'), ('end_date', 'Fin'), ('person', 'Colaborador'), ('person_id_number', 'Cédula'),
            ('reason_display', 'Motivo general'), ('days', 'Días'), ('expected_return_date', 'Reintegro previsto'),
            ('status_display', 'Estado'), ('responsible', 'Responsable'), ('next_review_date', 'Próxima revisión'),
        ),
    },
    'accidentes': {
        'title': 'Accidentes y cobertura', 'singular': 'accidente', 'icon': 'fa-triangle-exclamation',
        'model': AccidentCase, 'form': AccidentCaseForm, 'date_field': 'event_date', 'status_field': 'procedure_status',
        'search': ('person__first_name', 'person__last_name', 'person__id_number', 'event_type', 'event_place'),
        'select': ('person', 'medical_leave', 'benefit_case'),
        'export': (
            ('event_date', 'Fecha'), ('person', 'Colaborador'), ('person_id_number', 'Cédula'),
            ('event_type', 'Evento'), ('event_place', 'Lugar'), ('total_leave_days', 'Días totales'),
            ('company_days', 'Días empresa'), ('iess_days', 'Días IESS'), ('procedure_status_display', 'Trámite'),
            ('return_date', 'Reincorporación'),
        ),
    },
    'inspecciones': {
        'title': 'Inspecciones y seguimiento', 'singular': 'inspección', 'icon': 'fa-clipboard-check',
        'model': HRInspection, 'form': HRInspectionForm, 'date_field': 'inspection_date', 'status_field': 'status',
        'search': ('inspection_type', 'camp', 'location', 'finding', 'corrective_action', 'responsible'), 'select': (),
        'export': (
            ('inspection_date', 'Fecha'), ('inspection_type', 'Tipo'), ('camp', 'Campamento'), ('location', 'Lugar'),
            ('finding', 'Hallazgo'), ('priority_display', 'Prioridad'), ('corrective_action', 'Acción'),
            ('responsible', 'Responsable'), ('due_date', 'Plazo'), ('status_display', 'Estado'),
        ),
    },
}


def _config(module):
    try:
        return MODULES[module]
    except KeyError as exc:
        raise Http404('Módulo no encontrado') from exc


def _parse_date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date() if value else None
    except ValueError:
        return None


def _module_queryset(request, module):
    config = _config(module)
    queryset = config['model'].objects.filter(organization=request.user.organization)
    if config['select']:
        queryset = queryset.select_related(*config['select'])
    query = request.GET.get('q', '').strip()
    if query:
        search_q = Q()
        for field in config['search']:
            search_q |= Q(**{f'{field}__icontains': query})
        queryset = queryset.filter(search_q)
    status = request.GET.get('status', '').strip()
    if status:
        queryset = queryset.filter(**{config['status_field']: status})
    date_from = _parse_date(request.GET.get('date_from'))
    date_to = _parse_date(request.GET.get('date_to'))
    if date_from:
        queryset = queryset.filter(**{f"{config['date_field']}__gte": date_from})
    if date_to:
        queryset = queryset.filter(**{f"{config['date_field']}__lte": date_to})
    department = request.GET.get('department', '').strip()
    if department:
        if module in ('subsidios', 'descansos', 'accidentes'):
            queryset = queryset.filter(person__departamento=department)
        elif module == 'ingresos':
            queryset = queryset.filter(department=department)
    if module == 'ingresos':
        company = request.GET.get('company', '').strip()
        group = request.GET.get('group', '').strip()
        if company:
            queryset = queryset.filter(company=company)
        if group:
            queryset = queryset.filter(shift_group=group)
    camp = request.GET.get('camp', '').strip()
    if camp:
        camp_field = {'ingresos': 'destination_camp', 'inspecciones': 'camp'}.get(module)
        if camp_field:
            queryset = queryset.filter(**{camp_field: camp})
    return queryset


def _object_label(obj):
    person = getattr(obj, 'person', None)
    if person:
        return f'{person.first_name} {person.last_name} - {person.id_number}'
    if isinstance(obj, UpcomingEntry):
        return f'{obj.first_name} {obj.last_name} - {obj.id_number}'
    if isinstance(obj, AnnualActivity):
        return obj.action_line
    if isinstance(obj, HRInspection):
        return f'{obj.inspection_type} - {obj.location}'
    return f'{obj._meta.verbose_name} #{obj.pk}'


def _audit(request, module, obj, action, detail=''):
    HRAuditLog.objects.create(
        organization=request.user.organization, module=module, object_id=obj.pk,
        object_label=_object_label(obj), action=action, detail=detail, user=request.user,
    )


def _status_choices(config):
    field = config['model']._meta.get_field(config['status_field'])
    return field.choices


@login_required
@user_passes_test(is_rh_manager)
def hr_management_dashboard(request):
    today = timezone.localdate()
    month_value = request.GET.get('month', today.strftime('%Y-%m'))
    try:
        year, month = (int(value) for value in month_value.split('-', 1))
        month_start = date(year, month, 1)
    except (TypeError, ValueError):
        month_start = today.replace(day=1)
        month_value = month_start.strftime('%Y-%m')
    month_end = date(month_start.year, month_start.month, calendar.monthrange(month_start.year, month_start.month)[1])
    context = management_dashboard_context(
        request.user.organization, month_start, month_end, today, _object_label,
    )
    context.update({'modules': MODULES, 'month_value': month_value})
    return render(request, 'gestion_personal/rh/hr_management_dashboard.html', context)


@login_required
@user_passes_test(is_rh_manager)
def hr_module(request, module):
    config = _config(module)
    edit_id = request.POST.get('edit_id') if request.method == 'POST' else request.GET.get('edit')
    instance = None
    if edit_id:
        instance = get_object_or_404(config['model'], pk=edit_id, organization=request.user.organization)
    if request.method == 'POST':
        form = config['form'](request.POST, request.FILES, instance=instance, organization=request.user.organization)
        if form.is_valid():
            changed = ', '.join(form.changed_data)
            obj = form.save(commit=False)
            obj.organization = request.user.organization
            if not obj.pk:
                obj.created_by = request.user
            obj.updated_by = request.user
            obj.save()
            _audit(request, module, obj, 'updated' if instance else 'created', f'Campos: {changed}')
            messages.success(request, f'{config["singular"].capitalize()} guardado correctamente.')
            return redirect('hr_module', module=module)
        messages.error(request, 'Revise los campos señalados antes de guardar.')
    else:
        form = config['form'](instance=instance, organization=request.user.organization)
    queryset = _module_queryset(request, module)
    departments = Person.objects.filter(organization=request.user.organization).exclude(departamento='').values_list('departamento', flat=True).distinct().order_by('departamento')
    camps = []
    if module == 'ingresos':
        upcoming = UpcomingEntry.objects.filter(organization=request.user.organization)
        camps = upcoming.exclude(destination_camp='').values_list('destination_camp', flat=True).distinct().order_by('destination_camp')
        departments = upcoming.exclude(department='').values_list('department', flat=True).distinct().order_by('department')
    elif module == 'inspecciones':
        camps = HRInspection.objects.filter(organization=request.user.organization).exclude(camp='').values_list('camp', flat=True).distinct().order_by('camp')
    return render(request, 'gestion_personal/rh/hr_module.html', {
        'module': module, 'config': config, 'modules': MODULES, 'records': queryset[:500], 'form': form,
        'editing': instance, 'status_choices': _status_choices(config), 'departments': departments, 'camps': camps,
        'companies': UpcomingEntry.objects.filter(organization=request.user.organization).exclude(company='').values_list('company', flat=True).distinct().order_by('company') if module == 'ingresos' else (),
        'groups': UpcomingEntry.objects.filter(organization=request.user.organization).exclude(shift_group='').values_list('shift_group', flat=True).distinct().order_by('shift_group') if module == 'ingresos' else (),
    })


@login_required
@user_passes_test(is_rh_manager)
@require_POST
def hr_module_delete(request, module, pk):
    config = _config(module)
    obj = get_object_or_404(config['model'], pk=pk, organization=request.user.organization)
    label = _object_label(obj)
    object_id = obj.pk
    obj.delete()
    HRAuditLog.objects.create(
        organization=request.user.organization, module=module, object_id=object_id,
        object_label=label, action='deleted', detail='Registro eliminado', user=request.user,
    )
    messages.success(request, f'{config["singular"].capitalize()} eliminado correctamente.')
    return redirect('hr_module', module=module)


def _export_value(obj, key):
    if key == 'status_display':
        return obj.get_status_display()
    if key == 'procedure_status_display':
        return obj.get_procedure_status_display()
    if key == 'reason_display':
        return obj.get_reason_display()
    if key == 'priority_display':
        return obj.get_priority_display()
    if key == 'person_id_number':
        return obj.person.id_number
    if key == 'requirements':
        return 'Completos' if obj.requirements_complete else 'Pendientes'
    if key == 'months':
        return ', '.join(calendar.month_name[value].title() for value in obj.execution_months)
    if key == 'evidence_state':
        return 'Cargada' if obj.evidence or obj.evidence_link else 'Pendiente'
    value = getattr(obj, key, '')
    if callable(value):
        value = value()
    if isinstance(value, (date, datetime)):
        return value.strftime('%d/%m/%Y')
    return str(value or '')


@login_required
@user_passes_test(is_rh_manager)
def hr_module_export(request, module, output_format):
    config = _config(module)
    records = list(_module_queryset(request, module))
    headers = [label for _, label in config['export']]
    rows = [[_export_value(obj, key) for key, _ in config['export']] for obj in records]
    filename = f'{module}-{timezone.localdate():%Y%m%d}'
    if output_format == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow(headers)
        writer.writerows(rows)
    elif output_format == 'xlsx':
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = config['title'][:31]
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(max(len(str(cell.value or '')) for cell in column) + 2, 45)
        stream = BytesIO()
        workbook.save(stream)
        response = HttpResponse(stream.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
    elif output_format == 'pdf':
        stream = BytesIO()
        document = SimpleDocTemplate(stream, pagesize=landscape(A4), leftMargin=1 * cm, rightMargin=1 * cm, topMargin=1 * cm, bottomMargin=1 * cm)
        styles = getSampleStyleSheet()
        data = [[Paragraph(str(value), styles['BodyText']) for value in headers]]
        data.extend([[Paragraph(str(value), styles['BodyText']) for value in row] for row in rows])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#12304a')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), .3, colors.HexColor('#b8c2cc')), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTSIZE', (0, 0), (-1, -1), 7), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f6f8')]),
        ]))
        document.build([Paragraph(config['title'], styles['Title']), Spacer(1, .3 * cm), table])
        response = HttpResponse(stream.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'
    else:
        raise Http404('Formato no soportado')
    HRAuditLog.objects.create(
        organization=request.user.organization, module=module, object_id=0, object_label=config['title'],
        action='exported', detail=f'{len(records)} registros en {output_format.upper()}', user=request.user,
    )
    return response


@login_required
@user_passes_test(is_rh_manager)
def hr_evidence(request, module, pk):
    config = _config(module)
    obj = get_object_or_404(config['model'], pk=pk, organization=request.user.organization)
    evidence = getattr(obj, 'evidence', None)
    if not evidence:
        raise Http404('El registro no tiene evidencia')
    _audit(request, module, obj, 'viewed', 'Consulta de evidencia')
    evidence.open('rb')
    return FileResponse(evidence, as_attachment=False, filename=evidence.name.rsplit('/', 1)[-1])
