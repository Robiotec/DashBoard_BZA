import fcntl
import subprocess
import sys
import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from gestion_personal.models import PlateLookupRecord


class Command(BaseCommand):
    help = "Procesa consultas de placas pendientes con concurrencia controlada."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=2)
        parser.add_argument("--stale-minutes", type=int, default=10)
        parser.add_argument("--timeout-seconds", type=int, default=120)
        parser.add_argument("--sleep", type=float, default=2.0)

    def handle(self, *args, **options):
        lock_path = settings.BASE_DIR / "plate_lookup_drain.lock"
        with open(lock_path, "w") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.stdout.write("Otro drenaje de placas ya esta ejecutandose.")
                return

            cutoff = timezone.now() - timedelta(minutes=max(1, options["stale_minutes"]))
            records = list(
                PlateLookupRecord.objects.filter(
                    lookup_status__in=["pending", "running"],
                    updated_at__lt=cutoff,
                )
                .order_by("updated_at")
                .values_list("placa", flat=True)[: max(1, options["limit"])]
            )

            processed = 0
            timed_out = 0
            failed = 0
            manage_py = settings.BASE_DIR / "manage.py"
            for placa in records:
                timeout_seconds = max(30, min(int(options["timeout_seconds"] or 120), 120))
                command = [
                    sys.executable,
                    str(manage_py),
                    "lookup_plate",
                    placa,
                    "--timeout-seconds",
                    str(timeout_seconds),
                ]
                try:
                    subprocess.run(
                        command,
                        cwd=str(settings.BASE_DIR),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=timeout_seconds + 5,
                        check=True,
                    )
                    processed += 1
                except subprocess.TimeoutExpired:
                    timed_out += 1
                    PlateLookupRecord.objects.filter(placa=placa).update(
                        lookup_status="failed",
                        last_error=f"Timeout luego de {timeout_seconds} segundos",
                        completed_at=timezone.now(),
                    )
                except subprocess.SubprocessError as exc:
                    failed += 1
                    PlateLookupRecord.objects.filter(placa=placa).update(
                        lookup_status="failed",
                        last_error=str(exc),
                        completed_at=timezone.now(),
                    )

                if options["sleep"] > 0:
                    time.sleep(options["sleep"])

            self.stdout.write(
                f"pending={len(records)} processed={processed} timed_out={timed_out} failed={failed}"
            )
