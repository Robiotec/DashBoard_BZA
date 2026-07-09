import requests


RUC_URL = (
    "https://srienlinea.sri.gob.ec/sri-catastro-sujeto-servicio-internet/rest/"
    "ConsolidadoContribuyente/obtenerPorNumerosRuc"
)
ESTABLECIMIENTOS_URL = (
    "https://srienlinea.sri.gob.ec/sri-catastro-sujeto-servicio-internet/rest/"
    "Establecimiento/consultarPorNumeroRuc"
)


def _digits(value):
    return "".join(char for char in str(value or "").strip() if char.isdigit())


def _safe_json(response):
    if response.status_code == 204 or not response.text.strip():
        return []
    return response.json()


def consultar_cedula(cedula, timeout=15, max_establecimientos=20):
    cedula = _digits(cedula)
    if not cedula:
        return {"cedula": cedula, "error": "Cedula vacia."}

    ruc = f"{cedula}001"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        ruc_response = requests.get(RUC_URL, params={"ruc": ruc}, headers=headers, timeout=timeout)
        ruc_response.raise_for_status()
        ruc_data = _safe_json(ruc_response)
        if isinstance(ruc_data, list):
            contribuyente = ruc_data[0] if ruc_data else {}
        elif isinstance(ruc_data, dict):
            contribuyente = ruc_data
        else:
            contribuyente = {}

        establecimientos = []
        if contribuyente:
            est_response = requests.get(
                ESTABLECIMIENTOS_URL,
                params={"numeroRuc": ruc},
                headers=headers,
                timeout=timeout,
            )
            est_response.raise_for_status()
            est_data = _safe_json(est_response)
            if isinstance(est_data, list):
                establecimientos = est_data[:max_establecimientos]

        fechas = contribuyente.get("informacionFechasContribuyente") or {}
        return {
            "cedula": cedula,
            "ruc": ruc,
            "tiene_ruc": bool(contribuyente),
            "razon_social": contribuyente.get("razonSocial") or "",
            "estado": contribuyente.get("estadoContribuyenteRuc") or "",
            "actividad_economica": contribuyente.get("actividadEconomicaPrincipal") or "",
            "tipo_contribuyente": contribuyente.get("tipoContribuyente") or "",
            "regimen": contribuyente.get("regimen") or "",
            "obligado_llevar_contabilidad": contribuyente.get("obligadoLlevarContabilidad") or "",
            "agente_retencion": contribuyente.get("agenteRetencion") or "",
            "contribuyente_especial": contribuyente.get("contribuyenteEspecial") or "",
            "fecha_inicio_actividades": fechas.get("fechaInicioActividades") or "",
            "fecha_actualizacion": fechas.get("fechaActualizacion") or "",
            "representantes_legales": contribuyente.get("representantesLegales") or [],
            "establecimientos_total": len(establecimientos),
            "establecimientos": establecimientos,
            "raw": contribuyente,
            "error": None,
        }
    except Exception as exc:
        return {"cedula": cedula, "ruc": ruc, "error": str(exc)}
