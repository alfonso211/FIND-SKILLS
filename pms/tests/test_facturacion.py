"""Facturación: al registrar un cobro se emite la factura, con numeración correlativa por serie y año."""
from datetime import date, timedelta

from conftest import domicilio_fiscal, login

HOY = date.today()
ANIO = HOY.year


def d(n=0):
    return (HOY + timedelta(days=n)).isoformat()


def _reserva(client, h, asset_id, codigo, total, **extra):
    unit = client.get(f"/api/unidades?asset_id={asset_id}&q={codigo}", headers=h).json()[0]
    r = client.post("/api/turistico/reservas", headers=h, json={
        "unit_id": unit["id"], "guest": {"nombre": "Marta", "apellidos": "Gil", "documento_num": "12345678Z",
                                         "direccion": "Calle Mayor 1", "cp": "28013", "municipio": "Madrid"},
        "fecha_entrada": d(40), "fecha_salida": d(43), "importe_total": total, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _factura(client, h, fid):
    return client.get(f"/api/facturas/{fid}", headers=h).json()


def test_sin_domicilio_fiscal_no_se_factura(client, admin, ids):
    """Sin domicilio fiscal del emisor no se emite la factura, y el cobro tampoco se registra."""
    cc = [c for c in client.get("/api/sociedades", headers=admin).json() if c["nombre"] == "COMERCIAL DEL CAMPO S.A."][0]
    client.put(f"/api/sociedades/{cc['id']}", headers=admin, json={
        **{k: cc[k] for k in ("nombre", "cif", "parent_id", "activa")}, "direccion": None, "cp": None, "municipio": None})
    bab = ids["assets"]["BAB35"]["id"]
    trastero = client.get(f"/api/unidades?asset_id={bab}&uso=garaje", headers=admin).json()[-2]
    lease = client.post("/api/alquiler/contratos", headers=admin, json={
        "unit_id": trastero["id"], "tenant": {"nombre": "Sin Domicilio"}, "fecha_inicio": "2026-01-01",
        "renta_mensual": 50}).json()
    client.post("/api/alquiler/recibos/generar", headers=admin, json={"periodo": "2026-01"})
    rec = [c for c in client.get("/api/alquiler/recibos?periodo=2026-01", headers=admin).json()
           if c["lease_id"] == lease["id"]][0]
    r = client.post(f"/api/alquiler/recibos/{rec['id']}/cobro", headers=admin, json={"importe": 10})
    assert r.status_code == 400
    assert r.json()["detail"] == ("No se puede facturar: falta domicilio fiscal, código postal, municipio de "
                                  "COMERCIAL DEL CAMPO S.A.. Complételo en Administración → Sociedades.")
    assert client.get("/api/alquiler/recibos?periodo=2026-01", headers=admin).json()[0]["importe_pagado"] == 0
    domicilio_fiscal(client, admin)
    assert client.post(f"/api/alquiler/recibos/{rec['id']}/cobro", headers=admin,
                       json={"importe": 10}).status_code == 200
    _finalizar(client, admin, lease)


def _finalizar(client, admin, lease):  # libera la unidad para el resto de pruebas
    assert client.put(f"/api/alquiler/contratos/{lease['id']}", headers=admin,
                      json={"estado": "finalizado"}).status_code == 200


def test_series_correlativas_por_activo(client, admin, ids):
    domicilio_fiscal(client, admin)
    sfl, sae = ids["assets"]["SFL"]["id"], ids["assets"]["SAE"]["id"]
    r1 = _reserva(client, admin, sfl, "P2-1A", 300)
    # cobro parcial: pago a cuenta
    c1 = client.post(f"/api/turistico/reservas/{r1['id']}/cobro", headers=admin,
                     json={"importe": 100, "forma_pago": "tarjeta"})
    assert c1.status_code == 200, c1.text
    assert c1.json()["importe_pagado"] == 100
    f1 = _factura(client, admin, c1.json()["factura"]["id"])
    assert f1["codigo"] == f"SF/00001/{ANIO}" and f1["serie"] == "SF"
    # IVA del alojamiento turístico 10 %, IVA incluido en lo cobrado
    assert (f1["total"], f1["base_imponible"], f1["cuota_iva"], f1["tipo_iva"]) == (100, 90.91, 9.09, 10)
    assert f1["concepto"].startswith("Pago a cuenta · Alojamiento turístico · Suite Florida · Apartamento P2-1A")
    # factura la gestora (INVERSIETE) y el cliente es el huésped
    assert f1["emisor"]["nombre"] == "INVERSIETE SA" and f1["emisor"]["nif"] == "A78072915"
    assert f1["cliente"] == {"nombre": "Marta Gil", "nif": "12345678Z", "domicilio": "Calle Mayor 1, 28013, Madrid"}
    # no se puede cobrar más de lo pendiente
    assert client.post(f"/api/turistico/reservas/{r1['id']}/cobro", headers=admin,
                       json={"importe": 250}).status_code == 400
    c2 = client.post(f"/api/turistico/reservas/{r1['id']}/cobro", headers=admin, json={"importe": 200}).json()
    f2 = _factura(client, admin, c2["factura"]["id"])
    assert f2["codigo"] == f"SF/00002/{ANIO}" and not f2["concepto"].startswith("Pago a cuenta")
    # cadena de huellas
    assert f2["huella_anterior"] == f1["huella"] and len(f2["huella"]) == 64

    # Suite Aeropuerto: su propia serie, también desde 1. Pagado al reservar -> se factura al crear la reserva
    r3 = _reserva(client, admin, sae, "A-127", 180, importe_pagado=180, forma_pago="transferencia")
    f3 = _factura(client, admin, r3["factura"]["id"])
    assert f3["codigo"] == f"SA/00001/{ANIO}" and r3["importe_pagado"] == 180
    # la cadena es por sociedad emisora: SA sigue a SF (ambas de INVERSIETE)
    assert f3["huella_anterior"] == f2["huella"]
    # lo cobrado solo cambia con un cobro
    assert client.put(f"/api/turistico/reservas/{r3['id']}", headers=admin,
                      json={"importe_total": 100}).status_code == 400

    # facturar a una empresa en lugar del huésped
    r4 = _reserva(client, admin, sae, "A-128", 90)
    c4 = client.post(f"/api/turistico/reservas/{r4['id']}/cobro", headers=admin, json={
        "importe": 90, "facturar_a": {"nombre": "Construcciones Ejemplo SL", "nif": "b12345678",
                                       "domicilio": "Av. de Prueba 5, 28042 Madrid"}}).json()
    f4 = _factura(client, admin, c4["factura"]["id"])
    assert f4["codigo"] == f"SA/00002/{ANIO}"
    assert f4["cliente"] == {"nombre": "Construcciones Ejemplo SL", "nif": "B12345678",
                             "domicilio": "Av. de Prueba 5, 28042 Madrid"}

    # PDF
    pdf = client.get(f"/api/facturas/{f1['id']}/pdf", headers=admin)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-type"] == "application/pdf"
    assert f'Factura_SF-00001-{ANIO}.pdf' in pdf.headers["content-disposition"]


def test_alquiler_iva_por_uso(client, admin, ids):
    domicilio_fiscal(client, admin)
    bab = ids["assets"]["BAB35"]["id"]
    garaje = client.get(f"/api/unidades?asset_id={bab}&uso=garaje", headers=admin).json()[-1]
    lease = client.post("/api/alquiler/contratos", headers=admin, json={
        "unit_id": garaje["id"], "tenant": {"nombre": "Talleres Prueba SL", "documento_num": "B87654321"},
        "fecha_inicio": "2026-01-01", "renta_mensual": 100}).json()
    assert client.post("/api/alquiler/recibos/generar", headers=admin, json={"periodo": "2026-02"}).json()["creados"] >= 1
    rec = [c for c in client.get("/api/alquiler/recibos?periodo=2026-02", headers=admin).json()
           if c["lease_id"] == lease["id"]][0]
    assert rec["importe"] == 121.0 and rec["tipo_iva"] == 21  # garaje: renta + 21 % IVA
    p = client.post(f"/api/alquiler/recibos/{rec['id']}/cobro", headers=admin,
                    json={"importe": 121, "fecha_pago": "2026-02-05", "forma_pago": "transferencia"}).json()
    f = _factura(client, admin, p["factura"]["id"])
    assert f["serie"] == "B35" and f["emisor"]["nombre"] == "COMERCIAL DEL CAMPO S.A."
    assert (f["base_imponible"], f["cuota_iva"], f["total"], f["exencion"]) == (100, 21, 121, None)
    assert f["fecha_operacion"] == "2026-02-05" and f["fecha_expedicion"] == HOY.isoformat()
    assert f["concepto"].startswith("Renta febrero 2026 · Garaje")

    # vivienda: exenta, con la mención legal
    viv = [u for u in client.get(f"/api/unidades?asset_id={bab}&uso=vivienda", headers=admin).json()
           if u["estado"] == "disponible"][-1]
    lv = client.post("/api/alquiler/contratos", headers=admin, json={
        "unit_id": viv["id"], "tenant": {"nombre": "Eva"}, "fecha_inicio": "2026-01-01", "renta_mensual": 900}).json()
    client.post("/api/alquiler/recibos/generar", headers=admin, json={"periodo": "2026-03"})
    rv = [c for c in client.get("/api/alquiler/recibos?periodo=2026-03", headers=admin).json()
          if c["lease_id"] == lv["id"]][0]
    assert rv["importe"] == 900 and rv["tipo_iva"] == 0
    fv = _factura(client, admin, client.post(f"/api/alquiler/recibos/{rv['id']}/cobro", headers=admin,
                                             json={"importe": 900}).json()["factura"]["id"])
    assert (fv["base_imponible"], fv["cuota_iva"]) == (900, 0) and "art. 20.Uno.23º" in fv["exencion"]
    # la serie B35 no se mezcla con las de las Suites
    numeros = [x["numero"] for x in client.get(f"/api/facturas?serie=B35&anio={ANIO}", headers=admin).json()]
    assert sorted(numeros) == list(range(1, len(numeros) + 1))
    _finalizar(client, admin, lease)
    _finalizar(client, admin, lv)


def test_rectificativa_anula_el_cobro(client, admin, ids):
    domicilio_fiscal(client, admin)
    sfl = ids["assets"]["SFL"]["id"]
    r = _reserva(client, admin, sfl, "P3-2B", 200, importe_pagado=200)
    fid = r["factura"]["id"]
    assert client.post(f"/api/facturas/{fid}/rectificar", headers=admin, json={"motivo": "x"}).status_code == 422
    rc = client.post(f"/api/facturas/{fid}/rectificar", headers=admin, json={"motivo": "Cobro duplicado por error"})
    assert rc.status_code == 201, rc.text
    rect = rc.json()
    assert rect["codigo"] == f"SFR/00001/{ANIO}" and rect["tipo"] == "rectificativa"
    assert (rect["total"], rect["base_imponible"], rect["rectifica_id"]) == (-200, -181.82, fid)
    assert _factura(client, admin, fid)["rectificada_por"] == rect["codigo"]
    # el cobro queda deshecho
    res = client.get(f"/api/turistico/reservas?q=P3-2B&desde={d(30)}", headers=admin).json()[0]
    assert res["importe_pagado"] == 0
    # no se rectifica dos veces, ni una rectificativa
    assert client.post(f"/api/facturas/{fid}/rectificar", headers=admin, json={"motivo": "Otra vez"}).status_code == 400
    assert client.post(f"/api/facturas/{rect['id']}/rectificar", headers=admin,
                       json={"motivo": "Otra vez"}).status_code == 400
    pdf = client.get(f"/api/facturas/{rect['id']}/pdf", headers=admin)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # la numeración ordinaria sigue su curso
    nueva = _reserva(client, admin, sfl, "P3-2C", 200, importe_pagado=200)
    assert _factura(client, admin, nueva["factura"]["id"])["serie"] == "SF"

    # libro registro para la gestoría
    csv = client.get(f"/api/facturas/libro.csv?anio={ANIO}", headers=admin)
    assert csv.status_code == 200 and "text/csv" in csv.headers["content-type"]
    lineas = csv.content.decode("utf-8-sig").splitlines()
    assert lineas[0].startswith("Emisor;CIF emisor;Serie;Número;Factura")
    assert any(f"SFR/00001/{ANIO}" in x and "-200,00" in x and f"SF/" in x for x in lineas)


def test_permisos_facturas(client, admin, ids):
    domicilio_fiscal(client, admin)
    sfl, sae = ids["assets"]["SFL"]["id"], ids["assets"]["SAE"]["id"]
    email = "recepcion.facturas@inversiete.com"
    assert client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": "Rec", "password": "Provisional1",
        "asignaciones": [{"role_id": ids["roles"]["Recepción"], "asset_id": sae}]}).status_code == 201
    h = login(client, email, "Provisional1")
    client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "ClaveDefinitiva2026"})
    # recepción cobra y factura en su activo
    r = _reserva(client, h, sae, "B-2", 150)
    c = client.post(f"/api/turistico/reservas/{r['id']}/cobro", headers=h, json={"importe": 150}).json()
    assert c["factura"]["codigo"].startswith("SA/")
    assert client.get(f"/api/facturas/{c['factura']['id']}/pdf", headers=h).status_code == 200
    # solo ve las facturas de su activo
    visibles = client.get("/api/facturas", headers=h).json()
    assert visibles and all(f["asset_id"] == sae for f in visibles)
    otra = client.get(f"/api/facturas?asset_id={sfl}", headers=admin).json()[0]
    assert client.get(f"/api/facturas/{otra['id']}", headers=h).status_code == 403
    # pero no puede emitir rectificativas
    assert client.post(f"/api/facturas/{c['factura']['id']}/rectificar", headers=h,
                       json={"motivo": "Error de importe"}).status_code == 403


def test_serie_unica_y_requerida(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    assert client.put(f"/api/activos/{sfl}", headers=admin, json={"serie_factura": "SA"}).status_code == 400
    assert client.put(f"/api/activos/{sfl}", headers=admin, json={"serie_factura": "sf/1"}).status_code == 422
    cats = client.get("/api/catalogos", headers=admin).json()
    assert "transferencia" in cats["formas_pago"]
