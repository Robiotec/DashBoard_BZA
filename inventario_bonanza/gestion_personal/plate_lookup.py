import importlib.util
import logging
import re
from pathlib import Path

from django.utils import timezone

from .models import PlateLookupRecord


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONSULTA_PLATES_DIR = PROJECT_ROOT / "consulta_plates"
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

PLATE_LOOKUP_FIELDS = [
    'propietario', 'email', 'marca', 'modelo', 'anio', 'pais_fabricacion', 'clase',
    'tipo', 'servicio', 'uso', 'color_1', 'color_2', 'carroceria', 'peso', 'vin',
    'motor', 'placa_anterior', 'canton_matricula', 'fecha_matricula',
    'vencimiento_matricula', 'fecha_inspeccion', 'ultimo_pago', 'cilindraje',
    'estado', 'camv_cpn', 'informacion', 'fecha_compraventa',
    'anio_ultima_revision', 'ultima_revision_desde', 'ultima_revision_hasta',
    'tramites',
]


def normalize_plate(plate):
    cleaned = "".join(char for char in str(plate or "").upper().strip() if char.isalnum())
    match = re.fullmatch(r"([A-Z]{3})(\d{1,4})", cleaned)
    if match:
        letters, numbers = match.groups()
        if len(numbers) < 4:
            return f"{letters}{numbers.zfill(4)}"
    return cleaned


def plate_variants(plate):
    cleaned = "".join(char for char in str(plate or "").upper().strip() if char.isalnum())
    canonical = normalize_plate(cleaned)
    variants = [canonical]
    match = re.fullmatch(r"([A-Z]{3})(0+)(\d{1,3})", canonical)
    if match:
        unpadded = f"{match.group(1)}{match.group(3)}"
        variants.append(unpadded)
    if cleaned and cleaned not in variants:
        variants.append(cleaned)
    return variants


def load_consulta_module(module_name):
    module_path = CONSULTA_PLATES_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_consultar(module_name, plate):
    try:
        module = load_consulta_module(module_name)
        result = module.consultar_placa(plate)
        if not isinstance(result, dict):
            return {"placa": plate, "error": "La fuente no devolvio un diccionario."}
        return result
    except Exception as exc:
        return {"placa": plate, "error": str(exc)}


def first_value(*values):
    for value in values:
        if value not in (None, ""):
            return value
    return ""


def merge_value(current, incoming):
    if current in (None, "", [], {}):
        return incoming
    if incoming in (None, "", [], {}):
        return current
    if isinstance(current, dict) and isinstance(incoming, dict):
        merged = dict(current)
        for key, value in incoming.items():
            merged[key] = merge_value(merged.get(key), value)
        return merged
    if isinstance(current, list) and isinstance(incoming, list):
        return incoming if len(incoming) > len(current) else current
    return current


def merge_payloads(payloads):
    merged = {}
    for payload in payloads:
        for key, value in (payload or {}).items():
            if key == "error" and merged.get("error") in (None, ""):
                merged[key] = value
            elif key != "error":
                merged[key] = merge_value(merged.get(key), value)
    if any(not payload.get("error") for payload in payloads if isinstance(payload, dict)):
        merged["error"] = None
    return merged


def is_unregistered_plate_error(value):
    message = str(value or "").lower()
    return "placa no se encuentra registrada" in message or "no se encuentra registrada" in message


def build_normalized_payload(plate, source_results):
    ecuador = source_results.get("consultas_ecuador") or {}
    atm = source_results.get("atm_guayaquil") or {}
    axis = source_results.get("axis_crv") or {}
    axis_ident = axis.get("identificacion") or {}
    axis_modelo = axis.get("modelo") or {}
    axis_caracteristicas = axis.get("caracteristicas") or {}
    axis_revision = axis.get("revision") or {}
    axis_unregistered = is_unregistered_plate_error(axis.get("error"))

    return {
        "placa": plate,
        "propietario": first_value(ecuador.get("propietario"), atm.get("propietario")),
        "email": atm.get("email", ""),
        "marca": first_value(ecuador.get("marca"), axis_modelo.get("marca")),
        "modelo": first_value(ecuador.get("modelo"), axis_modelo.get("modelo")),
        "anio": first_value(ecuador.get("anio"), axis_modelo.get("anio_fabricacion")),
        "pais_fabricacion": first_value(ecuador.get("pais_fabricacion"), axis_modelo.get("pais_fabricacion")),
        "clase": first_value(ecuador.get("clase"), axis_caracteristicas.get("Clase Vehículo")),
        "tipo": axis_caracteristicas.get("Tipo Vehículo", ""),
        "servicio": first_value(ecuador.get("servicio"), axis.get("uso")),
        "uso": first_value(ecuador.get("uso"), axis.get("uso")),
        "color_1": axis_caracteristicas.get("Color 1", ""),
        "color_2": axis_caracteristicas.get("Color 2", ""),
        "carroceria": axis_caracteristicas.get("Carrocería", ""),
        "peso": axis_caracteristicas.get("Peso", ""),
        "vin": axis_ident.get("vin", ""),
        "motor": axis_ident.get("motor", ""),
        "placa_anterior": axis_ident.get("placa_anterior", ""),
        "canton_matricula": ecuador.get("canton_matricula", ""),
        "fecha_matricula": first_value(ecuador.get("fecha_matricula"), axis_revision.get("matricula_desde")),
        "vencimiento_matricula": first_value(
            ecuador.get("vencimiento_matricula"),
            axis_revision.get("matricula_hasta"),
        ),
        "fecha_inspeccion": ecuador.get("fecha_inspeccion", ""),
        "ultimo_pago": ecuador.get("ultimo_pago", ""),
        "cilindraje": ecuador.get("cilindraje", ""),
        "estado": first_value(ecuador.get("estado"), "Placa no registrada" if axis_unregistered else ""),
        "camv_cpn": ecuador.get("camv_cpn", ""),
        "informacion": first_value(ecuador.get("informacion"), axis.get("error") if axis_unregistered else ""),
        "fecha_compraventa": atm.get("fecha_compraventa", ""),
        "anio_ultima_revision": axis_revision.get("anio_ultima_revision", ""),
        "ultima_revision_desde": axis_revision.get("ultima_revision_desde", ""),
        "ultima_revision_hasta": axis_revision.get("ultima_revision_hasta", ""),
        "tramites": atm.get("tramites") or [],
    }


def consultar_placa_completa(plate):
    original_plate = "".join(char for char in str(plate or "").upper().strip() if char.isalnum())
    plate = normalize_plate(original_plate)
    variants = plate_variants(original_plate)
    source_modules = {
        "consultas_ecuador": "consulta_ecuador",
        "atm_guayaquil": "consulta_atm",
        "axis_crv": "consulta_vehiculo",
    }
    attempts = {}
    sources = {}
    for source_name, module_name in source_modules.items():
        source_attempts = []
        for variant in variants:
            payload = safe_consultar(module_name, variant)
            payload["placa_consultada"] = variant
            source_attempts.append(payload)
        attempts[source_name] = source_attempts
        sources[source_name] = merge_payloads(source_attempts)
    errors = {
        source: payload.get("error")
        for source, payload in sources.items()
        if payload.get("error")
    }
    return {
        "placa": plate,
        "placa_aliases": variants,
        "normalized": build_normalized_payload(plate, sources),
        "sources": sources,
        "source_attempts": attempts,
        "errors": errors,
    }


def save_plate_lookup_result(result, user=None):
    normalized = result.get('normalized') or {}
    sources = result.get('sources') or {}
    errors = result.get('errors') or {}
    defaults = {
        field: normalized.get(field)
        for field in PLATE_LOOKUP_FIELDS
    }
    defaults.update({
        'placa_aliases': result.get('placa_aliases') or [result.get('placa')],
        'lookup_status': 'completed_with_errors' if errors else 'completed',
        'last_error': '',
        'normalized_data': normalized,
        'consultas_ecuador_data': sources.get('consultas_ecuador') or {},
        'atm_guayaquil_data': sources.get('atm_guayaquil') or {},
        'axis_crv_data': sources.get('axis_crv') or {},
        'source_attempts': result.get('source_attempts') or {},
        'source_errors': errors,
        'completed_at': timezone.now(),
    })
    if user is not None:
        defaults['consultado_por'] = user
    record, _ = PlateLookupRecord.objects.update_or_create(
        placa=result.get('placa'),
        defaults=defaults,
    )
    return record
