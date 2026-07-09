from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_personal', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='person',
            name='anotaciones_rrhh',
            field=models.TextField(blank=True, null=True, verbose_name='Anotaciones de RRHH'),
        ),
        migrations.AddField(
            model_name='person',
            name='estado',
            field=models.CharField(
                choices=[('activo', 'Activo'), ('pasivo', 'Pasivo')],
                default='activo',
                max_length=10,
                verbose_name='Estado laboral',
            ),
        ),
        migrations.AddField(
            model_name='person',
            name='fecha_egreso',
            field=models.DateField(blank=True, null=True, verbose_name='Fecha de Egreso'),
        ),
        migrations.AddField(
            model_name='person',
            name='motivo_egreso',
            field=models.TextField(blank=True, null=True, verbose_name='Motivo de egreso'),
        ),
    ]
