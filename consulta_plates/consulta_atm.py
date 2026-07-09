"""
Scraper para consultas.atm.gob.ec — ATM Guayaquil
Consulta datos de matrícula, propietario y trámites por placa.
No requiere CAPTCHA ni browser.

Instalación:
    pip install httpx beautifulsoup4

Uso:
    python consulta_atm.py
    # o como módulo:
    from consulta_atm import consultar_placa
    datos = consultar_placa("GCA4771")
"""

import httpx
import json
from bs4 import BeautifulSoup


# ══════════════════════════════════════════════════════════════════════════════
# Configuración
# ══════════════════════════════════════════════════════════════════════════════

URL_BASE = (
    "https://consultas.atm.gob.ec/SVT/paginas/svt_datosPersonas.jsp"
    "?ps_tipoServicio=MAT&ps_servicio=1&ps_tramite=0&ps_area="
    "&ps_valorParametro1={placa}&ps_valorParametro2=&ps_identificacionSolicita="
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-EC,es;q=0.9,en;q=0.8",
    "Referer":         "https://consultas.atm.gob.ec/",
}


# ══════════════════════════════════════════════════════════════════════════════
# Parser HTML
# ══════════════════════════════════════════════════════════════════════════════

def _limpiar(texto: str) -> str:
    """Limpia espacios y caracteres extra."""
    return " ".join(texto.split()).strip()


def _parsear_html(html: str, placa: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    resultado = {
        "placa":            placa,
        "propietario":      "",
        "email":            "",
        "fecha_compraventa": "",
        "tramites":         [],
        "error":            None,
    }

    # ── Extraer tabla de datos personales ────────────────────────────────────
    # La página tiene tablas con celdas bold (label) + celda valor
    for fila in soup.find_all("tr"):
        celdas = fila.find_all("td")
        if len(celdas) < 2:
            continue

        label = _limpiar(celdas[0].get_text())
        valor = _limpiar(celdas[1].get_text())

        if "Nombre" in label:
            resultado["propietario"] = valor
        elif "Mail" in label or "Email" in label:
            resultado["email"] = valor
        elif "Fecha Compra" in label:
            resultado["fecha_compraventa"] = valor

    # ── Extraer trámites ──────────────────────────────────────────────────────
    # Tabla de trámites: número | descripción | fecha | estado
    tramites = []
    tablas = soup.find_all("table")
    for tabla in tablas:
        filas = tabla.find_all("tr")
        for fila in filas:
            celdas = fila.find_all("td")
            # Las filas de trámites tienen al menos 4 celdas con número de trámite
            if len(celdas) >= 4:
                num     = _limpiar(celdas[0].get_text())
                desc    = _limpiar(celdas[1].get_text())
                fecha   = _limpiar(celdas[2].get_text())
                estado  = _limpiar(celdas[3].get_text())
                # Filtrar filas vacías o de encabezado
                if num and num.isdigit() and desc:
                    tramites.append({
                        "numero":      num,
                        "descripcion": desc,
                        "fecha":       fecha,
                        "estado":      estado,
                    })

    resultado["tramites"] = tramites

    # Verificar si no encontró datos
    if not resultado["propietario"] and not tramites:
        # Buscar mensaje de error en la página
        texto_pagina = soup.get_text()
        if "no encontr" in texto_pagina.lower() or "no existe" in texto_pagina.lower():
            resultado["error"] = "Placa no encontrada en el sistema ATM"
        else:
            resultado["error"] = "No se pudieron extraer datos — posible cambio en la estructura de la página"

    return resultado


# ══════════════════════════════════════════════════════════════════════════════
# Función principal
# ══════════════════════════════════════════════════════════════════════════════

def consultar_placa(placa: str) -> dict:
    """
    Consulta datos de matrícula de un vehículo en el portal ATM Guayaquil.

    Args:
        placa: Ej. "GCA4771"

    Returns:
        {
          "placa": "GCA4771",
          "propietario": "SALAZAR TUBAY MARIA LORENA",
          "email": "mlsalazar80@hotmail.com",
          "fecha_compraventa": "",
          "tramites": [
            {
              "numero": "21004695",
              "descripcion": "CERTIFICADO ÚNICO VEHICULAR",
              "fecha": "07-05-2026 14:40",
              "estado": "LIQUIDADO"
            }
          ],
          "error": null
        }
    """
    placa = placa.upper().strip()
    url   = URL_BASE.format(placa=placa)

    try:
        with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            # La página usa encoding windows-1252
            html = response.content.decode("windows-1252", errors="replace")
    except Exception as e:
        return {"placa": placa, "error": str(e)}

    return _parsear_html(html, placa)


# ══════════════════════════════════════════════════════════════════════════════
# Modo standalone
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    PLACAS = [
        "GTI8095",
        "PBJ1979"   # Placa de ejemplo que no existe
        # Agrega más placas aquí
    ]

    resultados = []
    for placa in PLACAS:
        print(f"\n{'='*55}\n  PLACA: {placa}\n{'='*55}")

        datos = consultar_placa(placa)
        resultados.append(datos)

        if datos.get("error"):
            print(f"  ERROR: {datos['error']}")
        else:
            print(f"  Propietario     : {datos['propietario']}")
            print(f"  Email           : {datos['email']}")
            print(f"  Fecha compraventa: {datos['fecha_compraventa']}")
            print(f"\n  Trámites:")
            if datos["tramites"]:
                for t in datos["tramites"]:
                    print(f"    [{t['numero']}] {t['descripcion']}")
                    print(f"           Fecha: {t['fecha']} | Estado: {t['estado']}")
            else:
                print("    Sin trámites registrados")

    with open("resultados_atm.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Guardado en resultados_atm.json")
