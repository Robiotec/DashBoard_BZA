import requests


BASE_URL = "https://apps.ecuadorlegalonline.com/modulo/consultar-cedulanombre.php"


def _clean_name(value):
    return " ".join(str(value or "").upper().split())


def consultar_nombre(nombre_completo, timeout=12, max_results=20):
    nombre_completo = _clean_name(nombre_completo)
    if not nombre_completo:
        return {"nombre_completo": nombre_completo, "error": "Nombre vacio."}

    try:
        response = requests.get(
            BASE_URL,
            params={"nombres": nombre_completo},
            timeout=timeout,
            headers={
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.ecuadorlegalonline.com/consultas/consultar-numero-cedula/",
            },
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            data = []

        resultados = []
        coincidencia_exacta = None
        for item in data[:max_results]:
            if not isinstance(item, dict):
                continue
            nombre = _clean_name(item.get("nombreCompleto"))
            identificacion = "".join(char for char in str(item.get("identificacion") or "") if char.isdigit())
            row = {
                "identificacion": identificacion,
                "nombre_completo": nombre,
                "fecha_defuncion": item.get("fechaDefuncion") or "",
            }
            resultados.append(row)
            if nombre == nombre_completo and not coincidencia_exacta:
                coincidencia_exacta = row

        return {
            "nombre_completo": nombre_completo,
            "resultados_total": len(resultados),
            "resultados": resultados,
            "coincidencia_exacta": coincidencia_exacta or {},
            "fecha_defuncion": (coincidencia_exacta or {}).get("fecha_defuncion") if coincidencia_exacta else "",
            "error": None,
        }
    except Exception as exc:
        return {"nombre_completo": nombre_completo, "error": str(exc)}
