from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from datetime import datetime, timedelta
import xlwt
from io import BytesIO
from django.db.models import Q
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage

from gestion_personal.models import AttendanceRecord, VisitorRecord, VehicleRecord

class Command(BaseCommand):
    help = 'Envía reporte diario de ingresos y salidas por correo electrónico'

    def handle(self, *args, **options):
        # Obtener la fecha de ayer
        yesterday = timezone.now().date() - timedelta(days=1)
        fecha_str = yesterday.strftime('%d/%m/%Y')
        
        # Consultar registros de ayer
        ingresos = AttendanceRecord.objects.filter(
            timestamp__date=yesterday,
            record_type='entrada'
        ).select_related('person', 'recorded_by').order_by('timestamp')
        
        salidas = AttendanceRecord.objects.filter(
            timestamp__date=yesterday,
            record_type='salida'
        ).select_related('person', 'recorded_by').order_by('timestamp')
        
        visitantes = VisitorRecord.objects.filter(
            fecha__date=yesterday
        ).order_by('fecha')
        
        vehiculos = VehicleRecord.objects.filter(
            Q(fecha_ingreso__date=yesterday) | 
            Q(fecha_salida__date=yesterday)
        ).order_by('fecha_ingreso')
        
        # Crear mensaje básico
        message = f"""
        Reporte diario de ingresos y salidas - {fecha_str}
        
        RESUMEN:
        - Total ingresos: {ingresos.count()}
        - Total salidas: {salidas.count()}
        - Total visitantes: {visitantes.count()}
        - Total vehículos: {vehiculos.count()}
        
        El archivo Excel con el detalle completo se adjunta a este correo.
        """
        
        # Crear archivo Excel
        wb = xlwt.Workbook(encoding='utf-8')
        
        # Hoja para ingresos
        ws_ingresos = wb.add_sheet('Ingresos')
        
        # Estilo para encabezados
        font_style = xlwt.XFStyle()
        font_style.font.bold = True
        
        # Encabezados para ingresos
        columns = ['Hora', 'Cédula', 'Nombre', 'Apellido', 'Motivo', 'Razón', 'Destino', 'Registrado por']
        
        for col_num, column_title in enumerate(columns):
            ws_ingresos.write(0, col_num, column_title, font_style)
        
        # Poblar hoja de ingresos
        row_num = 1
        for registro in ingresos:
            row = [
                registro.timestamp.strftime('%H:%M:%S'),
                registro.person.id_number,
                registro.person.first_name,
                registro.person.last_name,
                registro.motivo or 'N/A',
                registro.get_reason_display() if registro.reason else 'N/A',
                registro.campamento_destino or 'N/A',
                registro.recorded_by.username if registro.recorded_by else 'N/A'
            ]
            
            for col_num, cell_value in enumerate(row):
                ws_ingresos.write(row_num, col_num, cell_value)
            
            row_num += 1
        
        # Hoja para salidas
        ws_salidas = wb.add_sheet('Salidas')
        
        # Encabezados para salidas
        for col_num, column_title in enumerate(columns):
            ws_salidas.write(0, col_num, column_title, font_style)
        
        # Poblar hoja de salidas
        row_num = 1
        for registro in salidas:
            row = [
                registro.timestamp.strftime('%H:%M:%S'),
                registro.person.id_number,
                registro.person.first_name,
                registro.person.last_name,
                registro.motivo or 'N/A',
                registro.get_reason_display() if registro.reason else 'N/A',
                registro.campamento_destino or 'N/A',
                registro.recorded_by.username if registro.recorded_by else 'N/A'
            ]
            
            for col_num, cell_value in enumerate(row):
                ws_salidas.write(row_num, col_num, cell_value)
            
            row_num += 1
        
        # Hoja para visitantes
        ws_visitantes = wb.add_sheet('Visitantes')
        
        # Encabezados para visitantes
        visitor_columns = ['Hora', 'Nombre', 'Cédula', 'Área de visita', 'Autorizado por']
        
        for col_num, column_title in enumerate(visitor_columns):
            ws_visitantes.write(0, col_num, column_title, font_style)
        
        # Poblar hoja de visitantes
        row_num = 1
        for visitante in visitantes:
            row = [
                visitante.fecha.strftime('%H:%M:%S'),
                visitante.nombre,
                visitante.cedula,
                visitante.area_visita,
                visitante.autorizado_por
            ]
            
            for col_num, cell_value in enumerate(row):
                ws_visitantes.write(row_num, col_num, cell_value)
            
            row_num += 1
        
        # Hoja para vehículos
        ws_vehiculos = wb.add_sheet('Vehículos')
        
        # Encabezados para vehículos
        vehicle_columns = ['Placa', 'Marca', 'Chofer', 'Cédula Chofer', 'Hora ingreso', 'Hora salida']
        
        for col_num, column_title in enumerate(vehicle_columns):
            ws_vehiculos.write(0, col_num, column_title, font_style)
        
        # Poblar hoja de vehículos
        row_num = 1
        for vehiculo in vehiculos:
            row = [
                vehiculo.placa,
                vehiculo.marca or 'N/A',
                vehiculo.driver_name,
                vehiculo.driver_id_number or 'N/A',
                vehiculo.fecha_ingreso.strftime('%H:%M:%S') if vehiculo.fecha_ingreso and vehiculo.fecha_ingreso.date() == yesterday else 'N/A',
                vehiculo.fecha_salida.strftime('%H:%M:%S') if vehiculo.fecha_salida and vehiculo.fecha_salida.date() == yesterday else 'N/A'
            ]
            
            for col_num, cell_value in enumerate(row):
                ws_vehiculos.write(row_num, col_num, cell_value)
            
            row_num += 1
        
        # Guardar Excel en memoria
        excel_file = BytesIO()
        wb.save(excel_file)
        excel_file.seek(0)
        
        # Preparar correo con adjunto
        email = EmailMessage(
            subject=f'Reporte diario de ingresos y salidas - {fecha_str}',
            body=message,
            from_email='registrodatos@grupominerobonanza.com',
            to=['sbarahona@grupominerobonanza.com'],
        )
        
        # Adjuntar Excel
        excel_file_name = f'reporte_ingresos_salidas_{yesterday.strftime("%Y-%m-%d")}.xls'
        email.attach(excel_file_name, excel_file.read(), 'application/ms-excel')
        
        # Enviar correo
        try:
            email.send()
            self.stdout.write(self.style.SUCCESS(f'Reporte diario enviado correctamente a sbarahona@grupominerobonanza.com'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error al enviar correo: {str(e)}'))
