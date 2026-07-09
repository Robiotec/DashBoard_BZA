import re

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://iess.gob.ec/empleador-web/pages/morapatronal/certificadoCumplimientoPublico.jsf"


def _clean_text(value):
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _extract_pdf_text(pdf_bytes):
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError("Falta instalar pypdf para leer el PDF del IESS.") from exc

    from io import BytesIO

    reader = PdfReader(BytesIO(pdf_bytes))
    chunks = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    return _clean_text(" ".join(chunks))


def _first_match(pattern, text):
    match = re.search(pattern, text or "", re.I | re.S)
    return _clean_text(match.group(1)) if match else ""


def _parse_certificate(text, cedula):
    nombre = _first_match(
        r"señor\(a\)\s+(.*?),\s+afiliado",
        text,
    )
    tipo_afiliado = _first_match(r"afiliado\s+(.+?)\s+con c[eé]dula", text)
    direccion = _first_match(
        rf"{re.escape(cedula)}\s+y\s+direcci[oó]n\s+(.*?),\s+(?:NO|SI|S[IÍ])\s+registra",
        text,
    )
    registra_mora = None
    if re.search(r"\bNO\s+registra obligaciones patronales en mora\b", text, re.I):
        registra_mora = False
    elif re.search(r"\b(SI|S[IÍ])\s+registra obligaciones patronales en mora\b", text, re.I):
        registra_mora = True
    fecha_emision = _first_match(r"Emitido el\s+(\d{2}\s+de\s+\w+\s+de\s+\d{4})", text)
    validez = _first_match(r"Validez del certificado:\s*([^\s]+(?:\s+[^\s]+)?)", text)
    return {
        "nombre_completo": nombre,
        "tipo_afiliado": tipo_afiliado,
        "direccion": direccion,
        "registra_mora_patronal": registra_mora,
        "fecha_emision": fecha_emision,
        "validez": validez,
    }


def consultar_cedula(cedula, timeout=25):
    cedula = "".join(char for char in str(cedula or "").strip() if char.isdigit())
    if not cedula:
        return {"cedula": cedula, "error": "Cedula vacia."}

    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        response = session.get(BASE_URL, timeout=timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        view_state = soup.find("input", {"name": "javax.faces.ViewState"})
        if not view_state or not view_state.get("value"):
            return {"cedula": cedula, "error": "IESS no devolvio ViewState."}

        data = {
            "frmCertificadoCumplimiento": "frmCertificadoCumplimiento",
            "frmCertificadoCumplimiento:j_id9": cedula,
            "frmCertificadoCumplimiento:j_id11": "CONSULTAR",
            "javax.faces.ViewState": view_state["value"],
        }
        pdf_response = session.post(BASE_URL, data=data, timeout=timeout)
        pdf_response.raise_for_status()
        content_type = pdf_response.headers.get("content-type", "").lower()
        if "pdf" not in content_type and not pdf_response.content.startswith(b"%PDF"):
            html_excerpt = _clean_text(BeautifulSoup(pdf_response.text, "html.parser").get_text(" "))
            return {
                "cedula": cedula,
                "error": "IESS no devolvio PDF.",
                "raw_excerpt": html_excerpt[:1000],
            }

        text = _extract_pdf_text(pdf_response.content)
        if not text:
            return {
                "cedula": cedula,
                "nombre_completo": "",
                "tipo_afiliado": "",
                "direccion": "",
                "registra_mora_patronal": None,
                "fecha_emision": "",
                "validez": "",
                "texto_certificado": "",
                "pdf_size": len(pdf_response.content),
                "mensaje": "IESS devolvio un PDF vacio o sin texto extraible para esta cedula.",
                "error": "IESS devolvio un PDF vacio o sin texto extraible.",
            }
        parsed = _parse_certificate(text, cedula)
        return {
            "cedula": cedula,
            **parsed,
            "texto_certificado": text,
            "pdf_size": len(pdf_response.content),
            "error": None,
        }
    except Exception as exc:
        return {"cedula": cedula, "error": str(exc)}
