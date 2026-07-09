import requests


BASE_URL = "https://srienlinea.sri.gob.ec/movil-servicios/api/v1.0/deudas/porIdentificacion/{cedula}/?tipoPersona=N"


def consultar_cedula(cedula, timeout=20):
    cedula = "".join(char for char in str(cedula or "").strip() if char.isdigit())
    if not cedula:
        return {"cedula": cedula, "error": "Cedula vacia."}

    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        response = requests.get(BASE_URL.format(cedula=cedula), headers=headers, timeout=timeout)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "html" in content_type or "request rejected" in response.text.lower():
            return {
                "cedula": cedula,
                "error": "SRI rechazo la consulta o devolvio una pagina HTML de proteccion.",
                "raw_excerpt": response.text[:1000],
            }
        try:
            data = response.json()
        except ValueError:
            return {
                "cedula": cedula,
                "error": "SRI no devolvio JSON.",
                "raw_excerpt": response.text[:1000],
            }
        if isinstance(data, list):
            first = data[0] if data else {}
        elif isinstance(data, dict):
            first = data
        else:
            first = {}
        return {
            "cedula": cedula,
            "nombre_completo": first.get("nombreComercial") or first.get("razonSocial") or first.get("nombre") or "",
            "identificacion": first.get("identificacion") or cedula,
            "deudas": data,
            "error": None,
        }
    except Exception as exc:
        return {"cedula": cedula, "error": str(exc)}
