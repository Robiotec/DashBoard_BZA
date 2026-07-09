from django.urls import path
from . import views
from django.views.generic.base import RedirectView

urlpatterns = [
    # Dashboard y redirección
    path('', RedirectView.as_view(pattern_name='role_based_redirect'), name='dashboard'),
    path('role_redirect/', views.role_based_redirect, name='role_based_redirect'),
    path('media-minio/<path:path>', views.private_media, name='private_media'),
    path('api/plate-lookup/<str:placa>/', views.api_plate_lookup, name='api_plate_lookup'),
    path('api/person-lookup/<str:cedula>/', views.api_person_lookup, name='api_person_lookup'),
    path('server/', views.server_status_page, name='server_status_page'),
    path('server/api/', views.server_status_api, name='server_status_api'),

    # Panel Administrador Global
    path('global/dashboard/', views.dashboard_global_admin, name='dashboard_global_admin'),
    path('global/organizaciones/', views.OrganizationListView.as_view(), name='organization_list'),
    path('global/organizaciones/nueva/', views.OrganizationCreateView.as_view(), name='organization_create'),
    path('global/organizaciones/<int:pk>/', views.OrganizationDetailView.as_view(), name='organization_detail'),
    path('global/organizaciones/<int:pk>/editar/', views.OrganizationUpdateView.as_view(), name='organization_update'),
    path('global/usuarios/', views.GlobalUserListView.as_view(), name='global_user_list'),
    path('global/usuarios/nuevo/', views.GlobalUserCreateView.as_view(), name='global_user_create'),
    path('global/usuarios/<int:pk>/editar/', views.GlobalUserUpdateView.as_view(), name='global_user_update'),
    path('global/personas/', views.PersonListView.as_view(), name='global_person_list'),
    path('global/personas/nueva/', views.PersonCreateView.as_view(), name='global_person_create'),
    path('global/personas/<int:pk>/editar/', views.PersonUpdateView.as_view(), name='global_person_update'),
    path('global/personas/<int:pk>/eliminar/', views.PersonDeleteView.as_view(), name='global_person_delete'),
    path('global/registros/', views.global_records, name='global_records'),
    path('global/placas/', views.global_plate_lookup, name='global_plate_lookup'),
    path('global/consultas-personas/', views.global_person_lookup, name='global_person_lookup'),
    path('global/exportar/personas.csv', views.global_people_csv, name='global_people_csv'),
    path('global/exportar/fotos.zip', views.global_people_photos_zip, name='global_people_photos_zip'),
    
    # Panel Operador
    path('operador/dashboard/', views.dashboard_operador, name='dashboard_operador'),
    path('operador/registros/', views.registros_diarios, name='registros_diarios'),
    path('operador/buscar-persona/', views.buscar_persona_por_cedula, name='buscar_persona_por_cedula'),
    path('operador/ingresar/', views.registrar_ingreso, name='registrar_ingreso'),
    path('operador/salir/', views.registrar_salida, name='registrar_salida'),
    path('operador/visitante/nuevo/', views.visitor_create, name='visitor_create'),
    path('operador/vehiculo/nuevo/', views.vehicle_create, name='vehicle_create'),
    path('operador/vehiculo/salida/', views.vehicle_exit, name='vehicle_exit'),
    
    # Panel Médico
    path('medico/dashboard/', views.dashboard_medico, name='dashboard_medico'),
    path('medico/personas/', views.PersonListMedical.as_view(), name='person_list_medical'),
    path('medico/personas/<int:pk>/', views.PersonDetailMedical.as_view(), name='person_detail_medical'),
    path('medico/personas/<int:pk>/checkup/', views.medical_checkup, name='medical_checkup'),
    path('medico/vacaciones/<int:vacation_id>/checkup/', views.medical_vacation_checkup, name='medical_vacation_checkup'),
    path('medico/consulta/nueva/', views.create_medical_consultation, name='create_medical_consultation'),
    path('medico/consulta/<int:pk>/', views.medical_consultation_detail, name='medical_consultation_detail'),
    
    # Panel de RRHH
    path('rh/dashboard/', views.dashboard_rrhh, name='dashboard_rrhh'),
    path('rh/personas/', views.PersonListView.as_view(), name='person_list'),
    path('rh/personas/nueva/', views.PersonCreateView.as_view(), name='person_create'),
    path('rh/personas/<int:pk>/editar/', views.PersonUpdateView.as_view(), name='person_update'),
    path('rh/personas/<int:pk>/eliminar/', views.PersonDeleteView.as_view(), name='person_delete'),
    path('rh/crear-permiso/', views.crear_permiso, name='crear_permiso'),
    path('rh/cancelar-permiso/<int:permiso_id>/', views.cancelar_permiso, name='cancelar_permiso'),
    path('rh/crear-vacaciones/', views.crear_vacaciones, name='crear_vacaciones'),
    path('rh/cancelar-vacaciones/<int:vacacion_id>/', views.cancelar_vacaciones, name='cancelar_vacaciones'),
    path('rh/crear-sancion/', views.crear_sancion, name='crear_sancion'),
    path('rh/personas/<int:person_id>/baja/', views.dar_baja_persona, name='dar_baja_persona'),
    path('rh/importar-excel/', views.import_excel, name='import_excel'),    
    path('rh/exportar-asistencia/', views.export_attendance, name='export_attendance'),
    path('rh/exportar-perfil/<int:person_id>/', views.export_person_profile, name='export_person_profile'),
    
    # Panel de Administradores (Mina y Molino)
    #path('admin/dashboard/', views.dashboard_admin, name='dashboard_admin'),
    path('admin-area/dashboard/', views.dashboard_admin, name='dashboard_admin'),
    path('admin-area/personal/', views.personal_area, name='personal_area'),
    path('admin-area/crear-permiso/', views.crear_permiso_admin, name='crear_permiso_admin'),
    path('admin-area/crear-vacaciones/', views.crear_vacaciones_admin, name='crear_vacaciones_admin'),
    path('admin-area/crear-sancion/', views.crear_sancion_admin, name='crear_sancion_admin'),
    path('admin-area/visitante/nuevo/', views.visitor_create_admin, name='visitor_create_admin'),
    path('admin-area/visitas-programadas/', views.visitas_programadas, name='visitas_programadas'),
    path('admin-area/visitas-programadas/<int:visita_id>/editar/', views.editar_visita_programada, name='editar_visita_programada'),
    path('admin-area/visitas-programadas/<int:visita_id>/cancelar/', views.cancelar_visita_programada, name='cancelar_visita_programada'),

    # Panel de Seguridad Física
    path('seguridad/dashboard/', views.dashboard_seguridad, name='dashboard_seguridad'),
    path('seguridad/registros/', views.registros_por_fecha, name='registros_por_fecha'),
    path('seguridad/visitante/nuevo/', views.visitor_create_seguridad, name='visitor_create_seguridad'),
    path('seguridad/crear-permiso/', views.crear_permiso_seguridad, name='crear_permiso_seguridad'),
    
    # Panel de Técnico de Seguridad
    path('tecnico/dashboard/', views.dashboard_tecnico, name='dashboard_tecnico'),
    path('tecnico/asignar-epp/', views.asignar_epp, name='asignar_epp'),
    
    # Compartidos
    path('buscar-persona-detallada/', views.buscar_persona_detallada, name='buscar_persona_detallada'),
    path('operador/registros/', views.registros_diarios, name='registros_detallados'),
    path('operador/marcacion-rapida/', views.marcacion_rapida, name='marcacion_rapida'),
    path('operador/retorno-vacaciones/', views.retorno_vacaciones, name='retorno_vacaciones'),
    path('rh/vacaciones/', views.vacation_list, name='vacation_list'),
    path('rh/vacaciones/nueva/', views.vacation_create, name='vacation_create'),
    path('rh/jornadas/', views.monthly_workday_template, name='monthly_workday_template'),
    path('rh/sanciones/nueva/', views.registrar_sancion, name='registrar_sancion'),
    path('rh/personas/<int:person_id>/pdf/', views.reporte_persona_pdf, name='reporte_persona_pdf'),
    path('operador/verificar-estado/', views.verificar_estado, name='verificar_estado'),
    path('operador/visita-programada/<int:visita_id>/completar/', views.completar_visita_programada, name='completar_visita_programada'),
    path('operador/visitante/salida/', views.visitor_exit, name='visitor_exit'),

    path('vehicle/list/', views.vehicle_list, name='vehicle_list'),
    path('vehicle/edit/<int:pk>/', views.vehicle_edit, name='vehicle_edit'),
    path('vehicle/delete/<int:pk>/', views.vehicle_delete, name='vehicle_delete'),

    
]
