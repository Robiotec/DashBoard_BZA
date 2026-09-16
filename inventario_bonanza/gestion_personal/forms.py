from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.core.files.base import ContentFile
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError
from PIL import Image
from .models import *

from io import BytesIO
from django.utils import timezone
from datetime import timedelta

##Nuevos

def default_short_period_initial():
    today = timezone.localdate()
    return {
        'start_date': today,
        'end_date': today + timedelta(days=7),
        'fecha_inicio': today,
        'fecha_fin': today + timedelta(days=7),
    }

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'user_type', 'organization', 'first_name', 'last_name')

class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'user_type', 'organization', 'first_name', 'last_name', 'is_active')


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ('name', 'slug', 'is_active')


def person_photo_path(person):
    folder = "pasivos" if person.estado == "pasivo" else "activos"
    return f"personas/{folder}/{person.id_number}.png"


def move_person_photo(person, folder):
    if not person.foto:
        return

    storage = person.foto.storage
    old_name = person.foto.name
    new_name = f"personas/{folder}/{person.id_number}.png"
    if old_name == new_name:
        return

    try:
        person.foto.open('rb')
        content = ContentFile(person.foto.read())
    except Exception:
        return
    finally:
        try:
            person.foto.close()
        except Exception:
            pass

    if storage.exists(new_name):
        storage.delete(new_name)
    storage.save(new_name, content)
    if old_name and storage.exists(old_name):
        storage.delete(old_name)
    person.foto.name = new_name


def previous_person_photo_name(person):
    if not person or not person.pk:
        return ''
    return Person.objects.filter(pk=person.pk).values_list('foto', flat=True).first() or ''


def delete_storage_file(storage, name):
    if name and storage.exists(name):
        storage.delete(name)


def move_existing_person_photo(instance, old_name, new_name):
    if not old_name or old_name == new_name:
        return

    storage = instance.foto.storage
    if not storage.exists(old_name):
        return

    instance.foto.open('rb')
    try:
        content = ContentFile(instance.foto.read())
    finally:
        instance.foto.close()

    delete_storage_file(storage, new_name)
    storage.save(new_name, content)
    delete_storage_file(storage, old_name)
    instance.foto.name = new_name


class PersonForm(forms.ModelForm):
    AREA_CHOICES = (
        ('mina', 'Mina'),
        ('molino', 'Molino'),
        ('otro', 'Otro'),
    )

    area_option = forms.ChoiceField(
        label="Área",
        choices=AREA_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm', 'data-area-option': 'true'}),
    )
    area_other = forms.CharField(
        label="Especifique el área",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Escriba el área'}),
    )
    birth_date = forms.DateField(
        label="Fecha de Nacimiento",
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
        input_formats=['%Y-%m-%d'],
    )
    fecha_ingreso = forms.DateField(
        label="Fecha de Ingreso a la Empresa",
        required=False,
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
        input_formats=['%Y-%m-%d'],
    )

    class Meta:
        model = Person
        fields = ('first_name', 'last_name', 'id_number', 'birth_date', 'gender', 
                  'address', 'phone_number', 'email', 'organization', 'cargo', 'departamento',
                  'fecha_ingreso', 'dias_jornada', 'observaciones_jornada',
                  'foto', 'contacto_emergencia', 'anotaciones_rrhh')
        widgets = {
            'observaciones_jornada': forms.Textarea(attrs={'rows': 2, 'class': 'form-control form-control-sm'}),
            'anotaciones_rrhh': forms.Textarea(attrs={'rows': 2, 'class': 'form-control form-control-sm'}),
            'address': forms.Textarea(attrs={'rows': 2, 'class': 'form-control form-control-sm'}),
        }

    def __init__(self, *args, **kwargs):
        self.forced_organization = kwargs.pop('forced_organization', None)
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            css_class = field.widget.attrs.get('class', '')
            if isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = f'{css_class} form-select form-select-sm'.strip()
            elif not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs['class'] = f'{css_class} form-control form-control-sm'.strip()

        current_area = (self.instance.area if self.instance and self.instance.pk else self.initial.get('area')) or 'mina'
        normalized_area = current_area.strip().lower()
        if normalized_area in ['mina', 'molino']:
            self.fields['area_option'].initial = normalized_area
            self.fields['area_other'].initial = ''
        else:
            self.fields['area_option'].initial = 'otro'
            self.fields['area_other'].initial = current_area

    def clean(self):
        cleaned_data = super().clean()
        area_option = cleaned_data.get('area_option')
        area_other = (cleaned_data.get('area_other') or '').strip()
        id_number = (cleaned_data.get('id_number') or '').strip()
        organization = cleaned_data.get('organization') or self.forced_organization or getattr(self.instance, 'organization', None)

        if area_option == 'otro':
            if not area_other:
                self.add_error('area_other', 'Escriba el área.')
            cleaned_data['area'] = area_other
        else:
            cleaned_data['area'] = area_option

        if id_number and organization:
            duplicate = Person.objects.filter(
                organization=organization,
                id_number__iexact=id_number,
            )
            if self.instance and self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error(
                    'id_number',
                    'Advertencia: ya existe una persona registrada con esta cédula en esta organización.',
                )
                cleaned_data['duplicate_id_number'] = True
        return cleaned_data

    def save(self, commit=True):
        old_photo_name = previous_person_photo_name(self.instance)
        instance = super().save(commit=False)
        instance.area = self.cleaned_data.get('area')
        if self.forced_organization:
            instance.organization = self.forced_organization
        if not instance.pk:
            instance.estado = 'activo'
        uploaded_photo = self.files.get('foto')
        photo_cleared = self.cleaned_data.get('foto') is False
        target_photo_name = person_photo_path(instance)

        if uploaded_photo:
            image = Image.open(uploaded_photo)
            if image.mode not in ('RGB', 'RGBA'):
                image = image.convert('RGB')

            output = BytesIO()
            image.save(output, format='PNG')
            instance.foto.save(
                target_photo_name,
                ContentFile(output.getvalue()),
                save=False,
            )
            if old_photo_name and old_photo_name != instance.foto.name:
                delete_storage_file(instance.foto.storage, old_photo_name)
        elif photo_cleared:
            delete_storage_file(instance.foto.storage, old_photo_name)
            instance.foto.name = ''
        elif old_photo_name and old_photo_name != target_photo_name:
            move_existing_person_photo(instance, old_photo_name, target_photo_name)

        if commit:
            instance.save()
            self.save_m2m()
        return instance


class BajaPersonaForm(forms.ModelForm):
    fecha_egreso = forms.DateField(
        label="Fecha de baja",
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        input_formats=['%Y-%m-%d'],
    )
    renuncia_pdf = forms.FileField(
        label="Renuncia en PDF",
        required=True,
        validators=[FileExtensionValidator(allowed_extensions=['pdf'])],
        widget=forms.ClearableFileInput(attrs={'accept': 'application/pdf'}),
    )

    class Meta:
        model = Person
        fields = ('fecha_egreso', 'motivo_egreso', 'renuncia_pdf')
        widgets = {
            'motivo_egreso': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Motivo de la baja o resumen de la renuncia'}),
        }

    def clean_renuncia_pdf(self):
        archivo = self.cleaned_data['renuncia_pdf']
        if archivo.content_type and archivo.content_type != 'application/pdf':
            raise forms.ValidationError("El archivo de renuncia debe ser un PDF.")
        return archivo

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.estado = 'pasivo'
        uploaded_pdf = self.files.get('renuncia_pdf')
        if uploaded_pdf:
            instance.renuncia_pdf.save(
                f"renuncias/{instance.id_number}.pdf",
                uploaded_pdf,
                save=False,
            )
        move_person_photo(instance, "pasivos")
        if commit:
            instance.save()
        return instance

class MedicalCheckupForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ('medical_checkup', 'medical_comment')
        widgets = {
            'medical_comment': forms.Textarea(attrs={'rows': 4}),
        }
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        # Si se marca como checkup completado, actualizar la fecha
        if instance.medical_checkup:
            instance.last_checkup_date = timezone.now().date()
        
        if commit:
            instance.save()
        return instance

class AttendanceRecordForm(forms.ModelForm):
    class Meta:
        model = AttendanceRecord
        fields = ('person', 'record_type', 'motivo', 'reason', 'campamento_destino')
        widgets = {
            'campamento_destino': forms.TextInput(attrs={'placeholder': 'Solo para traslados'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.recorded_by = kwargs.pop('recorded_by', None)
        super().__init__(*args, **kwargs)
        
        # Hacer el campo de campamento_destino visible solo si el motivo es traslado
        self.fields['campamento_destino'].widget.attrs['data-condition-field'] = 'reason'
        self.fields['campamento_destino'].widget.attrs['data-condition-value'] = 'traslado'
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.recorded_by:
            instance.recorded_by = self.recorded_by
        
        if commit:
            instance.save()
        return instance

class VacationRecordForm(forms.ModelForm):
    class Meta:
        model = VacationRecord
        fields = ('person', 'start_date', 'end_date')
        widgets = {
            'start_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'end_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.approved_by = kwargs.pop('approved_by', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.instance.pk:
            defaults = default_short_period_initial()
            self.fields['start_date'].initial = self.initial.get('start_date', defaults['start_date'])
            self.fields['end_date'].initial = self.initial.get('end_date', defaults['end_date'])
        if self.user and (getattr(self.user, 'user_type', None) != 'global_admin' or self.user.organization_id):
            if getattr(self.user, 'organization_id', None):
                self.fields['person'].queryset = Person.objects.filter(organization=self.user.organization).order_by('last_name', 'first_name')
            else:
                self.fields['person'].queryset = Person.objects.none()
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.approved_by:
            instance.approved_by = self.approved_by
        
        if commit:
            instance.save()
        return instance

class VisitorRecordForm(forms.ModelForm):
    class Meta:
        model = VisitorRecord
        fields = ['nombre', 'cedula', 'area_visita', 'autorizado_por']

class PermisoSalidaForm(forms.ModelForm):
    class Meta:
        model = PermisoSalida
        fields = ['person', 'motivo', 'fecha_inicio', 'fecha_fin']
        widgets = {
            'fecha_inicio': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'fecha_fin': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.instance.pk:
            defaults = default_short_period_initial()
            self.fields['fecha_inicio'].initial = self.initial.get('fecha_inicio', defaults['fecha_inicio'])
            self.fields['fecha_fin'].initial = self.initial.get('fecha_fin', defaults['fecha_fin'])

class MedicalHistoryForm(forms.ModelForm):
    class Meta:
        model = MedicalHistory
        fields = ['comments', 'is_post_vacation']
        widgets = {
            'comments': forms.Textarea(attrs={'rows': 4}),
        }

class MedicalConsultationForm(forms.ModelForm):
    class Meta:
        model = MedicalConsultation
        fields = ['person', 'peso', 'temperatura', 'presion', 'observaciones']
        widgets = {
            'observaciones': forms.Textarea(attrs={'rows': 4}),
        }
    
    def __init__(self, *args, **kwargs):
        self.doctor = kwargs.pop('doctor', None)
        super().__init__(*args, **kwargs)
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.doctor:
            instance.doctor = self.doctor
        
        if commit:
            instance.save()
        return instance

class VehicleRecordForm(forms.ModelForm):
    class Meta:
        model = VehicleRecord
        fields = ['placa', 'marca', 'organization', 'chofer_nombre', 'chofer_cedula']
        labels = {
            'placa': 'Placa del vehículo',
            'marca': 'Marca',
            'organization': 'Organización',
            'chofer_nombre': 'Nombre del chofer',
            'chofer_cedula': 'Cédula del chofer',
        }
    
    def __init__(self, *args, **kwargs):
        self.registrado_por = kwargs.pop('registrado_por', None)
        super().__init__(*args, **kwargs)
        self.fields['chofer_nombre'].required = True
        self.fields['chofer_cedula'].required = True
        self.fields['chofer_cedula'].widget.attrs.update({'placeholder': 'Número de cédula'})
        if self.registrado_por and (self.registrado_por.user_type != 'global_admin' or self.registrado_por.organization_id):
            self.fields['organization'].widget = forms.HiddenInput()
            self.fields['organization'].initial = self.registrado_por.organization
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.registrado_por:
            instance.registrado_por = self.registrado_por
            if (self.registrado_por.user_type != 'global_admin' or self.registrado_por.organization_id) and not instance.organization_id:
                instance.organization = self.registrado_por.organization
        
        if commit:
            instance.save()
        return instance


class PlateLookupForm(forms.Form):
    placa = forms.CharField(
        label='Placa',
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Ej: PBJ1979',
            'autocomplete': 'off',
        }),
    )

    def clean_placa(self):
        placa = ''.join(
            char for char in (self.cleaned_data.get('placa') or '').upper().strip()
            if char.isalnum()
        )
        if len(placa) < 5:
            raise forms.ValidationError('Ingrese una placa válida.')
        return placa


class PersonLookupForm(forms.Form):
    cedula = forms.CharField(
        label='Cédula',
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Ej: 0700000000',
            'autocomplete': 'off',
            'inputmode': 'numeric',
        }),
    )

    def clean_cedula(self):
        cedula = ''.join(
            char for char in (self.cleaned_data.get('cedula') or '').strip()
            if char.isdigit()
        )
        if len(cedula) != 10:
            raise forms.ValidationError('Ingrese una cédula válida de 10 dígitos.')
        return cedula


class VehiclePassengerForm(forms.ModelForm):
    class Meta:
        model = VehiclePassenger
        fields = ['person']

class EPPAssignmentForm(forms.ModelForm):
    class Meta:
        model = EPPAssignment
        fields = ['person', 'tipo_epp', 'observaciones']
        widgets = {
            'observaciones': forms.Textarea(attrs={'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        self.asignado_por = kwargs.pop('asignado_por', None)
        super().__init__(*args, **kwargs)
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.asignado_por:
            instance.asignado_por = self.asignado_por
        
        if commit:
            instance.save()
        return instance

class SanctionForm(forms.ModelForm):
    class Meta:
        model = Sanction
        fields = ['person', 'tipo', 'descripcion']
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 4}),
        }
    
    def __init__(self, *args, **kwargs):
        self.impuesta_por = kwargs.pop('impuesta_por', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        queryset = Person.objects.all()
        if self.user and (getattr(self.user, 'user_type', None) != 'global_admin' or self.user.organization_id):
            if getattr(self.user, 'organization_id', None):
                queryset = queryset.filter(organization=self.user.organization)
            else:
                queryset = queryset.filter(organization__isnull=True)
        self.fields['person'].queryset = queryset.filter(estado='activo').order_by('last_name', 'first_name')
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.impuesta_por:
            instance.impuesta_por = self.impuesta_por
        
        if commit:
            instance.save()
        return instance

class VisitaProgramadaForm(forms.ModelForm):
    autorizado_por = forms.ChoiceField(label="Autorizado por")

    class Meta:
        model = VisitaProgramada
        fields = ['nombre', 'identificacion', 'empresa', 'motivo', 'fecha_programada', 
                 'hora_programada', 'area_visita', 'autorizado_por', 'notas']
        widgets = {
            'fecha_programada': forms.DateInput(attrs={'type': 'date'}),
            'hora_programada': forms.TimeInput(attrs={'type': 'time'}),
            'notas': forms.Textarea(attrs={'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        self.programado_por = kwargs.pop('programado_por', None)
        super().__init__(*args, **kwargs)
        autorizadores = CustomUser.objects.filter(is_active=True)
        if self.programado_por and (getattr(self.programado_por, 'user_type', None) != 'global_admin' or self.programado_por.organization_id):
            if getattr(self.programado_por, 'organization_id', None):
                autorizadores = autorizadores.filter(organization=self.programado_por.organization)
            else:
                autorizadores = autorizadores.filter(organization__isnull=True)
        autorizadores = autorizadores.filter(
            user_type__in=['rh', 'admin_mina', 'admin_molino', 'seguridad_fisica', 'global_admin']
        ).order_by('user_type', 'first_name', 'last_name', 'username')
        self.fields['autorizado_por'].choices = [
            (
                user.get_user_type_display(),
                user.get_user_type_display(),
            )
            for user in autorizadores
        ]
        if not self.fields['autorizado_por'].choices:
            self.fields['autorizado_por'].choices = [('', 'No hay perfiles autorizadores activos')]
        if self.instance and self.instance.pk:
            self.fields['autorizado_por'].disabled = True
        
        # Si el usuario es administrador de área, preseleccionar su área
        if self.programado_por and hasattr(self.programado_por, 'user_type'):
            if self.programado_por.user_type == 'admin_mina':
                self.fields['area_visita'].initial = 'Mina'
            elif self.programado_por.user_type == 'admin_molino':
                self.fields['area_visita'].initial = 'Molino'
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.programado_por:
            instance.programado_por = self.programado_por
        
        if commit:
            instance.save()
        return instance
    


# Formulario para importar Excel
class ImportExcelForm(forms.Form):
    excel_file = forms.FileField(label='Seleccionar archivo Excel')


class OrganizationScopedFormMixin:
    def __init__(self, *args, organization=None, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'


class RoomForm(OrganizationScopedFormMixin, forms.ModelForm):
    class Meta:
        model = Room
        fields = ('camp', 'block', 'house', 'number', 'capacity', 'service_status', 'notes')
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization:
            instance.organization = self.organization
        if commit:
            instance.save()
        return instance


class DiningHallForm(OrganizationScopedFormMixin, forms.ModelForm):
    class Meta:
        model = DiningHall
        fields = ('name', 'location', 'is_active')

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization:
            instance.organization = self.organization
        if commit:
            instance.save()
        return instance


class RoomAssignmentForm(OrganizationScopedFormMixin, forms.ModelForm):
    class Meta:
        model = RoomAssignment
        fields = ('person', 'dining_hall', 'status', 'check_in_date', 'bed_label', 'notes')
        widgets = {
            'check_in_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, room=None, **kwargs):
        self.room = room
        super().__init__(*args, **kwargs)
        if self.organization:
            assigned_person_ids = RoomAssignment.objects.exclude(pk=self.instance.pk).values_list('person_id', flat=True)
            self.fields['person'].queryset = Person.objects.filter(
                organization=self.organization, estado='activo'
            ).exclude(id__in=assigned_person_ids).order_by('last_name', 'first_name')
            self.fields['dining_hall'].queryset = DiningHall.objects.filter(
                organization=self.organization, is_active=True
            ).order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        if self.room:
            used = RoomAssignment.objects.filter(room=self.room).exclude(pk=self.instance.pk).count()
            if self.room.service_status == 'out_of_service':
                self.add_error(None, 'No se puede asignar una habitación fuera de servicio.')
            elif used >= self.room.capacity:
                self.add_error(None, 'La habitación ya alcanzó su capacidad total.')
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.room:
            instance.room = self.room
        if commit:
            instance.full_clean()
            instance.save()
            if instance.person.dining_hall_id != instance.dining_hall_id:
                instance.person.dining_hall = instance.dining_hall
                instance.person.save(update_fields=['dining_hall'])
        return instance


class RoomMaintenanceIssueForm(OrganizationScopedFormMixin, forms.ModelForm):
    class Meta:
        model = RoomMaintenanceIssue
        fields = ('description', 'status')
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}


HR_EVIDENCE_EXTENSIONS = ['pdf', 'jpg', 'jpeg', 'png', 'xlsx', 'xls', 'doc', 'docx']
MONTH_OPTIONS = [(str(month), name) for month, name in enumerate(
    ('Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
     'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'), 1
)]


class HRCaseFormMixin(OrganizationScopedFormMixin):
    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, organization=organization, **kwargs)
        if 'person' in self.fields:
            self.fields['person'].queryset = Person.objects.filter(
                organization=organization, estado='activo'
            ).order_by('last_name', 'first_name') if organization else Person.objects.none()
        if 'evidence' in self.fields:
            self.fields['evidence'].validators.append(FileExtensionValidator(HR_EVIDENCE_EXTENSIONS))
            self.fields['evidence'].widget.attrs['accept'] = '.pdf,.jpg,.jpeg,.png,.xlsx,.xls,.doc,.docx'
        for name, field in self.fields.items():
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'})
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault('rows', 2)

    def clean_evidence(self):
        evidence = self.cleaned_data.get('evidence')
        if evidence and getattr(evidence, 'size', 0) > 10 * 1024 * 1024:
            raise ValidationError('El archivo no puede superar 10 MB.')
        return evidence


class UpcomingEntryForm(HRCaseFormMixin, forms.ModelForm):
    class Meta:
        model = UpcomingEntry
        exclude = ('organization', 'created_by', 'updated_by', 'created_at', 'updated_at')
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, organization=organization, **kwargs)
        self.fields['expected_entry_date'].initial = self.fields['expected_entry_date'].initial or timezone.localdate()
        self.fields['room'].queryset = Room.objects.filter(
            organization=organization, service_status='available'
        ).order_by('camp', 'block', 'house', 'number') if organization else Room.objects.none()
        self.fields['dining_hall'].queryset = DiningHall.objects.filter(
            organization=organization, is_active=True
        ).order_by('name') if organization else DiningHall.objects.none()

    def clean(self):
        data = super().clean()
        if data.get('expected_exit_date') and data.get('expected_entry_date') and data['expected_exit_date'] < data['expected_entry_date']:
            self.add_error('expected_exit_date', 'La salida no puede ser anterior al ingreso.')
        room = data.get('room')
        if room:
            current_assignments = room.assignments.count()
            future_reservations = room.upcoming_entries.exclude(pk=self.instance.pk).exclude(
                status__in=('entered', 'cancelled')
            ).count()
            if current_assignments + future_reservations >= room.capacity:
                self.add_error('room', 'La habitación no tiene camas disponibles para esta reserva.')
        return data


class AnnualActivityForm(HRCaseFormMixin, forms.ModelForm):
    execution_months = forms.MultipleChoiceField(
        choices=MONTH_OPTIONS, widget=forms.CheckboxSelectMultiple,
        label='Meses de ejecución', required=True,
    )

    class Meta:
        model = AnnualActivity
        exclude = ('organization', 'created_by', 'updated_by', 'created_at', 'updated_at')
        widgets = {'activity': forms.Textarea(attrs={'rows': 2}), 'notes': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            self.initial['execution_months'] = [str(value) for value in self.instance.execution_months]

    def clean_execution_months(self):
        return sorted({int(value) for value in self.cleaned_data['execution_months']})

    def clean_progress(self):
        progress = self.cleaned_data['progress']
        if progress > 100:
            raise ValidationError('El avance debe estar entre 0 y 100.')
        return progress


class SocialBenefitCaseForm(HRCaseFormMixin, forms.ModelForm):
    class Meta:
        model = SocialBenefitCase
        exclude = ('organization', 'created_by', 'updated_by', 'created_at', 'updated_at')
        widgets = {
            'pending_documents': forms.Textarea(attrs={'rows': 2}),
            'pending_action': forms.Textarea(attrs={'rows': 2}),
            'result': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class MedicalLeaveCaseForm(HRCaseFormMixin, forms.ModelForm):
    class Meta:
        model = MedicalLeaveCase
        exclude = ('organization', 'created_by', 'updated_by', 'created_at', 'updated_at')
        widgets = {
            'administrative_restriction': forms.Textarea(attrs={'rows': 2}),
            'follow_up_action': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields['start_date'].initial = self.fields['start_date'].initial or today
        self.fields['end_date'].initial = self.fields['end_date'].initial or today
        self.fields['expected_return_date'].initial = self.fields['expected_return_date'].initial or today + timedelta(days=1)

    def clean(self):
        data = super().clean()
        start, end, expected = data.get('start_date'), data.get('end_date'), data.get('expected_return_date')
        if start and end and end < start:
            self.add_error('end_date', 'La finalización no puede ser anterior al inicio.')
        if end and expected and expected < end:
            self.add_error('expected_return_date', 'El reintegro previsto no puede ser anterior al fin del descanso.')
        if start and end:
            data['days'] = (end - start).days + 1
        return data


class AccidentCaseForm(HRCaseFormMixin, forms.ModelForm):
    class Meta:
        model = AccidentCase
        exclude = ('organization', 'created_by', 'updated_by', 'created_at', 'updated_at')
        widgets = {
            'return_restrictions': forms.Textarea(attrs={'rows': 2}),
            'follow_up': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, organization=organization, **kwargs)
        self.fields['medical_leave'].queryset = MedicalLeaveCase.objects.filter(organization=organization).select_related('person') if organization else MedicalLeaveCase.objects.none()
        self.fields['benefit_case'].queryset = SocialBenefitCase.objects.filter(organization=organization).select_related('person') if organization else SocialBenefitCase.objects.none()

    def clean(self):
        data = super().clean()
        start, end = data.get('leave_start_date'), data.get('leave_end_date')
        if start and end and end < start:
            self.add_error('leave_end_date', 'El fin del descanso no puede ser anterior al inicio.')
        if start and end:
            data['total_leave_days'] = (end - start).days + 1
        total = data.get('total_leave_days') or 0
        if (data.get('company_days') or 0) + (data.get('iess_days') or 0) > total:
            raise ValidationError('Los días cubiertos por empresa e IESS no pueden superar el total del descanso.')
        return data


class HRInspectionForm(HRCaseFormMixin, forms.ModelForm):
    class Meta:
        model = HRInspection
        exclude = ('organization', 'created_by', 'updated_by', 'created_at', 'updated_at')
        widgets = {
            'finding': forms.Textarea(attrs={'rows': 2}),
            'corrective_action': forms.Textarea(attrs={'rows': 2}),
            'verification_notes': forms.Textarea(attrs={'rows': 2}),
        }
