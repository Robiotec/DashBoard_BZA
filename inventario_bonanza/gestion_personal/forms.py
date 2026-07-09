from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.core.files.base import ContentFile
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError
from PIL import Image
from .models import *

from io import BytesIO
from django.utils import timezone

##Nuevos

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
        if self.forced_organization and not instance.organization_id:
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
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.approved_by = kwargs.pop('approved_by', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.user and getattr(self.user, 'user_type', None) != 'global_admin':
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
            'fecha_inicio': forms.DateInput(attrs={'type': 'date'}),
            'fecha_fin': forms.DateInput(attrs={'type': 'date'}),
        }

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
        if self.registrado_por and self.registrado_por.user_type != 'global_admin':
            self.fields['organization'].widget = forms.HiddenInput()
            self.fields['organization'].initial = self.registrado_por.organization
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.registrado_por:
            instance.registrado_por = self.registrado_por
            if self.registrado_por.user_type != 'global_admin' and not instance.organization_id:
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
    cedula = forms.CharField(
        label="Cédula",
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Ingrese la cédula del personal'}),
    )

    class Meta:
        model = Sanction
        fields = ['cedula', 'tipo', 'descripcion']
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 4}),
        }
    
    def __init__(self, *args, **kwargs):
        self.impuesta_por = kwargs.pop('impuesta_por', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.person = None
        initial_person = self.initial.get('person')
        if initial_person:
            self.fields['cedula'].initial = initial_person.id_number
            self.fields['cedula'].widget.attrs['readonly'] = True

    def clean_cedula(self):
        cedula = self.cleaned_data['cedula'].strip()
        queryset = Person.objects.all()
        if self.user and getattr(self.user, 'user_type', None) != 'global_admin':
            if getattr(self.user, 'organization_id', None):
                queryset = queryset.filter(organization=self.user.organization)
            else:
                queryset = queryset.filter(organization__isnull=True)
        try:
            self.person = queryset.get(id_number=cedula)
        except Person.DoesNotExist:
            raise forms.ValidationError("No existe una persona con esa cédula en esta organización.")
        return cedula
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.person = self.person or instance.person
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
        if self.programado_por and getattr(self.programado_por, 'user_type', None) != 'global_admin':
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
