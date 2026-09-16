from django.db import migrations


INITIAL_DINING_HALLS = (
    'Comedor El Minero',
    'Comedor Arichabala',
    'Comedor Jorge Mina',
)


def seed_dining_halls(apps, schema_editor):
    Organization = apps.get_model('gestion_personal', 'Organization')
    DiningHall = apps.get_model('gestion_personal', 'DiningHall')
    for organization in Organization.objects.all():
        for name in INITIAL_DINING_HALLS:
            DiningHall.objects.get_or_create(
                organization=organization,
                name=name,
                defaults={'is_active': True},
            )


class Migration(migrations.Migration):
    dependencies = [('gestion_personal', '0017_roomoccupancymovement_room_label_and_more')]

    operations = [migrations.RunPython(seed_dining_halls, migrations.RunPython.noop)]
