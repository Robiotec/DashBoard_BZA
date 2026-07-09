from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone
import signal

from gestion_personal.models import PlateLookupRecord
from gestion_personal.plate_lookup import consultar_placa_completa, normalize_plate, plate_variants, save_plate_lookup_result


class PlateLookupTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise PlateLookupTimeout("La consulta superó el tiempo máximo permitido.")


class Command(BaseCommand):
    help = "Consulta una placa en fuentes externas y guarda el respaldo."

    def add_arguments(self, parser):
        parser.add_argument("placa")
        parser.add_argument("--user-id", type=int, default=None)
        parser.add_argument("--timeout-seconds", type=int, default=120)

    def handle(self, *args, **options):
        placa = normalize_plate(options["placa"])
        user = None
        if options.get("user_id"):
            user = get_user_model().objects.filter(pk=options["user_id"]).first()

        record, _ = PlateLookupRecord.objects.update_or_create(
            placa=placa,
            defaults={
                "placa_aliases": plate_variants(options["placa"]),
                "lookup_status": "running",
                "last_error": "",
                "consultado_por": user,
                "started_at": timezone.now(),
            },
        )

        previous_handler = signal.getsignal(signal.SIGALRM)
        timeout_seconds = max(30, min(int(options["timeout_seconds"] or 120), 120))
        try:
            previous_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_seconds)
            result = consultar_placa_completa(placa)
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)
            record = save_plate_lookup_result(result, user=user)
            self.stdout.write(self.style.SUCCESS(f"Consulta finalizada: {record.placa} ({record.lookup_status})"))
        except PlateLookupTimeout as exc:
            PlateLookupRecord.objects.filter(pk=record.pk).update(
                lookup_status="failed",
                last_error=f"Timeout luego de {max(30, min(int(options['timeout_seconds'] or 120), 120))} segundos",
                completed_at=timezone.now(),
            )
            raise
        except Exception as exc:
            signal.alarm(0)
            PlateLookupRecord.objects.filter(pk=record.pk).update(
                lookup_status="failed",
                last_error=str(exc),
                completed_at=timezone.now(),
            )
            raise
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)
