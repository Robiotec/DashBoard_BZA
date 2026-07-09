import re
from html import unescape

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://supa.funcionjudicial.gob.ec/pensiones/publico/consulta.jsf"


def _clean(value):
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(unescape(value).replace("\xa0", " ").split())


def _extract_update(html, update_id):
    pattern = rf'<update id="{re.escape(update_id)}"><!\[CDATA\[(.*?)\]\]></update>'
    match = re.search(pattern, html or "", re.I | re.S)
    return match.group(1) if match else ""


def _parse_tables(fragment):
    soup = BeautifulSoup(fragment or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    tables = []
    for table in soup.find_all("table"):
        rows = []
        for row in table.find_all("tr"):
            cells = [_clean(cell.get_text(" ")) for cell in row.find_all(["th", "td"])]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def consultar_cedula(cedula, timeout=25):
    cedula = "".join(char for char in str(cedula or "").strip() if char.isdigit())
    if not cedula:
        return {"cedula": cedula, "error": "Cedula vacia."}

    try:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        response = session.get(BASE_URL, timeout=timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        form = soup.find("form", {"id": "form"})
        view_state = soup.find("input", {"name": "javax.faces.ViewState"})
        if not form or not view_state:
            return {"cedula": cedula, "error": "SUPA no devolvio formulario JSF."}

        action = form.get("action") or "/pensiones/publico/consulta.jsf"
        if action.startswith("/"):
            action = "https://supa.funcionjudicial.gob.ec" + action

        data = {
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": "form:b_buscar_cedula",
            "javax.faces.partial.execute": "@all",
            "javax.faces.partial.render": "form:pResultado panelMensajes form:pFiltro",
            "form:b_buscar_cedula": "form:b_buscar_cedula",
            "form": "form",
            "form:t_texto_cedula": cedula,
            "form:s_criterio_busqueda": "",
            "form:t_texto": "",
            "javax.faces.ViewState": view_state.get("value", ""),
        }
        result = session.post(
            action,
            data=data,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Faces-Request": "partial/ajax",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/xml, text/xml, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": response.url,
            },
        )
        result.raise_for_status()
        result_fragment = _extract_update(result.text, "form:pResultado")
        message_fragment = _extract_update(result.text, "panelMensajes")
        result_soup = BeautifulSoup(result_fragment or "", "html.parser")
        for tag in result_soup(["script", "style"]):
            tag.decompose()
        message_soup = BeautifulSoup(message_fragment or "", "html.parser")
        for tag in message_soup(["script", "style"]):
            tag.decompose()
        combined_text = _clean(result_soup.get_text(" ") + " " + message_soup.get_text(" "))
        no_results = "No se encuentra resultados" in combined_text
        if no_results:
            combined_text = "No se encuentra resultados."
        tables = [] if no_results else _parse_tables(str(result_soup))
        result_rows = sum(max(0, len(table) - 1) for table in tables)
        return {
            "cedula": cedula,
            "tiene_registros_supa": bool(tables and not no_results),
            "registros_total": 0 if no_results else result_rows,
            "tablas": tables,
            "mensaje": combined_text[:1000],
            "raw_excerpt": _clean(result_soup.get_text(" "))[:2000],
            "error": None,
        }
    except Exception as exc:
        return {"cedula": cedula, "error": str(exc)}
