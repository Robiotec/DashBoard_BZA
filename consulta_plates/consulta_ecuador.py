"""
Scraper para consultasecuador.com — Consulta propietario y datos de vehículo
Usa la API REST directamente, sin browser ni CAPTCHA.

Instalación:
    pip install httpx

Uso:
    python consulta_ecuador.py
    # o como módulo:
    from consulta_ecuador import consultar_placa
    datos = consultar_placa("GCA4771")
"""

import httpx
import json

# ══════════════════════════════════════════════════════════════════════════════
# Configuración
# ══════════════════════════════════════════════════════════════════════════════

API_OWNER    = "https://app3902.privynote.net/api/v1/transit/vehicle-owner"
API_CAR_INFO = "https://app3902.privynote.net/api/v1/transit/car-info"

HEADERS = {
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Origin":       "https://consultasecuador.com",
    "Referer":      "https://consultasecuador.com/",
    "Accept":       "application/json",
}


# ══════════════════════════════════════════════════════════════════════════════
# Función principal
# ══════════════════════════════════════════════════════════════════════════════

def consultar_placa(placa: str) -> dict:
    """
    Consulta propietario y datos completos de un vehículo por placa.

    Args:
        placa: Ej. "GCA4771"

    Returns:
        {
          "placa": "GCA4771",
          "propietario": "SALAZAR TUBAY MARIA LORENA",
          "marca": "TOYOTA",
          "modelo": "YARIS HB AC 1.5 5P 4X2 TM",
          "anio": 2019,
          "pais_fabricacion": "TAILANDIA",
          "clase": "AUTOMOVIL",
          "servicio": "PARTICULAR",
          "canton_matricula": "GUAYAQUIL",
          "fecha_matricula": "03-09-2018",
          "vencimiento_matricula": "02-09-2023",
          "fecha_inspeccion": "17-02-2022",
          "ultimo_pago": 2025,
          "cilindraje": 1496,
          "estado": "ASIGNADO",
          "camv_cpn": "E02260206",
          "informacion": "El vehiculo no tiene registros por pagar",
          "error": null
        }
    """
    placa = placa.upper().strip()
    resultado = {"placa": placa, "error": None}

    with httpx.Client(headers=HEADERS, timeout=15, follow_redirects=True) as client:

        # ── 1. Propietario ────────────────────────────────────────────────────
        try:
            r = client.post(API_OWNER, json={"placa": placa})
            r.raise_for_status()
            data = r.json().get("data", {})
            resultado["propietario"] = data.get("name", "")
        except Exception as e:
            resultado["propietario"] = ""
            resultado["error"] = f"vehicle-owner: {e}"

        # ── 2. Información del vehículo ───────────────────────────────────────
        try:
            r = client.post(API_CAR_INFO, json={"placa": placa})
            r.raise_for_status()
            data = r.json().get("data", {})

            resultado["marca"]                = data.get("brand", "")
            resultado["modelo"]               = data.get("model", "")
            resultado["anio"]                 = data.get("modelYear", "")
            resultado["pais_fabricacion"]     = data.get("countryOfManufacture", "")
            resultado["clase"]                = data.get("vehicleClass", "")
            resultado["servicio"]             = data.get("serviceType", "")
            resultado["uso"]                  = data.get("usageType", "")
            resultado["canton_matricula"]     = data.get("registrationCanton", "")
            resultado["fecha_matricula"]      = data.get("lastRegistrationDate", "")
            resultado["vencimiento_matricula"] = data.get("registrationExpiryDate", "")
            resultado["fecha_inspeccion"]     = data.get("inspectionDate", "")
            resultado["ultimo_pago"]          = data.get("lastPaymentYear", "")
            resultado["cilindraje"]           = data.get("engineCapacity", "")
            resultado["estado"]               = data.get("vehicleStatus", "")
            resultado["camv_cpn"]             = data.get("camvCpn", "")
            resultado["informacion"]          = data.get("information", "")

        except Exception as e:
            if not resultado["error"]:
                resultado["error"] = f"car-info: {e}"

    return resultado


# ══════════════════════════════════════════════════════════════════════════════
# Modo standalone
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    PLACAS = [
        "PBJ1979"        # Agrega más placas aquí
    ]

    resultados = []
    for placa in PLACAS:
        print(f"\n{'='*55}\n  PLACA: {placa}\n{'='*55}")

        datos = consultar_placa(placa)
        resultados.append(datos)

        if datos.get("error"):
            print(f"  ERROR: {datos['error']}")
        else:
            print(f"  Propietario       : {datos['propietario']}")
            print(f"  Marca             : {datos['marca']}")
            print(f"  Modelo            : {datos['modelo']}")
            print(f"  Año               : {datos['anio']}")
            print(f"  País Fabricación  : {datos['pais_fabricacion']}")
            print(f"  Clase             : {datos['clase']}")
            print(f"  Servicio          : {datos['servicio']}")
            print(f"  Cantón matrícula  : {datos['canton_matricula']}")
            print(f"  Fecha matrícula   : {datos['fecha_matricula']}")
            print(f"  Vence matrícula   : {datos['vencimiento_matricula']}")
            print(f"  Última inspección : {datos['fecha_inspeccion']}")
            print(f"  Último pago año   : {datos['ultimo_pago']}")
            print(f"  Cilindraje        : {datos['cilindraje']} cc")
            print(f"  Estado            : {datos['estado']}")
            print(f"  Info              : {datos['informacion']}")

    with open("resultados_ecuador.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Guardado en resultados_ecuador.json")
