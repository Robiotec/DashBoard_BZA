import requests


BASE_URL = "https://api.funcionjudicial.gob.ec/EXPEL-CONSULTA-CAUSAS-SERVICE/api/consulta-causas/informacion"


def consultar_cedula(cedula, timeout=25):
    cedula = "".join(char for char in str(cedula or "").strip() if char.isdigit())
    if not cedula:
        return {"cedula": cedula, "error": "Cedula vacia."}

    session = requests.Session()
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://procesosjudiciales.funcionjudicial.gob.ec",
        "Referer": "https://procesosjudiciales.funcionjudicial.gob.ec/",
        "User-Agent": "Mozilla/5.0",
    }

    results = {}
    errors = {}
    queries = {
        "actor": {"actor": {"cedulaActor": cedula}, "demandado": {}, "numeroCausa": "", "recaptcha": "verdad"},
        "demandado": {"actor": {}, "demandado": {"cedulaDemandado": cedula}, "numeroCausa": "", "recaptcha": "verdad"},
    }

    for role, payload in queries.items():
        try:
            response = session.post(
                f"{BASE_URL}/buscarCausas?page=1&size=10",
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                items = data.get("content") or data.get("data") or []
                total = data.get("totalElements", len(items) if isinstance(items, list) else 0)
            elif isinstance(data, list):
                items = data
                total = len(data)
            else:
                items = []
                total = 0
            results[role] = {"total": total or 0, "items": items if isinstance(items, list) else []}
        except Exception as exc:
            errors[role] = str(exc)

    return {
        "cedula": cedula,
        "procesos_actor_total": results.get("actor", {}).get("total", 0),
        "procesos_demandado_total": results.get("demandado", {}).get("total", 0),
        "procesos_actor": results.get("actor", {}).get("items", []),
        "procesos_demandado": results.get("demandado", {}).get("items", []),
        "error": "; ".join(f"{key}: {value}" for key, value in errors.items()) if errors else None,
    }
