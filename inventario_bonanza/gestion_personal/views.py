from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.urls import reverse_lazy, reverse
from django.utils.decorators import method_decorator
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.conf import settings
from datetime import date, datetime, timedelta
from django.http import FileResponse, JsonResponse, HttpResponse
from django.db.models import Count, Q
from django import forms as django_forms
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
import calendar
import csv
import fcntl
import json
import os
import platform
import subprocess
import shutil
import socket
import sys
import tempfile
import traceback
import time
from urllib.parse import urlencode
import pandas as pd
import xlwt
import zipfile
import mimetypes
import requests

from django.db import connection
from .models import *
from .forms import *
from .plate_lookup import normalize_plate, plate_variants
from .person_lookup import normalize_cedula


PS_COMMAND = "/usr/bin/ps" if os.path.exists("/usr/bin/ps") else "/bin/ps"

#Nuevos
# Funciones para verificar roles
def is_operador(user):
    return user.is_authenticated and user.user_type == 'operador'

def is_rh(user):
    return user.is_authenticated and user.user_type == 'rh'

def is_rh_or_global(user):
    return user.is_authenticated and user.user_type in ['rh', 'global_admin']

def is_medico(user):
    return user.is_authenticated and user.user_type == 'medico'

def is_admin_mina(user):
    return user.is_authenticated and user.user_type == 'admin_mina'

def is_admin_molino(user):
    return user.is_authenticated and user.user_type == 'admin_molino'

def is_seguridad_fisica(user):
    return user.is_authenticated and user.user_type == 'seguridad_fisica'

def is_tecnico_seguridad(user):
    return user.is_authenticated and user.user_type == 'tecnico_seguridad'

def is_any_admin(user):
    return user.is_authenticated and user.user_type in ['admin_mina', 'admin_molino']

def is_global_admin(user):
    return user.is_authenticated and user.user_type == 'global_admin'


def _bytes_to_human(value):
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024


def _read_proc_file(path):
    try:
        with open(path, "r") as proc_file:
            return proc_file.read()
    except OSError:
        return ""


def _cpu_snapshot():
    line = (_read_proc_file("/proc/stat").splitlines() or [""])[0]
    parts = line.split()
    if not parts or parts[0] != "cpu":
        return None
    values = [int(part) for part in parts[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return idle, sum(values)


def _cpu_percent():
    first = _cpu_snapshot()
    if not first:
        return None
    time.sleep(0.12)
    second = _cpu_snapshot()
    if not second:
        return None
    idle_delta = second[0] - first[0]
    total_delta = second[1] - first[1]
    if total_delta <= 0:
        return None
    return round((1 - idle_delta / total_delta) * 100, 1)


def _memory_status():
    meminfo = {}
    for line in _read_proc_file("/proc/meminfo").splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        parts = raw_value.strip().split()
        if parts and parts[0].isdigit():
            meminfo[key] = int(parts[0]) * 1024
    total = meminfo.get("MemTotal", 0)
    available = meminfo.get("MemAvailable", 0)
    used = max(0, total - available)
    percent = round((used / total) * 100, 1) if total else None
    return {
        "total": total,
        "used": used,
        "available": available,
        "percent": percent,
        "total_human": _bytes_to_human(total),
        "used_human": _bytes_to_human(used),
        "available_human": _bytes_to_human(available),
    }


def _disk_status(paths=None):
    disks = []
    seen = set()
    for path in paths or ["/", str(settings.BASE_DIR), "/home"]:
        if not os.path.exists(path):
            continue
        real_path = os.path.realpath(path)
        if real_path in seen:
            continue
        seen.add(real_path)
        usage = shutil.disk_usage(path)
        percent = round((usage.used / usage.total) * 100, 1) if usage.total else None
        disks.append({
            "path": path,
            "total": usage.total,
            "used": usage.used,
            "available": usage.free,
            "percent": percent,
            "total_human": _bytes_to_human(usage.total),
            "used_human": _bytes_to_human(usage.used),
            "available_human": _bytes_to_human(usage.free),
        })
    return disks


def _uptime_status():
    raw = _read_proc_file("/proc/uptime").split()
    seconds = int(float(raw[0])) if raw else 0
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    return {
        "seconds": seconds,
        "human": f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m",
    }


def _process_status():
    result = {
        "gunicorn": 0,
        "lookup_person": 0,
        "lookup_plate": 0,
        "drain_person_lookups": 0,
        "drain_plate_lookups": 0,
    }
    try:
        active = subprocess.run(
            [PS_COMMAND, "-eo", "args="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return result
    for line in (active.stdout or "").splitlines():
        for key in result:
            if key in line:
                result[key] += 1
    return result


def _database_status():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return {"ok": True, "message": "Conectada"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def get_server_status_payload():
    load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (None, None, None)
    return {
        "ok": True,
        "generated_at": timezone.now().isoformat(),
        "host": {
            "hostname": socket.gethostname(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "uptime": _uptime_status(),
        "cpu": {
            "percent": _cpu_percent(),
            "cores": os.cpu_count(),
            "load_avg": {
                "1m": round(load_avg[0], 2) if load_avg[0] is not None else None,
                "5m": round(load_avg[1], 2) if load_avg[1] is not None else None,
                "15m": round(load_avg[2], 2) if load_avg[2] is not None else None,
            },
        },
        "memory": _memory_status(),
        "disks": _disk_status(),
        "database": _database_status(),
        "processes": _process_status(),
        "queues": {
            "plates": PlateLookupRecord.objects.aggregate(
                pending=Count("id", filter=Q(lookup_status="pending")),
                running=Count("id", filter=Q(lookup_status="running")),
                failed=Count("id", filter=Q(lookup_status="failed")),
            ),
            "people": PersonLookupRecord.objects.aggregate(
                pending=Count("id", filter=Q(lookup_status="pending")),
                running=Count("id", filter=Q(lookup_status="running")),
                failed=Count("id", filter=Q(lookup_status="failed")),
            ),
        },
    }

def organization_filter_for(user):
    if getattr(user, 'user_type', None) == 'global_admin':
        return Q()
    if getattr(user, 'organization_id', None):
        return Q(organization=user.organization)
    return Q(organization__isnull=True)

def person_queryset_for(user):
    return Person.objects.filter(organization_filter_for(user))

def person_by_cedula_for_user(user, cedula):
    return person_queryset_for(user).filter(id_number=cedula).first()

def send_telegram_access_alert(message, person=None):
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    chat_ids = getattr(settings, 'TELEGRAM_CHAT_IDS', [])
    if not token or not chat_ids:
        return

    caption = message.strip()
    if len(caption) > 1024:
        caption = caption[:1000] + "\n..."

    for chat_id in chat_ids:
        try:
            if person and person.foto:
                person.foto.open('rb')
                try:
                    response = requests.post(
                        f"https://api.telegram.org/bot{token}/sendPhoto",
                        data={'chat_id': chat_id, 'caption': caption},
                        files={'photo': person.foto.file},
                        timeout=15,
                    )
                finally:
                    person.foto.close()
            else:
                response = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data={'chat_id': chat_id, 'text': caption},
                    timeout=15,
                )
            response.raise_for_status()
        except Exception as e:
            print(f"Error al enviar alerta Telegram: {e}")


def access_alert_message(title, cedula=None, person=None, user=None, detail=None):
    now = timezone.localtime()
    lines = [
        "ALERTA DE CONTROL DE PERSONAL",
        "",
        title,
    ]
    if person:
        lines.extend([
            f"Persona: {person.first_name} {person.last_name}",
            f"Cédula: {person.id_number}",
            f"Estado: {person.get_estado_display()}",
        ])
    elif cedula:
        lines.append(f"Cédula: {cedula}")
    if detail:
        lines.append(f"Detalle: {detail}")
    if user and getattr(user, 'is_authenticated', False):
        lines.append(f"Registrado por: {user.username}")
    lines.append(f"Fecha y hora: {now.strftime('%d/%m/%Y %H:%M:%S')}")
    return "\n".join(lines)


def filename_part(value):
    text = str(value or '').strip()
    cleaned = ''.join(char if char.isalnum() or char in ('-', '_') else '_' for char in text)
    return cleaned.strip('_') or 'sin_dato'


def person_active_response(persona, action="marcación", user=None):
    if persona.estado != 'activo':
        send_telegram_access_alert(
            access_alert_message(
                f"Intento de {action} con personal pasivo.",
                person=persona,
                user=user,
                detail="El personal pasivo no puede marcar como trabajador activo.",
            ),
            person=persona,
        )
        return JsonResponse({
            "status": "error",
            "error": "La persona está en estado pasivo y no puede marcar ingreso o salida como personal activo.",
            "message": "La persona está en estado pasivo y no puede marcar ingreso o salida como personal activo.",
        })
    return None

def has_active_exit_authorization(persona, today=None):
    today = today or timezone.now().date()
    permiso_activo = PermisoSalida.objects.filter(
        person=persona,
        fecha_inicio__lte=today,
        fecha_fin__gte=today,
    ).exists()
    vacaciones_activas = VacationRecord.objects.filter(
        person=persona,
        start_date__lte=today,
        end_date__gte=today,
    ).exists()
    return permiso_activo or vacaciones_activas

MIN_MINUTES_BETWEEN_ATTENDANCE = 5
RECORD_LIST_LIMIT = 300

SPANISH_MONTHS = {
    1: 'Enero',
    2: 'Febrero',
    3: 'Marzo',
    4: 'Abril',
    5: 'Mayo',
    6: 'Junio',
    7: 'Julio',
    8: 'Agosto',
    9: 'Septiembre',
    10: 'Octubre',
    11: 'Noviembre',
    12: 'Diciembre',
}

WORKDAY_STATUS_META = {
    'worked': {'label': 'Trabajó', 'short': '1', 'class': 'workday-worked'},
    'free': {'label': 'Día libre', 'short': 'D', 'class': 'workday-free'},
    'vacation': {'label': 'Vacaciones anuales', 'short': 'V', 'class': 'workday-vacation'},
    'permission': {'label': 'Permiso', 'short': 'P', 'class': 'workday-permission'},
    'absent': {'label': 'No trabajó', 'short': 'F', 'class': 'workday-absent'},
    'late_return': {'label': 'Regresó tarde', 'short': 'T', 'class': 'workday-late'},
}


def attendance_wait_response(ultimo_registro):
    if not ultimo_registro:
        return None

    elapsed = timezone.now() - ultimo_registro.timestamp
    wait_time = timedelta(minutes=MIN_MINUTES_BETWEEN_ATTENDANCE)
    if elapsed >= wait_time:
        return None

    remaining_seconds = int((wait_time - elapsed).total_seconds())
    remaining_minutes = max(1, (remaining_seconds + 59) // 60)
    message = (
        f"Debe esperar al menos {MIN_MINUTES_BETWEEN_ATTENDANCE} minutos entre marcaciones. "
        f"Intente nuevamente en {remaining_minutes} minuto(s)."
    )
    return JsonResponse({"status": "error", "error": message, "message": message})


def selected_month_bounds(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
        if month < 1 or month > 12:
            raise ValueError
    except (TypeError, ValueError):
        year = today.year
        month = today.month

    last_day = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)
    days = [date(year, month, day) for day in range(1, last_day + 1)]
    return year, month, start_date, end_date, days


def inferred_workday_status(person_id, day, vacation_days, permission_days, attendance_days):
    if (person_id, day) in vacation_days:
        return 'vacation'
    if (person_id, day) in permission_days:
        return 'permission'
    if (person_id, day) in attendance_days:
        return 'worked'
    return ''


def build_monthly_workday_rows(people, days, existing_records, vacation_days, permission_days, attendance_days):
    rows = []
    for person in people:
        cells = []
        counts = {key: 0 for key in WORKDAY_STATUS_META}
        for day in days:
            record = existing_records.get((person.id, day))
            status = record.status if record else inferred_workday_status(
                person.id, day, vacation_days, permission_days, attendance_days
            )
            is_inferred = record is None and bool(status)
            meta = WORKDAY_STATUS_META.get(status, {})
            if status in counts:
                counts[status] += 1
            cells.append({
                'date': day,
                'status': status,
                'short': meta.get('short', ''),
                'label': meta.get('label', ''),
                'class': meta.get('class', 'workday-empty'),
                'is_inferred': is_inferred,
            })
        rows.append({
            'person': person,
            'cells': cells,
            'worked_days': counts['worked'],
            'free_days': counts['free'],
            'vacation_days': counts['vacation'],
            'permission_days': counts['permission'],
            'absent_days': counts['absent'],
            'late_days': counts['late_return'],
        })
    return rows


@login_required
def private_media(request, path):
    if not default_storage.exists(path):
        return HttpResponse(status=404)

    content_type, _ = mimetypes.guess_type(path)
    response = HttpResponse(
        default_storage.open(path, 'rb').read(),
        content_type=content_type or 'application/octet-stream',
    )
    response['Cache-Control'] = 'private, max-age=300'
    return response

#Redireccionamiento por Rol
@login_required
def role_based_redirect(request):
    """
    Redirige al usuario a su dashboard correspondiente según su rol
    """
    user = request.user
    
    if user.user_type == 'global_admin':
        return redirect('dashboard_global_admin')
    elif user.user_type == 'medico':
        return redirect('dashboard_medico')
    elif user.user_type == 'rh':
        return redirect('dashboard_rrhh')
    elif user.user_type == 'operador':
        return redirect('dashboard_operador')
    elif user.user_type == 'admin_mina' or user.user_type == 'admin_molino':
        return redirect('dashboard_admin')
    elif user.user_type == 'seguridad_fisica':
        return redirect('dashboard_seguridad')
    elif user.user_type == 'tecnico_seguridad':
        return redirect('dashboard_tecnico')
    else:
        # Si no tiene un rol específico, redirigir a una página genérica
        messages.warning(request, "Su rol de usuario no tiene un panel asignado. Contacte al administrador.")
        return redirect('login')


@login_required
@user_passes_test(is_global_admin)
def dashboard_global_admin(request):
    organizaciones = Organization.objects.annotate(
        user_count=Count('users', distinct=True),
        people_count=Count('people', distinct=True),
        people_photo_count=Count(
            'people',
            filter=Q(people__foto__isnull=False) & ~Q(people__foto=''),
            distinct=True,
        ),
    ).order_by('name')
    for organization in organizaciones:
        organization.people_without_photo_count = organization.people_count - organization.people_photo_count
    total_personas = Person.objects.count()
    total_personas_con_foto = Person.objects.exclude(foto='').exclude(foto__isnull=True).count()
    context = {
        'total_organizaciones': Organization.objects.count(),
        'organizaciones_activas': Organization.objects.filter(is_active=True).count(),
        'total_usuarios': CustomUser.objects.count(),
        'total_personas': total_personas,
        'total_personas_con_foto': total_personas_con_foto,
        'total_personas_sin_foto': total_personas - total_personas_con_foto,
        'organizaciones': organizaciones,
        'usuarios_recientes': CustomUser.objects.select_related('organization').order_by('-date_joined')[:10],
    }
    return render(request, 'gestion_personal/global_admin/dashboard.html', context)


@login_required
@user_passes_test(is_global_admin)
def server_status_api(request):
    return JsonResponse(get_server_status_payload())


@login_required
@user_passes_test(is_global_admin)
def server_status_page(request):
    return render(
        request,
        'gestion_personal/global_admin/server_status.html',
        {'server_status': get_server_status_payload()},
    )


@method_decorator(user_passes_test(is_global_admin), name='dispatch')
class OrganizationListView(ListView):
    model = Organization
    template_name = 'gestion_personal/global_admin/organization_list.html'
    context_object_name = 'organizaciones'

    def get_queryset(self):
        return Organization.objects.annotate(
            user_count=Count('users', distinct=True),
            people_count=Count('people', distinct=True),
        ).order_by('name')


@method_decorator(user_passes_test(is_global_admin), name='dispatch')
class OrganizationDetailView(DetailView):
    model = Organization
    template_name = 'gestion_personal/global_admin/organization_detail.html'
    context_object_name = 'organizacion'

    def get_queryset(self):
        return Organization.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organizacion = self.object
        people_qs = organizacion.people.all()
        vehicles_qs = organizacion.vehicles.all()
        context.update({
            'usuarios': organizacion.users.order_by('username'),
            'personas': people_qs.order_by('last_name', 'first_name')[:25],
            'vehiculos_recientes': vehicles_qs.order_by('-fecha_ingreso')[:10],
            'total_personas_activas': people_qs.filter(estado='activo').count(),
            'total_personas_pasivas': people_qs.filter(estado='pasivo').count(),
            'total_vehiculos': vehicles_qs.count(),
        })
        return context


@method_decorator(user_passes_test(is_global_admin), name='dispatch')
class OrganizationCreateView(CreateView):
    model = Organization
    form_class = OrganizationForm
    template_name = 'gestion_personal/global_admin/organization_form.html'
    success_url = reverse_lazy('organization_list')

    def form_valid(self, form):
        messages.success(self.request, 'Organización creada correctamente.')
        return super().form_valid(form)


@method_decorator(user_passes_test(is_global_admin), name='dispatch')
class OrganizationUpdateView(UpdateView):
    model = Organization
    form_class = OrganizationForm
    template_name = 'gestion_personal/global_admin/organization_form.html'
    success_url = reverse_lazy('organization_list')

    def form_valid(self, form):
        messages.success(self.request, 'Organización actualizada correctamente.')
        return super().form_valid(form)


@method_decorator(user_passes_test(is_global_admin), name='dispatch')
class GlobalUserListView(ListView):
    model = CustomUser
    template_name = 'gestion_personal/global_admin/user_list.html'
    context_object_name = 'usuarios'

    def get_queryset(self):
        return CustomUser.objects.select_related('organization').order_by('organization__name', 'username')


@method_decorator(user_passes_test(is_global_admin), name='dispatch')
class GlobalUserCreateView(CreateView):
    model = CustomUser
    form_class = CustomUserCreationForm
    template_name = 'gestion_personal/global_admin/user_form.html'
    success_url = reverse_lazy('global_user_list')

    def form_valid(self, form):
        messages.success(self.request, 'Usuario creado correctamente.')
        return super().form_valid(form)


@method_decorator(user_passes_test(is_global_admin), name='dispatch')
class GlobalUserUpdateView(UpdateView):
    model = CustomUser
    form_class = CustomUserChangeForm
    template_name = 'gestion_personal/global_admin/user_form.html'
    success_url = reverse_lazy('global_user_list')

    def form_valid(self, form):
        messages.success(self.request, 'Usuario actualizado correctamente.')
        return super().form_valid(form)


@login_required
@user_passes_test(is_global_admin)
def global_records(request):
    fecha_str = request.GET.get('fecha')
    if fecha_str:
        try:
            fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha_obj = timezone.localdate()
    else:
        fecha_obj = timezone.localdate()

    organization_id = request.GET.get('organization', '')
    cedula = request.GET.get('cedula', '').strip()

    registros_personal = AttendanceRecord.objects.select_related(
        'person', 'person__organization', 'recorded_by'
    ).filter(timestamp__date=fecha_obj)
    registros_vehiculos = VehicleRecord.objects.select_related(
        'organization', 'registrado_por', 'salida_registrada_por'
    ).filter(
        Q(fecha_ingreso__date=fecha_obj) |
        Q(fecha_salida__date=fecha_obj)
    )

    if organization_id.isdigit():
        registros_personal = registros_personal.filter(person__organization_id=organization_id)
        registros_vehiculos = registros_vehiculos.filter(organization_id=organization_id)

    if cedula:
        registros_personal = registros_personal.filter(person__id_number__icontains=cedula)
        registros_vehiculos = registros_vehiculos.filter(
            Q(chofer_cedula__icontains=cedula) |
            Q(chofer__id_number__icontains=cedula)
        )

    total_personal = registros_personal.count()
    total_entradas = registros_personal.filter(record_type='entrada').count()
    total_salidas = registros_personal.filter(record_type='salida').count()
    total_vehiculos = registros_vehiculos.count()
    vehiculos_dentro = registros_vehiculos.filter(fecha_salida__isnull=True).count()

    registros_personal = registros_personal.order_by('-timestamp')[:RECORD_LIST_LIMIT]
    registros_vehiculos = registros_vehiculos.order_by('-fecha_ingreso')[:RECORD_LIST_LIMIT]

    context = {
        'fecha': fecha_obj.strftime('%Y-%m-%d'),
        'organizaciones': Organization.objects.order_by('name'),
        'selected_organization': organization_id,
        'cedula': cedula,
        'registros_personal': registros_personal,
        'registros_vehiculos': registros_vehiculos,
        'registros_limit': RECORD_LIST_LIMIT,
        'total_personal': total_personal,
        'total_entradas': total_entradas,
        'total_salidas': total_salidas,
        'total_vehiculos': total_vehiculos,
        'vehiculos_dentro': vehiculos_dentro,
        'personal_limited': total_personal > RECORD_LIST_LIMIT,
        'vehiculos_limited': total_vehiculos > RECORD_LIST_LIMIT,
    }
    return render(request, 'gestion_personal/global_admin/records.html', context)


@login_required
@user_passes_test(is_global_admin)
def global_people_csv(request):
    organization_id = request.GET.get('organization', '')
    search = request.GET.get('q', '')
    estado = request.GET.get('estado', '')
    foto = request.GET.get('foto', '')
    personas = Person.objects.select_related('organization').order_by(
        'organization__name', 'last_name', 'first_name'
    )
    organization = None
    if organization_id.isdigit():
        organization = get_object_or_404(Organization, id=organization_id)
        personas = personas.filter(organization=organization)
    if search:
        personas = personas.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(id_number__icontains=search)
        )
    if estado in ['activo', 'pasivo']:
        personas = personas.filter(estado=estado)
    if foto == 'con':
        personas = personas.exclude(foto='').exclude(foto__isnull=True)
    elif foto == 'sin':
        personas = personas.filter(Q(foto='') | Q(foto__isnull=True))

    suffix = filename_part(organization.slug if organization else 'todas_las_organizaciones')
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="personas_{suffix}.csv"'
    response.write('\ufeff')

    writer = csv.writer(response)
    writer.writerow([
        'Organización',
        'Nombre',
        'Apellido',
        'Cédula',
        'Fecha de nacimiento',
        'Género',
        'Teléfono',
        'Correo',
        'Dirección',
        'Cargo',
        'Departamento',
        'Área',
        'Fecha de ingreso',
        'Estado',
        'Fecha de egreso',
        'Contacto emergencia',
        'Revisión médica',
        'Fecha última revisión',
        'Observaciones jornada',
        'Anotaciones RRHH',
        'Foto',
    ])

    for persona in personas:
        writer.writerow([
            persona.organization.name if persona.organization else '',
            persona.first_name,
            persona.last_name,
            persona.id_number,
            persona.birth_date.strftime('%Y-%m-%d') if persona.birth_date else '',
            persona.get_gender_display(),
            persona.phone_number or '',
            persona.email or '',
            persona.address or '',
            persona.cargo or '',
            persona.departamento or '',
            persona.area or '',
            persona.fecha_ingreso.strftime('%Y-%m-%d') if persona.fecha_ingreso else '',
            persona.get_estado_display(),
            persona.fecha_egreso.strftime('%Y-%m-%d') if persona.fecha_egreso else '',
            persona.contacto_emergencia or '',
            'Sí' if persona.medical_checkup else 'No',
            persona.last_checkup_date.strftime('%Y-%m-%d') if persona.last_checkup_date else '',
            persona.observaciones_jornada or '',
            persona.anotaciones_rrhh or '',
            persona.foto.name if persona.foto else '',
        ])

    return response


@login_required
@user_passes_test(is_global_admin)
def global_people_photos_zip(request):
    organization_id = request.GET.get('organization', '')
    search = request.GET.get('q', '')
    estado = request.GET.get('estado', '')
    personas = Person.objects.select_related('organization').exclude(foto='').order_by(
        'organization__name', 'last_name', 'first_name'
    )
    organization = None
    if organization_id.isdigit():
        organization = get_object_or_404(Organization, id=organization_id)
        personas = personas.filter(organization=organization)
    if search:
        personas = personas.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(id_number__icontains=search)
        )
    if estado in ['activo', 'pasivo']:
        personas = personas.filter(estado=estado)

    zip_buffer = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024)
    added = 0
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for persona in personas:
            if not persona.foto or not default_storage.exists(persona.foto.name):
                continue

            _, ext = os.path.splitext(persona.foto.name)
            ext = ext or '.png'
            organization_name = filename_part(persona.organization.slug if persona.organization else 'sin_organizacion')
            person_name = filename_part(f'{persona.last_name}_{persona.first_name}')
            id_number = filename_part(persona.id_number)
            archive_name = f'{organization_name}/{id_number}_{person_name}{ext}'

            with default_storage.open(persona.foto.name, 'rb') as photo_file:
                zip_file.writestr(archive_name, photo_file.read())
            added += 1

        if added == 0:
            zip_file.writestr('sin_fotos.txt', 'No hay fotografías disponibles para los filtros seleccionados.\n')

    suffix = filename_part(organization.slug if organization else 'todas_las_organizaciones')
    zip_buffer.seek(0)
    response = FileResponse(zip_buffer, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="fotos_personal_{suffix}.zip"'
    return response


def start_plate_lookup_process(placa, user):
    max_processes = int(getattr(settings, 'PLATE_LOOKUP_MAX_PROCESSES', 1) or 1)
    lock_path = settings.BASE_DIR / 'plate_lookup_spawn.lock'
    try:
        with open(lock_path, 'w') as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            active = subprocess.run(
                [PS_COMMAND, '-eo', 'args='],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            active_count = sum(
                1
                for line in (active.stdout or '').splitlines()
                if 'manage.py lookup_plate' in line and 'ps -eo args=' not in line
            )
            if active_count >= max_processes:
                return False

            manage_py = settings.BASE_DIR / 'manage.py'
            command = [
                sys.executable,
                str(manage_py),
                'lookup_plate',
                placa,
                '--timeout-seconds',
                '120',
            ]
            if user is not None:
                command.extend(['--user-id', str(user.id)])
            subprocess.Popen(
                command,
                cwd=str(settings.BASE_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
    except BlockingIOError:
        return False
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def start_person_lookup_process(cedula, user):
    max_processes = int(getattr(settings, 'PERSON_LOOKUP_MAX_PROCESSES', 1) or 1)
    lock_path = settings.BASE_DIR / 'person_lookup_spawn.lock'
    log_path = settings.BASE_DIR / 'person_lookup_spawn.log'
    def write_spawn_log(message):
        timestamp = timezone.now().isoformat()
        with open(log_path, 'a') as log_file:
            log_file.write(f'[{timestamp}] {message}\n')

    try:
        with open(lock_path, 'w') as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            active = subprocess.run(
                [PS_COMMAND, '-eo', 'args='],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            active_count = sum(
                1
                for line in (active.stdout or '').splitlines()
                if (
                    ('manage.py lookup_person' in line or 'manage.py drain_person_lookups' in line)
                    and 'ps -eo args=' not in line
                )
            )
            if active_count >= max_processes:
                write_spawn_log(f'cedula={cedula} cola activa, active_count={active_count}')
                return False

            manage_py = settings.BASE_DIR / 'manage.py'
            command = [
                sys.executable,
                str(manage_py),
                'drain_person_lookups',
                '--limit',
                '5',
                '--timeout-seconds',
                '120',
                '--sleep',
                '1',
            ]
            with open(log_path, 'ab') as output_log:
                subprocess.Popen(
                    command,
                    cwd=str(settings.BASE_DIR),
                    stdout=output_log,
                    stderr=output_log,
                    start_new_session=True,
                )
            write_spawn_log(f'cedula={cedula} drenador iniciado command={" ".join(command)}')
            return True
    except BlockingIOError:
        write_spawn_log(f'cedula={cedula} lock ocupado')
        return False
    except (OSError, ValueError, subprocess.SubprocessError):
        write_spawn_log(f'cedula={cedula} error al iniciar:\n{traceback.format_exc()}')
        return False


def _plate_lookup_api_payload(record):
    if not record:
        return {}
    normalized = record.normalized_data if isinstance(record.normalized_data, dict) else {}
    return {
        "placa": record.placa,
        "status": record.lookup_status,
        "ready": record.lookup_status in {"completed", "completed_with_errors"},
        "pending": record.lookup_status in {"pending", "running"},
        "propietario": record.propietario or normalized.get("propietario") or "",
        "marca": record.marca or normalized.get("marca") or "",
        "modelo": record.modelo or normalized.get("modelo") or "",
        "anio": record.anio or normalized.get("anio") or "",
        "pais_fabricacion": record.pais_fabricacion or normalized.get("pais_fabricacion") or "",
        "clase": record.clase or normalized.get("clase") or "",
        "tipo": record.tipo or normalized.get("tipo") or "",
        "servicio": record.servicio or normalized.get("servicio") or "",
        "uso": record.uso or normalized.get("uso") or "",
        "color_1": record.color_1 or normalized.get("color_1") or "",
        "color_2": record.color_2 or normalized.get("color_2") or "",
        "vin": record.vin or normalized.get("vin") or "",
        "motor": record.motor or normalized.get("motor") or "",
        "canton_matricula": record.canton_matricula or normalized.get("canton_matricula") or "",
        "fecha_matricula": record.fecha_matricula or normalized.get("fecha_matricula") or "",
        "vencimiento_matricula": record.vencimiento_matricula or normalized.get("vencimiento_matricula") or "",
        "fecha_inspeccion": record.fecha_inspeccion or normalized.get("fecha_inspeccion") or "",
        "ultimo_pago": record.ultimo_pago or normalized.get("ultimo_pago") or "",
        "cilindraje": record.cilindraje or normalized.get("cilindraje") or "",
        "estado": record.estado or normalized.get("estado") or "",
        "informacion": record.informacion or normalized.get("informacion") or "",
        "fecha_compraventa": record.fecha_compraventa or normalized.get("fecha_compraventa") or "",
        "tramites": record.tramites if isinstance(record.tramites, list) else [],
        "source_errors": record.source_errors if isinstance(record.source_errors, dict) else {},
        "normalized_data": normalized,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def api_plate_lookup(request, placa):
    token = getattr(settings, "PLATE_LOOKUP_API_TOKEN", "")
    if token and request.headers.get("X-Plate-Lookup-Token", "") != token:
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)

    normalized = normalize_plate(placa)
    if len(normalized) < 5:
        return JsonResponse({"ok": False, "error": "invalid_plate"}, status=400)

    record = PlateLookupRecord.objects.filter(placa=normalized).first()
    if record and record.lookup_status in {"completed", "completed_with_errors", "running", "pending"}:
        return JsonResponse({"ok": True, "record": _plate_lookup_api_payload(record)})

    PlateLookupRecord.objects.update_or_create(
        placa=normalized,
        defaults={
            "lookup_status": "pending",
            "last_error": "",
            "source_errors": {},
            "requested_at": timezone.now(),
        },
    )
    start_plate_lookup_process(normalized, None)
    record = PlateLookupRecord.objects.filter(placa=normalized).first()
    return JsonResponse({"ok": True, "record": _plate_lookup_api_payload(record)})


def _person_lookup_api_payload(record):
    if not record:
        return None

    normalized = record.normalized_data or {}
    return {
        "cedula": record.cedula,
        "estado": record.lookup_status,
        "last_error": record.last_error or "",
        "nombre_completo": record.nombre_completo or normalized.get("nombre_completo") or "",
        "procesos_actor_total": record.procesos_actor_total or normalized.get("procesos_actor_total") or 0,
        "procesos_demandado_total": record.procesos_demandado_total or normalized.get("procesos_demandado_total") or 0,
        "citaciones_total": record.citaciones_total or normalized.get("citaciones_total") or 0,
        "normalized_data": normalized,
        "funcion_judicial_data": record.funcion_judicial_data or {},
        "sri_data": record.sri_data or {},
        "ant_data": record.ant_data or {},
        "source_errors": record.source_errors if isinstance(record.source_errors, dict) else {},
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def api_person_lookup(request, cedula):
    token = getattr(settings, "PERSON_LOOKUP_API_TOKEN", "")
    if token and request.headers.get("X-Person-Lookup-Token", "") != token:
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)

    normalized = normalize_cedula(cedula)
    if len(normalized) < 5:
        return JsonResponse({"ok": False, "error": "invalid_cedula"}, status=400)

    record = PersonLookupRecord.objects.filter(cedula=normalized).first()
    if record and record.lookup_status in {"completed", "completed_with_errors", "running", "pending"}:
        return JsonResponse({"ok": True, "record": _person_lookup_api_payload(record)})

    PersonLookupRecord.objects.update_or_create(
        cedula=normalized,
        defaults={
            "lookup_status": "pending",
            "last_error": "",
            "source_errors": {},
            "requested_at": timezone.now(),
        },
    )
    start_person_lookup_process(normalized, None)
    record = PersonLookupRecord.objects.filter(cedula=normalized).first()
    return JsonResponse({"ok": True, "record": _person_lookup_api_payload(record)})


@login_required
@user_passes_test(is_global_admin)
def global_plate_lookup(request):
    form = PlateLookupForm(request.POST or None)
    record = None
    active_tab = request.GET.get('tab') or 'consultas'
    if request.method == 'POST' and form.is_valid():
        placa = normalize_plate(form.cleaned_data['placa'])
        PlateLookupRecord.objects.update_or_create(
            placa=placa,
            defaults={
                'placa_aliases': plate_variants(form.cleaned_data['placa']),
                'lookup_status': 'pending',
                'last_error': '',
                'source_errors': {},
                'consultado_por': request.user,
                'requested_at': timezone.now(),
            },
        )
        start_plate_lookup_process(placa, request.user)
        messages.info(request, f'Consulta de placa {placa} iniciada. Puede seguir usando el dashboard.')
        return redirect(f"{reverse('global_plate_lookup')}?tab=consultas&placa={placa}")

    requested_plate = normalize_plate(request.GET.get('placa', ''))
    if requested_plate:
        record = PlateLookupRecord.objects.filter(placa=requested_plate).select_related('consultado_por').first()
        if record:
            form = PlateLookupForm(initial={'placa': record.placa})

    status_choices = PlateLookupRecord.STATUS_CHOICES
    queue_qs = PlateLookupRecord.objects.select_related('consultado_por').order_by('-updated_at')
    queue_status = (request.GET.get('queue_status') or '').strip()
    queue_query = (request.GET.get('queue_q') or '').strip()
    if queue_status:
        queue_qs = queue_qs.filter(lookup_status=queue_status)
    else:
        queue_qs = queue_qs.filter(lookup_status__in=['pending', 'running', 'failed'])
    if queue_query:
        queue_qs = queue_qs.filter(
            Q(placa__icontains=queue_query) |
            Q(propietario__icontains=queue_query) |
            Q(last_error__icontains=queue_query) |
            Q(source_errors__icontains=queue_query)
        )
    queue_paginator = Paginator(queue_qs, 25)
    queue_page = queue_paginator.get_page(request.GET.get('queue_page'))
    queue_counts = PlateLookupRecord.objects.aggregate(
        pending=Count('id', filter=Q(lookup_status='pending')),
        running=Count('id', filter=Q(lookup_status='running')),
        failed=Count('id', filter=Q(lookup_status='failed')),
    )

    plate_query = (request.GET.get('q') or '').strip()
    exact_plate = normalize_plate(request.GET.get('db_placa', ''))
    db_status = (request.GET.get('db_status') or '').strip()
    saved_plates_qs = PlateLookupRecord.objects.select_related('consultado_por').order_by('-updated_at')
    if db_status:
        saved_plates_qs = saved_plates_qs.filter(lookup_status=db_status)
    if exact_plate:
        saved_plates_qs = saved_plates_qs.filter(Q(placa=exact_plate) | Q(placa_aliases__icontains=exact_plate))
    if plate_query:
        saved_plates_qs = saved_plates_qs.filter(
            Q(placa__icontains=plate_query) |
            Q(propietario__icontains=plate_query) |
            Q(marca__icontains=plate_query) |
            Q(modelo__icontains=plate_query) |
            Q(vin__icontains=plate_query) |
            Q(motor__icontains=plate_query)
        )
    total_placas_guardadas = saved_plates_qs.count()
    db_paginator = Paginator(saved_plates_qs, 30)
    db_page = db_paginator.get_page(request.GET.get('db_page'))
    recientes = PlateLookupRecord.objects.select_related('consultado_por').order_by('-updated_at')[:20]
    return render(request, 'gestion_personal/global_admin/plate_lookup.html', {
        'form': form,
        'record': record,
        'recientes': recientes,
        'queue_page': queue_page,
        'queue_query': queue_query,
        'queue_status': queue_status,
        'queue_counts': queue_counts,
        'db_page': db_page,
        'plate_query': plate_query,
        'exact_plate': exact_plate,
        'db_status': db_status,
        'status_choices': status_choices,
        'total_placas_guardadas': total_placas_guardadas,
        'active_tab': active_tab if active_tab in {'consultas', 'base'} else 'consultas',
    })


@login_required
@user_passes_test(is_global_admin)
def global_person_lookup(request):
    form = PersonLookupForm(request.POST or None)
    record = None
    active_tab = request.GET.get('tab') or 'consultas'
    if request.method == 'POST' and form.is_valid():
        cedula = normalize_cedula(form.cleaned_data['cedula'])
        PersonLookupRecord.objects.update_or_create(
            cedula=cedula,
            defaults={
                'lookup_status': 'pending',
                'last_error': '',
                'source_errors': {},
                'consultado_por': request.user,
                'requested_at': timezone.now(),
            },
        )
        started = start_person_lookup_process(cedula, request.user)
        if started:
            messages.info(request, f'Consulta de cédula {cedula} iniciada. Puede seguir usando el dashboard.')
        else:
            messages.info(request, f'Consulta de cédula {cedula} quedó en cola. El procesador ya está ocupado y la tomará enseguida.')
        return redirect(f"{reverse('global_person_lookup')}?tab=consultas&cedula={cedula}")

    requested_cedula = normalize_cedula(request.GET.get('cedula', ''))
    if requested_cedula:
        record = PersonLookupRecord.objects.filter(cedula=requested_cedula).select_related('consultado_por').first()
        if record:
            form = PersonLookupForm(initial={'cedula': record.cedula})
    record_details_json = ""
    if record:
        record_details_json = json.dumps({
            "cedula": record.cedula,
            "estado": record.lookup_status,
            "resumen_normalizado": record.normalized_data,
            "funcion_judicial": record.funcion_judicial_data,
            "ant": record.ant_data,
            "sri": record.sri_data,
            "sri_ruc_natural": record.normalized_data.get("sri_ruc_natural", {}),
            "ecuadorlegal": record.normalized_data.get("ecuadorlegal", {}),
            "sanciones": record.normalized_data.get("sanciones", {}),
            "errores_fuentes": record.source_errors,
        }, ensure_ascii=False, indent=2, default=str)

    status_choices = PersonLookupRecord.STATUS_CHOICES
    queue_qs = PersonLookupRecord.objects.select_related('consultado_por').order_by('-updated_at')
    queue_status = (request.GET.get('queue_status') or '').strip()
    queue_query = (request.GET.get('queue_q') or '').strip()
    if queue_status:
        queue_qs = queue_qs.filter(lookup_status=queue_status)
    else:
        queue_qs = queue_qs.filter(lookup_status__in=['pending', 'running', 'failed'])
    if queue_query:
        queue_qs = queue_qs.filter(
            Q(cedula__icontains=queue_query) |
            Q(nombre_completo__icontains=queue_query) |
            Q(last_error__icontains=queue_query) |
            Q(source_errors__icontains=queue_query)
        )
    queue_paginator = Paginator(queue_qs, 25)
    queue_page = queue_paginator.get_page(request.GET.get('queue_page'))
    queue_counts = PersonLookupRecord.objects.aggregate(
        pending=Count('id', filter=Q(lookup_status='pending')),
        running=Count('id', filter=Q(lookup_status='running')),
        failed=Count('id', filter=Q(lookup_status='failed')),
    )

    person_query = (request.GET.get('q') or '').strip()
    exact_cedula = normalize_cedula(request.GET.get('db_cedula', ''))
    db_status = (request.GET.get('db_status') or '').strip()
    saved_people_qs = PersonLookupRecord.objects.select_related('consultado_por').order_by('-updated_at')
    if db_status:
        saved_people_qs = saved_people_qs.filter(lookup_status=db_status)
    if exact_cedula:
        saved_people_qs = saved_people_qs.filter(cedula=exact_cedula)
    if person_query:
        saved_people_qs = saved_people_qs.filter(
            Q(cedula__icontains=person_query) |
            Q(nombre_completo__icontains=person_query)
        )
    total_personas_guardadas = saved_people_qs.count()
    db_paginator = Paginator(saved_people_qs, 30)
    db_page = db_paginator.get_page(request.GET.get('db_page'))
    return render(request, 'gestion_personal/global_admin/person_lookup.html', {
        'form': form,
        'record': record,
        'record_details_json': record_details_json,
        'queue_page': queue_page,
        'queue_query': queue_query,
        'queue_status': queue_status,
        'queue_counts': queue_counts,
        'db_page': db_page,
        'person_query': person_query,
        'exact_cedula': exact_cedula,
        'db_status': db_status,
        'status_choices': status_choices,
        'total_personas_guardadas': total_personas_guardadas,
        'active_tab': active_tab if active_tab in {'consultas', 'base'} else 'consultas',
    })

#Vstas para el operador
@login_required
@user_passes_test(is_operador)
def dashboard_operador(request):
    """Dashboard principal para operadores"""
    
     # Añadir visitas programadas para hoy
    today = timezone.now().date()
    visitas_programadas = VisitaProgramada.objects.filter(
        fecha_programada=today,
        status='pendiente'
    ).order_by('hora_programada')
    
    # Obtener visitantes activos (registrados hoy sin salida)
    visitantes_activos = VisitorRecord.objects.filter(
        fecha__date=today,
        fecha_salida__isnull=True
    ).order_by('-fecha')
    personas_org = person_queryset_for(request.user)
    permisos_activos_operador = PermisoSalida.objects.filter(
        person__in=personas_org,
        fecha_inicio__lte=today,
        fecha_fin__gte=today,
    ).select_related('person', 'creado_por').order_by('fecha_fin', 'person__first_name')
    vacaciones_activas_operador = VacationRecord.objects.filter(
        person__in=personas_org,
        start_date__lte=today,
        end_date__gte=today,
    ).select_related('person', 'approved_by').order_by('end_date', 'person__first_name')
    
    context = {
        'form_visitante': VisitorRecordForm(),
        'form_vehiculo': VehicleRecordForm(registrado_por=request.user),
        'current_date': timezone.now(),
        'today': timezone.now().date(),
        'visitas_programadas': visitas_programadas,
        'visitantes_activos': visitantes_activos,  # Añadir visitantes activos
        'permisos_activos_operador': permisos_activos_operador,
        'vacaciones_activas_operador': vacaciones_activas_operador,
    }
    
    cedula = request.GET.get('cedula')
    if cedula:
        try:
            # Recuperar persona
            persona = person_queryset_for(request.user).get(id_number=cedula)
            
            # Fecha actual
            hoy = timezone.now().date()
            now = timezone.now()

            # Obtener vacaciones activas si existen
            vacaciones_activas = VacationRecord.objects.filter(
                person=persona,
                start_date__lte=hoy,
                end_date__gte=hoy
            ).first()

            # Vacaciones programadas (que no hayan comenzado)
            vacaciones_programadas = VacationRecord.objects.filter(
                person=persona,
                start_date__gt=hoy
            ).order_by('start_date').first()

            # Permisos activos
            permiso_activo = PermisoSalida.objects.filter(
                person=persona,
                fecha_inicio__lte=hoy,
                fecha_fin__gte=hoy
            ).first()

            # Último registro de asistencia
            ultimo_registro = AttendanceRecord.objects.filter(
                person=persona
            ).order_by('-timestamp').first()
            
            # Determinar si está dentro
            esta_dentro = ultimo_registro and ultimo_registro.record_type == 'entrada'
            
            # Determinar si está en vacaciones
            en_vacaciones = bool(vacaciones_activas)
            
            # Determinar si necesita revisión médica post-vacaciones
            necesita_revision_medica = False
            if en_vacaciones or (ultimo_registro and ultimo_registro.motivo == 'Retorno de vacaciones' and not persona.medical_checkup):
                necesita_revision_medica = True

            # Registros recientes para esta persona
            historial = AttendanceRecord.objects.filter(
                person=persona
            ).order_by('-timestamp')[:10]

            # Actualizar contexto
            context.update({
                'persona': persona,
                'vacaciones_activas': vacaciones_activas,
                'vacaciones_programadas': vacaciones_programadas,
                'permiso_activo': permiso_activo,
                'historial': historial,
                'esta_dentro': esta_dentro,
                'en_vacaciones': en_vacaciones,
                'necesita_revision_medica': necesita_revision_medica,
            })

        except Person.DoesNotExist:
            context['error'] = "Persona no encontrada."
    
    return render(request, 'gestion_personal/operador/dashboard_operador.html', context)

@login_required
@user_passes_test(is_operador)
def registros_diarios(request):
    """Vista para mostrar registros diarios de entrada/salida"""
    # Obtener fecha del filtro o usar fecha actual
    fecha_str = request.GET.get('fecha')
    if fecha_str:
        try:
            from datetime import datetime
            fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha_obj = timezone.localdate()
    else:
        fecha_obj = timezone.localdate()
    
    # Obtener tipo de registro a mostrar
    tipo = request.GET.get('tipo')
    
    # Obtener término de búsqueda
    busqueda = request.GET.get('busqueda', '')
    
    # Filtrar registros de personal
    registros_personal = AttendanceRecord.objects.select_related('person', 'recorded_by').filter(
        timestamp__date=fecha_obj,
        person__in=person_queryset_for(request.user),
    )
    if busqueda:
        registros_personal = registros_personal.filter(
            Q(person__first_name__icontains=busqueda) | 
            Q(person__last_name__icontains=busqueda) | 
            Q(person__id_number__icontains=busqueda)
        )
    
    # Filtrar registros de visitantes
    registros_visitantes = VisitorRecord.objects.filter(fecha__date=fecha_obj)
    if busqueda:
        registros_visitantes = registros_visitantes.filter(
            Q(nombre__icontains=busqueda) | 
            Q(cedula__icontains=busqueda) | 
            Q(area_visita__icontains=busqueda)
        )
    
    # Filtrar registros de vehículos
    registros_vehiculos = VehicleRecord.objects.select_related('organization', 'registrado_por').filter(
        Q(fecha_ingreso__date=fecha_obj) | 
        Q(fecha_salida__date=fecha_obj)
    ).filter(organization_filter_for(request.user))
    if busqueda:
        registros_vehiculos = registros_vehiculos.filter(
            Q(placa__icontains=busqueda) |
            Q(chofer_nombre__icontains=busqueda) |
            Q(chofer_cedula__icontains=busqueda)
        )
    
    # Conteos para estadísticas
    total_entradas = registros_personal.filter(record_type='entrada').count()
    total_salidas = registros_personal.filter(record_type='salida').count()
    total_visitantes = registros_visitantes.count()
    total_vehiculos = registros_vehiculos.count()
    total_registros = total_entradas + total_salidas + total_visitantes + total_vehiculos

    registros_personal = registros_personal.order_by('-timestamp')[:RECORD_LIST_LIMIT]
    registros_visitantes = registros_visitantes.order_by('-fecha')[:RECORD_LIST_LIMIT]
    registros_vehiculos = registros_vehiculos.order_by('-fecha_ingreso')[:RECORD_LIST_LIMIT]
    
    context = {
        'fecha': fecha_obj.strftime('%Y-%m-%d'),
        'registros_personal': registros_personal,
        'registros_visitantes': registros_visitantes,
        'registros_vehiculos': registros_vehiculos,
        'total_entradas': total_entradas,
        'total_salidas': total_salidas,
        'total_visitantes': total_visitantes,
        'total_vehiculos': total_vehiculos,
        'total_registros': total_registros,
        'registros_limit': RECORD_LIST_LIMIT,
        'registros_limited': total_registros > RECORD_LIST_LIMIT,
        'tipo': tipo,
        'busqueda': busqueda,
        'form_visitante': VisitorRecordForm(),
        'form_vehiculo': VehicleRecordForm(registrado_por=request.user),
    }
    
    return render(request, 'gestion_personal/operador/registros_diarios.html', context)

@login_required
@user_passes_test(is_operador)
def buscar_persona_por_cedula(request):
    """Búsqueda de personas por cédula para operadores"""
    id_number = request.GET.get('id_number', '')
    if id_number:
        try:
            # Optimizar la consulta con select_related
            persona = person_queryset_for(request.user).get(id_number=id_number)
            
            # Obtener permisos activos
            hoy = timezone.now().date()
            permiso_activo = PermisoSalida.objects.filter(
                person=persona,
                fecha_inicio__lte=hoy,
                fecha_fin__gte=hoy
            ).exists()
            
            # Obtener si está en vacaciones
            vacaciones_activas = VacationRecord.objects.filter(
                person=persona,
                start_date__lte=hoy,
                end_date__gte=hoy
            ).exists()
            
            # Último registro de asistencia
            ultimo_registro = AttendanceRecord.objects.filter(
                person=persona
            ).order_by('-timestamp').first()
            
            # Determinar si está dentro
            esta_dentro = ultimo_registro and ultimo_registro.record_type == 'entrada'
            
            # Preparar datos para la respuesta
            response_data = {
                'id': persona.id,
                'nombre_completo': f"{persona.first_name} {persona.last_name}",
                'id_number': persona.id_number,
                'cargo': persona.cargo or '',
                'departamento': persona.departamento or '',
                'area': persona.area or '',
                'permiso_activo': permiso_activo,
                'en_vacaciones': vacaciones_activas,
                'esta_dentro': esta_dentro,
            }
            
            # Agregar URL de la foto si existe
            if persona.foto:
                response_data['foto_url'] = persona.foto.url
            
            return JsonResponse(response_data)
        except Person.DoesNotExist:
            return JsonResponse({'error': 'No se encontró ninguna persona con esta cédula'}, status=404)
    return JsonResponse({'error': 'Por favor ingrese un número de cédula'}, status=400)

@login_required
@user_passes_test(is_operador)
@require_POST
def registrar_ingreso(request):
    """Registrar ingreso de una persona"""
    id_number = request.POST.get("cedula")
    reason = request.POST.get("reason")
    campamento_destino = request.POST.get("campamento_destino")
    
    persona = person_by_cedula_for_user(request.user, id_number)
    if not persona:
        send_telegram_access_alert(
            access_alert_message(
                "Intento de ingreso con cédula no registrada.",
                cedula=id_number,
                user=request.user,
                detail="Si es visitante debe registrarse por el flujo de visitantes, no como personal activo.",
            )
        )
        return JsonResponse({"status": "error", "error": "Persona no encontrada"})

    active_response = person_active_response(persona, action="ingreso", user=request.user)
    if active_response:
        return active_response

    # Verificar último registro
    ultimo_registro = AttendanceRecord.objects.filter(
        person=persona
    ).order_by('-timestamp').first()

    wait_response = attendance_wait_response(ultimo_registro)
    if wait_response:
        return wait_response
    
    # Si ya está dentro, no permitir nuevo ingreso
    if ultimo_registro and ultimo_registro.record_type == 'entrada':
        return JsonResponse({"status": "error", "error": "La persona ya se encuentra dentro"})
    
    # Verificar si viene de vacaciones
    hoy = timezone.now().date()
    vacaciones_terminadas = VacationRecord.objects.filter(
        person=persona,
        end_date=hoy
    ).exists()
    
    # Si viene de vacaciones, verificar si pasó por revisión médica
    if vacaciones_terminadas and not persona.medical_checkup:
        send_telegram_access_alert(
            access_alert_message(
                "Intento de ingreso sin control médico posterior a vacaciones.",
                person=persona,
                user=request.user,
                detail="Debe pasar por revisión médica antes de ingresar.",
            ),
            person=persona,
        )
        return JsonResponse({
            "status": "error", 
            "error": "La persona debe pasar por control médico antes de ingresar por retorno de vacaciones"
        })
    
    # Crear registro de entrada
    AttendanceRecord.objects.create(
        person=persona,
        record_type='entrada',
        motivo=f"Ingreso por {reason}" if reason else "Ingreso regular",
        reason=reason,
        campamento_destino=campamento_destino if reason == 'traslado' else None,
        recorded_by=request.user
    )
    
    return JsonResponse({"status": "ok", "message": f"Ingreso registrado para {persona.first_name} {persona.last_name}"})

@login_required
@user_passes_test(is_operador)
@require_POST
def registrar_salida(request):
    """Registrar salida de una persona"""
    id_number = request.POST.get("cedula")
    reason = request.POST.get("reason")
    campamento_destino = request.POST.get("campamento_destino")
    
    persona = person_by_cedula_for_user(request.user, id_number)
    if not persona:
        send_telegram_access_alert(
            access_alert_message(
                "Intento de salida con cédula no registrada.",
                cedula=id_number,
                user=request.user,
                detail="No existe como personal activo de la organización.",
            )
        )
        return JsonResponse({"status": "error", "error": "Persona no encontrada"})

    active_response = person_active_response(persona, action="salida", user=request.user)
    if active_response:
        return active_response

    # Verificar último registro
    ultimo_registro = AttendanceRecord.objects.filter(
        person=persona
    ).order_by('-timestamp').first()

    wait_response = attendance_wait_response(ultimo_registro)
    if wait_response:
        return wait_response
    
    # Si no está dentro, no permitir salida
    if not ultimo_registro or ultimo_registro.record_type == 'salida':
        return JsonResponse({"status": "error", "error": "La persona no se encuentra dentro para registrar salida"})
    
    # Verificar si tiene permiso para salir
    hoy = timezone.now().date()
    if not has_active_exit_authorization(persona, hoy):
        send_telegram_access_alert(
            access_alert_message(
                "Intento de salida sin permiso activo.",
                person=persona,
                user=request.user,
                detail="Debe existir permiso de salida o vacaciones activas.",
            ),
            person=persona,
        )
        return JsonResponse({
            "status": "error", 
            "error": "La persona no tiene permiso activo para salir. Debe estar autorizado por Seguridad, RRHH o Administración."
        })
    
    # Crear registro de salida
    AttendanceRecord.objects.create(
        person=persona,
        record_type='salida',
        motivo=f"Salida por {reason}" if reason else "Salida regular",
        reason=reason,
        campamento_destino=campamento_destino if reason == 'traslado' else None,
        recorded_by=request.user
    )
    
    return JsonResponse({"status": "ok", "message": f"Salida registrada para {persona.first_name} {persona.last_name}"})

@login_required
@user_passes_test(is_operador)
def vehicle_create(request):
    if request.method == 'POST':
        form = VehicleRecordForm(request.POST, registrado_por=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Vehículo registrado correctamente")
            return redirect('vehicle_list')
        messages.error(request, "Revise los datos del vehículo.")
    else:
        form = VehicleRecordForm(registrado_por=request.user)
    
    return render(request, 'gestion_personal/operador/vehicle_form.html', {
        'form': form,
        'title': 'Registrar Nuevo Vehículo'
    })

@login_required
@user_passes_test(is_operador)
@require_POST
def visitor_create(request):
    """Registrar nuevo visitante"""
    form = VisitorRecordForm(request.POST)
    if form.is_valid():
        visitante = form.save(commit=False)
        visitante.fecha = timezone.localtime()
        visitante.save()
        
        # Comprobar si proviene de una visita programada
        visita_id = request.POST.get('visita_programada_id')
        if visita_id:
            try:
                visita = VisitaProgramada.objects.get(id=visita_id, status='pendiente')
                visita.status = 'completada'
                visita.save()
            except VisitaProgramada.DoesNotExist:
                pass  # No hacer nada si la visita ya no existe o no está pendiente
        
        messages.success(request, "Visitante registrado correctamente.")
    else:
        messages.error(request, "Error al registrar visitante.")
    
    # Redirigir a la URL que viene en el POST o a la página de origen
    redirect_url = request.POST.get('redirect_url')
    if redirect_url:
        return redirect(redirect_url)
    return redirect('dashboard_operador')

@login_required
@user_passes_test(is_operador)
@require_POST
def vehicle_exit(request):
    """Registrar salida de vehículo"""
    vehicle_id = request.POST.get("vehicle_id")
    
    vehicle = get_object_or_404(VehicleRecord, id=vehicle_id)
    
    # Verificar si ya salió
    if vehicle.fecha_salida:
        return JsonResponse({"status": "error", "error": "El vehículo ya ha registrado su salida"})
    
    # Registrar fecha de salida
    vehicle.fecha_salida = timezone.now()
    vehicle.salida_registrada_por = request.user
    vehicle.save(update_fields=['fecha_salida', 'salida_registrada_por'])

    if request.META.get('HTTP_ACCEPT', '').find('application/json') == -1:
        messages.success(request, f"Salida de vehículo {vehicle.placa} registrada correctamente")
        return redirect(request.META.get('HTTP_REFERER', 'vehicle_list'))
    
    return JsonResponse({
        "status": "ok", 
        "message": f"Salida de vehículo {vehicle.placa} registrada correctamente"
    })

#Vistas para el RecursosHumanos
@login_required
@user_passes_test(is_rh)
def dashboard_rrhh(request):
    """Dashboard principal para recursos humanos"""
    persona = None
    historial = AttendanceRecord.objects.none()
    permiso_activo = None
    vacaciones_activas = None
    today = timezone.now().date()
    now = timezone.now()
    
    # Conteos para estadísticas
    personal_qs = person_queryset_for(request.user)
    personal_counts = personal_qs.aggregate(
        total=Count('id'),
        activos=Count('id', filter=Q(estado='activo')),
        pasivos=Count('id', filter=Q(estado='pasivo')),
    )
    total_personas = personal_counts['total']
    total_activos = personal_counts['activos']
    total_pasivos = personal_counts['pasivos']

    month_names = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ]
    birthday_months = [
        {"number": index + 1, "name": name, "people": []}
        for index, name in enumerate(month_names)
    ]
    birthday_people = (
        personal_qs
        .filter(estado='activo')
        .exclude(birth_date__isnull=True)
        .only('first_name', 'last_name', 'birth_date', 'area')
        .order_by('birth_date__month', 'birth_date__day', 'last_name', 'first_name')
    )
    for person in birthday_people:
        area = (person.area or '').strip()
        area_normalized = area.lower()
        if 'molino' in area_normalized:
            area_class = 'birthday-person-molino'
            area_label = 'Molino'
        elif 'mina' in area_normalized:
            area_class = 'birthday-person-mina'
            area_label = 'Mina'
        else:
            area_class = 'birthday-person-other'
            area_label = area or 'Sin area'
        birthday_months[person.birth_date.month - 1]["people"].append({
            "name": f"{person.first_name} {person.last_name}",
            "day": person.birth_date.day,
            "area": area_label,
            "area_class": area_class,
        })
    
    # Permisos y vacaciones activos
    personas_org = personal_qs
    permisos_activos = PermisoSalida.objects.filter(
        person__in=personas_org,
        fecha_inicio__lte=today,
        fecha_fin__gte=today
    ).select_related('person', 'creado_por')
    permisos_activos_count = permisos_activos.count()
    
    vacaciones_actuales = VacationRecord.objects.filter(
        person__in=personas_org,
        start_date__lte=today,
        end_date__gte=today
    ).select_related('person', 'approved_by')
    vacaciones_actuales_count = vacaciones_actuales.count()

    form_permiso = PermisoSalidaForm()
    form_vacaciones = VacationRecordForm(user=request.user)
    form_sancion = SanctionForm(user=request.user)
    form_baja = BajaPersonaForm(initial={'fecha_egreso': today})

    cedula = request.GET.get('cedula')
    fecha_str = request.GET.get('fecha')

    if cedula:
        try:
            persona = person_queryset_for(request.user).get(id_number=cedula)

            # Historial de asistencia
            historial = AttendanceRecord.objects.filter(person=persona)
            if fecha_str:
                try:
                    fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                    historial = historial.filter(timestamp__date=fecha)
                except ValueError:
                    pass
            historial = historial.select_related('recorded_by').order_by('-timestamp')[:100]

            # Permiso activo
            permiso_activo = PermisoSalida.objects.filter(
                person=persona,
                fecha_inicio__lte=today,
                fecha_fin__gte=today
            ).first()

            # Vacaciones activas
            vacaciones_activas = VacationRecord.objects.filter(
                person=persona,
                start_date__lte=today,
                end_date__gte=today
            ).first()
            
            # Historial de permisos
            historial_permisos = PermisoSalida.objects.filter(
                person=persona
            ).order_by('-fecha_inicio')[:5]
            
            # Historial de vacaciones
            historial_vacaciones = VacationRecord.objects.filter(
                person=persona
            ).order_by('-start_date')[:100]

            # Historial de sanciones
            historial_sanciones = Sanction.objects.filter(
                person=persona
            ).order_by('-fecha')[:100]

            form_permiso = PermisoSalidaForm(initial={'person': persona})
            form_permiso.fields['person'].widget = django_forms.HiddenInput()
            form_vacaciones = VacationRecordForm(initial={'person': persona}, user=request.user)
            form_vacaciones.fields['person'].widget = django_forms.HiddenInput()
            form_sancion = SanctionForm(initial={'person': persona}, user=request.user)
            form_baja = BajaPersonaForm(instance=persona, initial={'fecha_egreso': today})

        except Person.DoesNotExist:
            persona = None
            messages.error(request, "No se encontró ninguna persona con esta cédula.")

    context = {
        'persona': persona,
        'historial': historial,
        'form_permiso': form_permiso,
        'form_vacaciones': form_vacaciones,
        'form_sancion': form_sancion,
        'form_baja': form_baja,
        'permiso_activo': permiso_activo,
        'vacaciones_activas': vacaciones_activas,
        'total_personas': total_personas,
        'total_activos': total_activos,
        'total_pasivos': total_pasivos,
        'birthday_months': birthday_months,
        'permisos_activos': permisos_activos,
        'permisos_activos_count': permisos_activos_count,
        'vacaciones_actuales_count': vacaciones_actuales_count,
        'historial_permisos': historial_permisos if 'historial_permisos' in locals() else None,
        'historial_vacaciones': historial_vacaciones if 'historial_vacaciones' in locals() else None,
        'historial_sanciones': historial_sanciones if 'historial_sanciones' in locals() else None,
        'today': today,
        'now': now,
    }
    
    return render(request, 'gestion_personal/rh/dashboard_rrhh.html', context)

@method_decorator(user_passes_test(is_rh_or_global), name='dispatch')
class PersonListView(ListView):
    """Lista de personas para RRHH"""
    model = Person
    template_name = 'gestion_personal/rh/person_list.html'
    context_object_name = 'personas'
    paginate_by = 50
    
    def get_queryset(self):
        queryset = person_queryset_for(self.request.user).select_related('organization')
        search = self.request.GET.get('q', '')
        estado = self.request.GET.get('estado', '')
        organization_id = self.request.GET.get('organization', '')
        foto = self.request.GET.get('foto', '')
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search) | 
                Q(last_name__icontains=search) | 
                Q(id_number__icontains=search)
            )
        if estado in ['activo', 'pasivo']:
            queryset = queryset.filter(estado=estado)
        if self.request.user.user_type == 'global_admin' and organization_id.isdigit():
            queryset = queryset.filter(organization_id=organization_id)
        if self.request.user.user_type == 'global_admin':
            if foto == 'con':
                queryset = queryset.exclude(foto='').exclude(foto__isnull=True)
            elif foto == 'sin':
                queryset = queryset.filter(Q(foto='') | Q(foto__isnull=True))
        return queryset.order_by('last_name', 'first_name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.user_type == 'global_admin':
            organization_id = self.request.GET.get('organization', '')
            base_queryset = Person.objects.all()
            if organization_id.isdigit():
                base_queryset = base_queryset.filter(organization_id=organization_id)
            photo_count = base_queryset.exclude(foto='').exclude(foto__isnull=True).count()
            context['organizaciones'] = Organization.objects.order_by('name')
            context['selected_organization'] = organization_id
            context['selected_foto'] = self.request.GET.get('foto', '')
            context['total_con_foto'] = photo_count
            context['total_sin_foto'] = base_queryset.count() - photo_count
            context['current_query_string'] = urlencode({
                key: value
                for key, value in self.request.GET.items()
                if key != 'page' and value
            })
        return context


@method_decorator(user_passes_test(is_rh_or_global), name='dispatch')
class PersonCreateView(CreateView):
    """Crear nueva persona"""
    model = Person
    form_class = PersonForm
    template_name = 'gestion_personal/rh/person_form.html'
    success_url = reverse_lazy('person_list')

    def get_initial(self):
        initial = super().get_initial()
        if self.request.user.user_type == 'global_admin':
            organization_id = self.request.GET.get('organization')
            if organization_id:
                initial['organization'] = organization_id
        return initial

    def get_success_url(self):
        if self.request.user.user_type == 'global_admin':
            return reverse('global_person_list')
        return reverse('person_list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if self.request.user.user_type != 'global_admin':
            form.fields['organization'].widget = django_forms.HiddenInput()
            form.fields['organization'].initial = self.request.user.organization
        return form

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.user.user_type != 'global_admin':
            kwargs['forced_organization'] = self.request.user.organization
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization_id = self.request.GET.get('organization') or self.get_initial().get('organization')
        if organization_id:
            context['form_organization'] = Organization.objects.filter(id=organization_id).first()
        elif self.request.user.user_type != 'global_admin':
            context['form_organization'] = self.request.user.organization
        return context
    
    def form_valid(self, form):
        if self.request.user.user_type != 'global_admin' and not form.instance.organization_id:
            form.instance.organization = self.request.user.organization
        messages.success(self.request, 'Persona creada exitosamente')
        return super().form_valid(form)

    def form_invalid(self, form):
        if form.cleaned_data.get('duplicate_id_number'):
            messages.warning(self.request, 'Advertencia: esa cédula ya está registrada en la organización seleccionada.')
        else:
            messages.error(self.request, 'No se pudo crear la persona. Revise la foto, la fecha de nacimiento y los campos obligatorios.')
        return super().form_invalid(form)

@method_decorator(user_passes_test(is_rh_or_global), name='dispatch')
class PersonUpdateView(UpdateView):
    """Actualizar persona existente"""
    model = Person
    form_class = PersonForm
    template_name = 'gestion_personal/rh/person_form.html'
    success_url = reverse_lazy('person_list')

    def get_success_url(self):
        if self.request.user.user_type == 'global_admin':
            return reverse('global_person_list')
        return reverse('person_list')

    def get_queryset(self):
        return person_queryset_for(self.request.user)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if self.request.user.user_type != 'global_admin':
            form.fields['organization'].widget = django_forms.HiddenInput()
        return form

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.user.user_type != 'global_admin':
            kwargs['forced_organization'] = self.request.user.organization
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_organization'] = self.object.organization
        return context
    
    def form_valid(self, form):
        messages.success(self.request, 'Persona actualizada exitosamente')
        return super().form_valid(form)

    def form_invalid(self, form):
        if form.cleaned_data.get('duplicate_id_number'):
            messages.warning(self.request, 'Advertencia: esa cédula ya está registrada en la organización seleccionada.')
        else:
            messages.error(self.request, 'No se pudo actualizar la persona. Revise la foto, la fecha de nacimiento y los campos obligatorios.')
        return super().form_invalid(form)

@method_decorator(user_passes_test(is_rh_or_global), name='dispatch')
class PersonDeleteView(DeleteView):
    """Eliminar persona"""
    model = Person
    template_name = 'gestion_personal/rh/person_confirm_delete.html'
    success_url = reverse_lazy('person_list')

    def get_success_url(self):
        if self.request.user.user_type == 'global_admin':
            return reverse('global_person_list')
        return reverse('person_list')

    def get_queryset(self):
        return person_queryset_for(self.request.user)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.POST.get('confirm_delete') != 'yes':
            messages.warning(request, 'Debe confirmar que está seguro antes de eliminar a esta persona.')
            return self.render_to_response(self.get_context_data(object=self.object))
        return super().post(request, *args, **kwargs)
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Persona eliminada exitosamente')
        return super().delete(request, *args, **kwargs)

@login_required
@user_passes_test(is_rh)
@require_POST
def crear_permiso(request):
    """Crear nuevo permiso de salida"""
    form = PermisoSalidaForm(request.POST)
    if form.is_valid():
        permiso = form.save(commit=False)
        permiso.creado_por = request.user
        permiso.save()
        messages.success(request, "Permiso registrado correctamente.")
    else:
        messages.error(request, "Hubo un error en el formulario.")

    # Redirigir a la URL que viene en el POST o a la página de origen
    return redirect(request.META.get('HTTP_REFERER', 'dashboard_rrhh'))

@login_required
@user_passes_test(is_rh)
@require_POST
def crear_vacaciones(request):
    """Crear nuevo registro de vacaciones"""
    form = VacationRecordForm(request.POST, approved_by=request.user, user=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, "Vacaciones registradas correctamente.")
    else:
        messages.error(request, "Hubo un error en el registro.")

    # Redirigir a la URL que viene en el POST o a la página de origen
    return redirect(request.META.get('HTTP_REFERER', 'dashboard_rrhh'))

@login_required
@user_passes_test(is_rh)
@require_POST
def crear_sancion(request):
    """Crear nueva sanción"""
    form = SanctionForm(request.POST, impuesta_por=request.user, user=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, "Sanción registrada correctamente.")
    else:
        messages.error(request, "Hubo un error en el registro.")

    # Redirigir a la URL que viene en el POST o a la página de origen
    return redirect(request.META.get('HTTP_REFERER', 'dashboard_rrhh'))


@login_required
@user_passes_test(is_rh)
@require_POST
def dar_baja_persona(request, person_id):
    """Pasa una persona a estado pasivo y guarda la renuncia PDF en MinIO."""
    persona = get_object_or_404(person_queryset_for(request.user), id=person_id)
    if persona.estado == 'pasivo':
        messages.info(request, "La persona ya está en estado pasivo.")
        return redirect(request.META.get('HTTP_REFERER', 'dashboard_rrhh'))

    form = BajaPersonaForm(request.POST, request.FILES, instance=persona)
    if form.is_valid():
        form.save()
        messages.success(request, f"{persona.first_name} {persona.last_name} fue dado de baja correctamente.")
    else:
        messages.error(request, "Revise la fecha, el motivo y el PDF de renuncia.")

    return redirect(request.META.get('HTTP_REFERER', 'dashboard_rrhh'))


@login_required
@user_passes_test(is_rh)
def import_excel(request):
    """Importar personal desde Excel"""
    if request.method == 'POST':
        form = ImportExcelForm(request.POST, request.FILES)
        if form.is_valid():
            excel_file = request.FILES['excel_file']
            
            # Validar tipo de archivo
            if not excel_file.name.endswith(('.xls', '.xlsx')):
                messages.error(request, 'El archivo debe ser de tipo Excel (.xls, .xlsx)')
                return redirect('import_excel')
            
            try:
                # Leer el Excel
                df = pd.read_excel(excel_file)
                
                # Contar registros procesados
                created_count = 0
                updated_count = 0
                error_count = 0
                
                # Procesar cada fila
                for _, row in df.iterrows():
                    try:
                        # Campos obligatorios
                        if 'cedula' not in row or 'nombre' not in row or 'apellido' not in row:
                            error_count += 1
                            continue
                        
                        cedula = str(row['cedula']).strip()
                        nombre = str(row['nombre']).strip()
                        apellido = str(row['apellido']).strip()
                        
                        if not cedula or not nombre or not apellido:
                            error_count += 1
                            continue
                        
                        # Buscar o crear persona por cédula
                        person = person_queryset_for(request.user).filter(id_number=cedula).first()
                        created = person is None
                        if created:
                            person = Person(
                                id_number=cedula,
                                first_name=nombre,
                                last_name=apellido,
                                birth_date=datetime.now().date(),
                                gender='O',
                                estado='activo',
                                organization=request.user.organization,
                            )
                        
                        # Siempre actualizar estos campos
                        person.first_name = nombre
                        person.last_name = apellido
                        
                        # Campos opcionales
                        if 'cargo' in row and pd.notna(row['cargo']):
                            person.cargo = str(row['cargo'])
                        
                        if 'departamento' in row and pd.notna(row['departamento']):
                            person.departamento = str(row['departamento'])
                        
                        if 'area' in row and pd.notna(row['area']):
                            person.area = str(row['area'])
                        
                        if 'email' in row and pd.notna(row['email']):
                            person.email = str(row['email'])
                        
                        if 'telefono' in row and pd.notna(row['telefono']):
                            person.phone_number = str(row['telefono'])
                        
                        if 'contacto_emergencia' in row and pd.notna(row['contacto_emergencia']):
                            person.contacto_emergencia = str(row['contacto_emergencia'])
                        
                        if 'fecha_nacimiento' in row and pd.notna(row['fecha_nacimiento']):
                            try:
                                person.birth_date = pd.to_datetime(row['fecha_nacimiento']).date()
                            except:
                                pass
                        
                        if 'fecha_ingreso' in row and pd.notna(row['fecha_ingreso']):
                            try:
                                person.fecha_ingreso = pd.to_datetime(row['fecha_ingreso']).date()
                            except:
                                pass
                        
                        if 'genero' in row and pd.notna(row['genero']):
                            genero = str(row['genero']).upper()
                            if genero in ['M', 'MASCULINO', 'HOMBRE']:
                                person.gender = 'M'
                            elif genero in ['F', 'FEMENINO', 'MUJER']:
                                person.gender = 'F'
                            else:
                                person.gender = 'O'
                        
                        if 'direccion' in row and pd.notna(row['direccion']):
                            person.address = str(row['direccion'])

                        if 'estado' in row and pd.notna(row['estado']):
                            estado = str(row['estado']).strip().lower()
                            person.estado = 'pasivo' if estado in ['pasivo', 'inactivo', 'retirado', 'egresado'] else 'activo'

                        if 'fecha_egreso' in row and pd.notna(row['fecha_egreso']):
                            try:
                                person.fecha_egreso = pd.to_datetime(row['fecha_egreso']).date()
                            except:
                                pass

                        if 'anotaciones' in row and pd.notna(row['anotaciones']):
                            person.anotaciones_rrhh = str(row['anotaciones'])

                        if not person.organization_id:
                            person.organization = request.user.organization
                        
                        person.save()
                        
                        if created:
                            created_count += 1
                        else:
                            updated_count += 1
                            
                    except Exception as e:
                        error_count += 1
                        print(f"Error en fila: {row}, Error: {str(e)}")
                
                # Mostrar mensaje de éxito
                messages.success(request, 
                    f'Importación completada: {created_count} registros creados, {updated_count} actualizados, {error_count} errores.')
                
                return redirect('person_list')
                
            except Exception as e:
                messages.error(request, f'Error al procesar el archivo: {str(e)}')
    else:
        form = ImportExcelForm()
    
    return render(request, 'gestion_personal/rh/import_excel.html', {'form': form})

@login_required
@user_passes_test(is_rh)
def export_attendance(request):
    """Exportar reporte de asistencia a Excel"""
    if 'start_date' in request.GET and 'end_date' in request.GET:
        try:
            # Obtener fechas
            start_date_str = request.GET.get('start_date')
            end_date_str = request.GET.get('end_date')
            
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            # Verificar orden de fechas
            if start_date > end_date:
                start_date, end_date = end_date, start_date
            
            # Crear libro Excel
            response = HttpResponse(content_type='application/ms-excel')
            response['Content-Disposition'] = f'attachment; filename="asistencia_{start_date_str}_al_{end_date_str}.xls"'
            
            wb = xlwt.Workbook(encoding='utf-8')
            ws = wb.add_sheet('Asistencia')
            
            # Estilo para encabezados
            font_style = xlwt.XFStyle()
            font_style.font.bold = True
            
            # Encabezados
            columns = ['Fecha', 'Hora', 'Cédula', 'Nombre', 'Apellido', 'Tipo', 'Motivo', 'Razón', 'Destino', 'Área', 'Departamento', 'Registrado por']
            
            for col_num, column_title in enumerate(columns):
                ws.write(0, col_num, column_title, font_style)
            
            # Estilo para datos
            font_style = xlwt.XFStyle()
            
            # Consultar registros
            registros = AttendanceRecord.objects.filter(
                timestamp__date__gte=start_date,
                timestamp__date__lte=end_date
            ).select_related('person', 'recorded_by').order_by('person__last_name', 'timestamp')
            
            # Poblar el Excel
            row_num = 1
            for registro in registros:
                row = [
                    registro.timestamp.strftime('%d/%m/%Y'),
                    registro.timestamp.strftime('%H:%M:%S'),
                    registro.person.id_number,
                    registro.person.first_name,
                    registro.person.last_name,
                    registro.get_record_type_display(),
                    registro.motivo or 'N/A',
                    registro.get_reason_display() if registro.reason else 'N/A',
                    registro.campamento_destino or 'N/A',
                    getattr(registro.person, 'area', 'N/A'),
                    getattr(registro.person, 'departamento', 'N/A'),
                    registro.recorded_by.username if registro.recorded_by else 'N/A'
                ]
                
                for col_num, cell_value in enumerate(row):
                    ws.write(row_num, col_num, cell_value, font_style)
                
                row_num += 1
            
            # Agregar hoja para visitantes
            ws_visitors = wb.add_sheet('Visitantes')
            
            # Encabezados para visitantes
            visitor_columns = ['Fecha', 'Hora', 'Nombre', 'Cédula', 'Área de visita', 'Autorizado por']
            
            for col_num, column_title in enumerate(visitor_columns):
                ws_visitors.write(0, col_num, column_title, font_style)
            
            # Consultar visitantes
            visitantes = VisitorRecord.objects.filter(
                fecha__date__gte=start_date,
                fecha__date__lte=end_date
            ).order_by('fecha')
            
            # Poblar la hoja de visitantes
            row_num = 1
            for visitante in visitantes:
                row = [
                    visitante.fecha.strftime('%d/%m/%Y'),
                    visitante.fecha.strftime('%H:%M:%S'),
                    visitante.nombre,
                    visitante.cedula,
                    visitante.area_visita,
                    visitante.autorizado_por
                ]
                
                for col_num, cell_value in enumerate(row):
                    ws_visitors.write(row_num, col_num, cell_value, font_style)
                
                row_num += 1
            
            # Agregar hoja para vehículos
            ws_vehicles = wb.add_sheet('Vehículos')
            
            # Encabezados para vehículos
            vehicle_columns = ['Placa', 'Marca', 'Chofer', 'Cédula Chofer', 'Ingreso', 'Salida', 'Registrado por']
            
            for col_num, column_title in enumerate(vehicle_columns):
                ws_vehicles.write(0, col_num, column_title, font_style)
            
            # Consultar vehículos
            vehiculos = VehicleRecord.objects.filter(
                Q(fecha_ingreso__date__gte=start_date, fecha_ingreso__date__lte=end_date) |
                Q(fecha_salida__date__gte=start_date, fecha_salida__date__lte=end_date)
            ).select_related('registrado_por').order_by('fecha_ingreso')
            
            # Poblar la hoja de vehículos
            row_num = 1
            for vehiculo in vehiculos:
                row = [
                    vehiculo.placa,
                    vehiculo.marca or 'N/A',
                    vehiculo.driver_name,
                    vehiculo.driver_id_number or 'N/A',
                    vehiculo.fecha_ingreso.strftime('%d/%m/%Y %H:%M:%S'),
                    vehiculo.fecha_salida.strftime('%d/%m/%Y %H:%M:%S') if vehiculo.fecha_salida else 'Sin salida',
                    vehiculo.registrado_por.username if vehiculo.registrado_por else 'N/A'
                ]
                
                for col_num, cell_value in enumerate(row):
                    ws_vehicles.write(row_num, col_num, cell_value, font_style)
                
                row_num += 1
            
            wb.save(response)
            return response
            
        except Exception as e:
            messages.error(request, f'Error al generar el reporte: {str(e)}')
            return redirect('export_attendance')
    
    return render(request, 'gestion_personal/rh/export_attendance.html')

@login_required
@user_passes_test(is_rh_or_global)
def export_person_profile(request, person_id):
    """Exportar perfil completo de una persona"""
    person = get_object_or_404(person_queryset_for(request.user), id=person_id)
    
    # Crear libro Excel
    response = HttpResponse(content_type='application/ms-excel')
    response['Content-Disposition'] = f'attachment; filename="perfil_{person.id_number}.xls"'
    
    wb = xlwt.Workbook(encoding='utf-8')
    
    # Hoja de datos personales
    ws_info = wb.add_sheet('Datos Personales')
    
    # Estilo para título
    title_style = xlwt.XFStyle()
    title_style.font.bold = True
    title_style.font.height = 260  # Aproximadamente tamaño 13
    
    # Estilo para encabezados
    header_style = xlwt.XFStyle()
    header_style.font.bold = True
    
    # Título
    ws_info.write(0, 0, f"PERFIL DE {person.first_name.upper()} {person.last_name.upper()}", title_style)
    
    # Datos personales
    row = 2
    ws_info.write(row, 0, "Datos Personales", header_style)
    row += 1
    
    personal_data = [
        ('Nombre completo', f"{person.first_name} {person.last_name}"),
        ('Cédula', person.id_number),
        ('Género', person.get_gender_display()),
        ('Fecha de nacimiento', person.birth_date.strftime('%d/%m/%Y') if person.birth_date else 'No especificada'),
        ('Dirección', person.address or 'No especificada'),
        ('Teléfono', person.phone_number or 'No especificado'),
        ('Correo electrónico', person.email or 'No especificado'),
        ('Contacto de emergencia', person.contacto_emergencia or 'No especificado'),
    ]
    
    for label, value in personal_data:
        ws_info.write(row, 0, label)
        ws_info.write(row, 1, value)
        row += 1
    
    # Datos laborales
    row += 1
    ws_info.write(row, 0, "Datos Laborales", header_style)
    row += 1
    
    work_data = [
        ('Cargo', person.cargo or 'No especificado'),
        ('Departamento', person.departamento or 'No especificado'),
        ('Área', person.area or 'No especificado'),
        ('Fecha de ingreso', person.fecha_ingreso.strftime('%d/%m/%Y') if person.fecha_ingreso else 'No especificada'),
    ]
    
    for label, value in work_data:
        ws_info.write(row, 0, label)
        ws_info.write(row, 1, value)
        row += 1
    
    # Hoja de registros de asistencia
    ws_attendance = wb.add_sheet('Registros de Asistencia')
    
    # Encabezados
    attendance_columns = ['Fecha', 'Hora', 'Tipo', 'Motivo', 'Razón', 'Destino', 'Registrado por']
    
    for col_num, column_title in enumerate(attendance_columns):
        ws_attendance.write(0, col_num, column_title, header_style)
    
    # Consultar registros
    registros = AttendanceRecord.objects.filter(
        person=person
    ).select_related('recorded_by').order_by('-timestamp')
    
    # Poblar la hoja de asistencia
    row_num = 1
    for registro in registros:
        row = [
            registro.timestamp.strftime('%d/%m/%Y'),
            registro.timestamp.strftime('%H:%M:%S'),
            registro.get_record_type_display(),
            registro.motivo or 'N/A',
            registro.get_reason_display() if registro.reason else 'N/A',
            registro.campamento_destino or 'N/A',
            registro.recorded_by.username if registro.recorded_by else 'N/A'
        ]
        
        for col_num, cell_value in enumerate(row):
            ws_attendance.write(row_num, col_num, cell_value)
        
        row_num += 1
    
    # Hoja de permisos y vacaciones
    ws_permits = wb.add_sheet('Permisos y Vacaciones')
    
    # Título para permisos
    ws_permits.write(0, 0, "Permisos", header_style)
    
    # Encabezados permisos
    permit_columns = ['Motivo', 'Fecha inicio', 'Fecha fin', 'Creado por']
    
    for col_num, column_title in enumerate(permit_columns):
        ws_permits.write(1, col_num, column_title, header_style)
    
    # Consultar permisos
    permisos = PermisoSalida.objects.filter(
        person=person
    ).select_related('creado_por').order_by('-fecha_inicio')
    
    # Poblar la sección de permisos
    row_num = 2
    for permiso in permisos:
        row = [
            permiso.motivo,
            permiso.fecha_inicio.strftime('%d/%m/%Y'),
            permiso.fecha_fin.strftime('%d/%m/%Y'),
            permiso.creado_por.username if permiso.creado_por else 'N/A'
        ]
        
        for col_num, cell_value in enumerate(row):
            ws_permits.write(row_num, col_num, cell_value)
        
        row_num += 1
    
    # Título para vacaciones
    row_num += 2
    ws_permits.write(row_num, 0, "Vacaciones", header_style)
    row_num += 1
    
    # Encabezados vacaciones
    vacation_columns = ['Fecha inicio', 'Fecha fin', 'Aprobado por', 'Control médico']
    
    for col_num, column_title in enumerate(vacation_columns):
        ws_permits.write(row_num, col_num, column_title, header_style)
    
    # Consultar vacaciones
    vacaciones = VacationRecord.objects.filter(
        person=person
    ).select_related('approved_by').order_by('-start_date')
    
    # Poblar la sección de vacaciones
    row_num += 1
    for vacacion in vacaciones:
        row = [
            vacacion.start_date.strftime('%d/%m/%Y'),
            vacacion.end_date.strftime('%d/%m/%Y'),
            vacacion.approved_by.username if vacacion.approved_by else 'N/A',
            'Completado' if vacacion.medical_checkup_done else 'Pendiente'
        ]
        
        for col_num, cell_value in enumerate(row):
            ws_permits.write(row_num, col_num, cell_value)
        
        row_num += 1
    
    # Hoja de historial médico
    ws_medical = wb.add_sheet('Historial Médico')
    
    # Encabezados
    medical_columns = ['Fecha', 'Tipo', 'Doctor', 'Observaciones']
    
    for col_num, column_title in enumerate(medical_columns):
        ws_medical.write(0, col_num, column_title, header_style)
    
    # Consultar historial médico
    historial = MedicalHistory.objects.filter(
        person=person
    ).select_related('doctor').order_by('-check_date')
    
    # Poblar la hoja de historial médico
    row_num = 1
    for record in historial:
        row = [
            record.check_date.strftime('%d/%m/%Y %H:%M'),
            'Post-vacaciones' if record.is_post_vacation else 'Control regular',
            record.doctor.username if record.doctor else 'N/A',
            record.comments
        ]
        
        for col_num, cell_value in enumerate(row):
            ws_medical.write(row_num, col_num, cell_value)
        
        row_num += 1
    
    # Hoja de sanciones
    ws_sanctions = wb.add_sheet('Sanciones')
    
    # Encabezados
    sanction_columns = ['Fecha', 'Tipo', 'Descripción', 'Impuesta por']
    
    for col_num, column_title in enumerate(sanction_columns):
        ws_sanctions.write(0, col_num, column_title, header_style)
    
    # Consultar sanciones
    sanciones = Sanction.objects.filter(
        person=person
    ).select_related('impuesta_por').order_by('-fecha')
    
    # Poblar la hoja de sanciones
    row_num = 1
    for sancion in sanciones:
        row = [
            sancion.fecha.strftime('%d/%m/%Y'),
            sancion.tipo,
            sancion.descripcion,
            sancion.impuesta_por.username if sancion.impuesta_por else 'N/A'
        ]
        
        for col_num, cell_value in enumerate(row):
            ws_sanctions.write(row_num, col_num, cell_value)
        
        row_num += 1
    
    wb.save(response)
    return response

@login_required
@user_passes_test(is_rh)
@require_POST
def cancelar_permiso(request, permiso_id):
    """Cancelar un permiso activo"""
    permiso = get_object_or_404(PermisoSalida, id=permiso_id)
    person = permiso.person
    permiso.delete()
    
    messages.success(request, f"Se ha cancelado el permiso para {person.first_name} {person.last_name}")
    
    # Redirigir a la ficha de la persona
    return redirect(f"{reverse('dashboard_rrhh')}?cedula={person.id_number}")

@login_required
@user_passes_test(is_rh)
@require_POST
def cancelar_vacaciones(request, vacacion_id):
    """Cancelar unas vacaciones"""
    vacacion = get_object_or_404(
        VacationRecord.objects.filter(person__in=person_queryset_for(request.user)),
        id=vacacion_id,
    )
    person = vacacion.person
    vacacion.delete()
    
    messages.success(request, f"Se han cancelado las vacaciones para {person.first_name} {person.last_name}")
    
    # Redirigir a la ficha de la persona
    return redirect(f"{reverse('dashboard_rrhh')}?cedula={person.id_number}")

#Vistas para el médico
@login_required
@user_passes_test(is_medico)
def dashboard_medico(request):
    """Dashboard principal para médicos"""
    # Inicializar variables
    persona = None
    vacaciones_activas = None
    historial_medico = None
    error = None
    
    # Estadísticas
    total_personas = Person.objects.count()
    aprobados_count = Person.objects.filter(medical_checkup=True).count()
    
    # Personas pendientes de revisión general
    personas_pendientes = Person.objects.filter(medical_checkup=False)
    
    # Personas que volvieron de vacaciones y necesitan revisión
    post_vacation = VacationRecord.objects.filter(
        end_date__lte=timezone.now().date(),
        medical_checkup_done=False,
        person__medical_checkup=False
    ).order_by('-end_date')
    
    # Búsqueda por cédula
    cedula = request.GET.get('cedula')
    if cedula:
        try:
            persona = person_queryset_for(request.user).get(id_number=cedula)
            
            # Obtener vacaciones activas si existen
            vacaciones_activas = VacationRecord.objects.filter(
                person=persona,
                start_date__lte=timezone.now().date(),
                end_date__gte=timezone.now().date()
            ).first()
            
            # Historial médico
            historial_medico = MedicalHistory.objects.filter(
                person=persona
            ).order_by('-check_date')
            
            # Consultas médicas
            consultas_medicas = MedicalConsultation.objects.filter(
                person=persona
            ).order_by('-fecha')
            
        except Person.DoesNotExist:
            error = "No se encontró ninguna persona con esta cédula."
    
    context = {
        'persona': persona,
        'vacaciones_activas': vacaciones_activas,
        'historial_medico': historial_medico,
        'consultas_medicas': consultas_medicas if 'consultas_medicas' in locals() else None,
        'error': error,
        'personas_pendientes': personas_pendientes,
        'post_vacation': post_vacation,
        'total_personas': total_personas,
        'aprobados_count': aprobados_count,
    }
    
    return render(request, 'gestion_personal/medico/dashboard_medico.html', context)

@method_decorator(user_passes_test(is_medico), name='dispatch')
class PersonListMedical(ListView):
    """Lista de personas para médicos"""
    model = Person
    template_name = 'gestion_personal/medico/person_list.html'
    context_object_name = 'personas'
    
    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.GET.get('search', '')
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search) | 
                Q(last_name__icontains=search) | 
                Q(id_number__icontains=search)
            )
        return queryset

@method_decorator(user_passes_test(is_medico), name='dispatch')
class PersonDetailMedical(DetailView):
    """Detalle de persona para médicos"""
    model = Person
    template_name = 'gestion_personal/medico/person_detail.html'
    context_object_name = 'persona'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        persona = self.object
        
        # Historial médico
        context['historial_medico'] = MedicalHistory.objects.filter(
            person=persona
        ).order_by('-check_date')
        
        # Consultas médicas
        context['consultas_medicas'] = MedicalConsultation.objects.filter(
            person=persona
        ).order_by('-fecha')
        
        # Vacaciones activas
        context['vacaciones_activas'] = VacationRecord.objects.filter(
            person=persona,
            start_date__lte=timezone.now().date(),
            end_date__gte=timezone.now().date()
        ).first()
        
        return context

@login_required
@user_passes_test(is_medico)
def medical_checkup(request, pk):
    """Realizar revisión médica a una persona"""
    persona = get_object_or_404(Person, pk=pk)
    
    if request.method == 'POST':
        form = MedicalCheckupForm(request.POST, instance=persona)
        if form.is_valid():
            # Guardar cambios en la persona
            person = form.save()
            
            # Crear registro en historial médico
            MedicalHistory.objects.create(
                person=persona,
                comments=persona.medical_comment,
                is_post_vacation=False,
                doctor=request.user
            )
            
            messages.success(request, f'Revisión médica actualizada para {persona}')
            return redirect('person_list_medical')
    else:
        form = MedicalCheckupForm(instance=persona)
    
    return render(request, 'gestion_personal/medico/medical_checkup_form.html', {
        'form': form,
        'persona': persona
    })

@login_required
@user_passes_test(is_medico)
def medical_vacation_checkup(request, vacation_id):
    """Realizar revisión médica post-vacaciones"""
    vacation = get_object_or_404(VacationRecord, pk=vacation_id)
    person = vacation.person
    
    if request.method == 'POST':
        form = MedicalHistoryForm(request.POST)
        if form.is_valid():
            # Crear registro en historial médico
            medical_history = form.save(commit=False)
            medical_history.person = person
            medical_history.is_post_vacation = True
            medical_history.doctor = request.user
            medical_history.save()
            
            # Actualizar la revisión médica de la persona
            person.medical_checkup = True
            person.last_checkup_date = timezone.now().date()
            person.medical_comment = form.cleaned_data['comments']
            person.save()
            
            # Marcar las vacaciones como con chequeo médico completado
            vacation.medical_checkup_done = True
            vacation.medical_checkup_date = timezone.now()
            vacation.medical_notes = form.cleaned_data['comments']
            vacation.save()
            
            messages.success(request, f'Revisión post-vacaciones registrada para {person}')
            return redirect('dashboard_medico')
    else:
        form = MedicalHistoryForm(initial={'is_post_vacation': True})
    
    context = {
        'form': form,
        'person': person,
        'vacation': vacation
    }
    
    return render(request, 'gestion_personal/medico/vacation_checkup.html', context)

@login_required
@user_passes_test(is_medico)
def create_medical_consultation(request):
    """Crear nueva consulta médica"""
    if request.method == 'POST':
        form = MedicalConsultationForm(request.POST, doctor=request.user)
        if form.is_valid():
            consulta = form.save()
            messages.success(request, "Consulta médica registrada correctamente.")
            return redirect('person_detail_medical', pk=consulta.person.id)
    else:
        # Si viene el id de la persona, pre-seleccionarla
        person_id = request.GET.get('person_id')
        initial = {}
        if person_id:
            try:
                initial['person'] = Person.objects.get(id=person_id)
            except Person.DoesNotExist:
                pass
        
        form = MedicalConsultationForm(doctor=request.user, initial=initial)
    
    return render(request, 'gestion_personal/medico/medical_consultation_form.html', {
        'form': form
    })

@login_required
@user_passes_test(is_medico)
def medical_consultation_detail(request, pk):
    """Ver detalle de una consulta médica"""
    consulta = get_object_or_404(MedicalConsultation, pk=pk)
    
    return render(request, 'gestion_personal/medico/medical_consultation_detail.html', {
        'consulta': consulta
    })

# Vistas para Administradores (Mina y Molino)
@login_required
@user_passes_test(is_any_admin)
def dashboard_admin(request):
    """Dashboard para administradores de mina o molino"""
    user = request.user
    area = 'mina' if user.user_type == 'admin_mina' else 'molino'
    today = timezone.now().date()

    # Obtener personal del área correspondiente
    personal = Person.objects.filter(area__icontains=area)
    
    # Obtener personas en vacaciones
    vacaciones_activas = VacationRecord.objects.filter(
        person__in=personal,
        start_date__lte=timezone.now().date(),
        end_date__gte=timezone.now().date()
    )
    
    # Personas que han regresado de vacaciones pero no han pasado por el médico
    sin_revision_medica = Person.objects.filter(
        id__in=[v.person.id for v in VacationRecord.objects.filter(
            person__in=personal,
            end_date__lt=timezone.now().date(),
            medical_checkup_done=False
        )]
    )
    
    # Inicializar variables para búsqueda de persona
    persona = None
    historial = None
    permiso_activo = None
    vacaciones_persona = None
    
    # Formularios
    form_permiso = PermisoSalidaForm()
    form_vacaciones = VacationRecordForm(user=request.user)
    form_sancion = SanctionForm(user=request.user)
    form_visitante = VisitorRecordForm()
    
    # Búsqueda por cédula
    cedula = request.GET.get('cedula')
    if cedula:
        try:
            persona = person_queryset_for(request.user).get(id_number=cedula)
            
            # Verificar si pertenece a esta área
            if not persona.area or area.lower() not in persona.area.lower():
                error = f"Esta persona no pertenece al área de {area}"
                messages.warning(request, error)
            
            # Historial de asistencia
            historial = AttendanceRecord.objects.filter(
                person=persona
            ).order_by('-timestamp')[:10]
            
            # Permiso activo
            permiso_activo = PermisoSalida.objects.filter(
                person=persona,
                fecha_inicio__lte=timezone.now().date(),
                fecha_fin__gte=timezone.now().date()
            ).first()
            
            # Vacaciones activas
            vacaciones_persona = VacationRecord.objects.filter(
                person=persona,
                start_date__lte=timezone.now().date(),
                end_date__gte=timezone.now().date()
            ).first()
            
        except Person.DoesNotExist:
            persona = None
            messages.error(request, "No se encontró ninguna persona con esta cédula.")
    
    context = {
        'personal': personal,
        'vacaciones_activas': vacaciones_activas,
        'sin_revision_medica': sin_revision_medica,
        'area': area.capitalize(),
        'persona': persona,
        'historial': historial,
        'permiso_activo': permiso_activo,
        'vacaciones_persona': vacaciones_persona,
        'form_permiso': form_permiso,
        'form_vacaciones': form_vacaciones,
        'form_sancion': form_sancion,
        'form_visitante': form_visitante,
        'today': today,  # Añadir esta línea
    }
    
    return render(request, 'gestion_personal/admin/dashboard_admin.html', context)

@login_required
@user_passes_test(is_any_admin)
def personal_area(request):
    """Lista del personal por área para administradores"""
    user = request.user
    area = 'mina' if user.user_type == 'admin_mina' else 'molino'
    
    # Buscar personas del área
    personal = Person.objects.filter(area__icontains=area)
    
    # Filtros
    search = request.GET.get('search', '')
    if search:
        personal = personal.filter(
            Q(first_name__icontains=search) | 
            Q(last_name__icontains=search) | 
            Q(id_number__icontains=search)
        )
    
    context = {
        'personal': personal,
        'area': area.capitalize(),
        'search': search,
    }
    
    return render(request, 'gestion_personal/admin/personal_area.html', context)

@login_required
@user_passes_test(is_any_admin)
@require_POST
def crear_permiso_admin(request):
    """Crear permiso desde administrador"""
    form = PermisoSalidaForm(request.POST)
    if form.is_valid():
        # Verificar que la persona pertenece a su área
        persona = form.cleaned_data['person']
        user = request.user
        area = 'mina' if user.user_type == 'admin_mina' else 'molino'
        
        if not persona.area or area.lower() not in persona.area.lower():
            messages.error(request, f"No puede gestionar permisos para personal fuera del área de {area}")
        else:
            permiso = form.save(commit=False)
            permiso.creado_por = request.user
            permiso.save()
            messages.success(request, "Permiso registrado correctamente.")
    else:
        messages.error(request, "Hubo un error en el formulario.")
    
    # Redirigir a la página de origen
    return redirect(request.META.get('HTTP_REFERER', 'dashboard_admin'))

@login_required
@user_passes_test(is_any_admin)
@require_POST
def crear_vacaciones_admin(request):
    """Crear vacaciones desde administrador"""
    form = VacationRecordForm(request.POST, approved_by=request.user, user=request.user)
    if form.is_valid():
        # Verificar que la persona pertenece a su área
        persona = form.cleaned_data['person']
        user = request.user
        area = 'mina' if user.user_type == 'admin_mina' else 'molino'
        
        if not persona.area or area.lower() not in persona.area.lower():
            messages.error(request, f"No puede gestionar vacaciones para personal fuera del área de {area}")
        else:
            form.save()
            messages.success(request, "Vacaciones registradas correctamente.")
    else:
        messages.error(request, "Hubo un error en el registro.")
    
    # Redirigir a la página de origen
    return redirect(request.META.get('HTTP_REFERER', 'dashboard_admin'))

@login_required
@user_passes_test(is_any_admin)
@require_POST
def crear_sancion_admin(request):
    """Crear sanción desde administrador"""
    form = SanctionForm(request.POST, impuesta_por=request.user, user=request.user)
    if form.is_valid():
        # Verificar que la persona pertenece a su área
        persona = form.person
        user = request.user
        area = 'mina' if user.user_type == 'admin_mina' else 'molino'
        
        if not persona.area or area.lower() not in persona.area.lower():
            messages.error(request, f"No puede imponer sanciones a personal fuera del área de {area}")
        else:
            form.save()
            messages.success(request, "Sanción registrada correctamente.")
    else:
        messages.error(request, "Hubo un error en el registro.")
    
    # Redirigir a la página de origen
    return redirect(request.META.get('HTTP_REFERER', 'dashboard_admin'))

@login_required
@user_passes_test(is_any_admin)
@require_POST
def visitor_create_admin(request):
    """Registrar nuevo visitante desde administrador"""
    form = VisitorRecordForm(request.POST)
    if form.is_valid():
        visitante = form.save(commit=False)
        visitante.fecha = timezone.localtime()
        visitante.save()
        messages.success(request, "Visitante registrado correctamente.")
    else:
        messages.error(request, "Error al registrar visitante.")
    
    # Redirigir a la página de origen
    return redirect(request.META.get('HTTP_REFERER', 'dashboard_admin'))

# Vistas para Seguridad Física
@login_required
@user_passes_test(is_seguridad_fisica)
def dashboard_seguridad(request):
    """Dashboard para personal de seguridad física"""
    # Registros del día de hoy
    today = timezone.now().date()
    
    # Registros de personal
    registros_personal = AttendanceRecord.objects.select_related('person', 'recorded_by').filter(
        timestamp__date=today
    ).filter(person__in=person_queryset_for(request.user)).order_by('-timestamp')[:RECORD_LIST_LIMIT]
    
    # Registros de visitantes
    registros_visitantes = VisitorRecord.objects.filter(
        fecha__date=today
    ).order_by('-fecha')[:RECORD_LIST_LIMIT]
    
    # Registros de vehículos
    registros_vehiculos = VehicleRecord.objects.select_related('organization', 'registrado_por').filter(
        Q(fecha_ingreso__date=today) | 
        Q(fecha_salida__date=today)
    ).filter(organization_filter_for(request.user)).order_by('-fecha_ingreso')[:RECORD_LIST_LIMIT]
    
    # Inicializar variables para búsqueda de persona
    persona = None
    historial = None
    
    # Búsqueda por cédula
    cedula = request.GET.get('cedula')
    if cedula:
        try:
            persona = person_queryset_for(request.user).get(id_number=cedula)
            
            # Historial de asistencia
            historial = AttendanceRecord.objects.filter(
                person=persona
            ).order_by('-timestamp')[:10]
             
        except Person.DoesNotExist:
            persona = None
            messages.error(request, "No se encontró ninguna persona con esta cédula.")
    
    context = {
        'registros_personal': registros_personal,
        'registros_visitantes': registros_visitantes,
        'registros_vehiculos': registros_vehiculos,
        'persona': persona,
        'historial': historial,
        'today': today,
        'form_visitante': VisitorRecordForm(),
        'form_permiso': PermisoSalidaForm(initial={'person': persona}) if persona else PermisoSalidaForm(),
    }
    
    return render(request, 'gestion_personal/seguridad/dashboard_seguridad.html', context)

@login_required
@user_passes_test(is_seguridad_fisica)
@require_POST
def crear_permiso_seguridad(request):
    form = PermisoSalidaForm(request.POST)
    if form.is_valid():
        permiso = form.save(commit=False)
        if permiso.person.organization_id != request.user.organization_id:
            messages.error(request, "No puede autorizar personas de otra organización.")
            return redirect(request.META.get('HTTP_REFERER', 'dashboard_seguridad'))
        permiso.creado_por = request.user
        permiso.save()
        messages.success(request, "Permiso de salida autorizado por seguridad.")
    else:
        messages.error(request, "No se pudo crear el permiso. Revise las fechas y el motivo.")
    return redirect(request.META.get('HTTP_REFERER', 'dashboard_seguridad'))

@login_required
@user_passes_test(is_seguridad_fisica)
def registros_por_fecha(request):
    """Ver registros por fecha para seguridad física"""
    # Obtener fecha del filtro o usar fecha actual
    fecha_str = request.GET.get('fecha')
    if fecha_str:
        try:
            from datetime import datetime
            fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha_obj = timezone.localdate()
    else:
        fecha_obj = timezone.localdate()
    
    # Registros de personal
    registros_personal_qs = AttendanceRecord.objects.select_related('person', 'recorded_by').filter(
        timestamp__date=fecha_obj
    ).filter(person__in=person_queryset_for(request.user))
    
    # Registros de visitantes
    registros_visitantes_qs = VisitorRecord.objects.filter(
        fecha__date=fecha_obj
    )
    
    # Registros de vehículos
    registros_vehiculos_qs = VehicleRecord.objects.select_related('organization', 'registrado_por').filter(
        Q(fecha_ingreso__date=fecha_obj) | 
        Q(fecha_salida__date=fecha_obj)
    ).filter(organization_filter_for(request.user))

    total_registros = (
        registros_personal_qs.count() +
        registros_visitantes_qs.count() +
        registros_vehiculos_qs.count()
    )
    registros_personal = registros_personal_qs.order_by('-timestamp')[:RECORD_LIST_LIMIT]
    registros_visitantes = registros_visitantes_qs.order_by('-fecha')[:RECORD_LIST_LIMIT]
    registros_vehiculos = registros_vehiculos_qs.order_by('-fecha_ingreso')[:RECORD_LIST_LIMIT]
    
    context = {
        'registros_personal': registros_personal,
        'registros_visitantes': registros_visitantes,
        'registros_vehiculos': registros_vehiculos,
        'fecha': fecha_obj.strftime('%Y-%m-%d'),
        'form_visitante': VisitorRecordForm(),
        'registros_limit': RECORD_LIST_LIMIT,
        'registros_limited': total_registros > RECORD_LIST_LIMIT,
    }
    
    return render(request, 'gestion_personal/seguridad/registros_por_fecha.html', context)

@login_required
@user_passes_test(is_seguridad_fisica)
@require_POST
def visitor_create_seguridad(request):
    """Registrar nuevo visitante desde seguridad"""
    form = VisitorRecordForm(request.POST)
    if form.is_valid():
        visitante = form.save(commit=False)
        visitante.fecha = timezone.localtime()
        visitante.save()
        messages.success(request, "Visitante registrado correctamente.")
    else:
        messages.error(request, "Error al registrar visitante.")
    
    # Redirigir a la página de origen
    return redirect(request.META.get('HTTP_REFERER', 'dashboard_seguridad'))

# Vistas para Técnico de Seguridad
@login_required
@user_passes_test(is_tecnico_seguridad)
def dashboard_tecnico(request):
    """Dashboard para técnico de seguridad"""
    # Inicializar variables para búsqueda de persona
    persona = None
    historial_epp = None
    
    # Formulario para asignación de EPP
    form_epp = EPPAssignmentForm()
    
    # Búsqueda por cédula
    cedula = request.GET.get('cedula')
    if cedula:
        try:
            persona = person_queryset_for(request.user).get(id_number=cedula)
            
            # Historial de EPP asignados
            historial_epp = EPPAssignment.objects.filter(
                person=persona
            ).order_by('-fecha_entrega')
            
        except Person.DoesNotExist:
            persona = None
            messages.error(request, "No se encontró ninguna persona con esta cédula.")
    
    context = {
        'persona': persona,
        'historial_epp': historial_epp,
        'form_epp': form_epp,
    }
    
    return render(request, 'gestion_personal/tecnico/dashboard_tecnico.html', context)

@login_required
@user_passes_test(is_tecnico_seguridad)
@require_POST
def asignar_epp(request):
    """Asignar EPP a una persona"""
    form = EPPAssignmentForm(request.POST, asignado_por=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, "EPP asignado correctamente.")
    else:
        messages.error(request, "Error al asignar EPP.")
    
    # Redirigir a la página de origen con la cédula de la persona
    person = form.cleaned_data.get('person')
    if person:
        return redirect(f"{reverse('dashboard_tecnico')}?cedula={person.id_number}")
    return redirect('dashboard_tecnico')
    """Dashboard para administradores de mina o molino"""
    user = request.user
    area = 'mina' if user.user_type == 'admin_mina' else 'molino'
    
    # Obtener personal del área correspondiente
    personal = Person.objects.filter(area__icontains=area)
    
    # Obtener personas en vacaciones
    vacaciones_activas = VacationRecord.objects.filter(
        person__in=personal,
        start_date__lte=timezone.now().date(),
        end_date__gte=timezone.now().date()
    )
    
    # Personas que han regresado de vacaciones pero no han pasado por el médico
    sin_revision_medica = Person.objects.filter(
        id__in=[v.person.id for v in VacationRecord.objects.filter(
            person__in=personal,
            end_date__lt=timezone.now().date(),
            medical_checkup_done=False
        )]
    )
    
    # Inicializar variables para búsqueda de persona
    persona = None
    historial = None
    permiso_activo = None
    vacaciones_persona = None
    
    # Formularios
    form_permiso = PermisoSalidaForm()
    form_vacaciones = VacationRecordForm(user=request.user)
    form_sancion = SanctionForm(user=request.user)
    form_visitante = VisitorRecordForm()
    
    # Búsqueda por cédula
    cedula = request.GET.get('cedula')
    if cedula:
        try:
            persona = person_queryset_for(request.user).get(id_number=cedula)
            
            # Verificar si pertenece a esta área
            if not persona.area or area.lower() not in persona.area.lower():
                error = f"Esta persona no pertenece al área de {area}"
                messages.warning(request, error)
            
            # Historial de asistencia
            historial = AttendanceRecord.objects.filter(
                person=persona
            ).order_by('-timestamp')[:10]
            
            # Permiso activo
            permiso_activo = PermisoSalida.objects.filter(
                person=persona,
                fecha_inicio__lte=timezone.now().date(),
                fecha_fin__gte=timezone.now().date()
            ).first()
            
            # Vacaciones activas
            vacaciones_persona = VacationRecord.objects.filter(
                person=persona,
                start_date__lte=timezone.now().date(),
                end_date__gte=timezone.now().date()
            ).first()
            
        except Person.DoesNotExist:
            persona = None
            messages.error(request, "No se encontró ninguna persona con esta cédula.")
    
    context = {
        'personal': personal,
        'vacaciones_activas': vacaciones_activas,
        'sin_revision_medica': sin_revision_medica,
        'area': area.capitalize(),
        'persona': persona,
        'historial': historial,
        'permiso_activo': permiso_activo,
        'vacaciones_persona': vacaciones_persona,
        'form_permiso': form_permiso,
        'form_vacaciones': form_vacaciones,
        'form_sancion': form_sancion,
        'form_visitante': form_visitante,
    }
    
    return render(request, 'gestion_personal/admin/dashboard_admin.html', context)

@login_required
def buscar_persona_detallada(request):
    """
    Vista compartida para búsqueda detallada de personas con información completa
    """
    search_term = request.GET.get('q', '')
    user = request.user
    
    if not search_term:
        return JsonResponse({'error': 'Por favor proporcione un término de búsqueda'}, status=400)
    
    # Filtro de área para administradores
    area_filter = None
    if user.user_type in ['admin_mina', 'admin_molino']:
        area = 'mina' if user.user_type == 'admin_mina' else 'molino'
        area_filter = Q(area__icontains=area)
    
    # Aplicar búsqueda base
    query = Q(first_name__icontains=search_term) | Q(last_name__icontains=search_term) | Q(id_number__icontains=search_term)
    
    # Aplicar filtro de área si existe
    if area_filter:
        query = query & area_filter
    
    personas = Person.objects.filter(query)[:20]
    
    # Preparar datos detallados
    today = timezone.now().date()
    
    results = []
    for persona in personas:
        # Verificar estado actual
        permiso_activo = PermisoSalida.objects.filter(
            person=persona,
            fecha_inicio__lte=today,
            fecha_fin__gte=today
        ).exists()
        
        vacaciones_activas = VacationRecord.objects.filter(
            person=persona,
            start_date__lte=today,
            end_date__gte=today
        ).exists()
        
        ultimo_registro = AttendanceRecord.objects.filter(
            person=persona
        ).order_by('-timestamp').first()
        
        esta_dentro = ultimo_registro and ultimo_registro.record_type == 'entrada'
        
        persona_data = {
            'id': persona.id,
            'nombre_completo': f"{persona.first_name} {persona.last_name}",
            'id_number': persona.id_number,
            'cargo': persona.cargo or '',
            'departamento': persona.departamento or '',
            'area': persona.area or '',
            'contacto': persona.phone_number or '',
            'email': persona.email or '',
            'fecha_ingreso': persona.fecha_ingreso.strftime('%d/%m/%Y') if persona.fecha_ingreso else '',
            'permiso_activo': permiso_activo,
            'en_vacaciones': vacaciones_activas,
            'esta_dentro': esta_dentro,
            'chequeo_medico': persona.medical_checkup,
        }
        
        # Añadir URL de la foto si existe
        if persona.foto:
            persona_data['foto_url'] = persona.foto.url
            
        results.append(persona_data)
    
    return JsonResponse({'results': results})

@login_required
@user_passes_test(is_operador)
def retorno_vacaciones(request):
    """Vista para registrar el retorno de personas que estaban de vacaciones"""
    if request.method == 'POST':
        cedula = request.POST.get('cedula')
        
        if not cedula:
            messages.error(request, "Debe proporcionar una cédula")
            return redirect('dashboard_operador')
        
        try:
            persona = person_queryset_for(request.user).get(id_number=cedula)
            
            # Verificar si la persona estaba de vacaciones
            today = timezone.now().date()
            vacaciones = VacationRecord.objects.filter(
                person=persona,
                end_date__lte=today,
                medical_checkup_done=False
            ).order_by('-end_date').first()
            
            if not vacaciones:
                messages.warning(request, f"{persona.first_name} {persona.last_name} no tiene registro de vacaciones recientes para retorno.")
                return redirect('dashboard_operador')
            
            # Marcar para control médico
            persona.medical_checkup = False
            persona.save()
            
            # Registrar ingreso con motivo específico
            AttendanceRecord.objects.create(
                person=persona,
                record_type='entrada',
                motivo="Retorno de vacaciones",
                reason="permiso",
                recorded_by=request.user
            )
            
            messages.success(
                request, 
                f"Se ha registrado el retorno de vacaciones de {persona.first_name} {persona.last_name}. "
                f"Debe pasar por control médico."
            )
            
            # Redireccionar a la página anterior o a la página principal
            return redirect(request.META.get('HTTP_REFERER', 'dashboard_operador'))
            
        except Person.DoesNotExist:
            messages.error(request, "No se encontró ninguna persona con esta cédula.")
            return redirect('dashboard_operador')
    
    today = timezone.now().date()
    personas_org = person_queryset_for(request.user)
    permisos_activos = PermisoSalida.objects.filter(
        person__in=personas_org,
        fecha_inicio__lte=today,
        fecha_fin__gte=today,
    ).select_related('person', 'creado_por').order_by('fecha_fin', 'person__first_name')
    vacaciones_activas = VacationRecord.objects.filter(
        person__in=personas_org,
        start_date__lte=today,
        end_date__gte=today,
    ).select_related('person', 'approved_by').order_by('end_date', 'person__first_name')

    return render(request, 'gestion_personal/operador/retorno_vacaciones.html', {
        'permisos_activos': permisos_activos,
        'vacaciones_activas': vacaciones_activas,
        'today': today,
    })

@login_required
@user_passes_test(is_rh)
def vacation_list(request):
    """Vista para listar todas las vacaciones registradas"""
    # Obtener parámetros de filtrado
    estado = request.GET.get('estado', 'todas')
    search = request.GET.get('search', '')
    
    # Iniciar queryset base
    personal_qs = person_queryset_for(request.user)
    vacaciones_base = VacationRecord.objects.select_related('person', 'approved_by').filter(person__in=personal_qs)
    vacaciones = vacaciones_base
    
    # Filtrar por estado
    today = timezone.now().date()
    if estado == 'activas':
        vacaciones = vacaciones.filter(
            start_date__lte=today,
            end_date__gte=today
        )
    elif estado == 'futuras':
        vacaciones = vacaciones.filter(
            start_date__gt=today
        )
    elif estado == 'pasadas':
        vacaciones = vacaciones.filter(
            end_date__lt=today
        )
    elif estado == 'pendientes_control':
        vacaciones = vacaciones.filter(
            end_date__lt=today,
            medical_checkup_done=False
        )
    
    # Filtrar por búsqueda
    if search:
        vacaciones = vacaciones.filter(
            Q(person__first_name__icontains=search) |
            Q(person__last_name__icontains=search) |
            Q(person__id_number__icontains=search)
        )
    
    # Ordenar resultados
    vacaciones = vacaciones.order_by('-start_date')
    
    # Estadísticas
    total_activas = vacaciones_base.filter(
        start_date__lte=today,
        end_date__gte=today
    ).count()
    
    total_futuras = vacaciones_base.filter(
        start_date__gt=today
    ).count()
    
    total_pendientes_control = vacaciones_base.filter(
        end_date__lt=today,
        medical_checkup_done=False
    ).count()
    
    context = {
        'vacaciones': vacaciones,
        'estado': estado,
        'search': search,
        'total_activas': total_activas,
        'total_futuras': total_futuras,
        'total_pendientes_control': total_pendientes_control,
        'today': today,
    }
    
    return render(request, 'gestion_personal/rh/vacation_list.html', context)

@login_required
@user_passes_test(is_rh)
def vacation_create(request):
    """Vista para crear un nuevo registro de vacaciones"""
    if request.method == 'POST':
        form = VacationRecordForm(request.POST, approved_by=request.user, user=request.user)
        if form.is_valid():
            vacation = form.save()
            messages.success(request, f"Vacaciones registradas correctamente para {vacation.person.first_name} {vacation.person.last_name}")
            
            # Redirigir a la ficha de la persona o al listado de vacaciones
            if 'source' in request.POST and request.POST.get('source') == 'person':
                return redirect(f"{reverse('dashboard_rrhh')}?cedula={vacation.person.id_number}")
            else:
                return redirect('vacation_list')
        else:
            messages.error(request, "Hubo errores en el formulario. Por favor revise los datos ingresados.")
    else:
        # Inicializar con la persona seleccionada si se proporciona un ID
        initial = {}
        person_id = request.GET.get('person_id')
        if person_id:
            try:
                person = person_queryset_for(request.user).get(id=person_id)
                initial['person'] = person
            except Person.DoesNotExist:
                pass
                
        form = VacationRecordForm(approved_by=request.user, initial=initial, user=request.user)
    
    context = {
        'form': form,
        'is_new': True,
    }
    
    return render(request, 'gestion_personal/rh/vacation_form.html', context)


@login_required
@user_passes_test(is_rh)
def monthly_workday_template(request):
    year, month, start_date, end_date, days = selected_month_bounds(request)
    area_filter = request.GET.get('area', '').strip()
    search = request.GET.get('q', '').strip()
    people_qs = person_queryset_for(request.user).filter(estado='activo')
    if area_filter:
        people_qs = people_qs.filter(area__icontains=area_filter)
    if search:
        people_qs = people_qs.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(id_number__icontains=search)
        )
    people = list(
        people_qs.only('id', 'first_name', 'last_name', 'id_number', 'cargo', 'area')
        .order_by('area', 'cargo', 'last_name', 'first_name')
    )

    if request.method == 'POST':
        saved = 0
        deleted = 0
        allowed_statuses = set(WORKDAY_STATUS_META.keys())
        for person in people:
            for day in days:
                field_name = f"status_{person.id}_{day.isoformat()}"
                if field_name not in request.POST:
                    continue
                status = request.POST.get(field_name, '').strip()
                if status and status not in allowed_statuses:
                    continue
                existing = MonthlyWorkDay.objects.filter(person=person, date=day)
                if not status:
                    deleted += existing.delete()[0]
                    continue
                MonthlyWorkDay.objects.update_or_create(
                    person=person,
                    date=day,
                    defaults={'status': status, 'recorded_by': request.user},
                )
                saved += 1

        messages.success(request, f"Plantilla mensual actualizada: {saved} días guardados, {deleted} días limpiados.")
        query = urlencode({
            'year': year,
            'month': month,
            'area': request.GET.get('area', '').strip(),
            'q': request.GET.get('q', '').strip(),
        })
        return redirect(f"{reverse('monthly_workday_template')}?{query}")

    existing_records = {
        (record.person_id, record.date): record
        for record in MonthlyWorkDay.objects.filter(
            person__in=people,
            date__gte=start_date,
            date__lte=end_date,
        )
    }

    vacation_days = set()
    for vacation in VacationRecord.objects.filter(
        person__in=people,
        start_date__lte=end_date,
        end_date__gte=start_date,
    ).only('person_id', 'start_date', 'end_date'):
        current = max(vacation.start_date, start_date)
        finish = min(vacation.end_date, end_date)
        while current <= finish:
            vacation_days.add((vacation.person_id, current))
            current += timedelta(days=1)

    permission_days = set()
    for permiso in PermisoSalida.objects.filter(
        person__in=people,
        fecha_inicio__lte=end_date,
        fecha_fin__gte=start_date,
    ).only('person_id', 'fecha_inicio', 'fecha_fin'):
        current = max(permiso.fecha_inicio, start_date)
        finish = min(permiso.fecha_fin, end_date)
        while current <= finish:
            permission_days.add((permiso.person_id, current))
            current += timedelta(days=1)

    attendance_days = set(
        AttendanceRecord.objects.filter(
            person__in=people,
            timestamp__date__gte=start_date,
            timestamp__date__lte=end_date,
            record_type='entrada',
        ).values_list('person_id', 'timestamp__date')
    )

    rows = build_monthly_workday_rows(
        people, days, existing_records, vacation_days, permission_days, attendance_days
    )

    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = f'attachment; filename="jornada_{year}_{month:02d}.csv"'
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow(['Nombre', 'Cédula', 'Cargo', 'Área'] + [day.strftime('%d/%m/%Y') for day in days] + [
            'Trabajados', 'Libres', 'Vacaciones', 'Permisos', 'No trabajó', 'Tardes'
        ])
        for row in rows:
            person = row['person']
            writer.writerow([
                f"{person.first_name} {person.last_name}",
                person.id_number,
                person.cargo or '',
                person.area or '',
                *[cell['short'] for cell in row['cells']],
                row['worked_days'],
                row['free_days'],
                row['vacation_days'],
                row['permission_days'],
                row['absent_days'],
                row['late_days'],
            ])
        return response

    prev_month = month - 1 or 12
    prev_year = year - 1 if month == 1 else year
    next_month = month + 1 if month < 12 else 1
    next_year = year + 1 if month == 12 else year

    context = {
        'year': year,
        'month': month,
        'month_name': SPANISH_MONTHS[month],
        'month_options': SPANISH_MONTHS.items(),
        'year_options': range(year - 2, year + 3),
        'days': days,
        'rows': rows,
        'status_meta': WORKDAY_STATUS_META,
        'prev_year': prev_year,
        'prev_month': prev_month,
        'next_year': next_year,
        'next_month': next_month,
        'area_filter': area_filter,
        'search': search,
        'area_options': (
            person_queryset_for(request.user)
            .filter(estado='activo')
            .exclude(area__isnull=True)
            .exclude(area='')
            .values_list('area', flat=True)
            .distinct()
            .order_by('area')
        ),
    }
    return render(request, 'gestion_personal/rh/monthly_workday_template.html', context)


@login_required
@user_passes_test(is_rh)
def registrar_sancion(request):
    """Vista para registrar una nueva sanción"""
    if request.method == 'POST':
        form = SanctionForm(request.POST, impuesta_por=request.user, user=request.user)
        if form.is_valid():
            sancion = form.save()
            messages.success(request, f"Sanción registrada correctamente para {sancion.person.first_name} {sancion.person.last_name}")
            
            # Redirigir a la ficha de la persona
            return redirect(f"{reverse('dashboard_rrhh')}?cedula={sancion.person.id_number}")
        else:
            messages.error(request, "Hubo errores en el formulario. Por favor revise los datos ingresados.")
    else:
        # Inicializar con la persona seleccionada si se proporciona un ID
        initial = {}
        person_id = request.GET.get('person_id')
        if person_id:
            try:
                person = Person.objects.get(id=person_id)
                initial['person'] = person
            except Person.DoesNotExist:
                pass
                
        form = SanctionForm(impuesta_por=request.user, user=request.user, initial=initial)
    
    context = {
        'form': form,
    }
    
    return render(request, 'gestion_personal/rh/registrar_sancion.html', context)

@login_required
@user_passes_test(is_rh_or_global)
def reporte_persona_pdf(request, person_id):
    """Vista para generar un reporte PDF del perfil de una persona"""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.styles import getSampleStyleSheet
    from io import BytesIO
    
    # Obtener la persona
    person = get_object_or_404(Person, id=person_id)
    
    # Crear el objeto de respuesta con el tipo MIME adecuado
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="perfil_{person.id_number}.pdf"'
    
    # Crear el PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    
    # Estilos
    styles = getSampleStyleSheet()
    title_style = styles['Heading1']
    subtitle_style = styles['Heading2']
    normal_style = styles['Normal']
    
    # Contenido del PDF
    elements = []
    
    # Título
    elements.append(Paragraph(f"PERFIL DE {person.first_name.upper()} {person.last_name.upper()}", title_style))
    elements.append(Spacer(1, 12))

    # Datos personales
    personal_data = [
        ['Nombre completo', f"{person.first_name} {person.last_name}"],
        ['Cédula', person.id_number],
        ['Género', person.get_gender_display()],
        ['Fecha de nacimiento', person.birth_date.strftime('%d/%m/%Y') if person.birth_date else 'No especificada'],
        ['Dirección', person.address or 'No especificada'],
        ['Teléfono', person.phone_number or 'No especificado'],
        ['Correo electrónico', person.email or 'No especificado'],
        ['Contacto de emergencia', person.contacto_emergencia or 'No especificado'],
    ]
    
    personal_table = Table(personal_data, colWidths=[120, 260])
    personal_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))

    if person.foto:
        try:
            photo = Image(person.foto.open('rb'), width=105, height=130)
        except Exception:
            photo = Paragraph("Foto no disponible", normal_style)
    else:
        photo = Paragraph("Sin foto", normal_style)

    profile_header = Table(
        [[photo, [Paragraph("Datos Personales", subtitle_style), Spacer(1, 6), personal_table]]],
        colWidths=[125, 395],
    )
    profile_header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(profile_header)
    elements.append(Spacer(1, 12))
    
    # Datos laborales
    elements.append(Paragraph("Datos Laborales", subtitle_style))
    work_data = [
        ['Cargo', person.cargo or 'No especificado'],
        ['Departamento', person.departamento or 'No especificado'],
        ['Área', person.area or 'No especificado'],
        ['Fecha de ingreso', person.fecha_ingreso.strftime('%d/%m/%Y') if person.fecha_ingreso else 'No especificada'],
        ['Jornada', f"{person.dias_jornada} días"],
        ['Notas de jornada', person.observaciones_jornada or 'Sin observaciones'],
        ['Estado laboral', person.get_estado_display()],
        ['Fecha de egreso', person.fecha_egreso.strftime('%d/%m/%Y') if person.fecha_egreso else 'No aplica'],
        ['Motivo de egreso', person.motivo_egreso or 'No aplica'],
        ['Documento de renuncia', person.renuncia_pdf.name if person.renuncia_pdf else 'No registrado'],
    ]
    
    t = Table(work_data, colWidths=[120, 300])
    t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("Anotaciones de RRHH", subtitle_style))
    elements.append(Paragraph(person.anotaciones_rrhh or "Sin anotaciones registradas", normal_style))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("Información Médica General", subtitle_style))
    medical_data = [
        ['Revisión médica', 'Completada' if person.medical_checkup else 'Pendiente'],
        ['Última revisión', person.last_checkup_date.strftime('%d/%m/%Y') if person.last_checkup_date else 'No registrada'],
        ['Comentario médico', person.medical_comment or 'Sin comentarios'],
    ]
    t = Table(medical_data, colWidths=[120, 300])
    t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 12))
    
    # Historial de asistencia (últimos 10 registros)
    elements.append(Paragraph("Historial de Asistencia", subtitle_style))
    
    registros = AttendanceRecord.objects.filter(
        person=person
    ).order_by('-timestamp')[:10]
    
    if registros:
        attendance_data = [['Fecha', 'Hora', 'Tipo', 'Motivo']]
        for registro in registros:
            attendance_data.append([
                registro.timestamp.strftime('%d/%m/%Y'),
                registro.timestamp.strftime('%H:%M:%S'),
                registro.get_record_type_display(),
                registro.motivo or 'N/A',
            ])
        
        t = Table(attendance_data, colWidths=[80, 80, 80, 180])
        t.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(t)
    else:
        elements.append(Paragraph("No hay registros de asistencia", normal_style))
    
    elements.append(Spacer(1, 12))
    
    # Vacaciones y permisos
    elements.append(Paragraph("Vacaciones", subtitle_style))
    
    vacaciones = VacationRecord.objects.filter(
        person=person
    ).order_by('-start_date')[:5]
    
    if vacaciones:
        vacation_data = [['Inicio', 'Fin', 'Aprobado por', 'Control médico']]
        for vacacion in vacaciones:
            vacation_data.append([
                vacacion.start_date.strftime('%d/%m/%Y'),
                vacacion.end_date.strftime('%d/%m/%Y'),
                vacacion.approved_by.username if vacacion.approved_by else 'N/A',
                'Completado' if vacacion.medical_checkup_done else 'Pendiente',
            ])
        
        t = Table(vacation_data, colWidths=[80, 80, 110, 150])
        t.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(t)
    else:
        elements.append(Paragraph("No hay registros de vacaciones", normal_style))
    
    elements.append(Spacer(1, 12))
    
    # Sanciones
    elements.append(Paragraph("Sanciones", subtitle_style))
    
    sanciones = Sanction.objects.filter(
        person=person
    ).order_by('-fecha')[:5]
    
    if sanciones:
        sanction_data = [['Fecha', 'Tipo', 'Descripción', 'Impuesta por']]
        for sancion in sanciones:
            sanction_data.append([
                sancion.fecha.strftime('%d/%m/%Y'),
                sancion.tipo,
                sancion.descripcion,
                sancion.impuesta_por.username if sancion.impuesta_por else 'N/A',
            ])
        
        t = Table(sanction_data, colWidths=[80, 80, 180, 80])
        t.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(t)
    else:
        elements.append(Paragraph("No hay registros de sanciones", normal_style))
    
    # Generar el PDF
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    
    return response


@login_required
def verificar_estado(request):
    """
    Verifica si una persona está dentro o fuera del campamento.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'error': 'Método no permitido'}, status=405)
    
    cedula = request.POST.get('cedula')
    if not cedula:
        return JsonResponse({'status': 'error', 'error': 'Cédula no proporcionada'}, status=400)
    
    try:
        # Buscar la persona por cédula
        persona = person_queryset_for(request.user).get(id_number=cedula)
        
        # Obtener el último registro de acceso de esta persona
        ultimo_registro = AttendanceRecord.objects.filter(
            person=persona
        ).order_by('-timestamp').first()
        
        # Determinar si está dentro o fuera
        esta_dentro = False
        if ultimo_registro:
            # Si el último registro es 'entrada', está dentro
            esta_dentro = ultimo_registro.record_type == 'entrada'
        
        return JsonResponse({
            'status': 'ok',
            'esta_dentro': esta_dentro,
            'nombre': f"{persona.first_name} {persona.last_name}",
            'id_number': persona.id_number,
            'ultimo_registro': ultimo_registro.timestamp.strftime('%Y-%m-%d %H:%M:%S') if ultimo_registro else None,
        })
        
    except Person.DoesNotExist:
        return JsonResponse({
            'status': 'error', 
            'error': 'Persona no encontrada con esta cédula'
        }, status=404)
    
    except Exception as e:
        return JsonResponse({
            'status': 'error', 
            'error': f'Error al verificar estado: {str(e)}'
        }, status=500)
    
@login_required
@user_passes_test(is_operador)
def marcacion_rapida(request):
    """Vista para realizar marcaciones rápidas de entrada/salida con detección automática"""
    if request.method == 'POST':
        cedula = request.POST.get('cedula')
        tipo = request.POST.get('tipo')  # puede ser 'entrada', 'salida' o 'auto'
        motivo = request.POST.get('motivo', 'Marcación rápida')
        
        if not cedula:
            return JsonResponse({'status': 'error', 'error': 'Cédula no proporcionada'})
        
        try:
            persona = person_queryset_for(request.user).get(id_number=cedula)

            active_response = person_active_response(persona, action="marcación rápida", user=request.user)
            if active_response:
                return active_response
            
            # Verificar último registro
            ultimo_registro = AttendanceRecord.objects.filter(
                person=persona
            ).order_by('-timestamp').first()

            wait_response = attendance_wait_response(ultimo_registro)
            if wait_response:
                return wait_response
            
            # Si el tipo es 'auto', determinar automáticamente si es entrada o salida
            if tipo == 'auto':
                # Si el último registro es entrada o no hay registros, registrar salida
                # Si el último registro es salida, registrar entrada
                if ultimo_registro and ultimo_registro.record_type == 'entrada':
                    tipo = 'salida'
                else:
                    tipo = 'entrada'
            
            # Validaciones según el tipo de marcación
            if tipo == 'entrada':
                # Si ya está dentro, no permitir nuevo ingreso
                if ultimo_registro and ultimo_registro.record_type == 'entrada':
                    return JsonResponse({"status": "error", "error": "La persona ya se encuentra dentro"})

                hoy = timezone.now().date()
                vacaciones_terminadas = VacationRecord.objects.filter(
                    person=persona,
                    end_date=hoy
                ).exists()
                if vacaciones_terminadas and not persona.medical_checkup:
                    send_telegram_access_alert(
                        access_alert_message(
                            "Intento de ingreso rápido sin control médico posterior a vacaciones.",
                            person=persona,
                            user=request.user,
                            detail="Debe pasar por revisión médica antes de ingresar.",
                        ),
                        person=persona,
                    )
                    return JsonResponse({
                        "status": "error",
                        "error": "La persona debe pasar por control médico antes de ingresar por retorno de vacaciones",
                    })
                
                # Crear registro de entrada
                registro = AttendanceRecord.objects.create(
                    person=persona,
                    record_type='entrada',
                    motivo=motivo or "Ingreso regular (marcación rápida)",
                    recorded_by=request.user
                )
                
                return JsonResponse({
                    "status": "ok", 
                    "message": f"Ingreso registrado para {persona.first_name} {persona.last_name}",
                    "person_name": f"{persona.first_name} {persona.last_name}",
                    "tipo": "entrada"
                })
                
            elif tipo == 'salida':
                # Si no está dentro, no permitir salida
                if not ultimo_registro or ultimo_registro.record_type == 'salida':
                    return JsonResponse({"status": "error", "error": "La persona no se encuentra dentro para registrar salida"})

                if not has_active_exit_authorization(persona):
                    send_telegram_access_alert(
                        access_alert_message(
                            "Intento de salida rápida sin permiso activo.",
                            person=persona,
                            user=request.user,
                            detail="Debe existir permiso de salida o vacaciones activas.",
                        ),
                        person=persona,
                    )
                    return JsonResponse({
                        "status": "error",
                        "error": "La persona no tiene permiso activo para salir. Debe estar autorizado por Seguridad, RRHH o Administración.",
                    })
                
                # Crear registro de salida
                registro = AttendanceRecord.objects.create(
                    person=persona,
                    record_type='salida',
                    motivo=motivo or "Salida regular (marcación rápida)",
                    recorded_by=request.user
                )
                
                return JsonResponse({
                    "status": "ok", 
                    "message": f"Salida registrada para {persona.first_name} {persona.last_name}",
                    "person_name": f"{persona.first_name} {persona.last_name}",
                    "tipo": "salida"
                })
            
            else:
                return JsonResponse({"status": "error", "error": f"Tipo de marcación no válido: {tipo}"})
                
        except Person.DoesNotExist:
            send_telegram_access_alert(
                access_alert_message(
                    "Intento de marcación rápida con cédula no registrada.",
                    cedula=cedula,
                    user=request.user,
                    detail="Si es visitante debe registrarse por el flujo de visitantes.",
                )
            )
            return JsonResponse({"status": "error", "error": "Persona no encontrada con esta cédula"})
        
        except Exception as e:
            import traceback
            return JsonResponse({
                "status": "error", 
                "error": str(e),
                "details": traceback.format_exc()
            })
    
    return redirect('dashboard_operador')

@login_required
@user_passes_test(is_operador)
@require_POST
def completar_visita_programada(request, visita_id):
    """Registrar visitante desde una visita programada"""
    visita = get_object_or_404(VisitaProgramada, id=visita_id, status='pendiente')
    
    # Crear registro de visitante
    visitante = VisitorRecord(
        nombre=visita.nombre,
        cedula=visita.identificacion,
        area_visita=visita.area_visita,
        autorizado_por=visita.autorizado_por
    )
    visitante.save()
    
    # Actualizar estado de la visita programada
    visita.status = 'completada'
    visita.save()
    
    return JsonResponse({
        'status': 'ok',
        'message': f'Visitante {visita.nombre} registrado correctamente'
    })

@login_required
@user_passes_test(is_operador)
@require_POST
def visitor_exit(request):
    """Registrar salida de visitante"""
    visitante_id = request.POST.get("visitante_id")
    if not visitante_id:
        return JsonResponse({"status": "error", "error": "ID de visitante no proporcionado"})
    
    try:
        visitante = VisitorRecord.objects.get(id=visitante_id, fecha_salida__isnull=True)
        visitante.fecha_salida = timezone.now()
        visitante.save()
        
        return JsonResponse({
            "status": "ok",
            "message": f"Salida de visitante {visitante.nombre} registrada correctamente"
        })
    except VisitorRecord.DoesNotExist:
        return JsonResponse({
            "status": "error",
            "error": "Visitante no encontrado o ya registró su salida"
        })
    except Exception as e:
        return JsonResponse({
            "status": "error",
            "error": str(e)
        })

@login_required
@user_passes_test(is_operador)
def vehicle_list(request):
    vehicles_qs = VehicleRecord.objects.select_related('organization').filter(
        organization_filter_for(request.user)
    ).order_by('fecha_salida', '-fecha_ingreso')
    paginator = Paginator(vehicles_qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'gestion_personal/operador/vehicle_list.html', {
        'vehicles': page_obj,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'title': 'Lista de Vehículos'
    })

@login_required
@user_passes_test(is_operador)
def vehicle_edit(request, pk):
    vehicle = get_object_or_404(VehicleRecord.objects.filter(organization_filter_for(request.user)), pk=pk)
    if request.method == 'POST':
        form = VehicleRecordForm(request.POST, instance=vehicle, registrado_por=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Vehículo actualizado correctamente")
            return redirect('vehicle_list')
    else:
        form = VehicleRecordForm(instance=vehicle, registrado_por=request.user)
    
    return render(request, 'gestion_personal/operador/vehicle_form.html', {
        'form': form,
        'title': 'Editar Vehículo'
    })

@login_required
@user_passes_test(is_operador)
def vehicle_delete(request, pk):
    vehicle = get_object_or_404(VehicleRecord.objects.filter(organization_filter_for(request.user)), pk=pk)
    vehicle.delete()
    messages.success(request, "Vehículo eliminado correctamente")
    return redirect('vehicle_list')

# Modificar el decorador de visitas_programadas para permitir más roles
def can_program_visits(user):
    """Verifica si un usuario puede programar visitas"""
    return user.is_authenticated and user.user_type in ['admin_mina', 'admin_molino', 'rh', 'seguridad_fisica']

@login_required
@user_passes_test(can_program_visits)
def visitas_programadas(request):
    """Vista para listar y crear visitas programadas"""
    # Obtener todas las visitas programadas por este usuario
    visitas = VisitaProgramada.objects.filter(programado_por=request.user).order_by('fecha_programada', 'hora_programada')
    
    # Filtrar por fecha si se proporciona
    fecha_str = request.GET.get('fecha')
    if fecha_str:
        try:
            fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            visitas = visitas.filter(fecha_programada=fecha_obj)
        except ValueError:
            pass
    
    # Filtrar por estado si se proporciona
    status = request.GET.get('status')
    if status:
        visitas = visitas.filter(status=status)
    
    # Formulario para nueva visita programada
    if request.method == 'POST':
        form = VisitaProgramadaForm(request.POST, programado_por=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Visita programada correctamente.")
            return redirect('visitas_programadas')
    else:
        # Preseleccionar fecha actual en el formulario
        form = VisitaProgramadaForm(
            initial={'fecha_programada': timezone.localdate()},
            programado_por=request.user
        )
    
    context = {
        'visitas': visitas,
        'form': form,
    }
    
    return render(request, 'gestion_personal/admin/visitas_programadas.html', context)

# También actualizar los otros métodos relacionados
@login_required
@user_passes_test(can_program_visits)
def editar_visita_programada(request, visita_id):
    """Vista para editar una visita programada"""
    visita = get_object_or_404(VisitaProgramada, id=visita_id, programado_por=request.user)
    
    if request.method == 'POST':
        form = VisitaProgramadaForm(request.POST, instance=visita, programado_por=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Visita actualizada correctamente.")
            return redirect('visitas_programadas')
    else:
        form = VisitaProgramadaForm(instance=visita, programado_por=request.user)
    
    context = {
        'form': form,
        'visita': visita,
    }
    
    return render(request, 'gestion_personal/admin/editar_visita_programada.html', context)

@login_required
@user_passes_test(can_program_visits)
@require_POST
def cancelar_visita_programada(request, visita_id):
    """Vista para cancelar una visita programada"""
    visita = get_object_or_404(VisitaProgramada, id=visita_id, programado_por=request.user)
    visita.status = 'cancelada'
    visita.save()
    
    return JsonResponse({
        'status': 'ok',
        'message': f'Visita de {visita.nombre} cancelada correctamente'
    })

###
