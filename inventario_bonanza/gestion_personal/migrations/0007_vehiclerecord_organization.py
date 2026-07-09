from django.db import migrations, models
import django.db.models.deletion


def set_vehicle_organizations(apps, schema_editor):
    VehicleRecord = apps.get_model('gestion_personal', 'VehicleRecord')
    for vehicle in VehicleRecord.objects.select_related('chofer', 'registrado_por'):
        organization_id = None
        if vehicle.chofer_id:
            organization_id = vehicle.chofer.organization_id
        if not organization_id and vehicle.registrado_por_id:
            organization_id = vehicle.registrado_por.organization_id
        if organization_id:
            vehicle.organization_id = organization_id
            vehicle.save(update_fields=['organization'])


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_personal', '0006_person_renuncia_pdf'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehiclerecord',
            name='organization',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='vehicles', to='gestion_personal.organization', verbose_name='Organización'),
        ),
        migrations.RunPython(set_vehicle_organizations, migrations.RunPython.noop),
    ]
