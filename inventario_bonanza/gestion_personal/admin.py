from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Organization, CustomUser, Person, AttendanceRecord, VacationRecord, MedicalHistory, PlateLookupRecord, PersonLookupRecord
from .forms import CustomUserCreationForm, CustomUserChangeForm

class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser
    list_display = ['username', 'email', 'user_type', 'organization', 'first_name', 'last_name', 'is_active']
    list_filter = ['user_type', 'organization', 'is_active']
    
    # Modificamos los fieldsets para que no incluyan campos inexistentes
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Información personal', {'fields': ('first_name', 'last_name', 'email')}),
        ('Tipo de Usuario', {'fields': ('user_type', 'organization')}),
        ('Permisos', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Fechas importantes', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'user_type', 'organization', 'email', 'first_name', 'last_name', 'is_active'),
        }),
    )

class PersonAdmin(admin.ModelAdmin):
    list_display = ['first_name', 'last_name', 'id_number', 'organization', 'medical_checkup', 'last_checkup_date']
    list_filter = ['organization', 'medical_checkup', 'gender']
    search_fields = ['first_name', 'last_name', 'id_number']

class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'slug']

class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ['person', 'record_type', 'timestamp', 'recorded_by']
    list_filter = ['record_type', 'timestamp']
    date_hierarchy = 'timestamp'

class VacationRecordAdmin(admin.ModelAdmin):
    list_display = ['person', 'start_date', 'end_date', 'approved_by']
    list_filter = ['start_date', 'end_date']

admin.site.register(Organization, OrganizationAdmin)
admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(Person, PersonAdmin)
admin.site.register(AttendanceRecord, AttendanceRecordAdmin)
admin.site.register(VacationRecord, VacationRecordAdmin)

class MedicalHistoryAdmin(admin.ModelAdmin):
    list_display = ['person', 'check_date', 'is_post_vacation', 'doctor']
    list_filter = ['is_post_vacation', 'check_date']
    search_fields = ['person__first_name', 'person__last_name', 'person__id_number']

admin.site.register(MedicalHistory, MedicalHistoryAdmin)


class PlateLookupRecordAdmin(admin.ModelAdmin):
    list_display = ['placa', 'placa_aliases', 'lookup_status', 'propietario', 'marca', 'modelo', 'updated_at', 'consultado_por']
    search_fields = ['placa', 'propietario', 'marca', 'modelo', 'vin', 'motor']
    list_filter = ['lookup_status', 'marca', 'estado', 'updated_at']
    readonly_fields = ['created_at', 'updated_at']


admin.site.register(PlateLookupRecord, PlateLookupRecordAdmin)


class PersonLookupRecordAdmin(admin.ModelAdmin):
    list_display = ['cedula', 'lookup_status', 'nombre_completo', 'procesos_actor_total', 'procesos_demandado_total', 'citaciones_total', 'updated_at', 'consultado_por']
    search_fields = ['cedula', 'nombre_completo']
    list_filter = ['lookup_status', 'updated_at']
    readonly_fields = ['created_at', 'updated_at']


admin.site.register(PersonLookupRecord, PersonLookupRecordAdmin)
