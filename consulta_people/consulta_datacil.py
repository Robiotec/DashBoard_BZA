import requests


BASE_URL = "https://api.datacil.com/v1/ecuador/data/check-cedula/{cedula}"


def consultar_cedula(cedula, timeout=12):
    cedula = "".join(char for char in str(cedula or "").strip() if char.isdigit())
    if not cedula:
        return {"cedula": cedula, "error": "Cedula vacia."}

    try:
        response = requests.get(
            BASE_URL.format(cedula=cedula),
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        return {
            "cedula": cedula,
            "cedula_valida": bool(data.get("data")),
            "mensaje": data.get("message") or "",
            "respuesta": data,
            "error": None,
        }
    except Exception as exc:
        return {"cedula": cedula, "error": str(exc)}
