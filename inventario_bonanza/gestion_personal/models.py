
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.db.models.fields.files import ImageField
from django.core.mail import send_mail
from django.conf import settings
import requests

#Nuevos
def person_photo_upload_to(instance, filename):
    folder = "pasivos" if instance.estado == "pasivo" else "activos"
    return f"personas/{folder}/{instance.id_number}.png"


def resignation_pdf_upload_to(instance, filename):
    return f"renuncias/{instance.id_number}.pdf"


class Organization(models.Model):
    name = models.CharField(max_length=150, unique=True, verbose_name="Nombre")
    slug = models.SlugField(max_length=80, unique=True, verbose_name="Identificador")
    is_active = models.BooleanField(default=True, verbose_name="Activa")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última Actualización")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Organización"
        verbose_name_plural = "Organizaciones"


class CustomUser(AbstractUser):
    USER_TYPE_CHOICES = (
        ('global_admin', 'Administrador Global'),
        ('medico', 'Médico'),
        ('rh', 'Recursos Humanos'),
        ('operador', 'Operador'),
        ('admin_mina', 'Administrador Mina'),
        ('admin_molino', 'Administrador Molino'),
        ('seguridad_fisica', 'Seguridad Física'),
        ('tecnico_seguridad', 'Técnico de Seguridad'),
    )
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, blank=True, null=True, related_name='users', verbose_name="Organización")
    
    def __str__(self):
        return f"{self.username} - {self.get_user_type_display()}"
    
    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

class Person(models.Model):
    GENDER_CHOICES = (
        ('M', 'Masculino'),
        ('F', 'Femenino'),
        ('O', 'Otro'),
    )

    STATUS_CHOICES = (
        ('activo', 'Activo'),
        ('pasivo', 'Pasivo'),
    )
    
    first_name = models.CharField(max_length=100, verbose_name="Nombre")
    last_name = models.CharField(max_length=100, verbose_name="Apellido")
    id_number = models.CharField(max_length=20, verbose_name="Número de Identificación")
    birth_date = models.DateField(verbose_name="Fecha de Nacimiento")
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, verbose_name="Género")
    address = models.TextField(verbose_name="Dirección", blank=True, null=True)
    phone_number = models.CharField(max_length=20, verbose_name="Número de Teléfono", blank=True, null=True)
    email = models.EmailField(verbose_name="Correo Electrónico", blank=True, null=True)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, blank=True, null=True, related_name='people', verbose_name="Organización")
    
    # Campos para información laboral
    cargo = models.CharField(max_length=100, verbose_name="Cargo", blank=True, null=True)
    departamento = models.CharField(max_length=100, verbose_name="Departamento", blank=True, null=True)
    area = models.CharField(max_length=100, verbose_name="Área", blank=True, null=True)
    fecha_ingreso = models.DateField(verbose_name="Fecha de Ingreso a la Empresa", blank=True, null=True)
    dias_jornada = models.PositiveIntegerField(default=22, verbose_name="Días de jornada")
    observaciones_jornada = models.TextField(verbose_name="Observaciones de jornada", blank=True, null=True)
    estado = models.CharField(max_length=10, choices=STATUS_CHOICES, default='activo', verbose_name="Estado laboral")
    fecha_egreso = models.DateField(verbose_name="Fecha de Egreso", blank=True, null=True)
    motivo_egreso = models.TextField(verbose_name="Motivo de egreso", blank=True, null=True)
    renuncia_pdf = models.FileField(upload_to=resignation_pdf_upload_to, blank=True, null=True, verbose_name="PDF de renuncia")
    foto = ImageField(upload_to=person_photo_upload_to, blank=True, null=True, verbose_name="Fotografía")
    contacto_emergencia = models.CharField(max_length=200, verbose_name="Contacto de Emergencia", blank=True, null=True)
    anotaciones_rrhh = models.TextField(verbose_name="Anotaciones de RRHH", blank=True, null=True)
    
    # Campos médicos
    medical_checkup = models.BooleanField(default=False, verbose_name="Revisión Médica Completada")
    medical_comment = models.TextField(blank=True, null=True, verbose_name="Comentario Médico")
    last_checkup_date = models.DateField(blank=True, null=True, verbose_name="Fecha de Última Revisión")
    
    # Campo para usuario del sistema (opcional)
    user = models.OneToOneField(CustomUser, on_delete=models.SET_NULL, blank=True, null=True, related_name='person')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última Actualización")
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.id_number}"
    
    class Meta:
        verbose_name = "Persona"
        verbose_name_plural = "Personas"
        indexes = [
            models.Index(fields=['organization', 'id_number'], name='person_org_id_idx'),
            models.Index(fields=['organization', 'estado'], name='person_org_estado_idx'),
            models.Index(fields=['last_name', 'first_name'], name='person_name_idx'),
        ]
        constraints = [
            models.UniqueConstraint(fields=['organization', 'id_number'], name='unique_person_id_per_organization')
        ]

class AttendanceReason(models.Model):
    name = models.CharField(max_length=100, verbose_name="Nombre")
    description = models.TextField(blank=True, null=True, verbose_name="Descripción")
    
    def __str__(self):
        return self.name

class AttendanceRecord(models.Model):
    RECORD_TYPE_CHOICES = (
        ('entrada', 'Entrada'),
        ('salida', 'Salida'),
    )
    
    REASON_CHOICES = (
        ('permiso', 'Permiso'),
        ('traslado', 'Traslado a otro campamento'),
        ('reunion', 'Reunión'),
        ('vacaciones', 'Vacaciones'),
    )
    
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='attendance_records', verbose_name="Persona")
    record_type = models.CharField(max_length=10, choices=RECORD_TYPE_CHOICES, verbose_name="Tipo de Registro")
    timestamp = models.DateTimeField(default=timezone.now, verbose_name="Fecha y Hora")
    recorded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='recorded_attendances', verbose_name="Registrado por")
    motivo = models.CharField(max_length=200, blank=True, null=True, verbose_name="Motivo de ingreso/salida")
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, blank=True, null=True, verbose_name="Razón")
    campamento_destino = models.CharField(max_length=100, blank=True, null=True, verbose_name="Campamento Destino")

    def __str__(self):
        return f"{self.person} - {self.get_record_type_display()} - {self.timestamp}"
    
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # Enviar notificación por correo solo si es un nuevo registro
        if is_new:
            self.notify_attendance()
    
    def notify_attendance(self):
        """Envía notificación de ingreso/salida a los administradores y seguridad física"""
        subject = f"Registro de {'ingreso' if self.record_type == 'entrada' else 'salida'} - {self.person.first_name} {self.person.last_name}"
        
        message = f"""
        Se ha registrado un {'ingreso' if self.record_type == 'entrada' else 'salida'} para:
        
        Nombre: {self.person.first_name} {self.person.last_name}
        Cédula: {self.person.id_number}
        Fecha y hora: {self.timestamp.strftime('%d/%m/%Y %H:%M:%S')}
        """
        
        if self.reason:
            message += f"Motivo: {self.get_reason_display()}\n"
        
        if self.campamento_destino and self.reason == 'traslado':
            message += f"Destino: {self.campamento_destino}\n"
        
        from_email = "registrodatos@grupominerobonanza.com"
        recipient_list = ["sbarahona@grupominerobonanza.com"]
        
        # Obtener administradores y seguridad física
        admins = CustomUser.objects.filter(
            user_type__in=['admin_mina', 'admin_molino', 'seguridad_fisica']
        ).values_list('email', flat=True)
        
        recipient_list.extend(admins)
        
        try:
            send_mail(subject, message, from_email, recipient_list, fail_silently=True)
        except Exception as e:
            print(f"Error al enviar correo: {e}")

        self.notify_telegram(message)

    def notify_telegram(self, message):
        token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        chat_ids = getattr(settings, 'TELEGRAM_CHAT_IDS', [])
        if not token or not chat_ids:
            return

        caption = message.strip()
        if len(caption) > 1024:
            caption = caption[:1000] + "\n..."

        for chat_id in chat_ids:
            try:
                if self.person.foto:
                    self.person.foto.open('rb')
                    try:
                        response = requests.post(
                            f"https://api.telegram.org/bot{token}/sendPhoto",
                            data={'chat_id': chat_id, 'caption': caption},
                            files={'photo': self.person.foto.file},
                            timeout=15,
                        )
                    finally:
                        self.person.foto.close()
                else:
                    response = requests.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        data={'chat_id': chat_id, 'text': caption},
                        timeout=15,
                    )
                response.raise_for_status()
            except Exception as e:
                print(f"Error al enviar Telegram: {e}")
    
    class Meta:
        verbose_name = "Registro de Asistencia"
        verbose_name_plural = "Registros de Asistencia"
        indexes = [
            models.Index(fields=['timestamp'], name='attendance_time_idx'),
            models.Index(fields=['person', 'timestamp'], name='attendance_person_time_idx'),
            models.Index(fields=['record_type', 'timestamp'], name='attendance_type_time_idx'),
        ]

class PermisoSalida(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='permisos')
    motivo = models.CharField(max_length=255)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    creado_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.person} - {self.motivo}"

class VacationRecord(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='vacation_records', verbose_name="Persona")
    start_date = models.DateField(verbose_name="Fecha de Inicio")
    end_date = models.DateField(verbose_name="Fecha de Fin")
    approved_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='approved_vacations', verbose_name="Aprobado por")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    
    # Campos para control médico post-vacaciones
    medical_checkup_done = models.BooleanField(default=False, verbose_name="Control Médico Completado")
    medical_checkup_date = models.DateTimeField(blank=True, null=True, verbose_name="Fecha de Control Médico")
    medical_notes = models.TextField(blank=True, null=True, verbose_name="Notas Médicas")

    def __str__(self):
        return f"{self.person} - Vacaciones: {self.start_date} a {self.end_date}"
    
    class Meta:
        verbose_name = "Registro de Vacaciones"
        verbose_name_plural = "Registros de Vacaciones"


class MonthlyWorkDay(models.Model):
    STATUS_CHOICES = (
        ('worked', 'Trabajó'),
        ('free', 'Día libre'),
        ('vacation', 'Vacaciones anuales'),
        ('permission', 'Permiso'),
        ('absent', 'No trabajó'),
        ('late_return', 'Regresó tarde'),
    )

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='monthly_work_days', verbose_name="Persona")
    date = models.DateField(verbose_name="Fecha")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, verbose_name="Estado")
    notes = models.CharField(max_length=200, blank=True, null=True, verbose_name="Notas")
    recorded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, blank=True, null=True, related_name='monthly_workday_records', verbose_name="Registrado por")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última actualización")

    def __str__(self):
        return f"{self.person} - {self.date} - {self.get_status_display()}"

    class Meta:
        verbose_name = "Control mensual de jornada"
        verbose_name_plural = "Controles mensuales de jornada"
        constraints = [
            models.UniqueConstraint(fields=['person', 'date'], name='unique_monthly_workday_per_person_date')
        ]
        indexes = [
            models.Index(fields=['date'], name='workday_date_idx'),
            models.Index(fields=['person', 'date'], name='workday_person_date_idx'),
            models.Index(fields=['status', 'date'], name='workday_status_date_idx'),
        ]

class MedicalHistory(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='medical_history')
    check_date = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de revisión")
    comments = models.TextField(verbose_name="Observaciones médicas")
    is_post_vacation = models.BooleanField(default=False, verbose_name="Control post-vacaciones")
    doctor = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='medical_checks')
    
    def __str__(self):
        return f"Control médico de {self.person} - {self.check_date.strftime('%d/%m/%Y')}"
    
    class Meta:
        verbose_name = "Historial Médico"
        verbose_name_plural = "Historiales Médicos"
        ordering = ['-check_date']

class MedicalConsultation(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='medical_consultations')
    doctor = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='medical_consultations')
    fecha = models.DateTimeField(auto_now_add=True)
    peso = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, verbose_name="Peso (kg)")
    temperatura = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True, verbose_name="Temperatura (°C)")
    presion = models.CharField(max_length=20, blank=True, null=True, verbose_name="Presión Arterial")
    observaciones = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"Consulta médica: {self.person} - {self.fecha.strftime('%d/%m/%Y')}"
    
    class Meta:
        verbose_name = "Consulta Médica"
        verbose_name_plural = "Consultas Médicas"
        ordering = ['-fecha']

class VehicleRecord(models.Model):
    placa = models.CharField(max_length=20, verbose_name="Placa del Vehículo")
    marca = models.CharField(max_length=50, blank=True, null=True)
    modelo = models.CharField(max_length=50, blank=True, null=True)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, blank=True, null=True, related_name='vehicles', verbose_name="Organización")
    chofer = models.ForeignKey(Person, on_delete=models.SET_NULL, blank=True, null=True, related_name='vehiculos_conducidos')
    chofer_nombre = models.CharField(max_length=150, blank=True, null=True, verbose_name="Nombre del chofer")
    chofer_cedula = models.CharField(max_length=20, blank=True, null=True, verbose_name="Cédula del chofer")
    fecha_ingreso = models.DateTimeField(auto_now_add=True)
    fecha_salida = models.DateTimeField(blank=True, null=True)
    registrado_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    salida_registrada_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, blank=True, null=True, related_name='vehicle_exits')
    
    def __str__(self):
        return f"Vehículo {self.placa} - Chofer: {self.driver_name}"

    @property
    def driver_name(self):
        if self.chofer_nombre:
            return self.chofer_nombre
        if self.chofer:
            return f"{self.chofer.first_name} {self.chofer.last_name}"
        return "No especificado"

    @property
    def driver_id_number(self):
        if self.chofer_cedula:
            return self.chofer_cedula
        if self.chofer:
            return self.chofer.id_number
        return ""

    @property
    def esta_dentro(self):
        return self.fecha_salida is None
    
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # Enviar notificación por correo solo si es un nuevo registro
        if is_new:
            self.notify_vehicle()
    
    def notify_vehicle(self):
        """Envía notificación de ingreso de vehículo"""
        subject = f"Registro de vehículo - {self.placa}"
        
        message = f"""
        Se ha registrado un vehículo:
        
        Placa: {self.placa}
        Marca: {self.marca or 'No especificada'}
        Chofer: {self.driver_name}
        Cédula chofer: {self.driver_id_number or 'No especificada'}
        Fecha y hora: {self.fecha_ingreso.strftime('%d/%m/%Y %H:%M:%S')}
        """
        
        # Añadir pasajeros si los hay
        pasajeros = VehiclePassenger.objects.filter(vehicle=self)
        if pasajeros.exists():
            message += "\nPasajeros:\n"
            for pasajero in pasajeros:
                message += f"- {pasajero.person.first_name} {pasajero.person.last_name}\n"
        
        from_email = "registrodatos@grupominerobonanza.com"
        recipient_list = ["sbarahona@grupominerobonanza.com"]
        
        # Obtener seguridad física
        security = CustomUser.objects.filter(
            user_type='seguridad_fisica'
        ).values_list('email', flat=True)
        
        recipient_list.extend(security)
        
        try:
            send_mail(subject, message, from_email, recipient_list, fail_silently=True)
        except Exception as e:
            print(f"Error al enviar correo: {e}")
    
    class Meta:
        verbose_name = "Registro de Vehículo"
        verbose_name_plural = "Registros de Vehículos"
        indexes = [
            models.Index(fields=['organization', 'fecha_ingreso'], name='vehicle_org_in_idx'),
            models.Index(fields=['organization', 'fecha_salida'], name='vehicle_org_out_idx'),
            models.Index(fields=['chofer_cedula'], name='vehicle_driver_id_idx'),
        ]

class VehiclePassenger(models.Model):
    vehicle = models.ForeignKey(VehicleRecord, on_delete=models.CASCADE, related_name='pasajeros')
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    
    def __str__(self):
        return f"{self.person} en {self.vehicle.placa}"
    
    class Meta:
        verbose_name = "Pasajero de Vehículo"
        verbose_name_plural = "Pasajeros de Vehículos"


class PlateLookupRecord(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pendiente'),
        ('running', 'Consultando'),
        ('completed', 'Completada'),
        ('completed_with_errors', 'Completada con errores'),
        ('failed', 'Fallida'),
    )

    placa = models.CharField(max_length=20, unique=True, verbose_name="Placa")
    placa_aliases = models.JSONField(default=list, blank=True, verbose_name="Alias de placa")
    lookup_status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='completed', verbose_name="Estado de consulta")
    last_error = models.TextField(blank=True, null=True, verbose_name="Último error")
    propietario = models.CharField(max_length=200, blank=True, null=True, verbose_name="Propietario")
    email = models.EmailField(blank=True, null=True, verbose_name="Correo")
    marca = models.CharField(max_length=100, blank=True, null=True)
    modelo = models.CharField(max_length=200, blank=True, null=True)
    anio = models.CharField(max_length=20, blank=True, null=True, verbose_name="Año")
    pais_fabricacion = models.CharField(max_length=100, blank=True, null=True, verbose_name="País de fabricación")
    clase = models.CharField(max_length=100, blank=True, null=True)
    tipo = models.CharField(max_length=100, blank=True, null=True)
    servicio = models.CharField(max_length=100, blank=True, null=True)
    uso = models.CharField(max_length=100, blank=True, null=True)
    color_1 = models.CharField(max_length=80, blank=True, null=True)
    color_2 = models.CharField(max_length=80, blank=True, null=True)
    carroceria = models.CharField(max_length=100, blank=True, null=True)
    peso = models.CharField(max_length=50, blank=True, null=True)
    vin = models.CharField(max_length=80, blank=True, null=True)
    motor = models.CharField(max_length=80, blank=True, null=True)
    placa_anterior = models.CharField(max_length=40, blank=True, null=True)
    canton_matricula = models.CharField(max_length=100, blank=True, null=True)
    fecha_matricula = models.CharField(max_length=50, blank=True, null=True)
    vencimiento_matricula = models.CharField(max_length=50, blank=True, null=True)
    fecha_inspeccion = models.CharField(max_length=50, blank=True, null=True)
    ultimo_pago = models.CharField(max_length=20, blank=True, null=True)
    cilindraje = models.CharField(max_length=30, blank=True, null=True)
    estado = models.CharField(max_length=80, blank=True, null=True)
    camv_cpn = models.CharField(max_length=80, blank=True, null=True)
    informacion = models.TextField(blank=True, null=True)
    fecha_compraventa = models.CharField(max_length=50, blank=True, null=True)
    anio_ultima_revision = models.CharField(max_length=20, blank=True, null=True)
    ultima_revision_desde = models.CharField(max_length=50, blank=True, null=True)
    ultima_revision_hasta = models.CharField(max_length=50, blank=True, null=True)
    tramites = models.JSONField(default=list, blank=True)
    normalized_data = models.JSONField(default=dict, blank=True)
    consultas_ecuador_data = models.JSONField(default=dict, blank=True)
    atm_guayaquil_data = models.JSONField(default=dict, blank=True)
    axis_crv_data = models.JSONField(default=dict, blank=True)
    source_attempts = models.JSONField(default=dict, blank=True)
    source_errors = models.JSONField(default=dict, blank=True)
    consultado_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, blank=True, null=True, related_name='plate_lookups')
    requested_at = models.DateTimeField(blank=True, null=True, verbose_name="Consulta solicitada")
    started_at = models.DateTimeField(blank=True, null=True, verbose_name="Consulta iniciada")
    completed_at = models.DateTimeField(blank=True, null=True, verbose_name="Consulta finalizada")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.placa} - {self.propietario or 'Sin propietario'}"

    class Meta:
        verbose_name = "Consulta de Placa"
        verbose_name_plural = "Consultas de Placas"
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['placa'], name='plate_lookup_plate_idx'),
            models.Index(fields=['updated_at'], name='plate_lookup_updated_idx'),
        ]


class PersonLookupRecord(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pendiente'),
        ('running', 'Consultando'),
        ('completed', 'Completada'),
        ('completed_with_errors', 'Completada con errores'),
        ('failed', 'Fallida'),
    )

    cedula = models.CharField(max_length=20, unique=True, verbose_name="Cédula")
    lookup_status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending', verbose_name="Estado de consulta")
    last_error = models.TextField(blank=True, null=True, verbose_name="Último error")
    nombre_completo = models.CharField(max_length=250, blank=True, null=True, verbose_name="Nombre completo")
    procesos_actor_total = models.PositiveIntegerField(default=0, verbose_name="Procesos como actor")
    procesos_demandado_total = models.PositiveIntegerField(default=0, verbose_name="Procesos como demandado")
    citaciones_total = models.PositiveIntegerField(default=0, verbose_name="Citaciones ANT")
    normalized_data = models.JSONField(default=dict, blank=True)
    funcion_judicial_data = models.JSONField(default=dict, blank=True)
    sri_data = models.JSONField(default=dict, blank=True)
    ant_data = models.JSONField(default=dict, blank=True)
    source_errors = models.JSONField(default=dict, blank=True)
    consultado_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, blank=True, null=True, related_name='person_lookups')
    requested_at = models.DateTimeField(blank=True, null=True, verbose_name="Consulta solicitada")
    started_at = models.DateTimeField(blank=True, null=True, verbose_name="Consulta iniciada")
    completed_at = models.DateTimeField(blank=True, null=True, verbose_name="Consulta finalizada")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.cedula} - {self.nombre_completo or 'Sin nombre'}"

    class Meta:
        verbose_name = "Consulta de Persona"
        verbose_name_plural = "Consultas de Personas"
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['cedula'], name='person_lookup_id_idx'),
            models.Index(fields=['updated_at'], name='person_lookup_updated_idx'),
        ]


class EPPAssignment(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='epp_assignments')
    tipo_epp = models.CharField(max_length=100)
    fecha_entrega = models.DateTimeField(auto_now_add=True)
    asignado_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    observaciones = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"EPP: {self.tipo_epp} para {self.person}"
    
    class Meta:
        verbose_name = "Asignación de EPP"
        verbose_name_plural = "Asignaciones de EPP"

class Sanction(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='sanctions')
    tipo = models.CharField(max_length=100)
    descripcion = models.TextField()
    fecha = models.DateField(auto_now_add=True)
    impuesta_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    
    def __str__(self):
        return f"Sanción: {self.tipo} - {self.person}"
    
    class Meta:
        verbose_name = "Sanción"
        verbose_name_plural = "Sanciones"

# Añadir fecha_salida a VisitorRecord en models.py
class VisitorRecord(models.Model):
    nombre = models.CharField(max_length=100)
    cedula = models.CharField(max_length=20)
    area_visita = models.CharField(max_length=100)
    autorizado_por = models.CharField(max_length=100)
    fecha = models.DateTimeField(auto_now_add=True)
    fecha_salida = models.DateTimeField(blank=True, null=True, verbose_name="Fecha de Salida")

    def __str__(self):
        return f"{self.nombre} ({self.fecha})"
    
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # Enviar notificación por correo solo si es un nuevo registro
        if is_new:
            self.notify_visitor()
    
    def notify_visitor(self):
        """Envía notificación de nuevo visitante"""
        subject = f"Registro de visitante - {self.nombre}"
        
        message = f"""
        Se ha registrado un nuevo visitante:
        
        Nombre: {self.nombre}
        Cédula: {self.cedula}
        Área de visita: {self.area_visita}
        Autorizado por: {self.autorizado_por}
        Fecha y hora: {self.fecha.strftime('%d/%m/%Y %H:%M:%S')}
        """
        
        from_email = "registrodatos@grupominerobonanza.com"
        recipient_list = ["sbarahona@grupominerobonanza.com"]
        
        # Obtener seguridad física
        security = CustomUser.objects.filter(
            user_type='seguridad_fisica'
        ).values_list('email', flat=True)
        
        recipient_list.extend(security)
        
        try:
            send_mail(subject, message, from_email, recipient_list, fail_silently=True)
        except Exception as e:
            print(f"Error al enviar correo: {e}")

    class Meta:
        indexes = [
            models.Index(fields=['fecha'], name='visitor_date_idx'),
            models.Index(fields=['cedula'], name='visitor_id_idx'),
        ]

class VisitaProgramada(models.Model):
    STATUS_CHOICES = (
        ('pendiente', 'Pendiente'),
        ('completada', 'Completada'),
        ('cancelada', 'Cancelada'),
    )
    
    nombre = models.CharField(max_length=100, verbose_name="Nombre del Visitante")
    identificacion = models.CharField(max_length=20, verbose_name="Número de Identificación")
    empresa = models.CharField(max_length=100, blank=True, null=True, verbose_name="Empresa")
    motivo = models.CharField(max_length=200, verbose_name="Motivo de la Visita")
    fecha_programada = models.DateField(verbose_name="Fecha Programada")
    hora_programada = models.TimeField(verbose_name="Hora Programada")
    area_visita = models.CharField(max_length=100, verbose_name="Área a Visitar")
    autorizado_por = models.CharField(max_length=100, verbose_name="Autorizado Por")
    programado_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='visitas_programadas')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendiente', verbose_name="Estado")
    notas = models.TextField(blank=True, null=True, verbose_name="Notas Adicionales")
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name="Última Actualización")
    
    def __str__(self):
        return f"{self.nombre} - {self.fecha_programada.strftime('%d/%m/%Y')} {self.hora_programada.strftime('%H:%M')}"
    
    class Meta:
        verbose_name = "Visita Programada"
        verbose_name_plural = "Visitas Programadas"
        ordering = ['fecha_programada', 'hora_programada']
