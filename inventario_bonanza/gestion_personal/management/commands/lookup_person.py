import signal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from gestion_personal.models import PersonLookupRecord
from gestion_personal.person_lookup import consultar_persona_completa, normalize_cedula, save_person_lookup_result


class PersonLookupTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise PersonLookupTimeout("La consulta supero el tiempo maximo permitido.")


class Command(BaseCommand):
    help = "Consulta una cedula en fuentes externas y guarda el respaldo."

    def add_arguments(self, parser):
        parser.add_argument("cedula")
        parser.add_argument("--user-id", type=int, default=None)
        parser.add_argument("--timeout-seconds", type=int, default=120)

    def handle(self, *args, **options):
        cedula = normalize_cedula(options["cedula"])
        user = None
        if options.get("user_id"):
            user = get_user_model().objects.filter(pk=options["user_id"]).first()

        defaults = {
            "lookup_status": "running",
            "last_error": "",
            "started_at": timezone.now(),
        }
        if user is not None:
            defaults["consultado_por"] = user

        record, _ = PersonLookupRecord.objects.update_or_create(
            cedula=cedula,
            defaults=defaults,
        )

        previous_handler = signal.getsignal(signal.SIGALRM)
        timeout_seconds = max(30, min(int(options["timeout_seconds"] or 120), 120))
        try:
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_seconds)
            result = consultar_persona_completa(cedula)
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)
            record = save_person_lookup_result(result, user=user)
            self.stdout.write(self.style.SUCCESS(f"Consulta finalizada: {record.cedula} ({record.lookup_status})"))
        except PersonLookupTimeout:
            PersonLookupRecord.objects.filter(pk=record.pk).update(
                lookup_status="failed",
                last_error=f"Timeout luego de {timeout_seconds} segundos",
                completed_at=timezone.now(),
            )
            raise
        except Exception as exc:
            signal.alarm(0)
            PersonLookupRecord.objects.filter(pk=record.pk).update(
                lookup_status="failed",
                last_error=str(exc),
                completed_at=timezone.now(),
            )
            raise
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)
