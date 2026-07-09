import csv
import io
import re
import time
import unicodedata
from pathlib import Path

import requests


CSV_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
CACHE_PATH = Path("/tmp/dashboardbza_ofac_sdn.csv")
CACHE_SECONDS = 24 * 60 * 60


def _normalize(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^A-Z0-9 ]+", " ", value.upper())
    return " ".join(value.split())


def _score(query_tokens, candidate):
    candidate_tokens = set(_normalize(candidate).split())
    if not query_tokens or not candidate_tokens:
        return 0
    matches = len(query_tokens & candidate_tokens)
    return int((matches / len(query_tokens)) * 100)


def _get_csv_text(timeout):
    if CACHE_PATH.exists() and time.time() - CACHE_PATH.stat().st_mtime < CACHE_SECONDS:
        return CACHE_PATH.read_text(encoding="utf-8", errors="ignore")
    response = requests.get(
        CSV_URL,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*"},
    )
    response.raise_for_status()
    CACHE_PATH.write_text(response.text, encoding="utf-8")
    return response.text


def consultar_nombre(nombre_completo, timeout=25, min_score=85, max_matches=10):
    nombre_completo = " ".join(str(nombre_completo or "").split())
    if not nombre_completo:
        return {"nombre_completo": nombre_completo, "error": "Nombre vacio."}

    try:
        csv_text = _get_csv_text(timeout)
        query_tokens = set(_normalize(nombre_completo).split())
        matches = []
        reader = csv.reader(io.StringIO(csv_text))
        for row in reader:
            if len(row) < 4:
                continue
            sdn_id, name, sdn_type, program = row[:4]
            score = _score(query_tokens, name)
            if score >= min_score:
                matches.append({
                    "sdn_id": sdn_id,
                    "nombre": name,
                    "tipo": sdn_type,
                    "programa": program,
                    "pais": row[11] if len(row) > 11 else "",
                    "score": score,
                })
                if len(matches) >= max_matches:
                    break
        return {
            "nombre_completo": nombre_completo,
            "coincidencias_total": len(matches),
            "coincidencias": matches,
            "min_score": min_score,
            "error": None,
        }
    except Exception as exc:
        return {"nombre_completo": nombre_completo, "error": str(exc)}
