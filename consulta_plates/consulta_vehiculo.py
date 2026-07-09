import asyncio, json

EMPRESA  = "05"
BASE_URL = "https://servicios.axiscloud.ec/CRV"
HOME_URL = f"{BASE_URL}/?ps_empresa={EMPRESA}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"

def _a_dict(lista):
    if not isinstance(lista, list):
        return {}
    r = {}
    for item in lista:
        k = item.get("etiqueta", "").strip().rstrip(":")
        v = item.get("valor", "").strip()
        if k:
            r[k] = v
    return r

def _parsear(json_crudo):
    res = {
        "placa": "", "uso": "", "ultima_actualizacion": "",
        "identificacion": {}, "modelo": {}, "caracteristicas": {},
        "crv": {}, "revision": {}, "error": None
    }
    try:
        data = json.loads(json_crudo)
    except Exception as e:
        res["error"] = f"JSON invalido: {e}"
        return res

    if data.get("codError", "") != "0":
        res["error"] = data.get("mensajeError", f"codError={data.get('codError')}")
        return res

    campos = data.get("campos", {})

    # *** FIX PRINCIPAL: campos viene como string JSON, hay que deserializarlo ***
    if isinstance(campos, str):
        try:
            campos = json.loads(campos)
        except Exception as e:
            res["error"] = f"No se pudo parsear campos: {e}"
            return res

    res["placa"] = campos.get("lsPlaca", "")
    res["uso"]   = campos.get("lsServicio", "")
    res["ultima_actualizacion"] = campos.get("lsUltimaActualizacion", "")

    id_d = _a_dict(campos.get("lsDatosIdentificacion", []))
    res["identificacion"] = {
        "vin":            id_d.get("VIN", ""),
        "motor":          id_d.get("Motor", ""),
        "placa":          id_d.get("Placa", res["placa"]),
        "placa_anterior": id_d.get("Placa Anterior", ""),
    }

    mod_d = _a_dict(campos.get("lsDatosModelo", []))
    res["modelo"] = {
        "marca":            mod_d.get("Marca", ""),
        "modelo":           mod_d.get("Modelo", ""),
        "anio_fabricacion": mod_d.get("Año Fabricación", ""),
        "pais_fabricacion": mod_d.get("País Fabricación", ""),
    }

    res["caracteristicas"] = _a_dict(campos.get("lsOtrasCaracteristicas", []))
    res["crv"]             = _a_dict(campos.get("lsCrv", []))

    rev_d = _a_dict(campos.get("lsRevision", []))
    res["revision"] = {
        "matricula_desde":       rev_d.get("Matrícula Desde", ""),
        "matricula_hasta":       rev_d.get("Matrícula Hasta", ""),
        "anio_ultima_revision":  rev_d.get("Año Última Revisión", ""),
        "ultima_revision_desde": rev_d.get("Última Revisión Desde", ""),
        "ultima_revision_hasta": rev_d.get("Última Revisión Hasta", ""),
    }
    return res

async def _scrape(placa):
    from playwright.async_api import async_playwright
    placa = placa.upper().strip()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(viewport={"width": 1366, "height": 768}, user_agent=UA, locale="es-EC")
        page = await ctx.new_page()
        await page.goto(HOME_URL, wait_until="networkidle")
        await asyncio.sleep(1)
        await page.locator("#valorBusqueda, input[type='text']").first.fill(placa)
        async with page.expect_response(lambda response: "datosVehiculo.jsp" in response.url, timeout=15000) as response_info:
            await page.locator("#boton_buscar, button:has-text('Buscar'), input[value='Buscar'], #btnBuscar").first.click()
        response = await response_info.value
        json_cap = await response.text()
        await browser.close()

    if not json_cap:
        return {"placa": placa, "error": "No se capturo respuesta"}
    return _parsear(json_cap)

def consultar_placa(placa):
    return asyncio.run(_scrape(placa))

if __name__ == "__main__":
    PLACAS = ["PBJ1979"]  # <-- pon tus placas aqui

    resultados = []
    for placa in PLACAS:
        print(f"\n{'='*55}\n  PLACA: {placa}\n{'='*55}")
        datos = consultar_placa(placa)
        resultados.append(datos)

        if datos.get("error"):
            print(f"\n  ERROR: {datos['error']}")
        else:
            print(f"\nRESULTADO:")
            print(f"  Placa  : {datos['placa']}")
            print(f"  Uso    : {datos['uso']}")
            print(f"  VIN    : {datos['identificacion'].get('vin','')}")
            print(f"  Motor  : {datos['identificacion'].get('motor','')}")
            print(f"  Marca  : {datos['modelo'].get('marca','')}")
            print(f"  Modelo : {datos['modelo'].get('modelo','')}")
            print(f"  Anio   : {datos['modelo'].get('anio_fabricacion','')}")
            print(f"  Pais   : {datos['modelo'].get('pais_fabricacion','')}")
            print(f"\n  Caracteristicas:")
            for k, v in datos.get("caracteristicas", {}).items():
                if v: print(f"    {k}: {v}")
            print(f"\n  Revision:")
            for k, v in datos.get("revision", {}).items():
                if v: print(f"    {k}: {v}")

    with open("resultados.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)
    print(f"\nGuardado en resultados.json")
