import re
from html import unescape

import requests


BASE_URL = "https://consultaweb.ant.gob.ec/PortalWEB/paginas/clientes/clp_grid_citaciones.jsp"
JSON_URL = "https://consultaweb.ant.gob.ec/PortalWEB/paginas/clientes/clp_json_citaciones.jsp"


def _clean_html(value):
    text = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(unescape(text).split())


def _first_match(pattern, text):
    match = re.search(pattern, text or "", re.I | re.S)
    return _clean_html(match.group(1)) if match else ""


def _extract_status_counts(text):
    counts = {}
    for label, value in re.findall(r"(Pendientes|En Impugnación|En Impugnacion|Impugnadas|Anuladas|Pagadas|En Convenio)\s*\((\d+)\)", text or "", re.I):
        key = (
            label.lower()
            .replace("ó", "o")
            .replace("á", "a")
            .replace(" ", "_")
        )
        counts[key] = int(value)
    return counts


def consultar_cedula(cedula, timeout=25):
    cedula = "".join(char for char in str(cedula or "").strip() if char.isdigit())
    if not cedula:
        return {"cedula": cedula, "error": "Cedula vacia."}

    params = {"ps_identificacion": cedula, "ps_tipo_identificacion": "CED"}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        session = requests.Session()
        response = session.get(BASE_URL, params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        html = response.text
        lower_html = html.lower()
        if "request rejected" in lower_html or "service unavailable" in lower_html:
            return {
                "cedula": cedula,
                "error": "ANT rechazo la consulta o no estuvo disponible.",
                "raw_excerpt": _clean_html(html)[:1000],
            }
        nombre_completo = _first_match(r'<td[^>]*class=["\']titulo1["\'][^>]*>(.*?)</td>', html)
        id_persona = _first_match(r"ps_id_persona=(\d+)", html)
        puntos_text = _first_match(r"Puntos:</div></td>\s*<td[^>]*>(.*?)</td>", html)
        status_counts = _extract_status_counts(_clean_html(html))
        citaciones = []
        citaciones_total = int(status_counts.get("pendientes", 0) or 0)
        if id_persona:
            json_params = {
                "ps_opcion": "P",
                "ps_id_contrato": "",
                "ps_id_persona": id_persona,
                "ps_placa": "",
                "ps_identificacion": cedula,
                "ps_tipo_identificacion": "CED",
                "_search": "false",
                "page": "1",
                "rows": "100",
                "sidx": "id_factura",
                "sord": "asc",
            }
            json_response = session.get(
                JSON_URL,
                params=json_params,
                headers={
                    **headers,
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": response.url,
                },
                timeout=timeout,
            )
            if "json" in json_response.headers.get("content-type", "").lower() or json_response.text.lstrip().startswith("{"):
                grid = json_response.json()
                citaciones_total = int(grid.get("records") or citaciones_total or 0)
                citaciones = grid.get("rows") or []
        rows = []
        for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S):
            cells = [_clean_html(cell) for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.I | re.S)]
            cells = [cell for cell in cells if cell]
            joined = " ".join(cells).lower()
            if cells and joined not in {"detalle de citación -->", "detalle de citacion -->"}:
                rows.append(cells)
        return {
            "cedula": cedula,
            "nombre_completo": nombre_completo,
            "id_persona": id_persona,
            "puntos": puntos_text,
            "estado_cuenta": status_counts,
            "citaciones_total": citaciones_total,
            "citaciones": citaciones,
            "html_rows": rows,
            "raw_excerpt": _clean_html(html)[:2000],
            "error": None,
        }
    except Exception as exc:
        return {"cedula": cedula, "error": str(exc)}
