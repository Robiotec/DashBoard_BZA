
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.db.models.fields.files import ImageField
from django.core.exceptions import ValidationError
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .services.notifications import send_email_notification, send_telegram_message

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
    dining_hall = models.ForeignKey('DiningHall', on_delete=models.SET_NULL, blank=True, null=True, related_name='diners', verbose_name="Comedor asignado")
    
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


class DiningHall(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='dining_halls', verbose_name="Organización")
    name = models.CharField(max_length=120, verbose_name="Nombre del comedor")
    location = models.CharField(max_length=180, blank=True, verbose_name="Ubicación")
    is_active = models.BooleanField(default=True, verbose_name="Activo")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Comedor"
        verbose_name_plural = "Comedores"
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'name'], name='unique_dining_hall_per_org')
        ]


@receiver(post_save, sender=Organization)
def create_initial_dining_halls(sender, instance, created, **kwargs):
    if created:
        for name in ('Comedor El Minero', 'Comedor Arichabala', 'Comedor Jorge Mina'):
            DiningHall.objects.get_or_create(organization=instance, name=name)


class Room(models.Model):
    SERVICE_STATUS_CHOICES = (
        ('available', 'Disponible'),
        ('out_of_service', 'Fuera de servicio'),
    )

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='rooms', verbose_name="Organización")
    camp = models.CharField(max_length=100, blank=True, verbose_name="Campamento")
    block = models.CharField(max_length=80, verbose_name="Bloque")
    house = models.CharField(max_length=80, blank=True, verbose_name="Casa")
    number = models.CharField(max_length=30, verbose_name="Número de habitación")
    capacity = models.PositiveSmallIntegerField(verbose_name="Capacidad total")
    service_status = models.CharField(max_length=20, choices=SERVICE_STATUS_CHOICES, default='available', verbose_name="Estado operativo")
    notes = models.TextField(blank=True, verbose_name="Observaciones")

    def __str__(self):
        location = f"{self.block} / {self.house}" if self.house else self.block
        return f"{location} / Hab. {self.number}"

    @property
    def occupied_beds(self):
        return self.assignments.filter(status='occupied').count()

    @property
    def available_beds(self):
        return max(self.capacity - self.occupied_beds, 0)

    class Meta:
        verbose_name = "Habitación"
        verbose_name_plural = "Habitaciones"
        ordering = ['block', 'house', 'number']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'block', 'house', 'number'], name='unique_room_per_org')
        ]


class RoomAssignment(models.Model):
    STATUS_CHOICES = (
        ('reserved', 'Reservada'),
        ('occupied', 'Ocupada'),
    )

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='assignments', verbose_name="Habitación")
    person = models.OneToOneField(Person, on_delete=models.CASCADE, related_name='room_assignment', verbose_name="Colaborador")
    dining_hall = models.ForeignKey(DiningHall, on_delete=models.SET_NULL, blank=True, null=True, related_name='assignments', verbose_name="Comedor asignado")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='occupied', verbose_name="Estado")
    check_in_date = models.DateField(default=timezone.localdate, verbose_name="Fecha de ingreso")
    bed_label = models.CharField(max_length=30, blank=True, verbose_name="Cama o litera")
    notes = models.TextField(blank=True, verbose_name="Novedades")
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        errors = {}
        if self.person_id and self.room_id and self.person.organization_id != self.room.organization_id:
            errors['person'] = "El colaborador y la habitación deben pertenecer a la misma organización."
        if self.dining_hall_id and self.room_id and self.dining_hall.organization_id != self.room.organization_id:
            errors['dining_hall'] = "El comedor debe pertenecer a la misma organización."
        if self.room_id and self.room.service_status == 'out_of_service':
            errors['room'] = "No se puede asignar una habitación fuera de servicio."
        if self.room_id:
            used = RoomAssignment.objects.filter(room=self.room).exclude(pk=self.pk).count()
            if used >= self.room.capacity:
                errors['room'] = "La habitación ya alcanzó su capacidad total."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.person} - {self.room}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.person.dining_hall_id != self.dining_hall_id:
            Person.objects.filter(pk=self.person_id).update(dining_hall_id=self.dining_hall_id)
            self.person.dining_hall_id = self.dining_hall_id

    class Meta:
        verbose_name = "Asignación de habitación"
        verbose_name_plural = "Asignaciones de habitaciones"
        ordering = ['room', 'person__last_name']


class RoomMaintenanceIssue(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pendiente'),
        ('in_progress', 'En proceso'),
        ('resolved', 'Resuelta'),
    )

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='maintenance_issues', verbose_name="Habitación")
    description = models.TextField(verbose_name="Novedad o requerimiento")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending', verbose_name="Estado")
    reported_at = models.DateTimeField(auto_now_add=True, verbose_name="Reportada")
    resolved_at = models.DateTimeField(blank=True, null=True, verbose_name="Resuelta")

    def __str__(self):
        return f"{self.room}: {self.description[:60]}"

    class Meta:
        verbose_name = "Novedad de mantenimiento"
        verbose_name_plural = "Novedades de mantenimiento"
        ordering = ['status', '-reported_at']


class RoomOccupancyMovement(models.Model):
    MOVEMENT_CHOICES = (
        ('assigned', 'Asignación'),
        ('updated', 'Cambio'),
        ('released', 'Liberación'),
    )

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='room_movements')
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='room_movements')
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True, related_name='occupancy_movements')
    room_label = models.CharField(max_length=240, blank=True, default='')
    movement_type = models.CharField(max_length=12, choices=MOVEMENT_CHOICES)
    status = models.CharField(max_length=12, choices=RoomAssignment.STATUS_CHOICES)
    bed_label = models.CharField(max_length=30, blank=True)
    movement_date = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='room_movements_recorded')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class DiningAssignmentHistory(models.Model):
    STATUS_CHOICES = (
        ('active', 'Activo'),
        ('pending_change', 'Cambio pendiente'),
        ('temporary', 'Temporal'),
        ('finished', 'Finalizado'),
    )

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='dining_assignment_history')
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='dining_assignment_history')
    dining_hall = models.ForeignKey(DiningHall, on_delete=models.SET_NULL, null=True, blank=True, related_name='assignment_history')
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='dining_assignments_recorded')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date', '-created_at']

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
        
        admins = CustomUser.objects.filter(
            user_type__in=['admin_mina', 'admin_molino', 'seguridad_fisica']
        ).values_list('email', flat=True)
        send_email_notification(subject, message, ['sbarahona@grupominerobonanza.com', *admins])

        self.notify_telegram(message)

    def notify_telegram(self, message):
        send_telegram_message(message, photo=self.person.foto if self.person.foto else None)
    
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
        
        security = CustomUser.objects.filter(
            user_type='seguridad_fisica'
        ).values_list('email', flat=True)
        send_email_notification(subject, message, ['sbarahona@grupominerobonanza.com', *security])
    
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
        
        security = CustomUser.objects.filter(
            user_type='seguridad_fisica'
        ).values_list('email', flat=True)
        send_email_notification(subject, message, ['sbarahona@grupominerobonanza.com', *security])

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


def hr_evidence_upload_to(instance, filename):
    module = instance.__class__.__name__.lower()
    return f"rrhh/{instance.organization_id}/{module}/{timezone.now():%Y/%m}/{filename}"


class HRTrackedRecord(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UpcomingEntry(HRTrackedRecord):
    PROCESS_STATUS_CHOICES = (
        ('draft', 'Por iniciar'), ('pending', 'Pendiente'), ('ready', 'Listo'),
        ('entered', 'Ingresó'), ('cancelled', 'Cancelado'),
    )
    first_name = models.CharField(max_length=120, verbose_name='Nombres')
    last_name = models.CharField(max_length=120, verbose_name='Apellidos')
    id_number = models.CharField(max_length=20, verbose_name='Cédula')
    company = models.CharField(max_length=150, blank=True, verbose_name='Empresa')
    position = models.CharField(max_length=120, blank=True, verbose_name='Cargo')
    department = models.CharField(max_length=120, blank=True, verbose_name='Departamento')
    shift_group = models.CharField(max_length=80, blank=True, verbose_name='Turno o grupo')
    destination_camp = models.CharField(max_length=120, verbose_name='Campamento de destino')
    expected_entry_date = models.DateField(verbose_name='Fecha prevista de ingreso')
    expected_exit_date = models.DateField(blank=True, null=True, verbose_name='Fecha prevista de salida')
    documentation_complete = models.BooleanField(default=False, verbose_name='Documentación completa')
    medical_exam_complete = models.BooleanField(default=False, verbose_name='Examen médico completo')
    induction_complete = models.BooleanField(default=False, verbose_name='Inducción completa')
    accreditation_complete = models.BooleanField(default=False, verbose_name='Acreditación completa')
    final_approval = models.BooleanField(default=False, verbose_name='Aprobación final')
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, blank=True, null=True, related_name='upcoming_entries', verbose_name='Habitación reservada')
    dining_hall = models.ForeignKey(DiningHall, on_delete=models.SET_NULL, blank=True, null=True, related_name='upcoming_entries', verbose_name='Comedor previsto')
    status = models.CharField(max_length=12, choices=PROCESS_STATUS_CHOICES, default='draft', verbose_name='Estado')
    notes = models.TextField(blank=True, verbose_name='Observaciones')
    evidence = models.FileField(upload_to=hr_evidence_upload_to, blank=True, null=True, verbose_name='Documento de respaldo')

    @property
    def requirements_complete(self):
        return all((self.documentation_complete, self.medical_exam_complete, self.induction_complete, self.accreditation_complete, self.final_approval))

    def __str__(self):
        return f'{self.first_name} {self.last_name} - {self.id_number}'

    class Meta:
        ordering = ['expected_entry_date', 'last_name']
        indexes = [models.Index(fields=['organization', 'expected_entry_date', 'status'], name='upcoming_org_date_idx')]


class AnnualActivity(HRTrackedRecord):
    STATUS_CHOICES = (
        ('planned', 'Planificada'), ('in_progress', 'En ejecución'), ('completed', 'Cumplida'),
        ('rescheduled', 'Reprogramada'), ('cancelled', 'Cancelada'),
    )
    action_line = models.CharField(max_length=160, verbose_name='Línea de acción')
    activity = models.TextField(verbose_name='Actividad')
    target_population = models.CharField(max_length=180, blank=True, verbose_name='Población objetivo')
    responsible = models.CharField(max_length=160, verbose_name='Responsable')
    execution_months = models.JSONField(default=list, verbose_name='Meses de ejecución')
    planned_date = models.DateField(blank=True, null=True, verbose_name='Fecha planificada')
    due_date = models.DateField(blank=True, null=True, verbose_name='Fecha límite')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='planned', verbose_name='Estado')
    progress = models.PositiveSmallIntegerField(default=0, verbose_name='Avance (%)')
    evidence = models.FileField(upload_to=hr_evidence_upload_to, blank=True, null=True, verbose_name='Evidencia')
    evidence_link = models.URLField(blank=True, verbose_name='Enlace de evidencia')
    notes = models.TextField(blank=True, verbose_name='Observaciones')

    def __str__(self):
        return self.action_line

    class Meta:
        ordering = ['planned_date', 'action_line']


class SocialBenefitCase(HRTrackedRecord):
    STATUS_CHOICES = (
        ('not_started', 'Por iniciar'), ('processing', 'En trámite'), ('observed', 'Observado'),
        ('approved', 'Aprobado'), ('paid', 'Pagado'), ('closed', 'Cerrado'), ('not_applicable', 'No aplica'),
    )
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='social_benefit_cases', verbose_name='Colaborador')
    case_date = models.DateField(default=timezone.localdate, verbose_name='Fecha del caso')
    management_type = models.CharField(max_length=140, verbose_name='Tipo de subsidio o prestación')
    required_document = models.CharField(max_length=180, blank=True, verbose_name='Documento requerido')
    received_date = models.DateField(blank=True, null=True, verbose_name='Fecha de recepción')
    pending_documents = models.TextField(blank=True, verbose_name='Documentos pendientes')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_started', verbose_name='Estado')
    pending_action = models.TextField(blank=True, verbose_name='Acción pendiente')
    responsible = models.CharField(max_length=160, verbose_name='Responsable')
    close_date = models.DateField(blank=True, null=True, verbose_name='Fecha de cierre')
    result = models.TextField(blank=True, verbose_name='Resultado')
    notes = models.TextField(blank=True, verbose_name='Observaciones')
    evidence = models.FileField(upload_to=hr_evidence_upload_to, blank=True, null=True, verbose_name='Documento de respaldo')

    def __str__(self):
        return f'{self.person} - {self.management_type}'

    class Meta:
        ordering = ['-case_date', 'person__last_name']


class MedicalLeaveCase(HRTrackedRecord):
    REASON_CHOICES = (
        ('general_illness', 'Enfermedad general'), ('work_accident', 'Accidente laboral'),
        ('non_work_accident', 'Accidente no laboral'), ('occupational_disease', 'Enfermedad profesional'),
        ('other', 'Otra novedad'),
    )
    STATUS_CHOICES = (
        ('active', 'Activo'), ('pending', 'Pendiente'), ('returned', 'Reincorporado'),
        ('relocated', 'Reubicado'), ('closed', 'Cerrado'),
    )
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='medical_leave_cases', verbose_name='Colaborador')
    start_date = models.DateField(default=timezone.localdate, verbose_name='Fecha de inicio')
    end_date = models.DateField(verbose_name='Fecha de finalización')
    expected_return_date = models.DateField(verbose_name='Fecha prevista de reintegro')
    reason = models.CharField(max_length=24, choices=REASON_CHOICES, verbose_name='Motivo general')
    days = models.PositiveSmallIntegerField(default=1, verbose_name='Número de días')
    medical_clearance_date = models.DateField(blank=True, null=True, verbose_name='Fecha de alta médica')
    clearance_validated = models.BooleanField(default=False, verbose_name='Alta médica validada')
    administrative_restriction = models.TextField(blank=True, verbose_name='Restricción o reubicación administrativa')
    follow_up_action = models.TextField(blank=True, verbose_name='Acción de seguimiento')
    responsible = models.CharField(max_length=160, verbose_name='Responsable')
    next_review_date = models.DateField(blank=True, null=True, verbose_name='Próxima revisión')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='active', verbose_name='Estado')
    evidence = models.FileField(upload_to=hr_evidence_upload_to, blank=True, null=True, verbose_name='Certificado o respaldo')

    def __str__(self):
        return f'{self.person} - {self.start_date:%d/%m/%Y}'

    class Meta:
        ordering = ['-start_date', 'person__last_name']
        indexes = [models.Index(fields=['organization', 'start_date', 'status'], name='medleave_org_date_idx')]


class AccidentCase(HRTrackedRecord):
    STATUS_CHOICES = (
        ('notice_pending', 'Aviso pendiente'), ('qualification', 'En calificación'),
        ('documents_pending', 'Documentación pendiente'), ('subsidy_processing', 'Subsidio en trámite'),
        ('returned', 'Reincorporado'), ('closed', 'Cerrado'),
    )
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='accident_cases', verbose_name='Colaborador')
    medical_leave = models.ForeignKey(MedicalLeaveCase, on_delete=models.SET_NULL, blank=True, null=True, related_name='accidents', verbose_name='Descanso médico relacionado')
    benefit_case = models.ForeignKey(SocialBenefitCase, on_delete=models.SET_NULL, blank=True, null=True, related_name='accidents', verbose_name='Subsidio relacionado')
    event_type = models.CharField(max_length=140, verbose_name='Tipo de accidente o contingencia')
    event_date = models.DateField(default=timezone.localdate, verbose_name='Fecha del evento')
    event_place = models.CharField(max_length=180, verbose_name='Lugar del evento')
    leave_start_date = models.DateField(verbose_name='Inicio del descanso')
    leave_end_date = models.DateField(verbose_name='Fin del descanso')
    total_leave_days = models.PositiveSmallIntegerField(default=1, verbose_name='Total de días')
    company_days = models.PositiveSmallIntegerField(default=0, verbose_name='Días cubiertos por empresa')
    company_period = models.CharField(max_length=100, blank=True, verbose_name='Periodo empresa')
    iess_days = models.PositiveSmallIntegerField(default=0, verbose_name='Días cubiertos por IESS')
    iess_period = models.CharField(max_length=100, blank=True, verbose_name='Periodo IESS')
    procedure_status = models.CharField(max_length=24, choices=STATUS_CHOICES, default='notice_pending', verbose_name='Estado del trámite')
    return_date = models.DateField(blank=True, null=True, verbose_name='Fecha de retorno')
    return_restrictions = models.TextField(blank=True, verbose_name='Restricciones de retorno')
    follow_up = models.TextField(blank=True, verbose_name='Seguimiento y cierre')
    evidence = models.FileField(upload_to=hr_evidence_upload_to, blank=True, null=True, verbose_name='Documento de respaldo')

    def __str__(self):
        return f'{self.person} - {self.event_date:%d/%m/%Y}'

    class Meta:
        ordering = ['-event_date', 'person__last_name']


class HRInspection(HRTrackedRecord):
    PRIORITY_CHOICES = (('high', 'Alta'), ('medium', 'Media'), ('low', 'Baja'))
    STATUS_CHOICES = (
        ('pending', 'Pendiente'), ('in_progress', 'En proceso'), ('completed', 'Cumplido'),
        ('verified', 'Verificado'), ('closed', 'Cerrado'),
    )
    inspection_date = models.DateField(default=timezone.localdate, verbose_name='Fecha de inspección')
    inspection_type = models.CharField(max_length=140, verbose_name='Tipo de inspección')
    camp = models.CharField(max_length=120, blank=True, verbose_name='Campamento')
    location = models.CharField(max_length=180, verbose_name='Bloque, área o lugar')
    finding = models.TextField(verbose_name='Hallazgo')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium', verbose_name='Prioridad')
    corrective_action = models.TextField(verbose_name='Acción correctiva')
    responsible = models.CharField(max_length=160, verbose_name='Responsable')
    due_date = models.DateField(verbose_name='Fecha prevista de cumplimiento')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='pending', verbose_name='Estado')
    evidence = models.FileField(upload_to=hr_evidence_upload_to, blank=True, null=True, verbose_name='Evidencia')
    verification_notes = models.TextField(blank=True, verbose_name='Notas de verificación')

    def __str__(self):
        return f'{self.inspection_type} - {self.location}'

    class Meta:
        ordering = ['-inspection_date', 'priority']


class HRAuditLog(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='hr_audit_logs')
    module = models.CharField(max_length=40)
    object_id = models.PositiveIntegerField()
    object_label = models.CharField(max_length=240)
    action = models.CharField(max_length=20, choices=(('created', 'Creado'), ('updated', 'Actualizado'), ('deleted', 'Eliminado'), ('viewed', 'Consultado'), ('exported', 'Exportado')))
    detail = models.TextField(blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='hr_audit_logs')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['organization', 'module', 'created_at'], name='hraudit_org_module_idx')]
