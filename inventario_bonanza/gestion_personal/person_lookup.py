import importlib.util
import logging
from pathlib import Path

from django.utils import timezone

from .models import PersonLookupRecord


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONSULTA_PEOPLE_DIR = PROJECT_ROOT / "consulta_people"
logging.getLogger("urllib3").setLevel(logging.WARNING)

PERSON_LOOKUP_FIELDS = [
    "nombre_completo",
    "procesos_actor_total",
    "procesos_demandado_total",
    "citaciones_total",
]


def normalize_cedula(cedula):
    return "".join(char for char in str(cedula or "").strip() if char.isdigit())


def load_consulta_module(module_name):
    module_path = CONSULTA_PEOPLE_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_consultar(module_name, cedula):
    try:
        module = load_consulta_module(module_name)
        result = module.consultar_cedula(cedula)
        if not isinstance(result, dict):
            return {"cedula": cedula, "error": "La fuente no devolvio un diccionario."}
        return result
    except Exception as exc:
        return {"cedula": cedula, "error": str(exc)}


def safe_consultar_nombre(module_name, nombre):
    try:
        module = load_consulta_module(module_name)
        result = module.consultar_nombre(nombre)
        if not isinstance(result, dict):
            return {"nombre_completo": nombre, "error": "La fuente no devolvio un diccionario."}
        return result
    except Exception as exc:
        return {"nombre_completo": nombre, "error": str(exc)}


def first_value(*values):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return ""


def consultar_persona_completa(cedula):
    cedula = normalize_cedula(cedula)
    source_modules = {
        "datacil": "consulta_datacil",
        "funcion_judicial": "consulta_funcion_judicial",
        "sri": "consulta_sri",
        "sri_ruc_natural": "consulta_sri_ruc_natural",
        "ant": "consulta_ant",
        "iess_cumplimiento": "consulta_iess_cumplimiento",
        "supa": "consulta_supa",
    }
    sources = {}
    for source_name, module_name in source_modules.items():
        sources[source_name] = safe_consultar(module_name, cedula)
    fj = sources.get("funcion_judicial") or {}
    sri = sources.get("sri") or {}
    ant = sources.get("ant") or {}
    datacil = sources.get("datacil") or {}
    sri_ruc = sources.get("sri_ruc_natural") or {}
    iess = sources.get("iess_cumplimiento") or {}
    supa = sources.get("supa") or {}
    nombre_completo = first_value(
        sri.get("nombre_completo"),
        ant.get("nombre_completo"),
        iess.get("nombre_completo"),
        sri_ruc.get("razon_social"),
    )
    sources["ecuadorlegal_nombre"] = safe_consultar_nombre("consulta_ecuadorlegal_nombre", nombre_completo) if nombre_completo else {
        "nombre_completo": "",
        "resultados_total": 0,
        "resultados": [],
        "coincidencia_exacta": {},
        "error": None,
    }
    sources["ofac"] = safe_consultar_nombre("consulta_ofac", nombre_completo) if nombre_completo else {
        "nombre_completo": "",
        "coincidencias_total": 0,
        "coincidencias": [],
        "error": None,
    }
    sources["sanctions_network"] = safe_consultar_nombre("consulta_sanctions_network", nombre_completo) if nombre_completo else {
        "nombre_completo": "",
        "coincidencias_total": 0,
        "coincidencias": [],
        "error": None,
    }
    ecuadorlegal = sources.get("ecuadorlegal_nombre") or {}
    ofac = sources.get("ofac") or {}
    sanctions = sources.get("sanctions_network") or {}
    errors = {
        source: payload.get("error")
        for source, payload in sources.items()
        if isinstance(payload, dict) and payload.get("error")
    }
    normalized = {
        "cedula": cedula,
        "cedula_valida": datacil.get("cedula_valida"),
        "nombre_completo": nombre_completo,
        "procesos_actor_total": int(fj.get("procesos_actor_total") or 0),
        "procesos_demandado_total": int(fj.get("procesos_demandado_total") or 0),
        "citaciones_total": int(ant.get("citaciones_total") or 0),
        "puntos_ant": ant.get("puntos") or "",
        "estado_cuenta_ant": ant.get("estado_cuenta") or {},
        "iess_cumplimiento": {
            "tipo_afiliado": iess.get("tipo_afiliado") or "",
            "direccion": iess.get("direccion") or "",
            "registra_mora_patronal": iess.get("registra_mora_patronal"),
            "fecha_emision": iess.get("fecha_emision") or "",
            "validez": iess.get("validez") or "",
            "mensaje": iess.get("mensaje") or iess.get("error") or "",
        },
        "sri_ruc_natural": {
            "tiene_ruc": bool(sri_ruc.get("tiene_ruc")),
            "ruc": sri_ruc.get("ruc") or "",
            "razon_social": sri_ruc.get("razon_social") or "",
            "estado": sri_ruc.get("estado") or "",
            "actividad_economica": sri_ruc.get("actividad_economica") or "",
            "tipo_contribuyente": sri_ruc.get("tipo_contribuyente") or "",
            "regimen": sri_ruc.get("regimen") or "",
            "obligado_llevar_contabilidad": sri_ruc.get("obligado_llevar_contabilidad") or "",
            "fecha_inicio_actividades": sri_ruc.get("fecha_inicio_actividades") or "",
            "fecha_actualizacion": sri_ruc.get("fecha_actualizacion") or "",
            "establecimientos_total": int(sri_ruc.get("establecimientos_total") or 0),
            "establecimientos": sri_ruc.get("establecimientos") or [],
        },
        "ecuadorlegal": {
            "resultados_total": int(ecuadorlegal.get("resultados_total") or 0),
            "coincidencia_exacta": ecuadorlegal.get("coincidencia_exacta") or {},
            "fecha_defuncion": ecuadorlegal.get("fecha_defuncion") or "",
            "resultados": ecuadorlegal.get("resultados") or [],
        },
        "supa": {
            "tiene_registros": bool(supa.get("tiene_registros_supa")),
            "registros_total": int(supa.get("registros_total") or 0),
            "mensaje": supa.get("mensaje") or "",
            "tablas": supa.get("tablas") or [],
        },
        "ofac": {
            "coincidencias_total": int(ofac.get("coincidencias_total") or 0),
            "coincidencias": ofac.get("coincidencias") or [],
            "min_score": ofac.get("min_score") or "",
        },
        "sanciones": {
            "coincidencias_total": int(sanctions.get("coincidencias_total") or 0),
            "coincidencias": sanctions.get("coincidencias") or [],
            "min_score": sanctions.get("min_score") or "",
        },
        "fuentes_pendientes": {
            "senescyt": "Requiere captcha.",
            "midena": "Requiere captcha.",
            "antecedentes": "Requiere navegador/WAF.",
        },
    }
    return {
        "cedula": cedula,
        "normalized": normalized,
        "sources": sources,
        "errors": errors,
    }


def save_person_lookup_result(result, user=None):
    normalized = result.get("normalized") or {}
    sources = result.get("sources") or {}
    errors = result.get("errors") or {}
    defaults = {
        field: normalized.get(field)
        for field in PERSON_LOOKUP_FIELDS
    }
    defaults.update({
        "lookup_status": "completed_with_errors" if errors else "completed",
        "last_error": "",
        "normalized_data": normalized,
        "funcion_judicial_data": sources.get("funcion_judicial") or {},
        "sri_data": sources.get("sri") or {},
        "ant_data": sources.get("ant") or {},
        "source_errors": errors,
        "completed_at": timezone.now(),
    })
    if user is not None:
        defaults["consultado_por"] = user
    record, _ = PersonLookupRecord.objects.update_or_create(
        cedula=result.get("cedula"),
        defaults=defaults,
    )
    return record
