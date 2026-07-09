import re
import unicodedata

import requests


BASE_URL = "https://api.sanctions.network/rpc/search_sanctions"


def _normalize(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^A-Z0-9 ]+", " ", value.upper())
    return " ".join(value.split())


def _score(query_tokens, names):
    candidate_tokens = set()
    for name in names or []:
        candidate_tokens.update(_normalize(name).split())
    if not query_tokens or not candidate_tokens:
        return 0
    return int((len(query_tokens & candidate_tokens) / len(query_tokens)) * 100)


def consultar_nombre(nombre_completo, timeout=15, min_score=85, max_matches=20):
    nombre_completo = " ".join(str(nombre_completo or "").split())
    if not nombre_completo:
        return {"nombre_completo": nombre_completo, "error": "Nombre vacio."}

    try:
        response = requests.get(
            BASE_URL,
            params={"limit": max_matches, "name": nombre_completo},
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            data = []

        query_tokens = set(_normalize(nombre_completo).split())
        matches = []
        for item in data:
            if not isinstance(item, dict):
                continue
            names = item.get("names") or []
            score = _score(query_tokens, names)
            if score < min_score:
                continue
            matches.append({
                "id": item.get("id") or "",
                "source": item.get("source") or "",
                "source_id": item.get("source_id") or "",
                "target_type": item.get("target_type") or "",
                "names": names,
                "listed_on": item.get("listed_on") or "",
                "remarks": item.get("remarks") or "",
                "score": score,
            })

        return {
            "nombre_completo": nombre_completo,
            "coincidencias_total": len(matches),
            "coincidencias": matches,
            "min_score": min_score,
            "error": None,
        }
    except Exception as exc:
        return {"nombre_completo": nombre_completo, "error": str(exc)}
