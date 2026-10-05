"""Alquiler mensual de plazas de garaje a clientes externos (no huéspedes): contrato, recibos, cobro y avisos."""
from datetime import date, timedelta

from app import avisos, recibos
from app.database import SessionLocal

HOY = date.today()
CLIENTE = {"nombre": "Talleres", "apellidos": "Ruiz SL", "documento_tipo": "CIF", "documento_num": "B12345678",
           "telefono": "600999888", "email": "talleres@example.com", "direccion": "C/ Alcalá 1", "cp": "28009",
           "municipio": "Madrid", "pais": "España"}


def _plaza(client, h, asset_id, codigo):
    return next(u for u in client.get(f"/api/unidades?asset_id={asset_id}&q={codigo}", headers=h).json()
                if u["codigo"] == codigo)


def test_alquiler_mensual_de_garaje(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    plaza = _plaza(client, admin, sae, "EXT-40")
    inicio = (HOY.replace(day=1) - timedelta(days=40)).replace(day=15)  # hace dos meses, a mitad de mes
    r = client.post("/api/garajes/contratos", headers=admin, json={
        "unit_id": plaza["id"], "cliente": CLIENTE, "fecha_inicio": inicio.isoformat(), "renta_mensual": 100,
        "dia_pago": 5, "matricula": "1234 abc", "vehiculo": "Furgoneta blanca", "mandos": "1 mando + tarjeta 77"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["matricula"] == "1234ABC" and c["renta_con_iva"] == 121 and c["cliente"] == "Talleres Ruiz SL"
    # no es huésped: no aparece en la lista de huéspedes
    assert not [x for x in client.get("/api/terceros?tipo=huesped&q=Talleres", headers=admin).json()]
    assert client.get("/api/terceros?tipo=cliente_garaje&q=Talleres", headers=admin).json()[0]["id"] == c["cliente_id"]

    # recibos emitidos solos desde el inicio hasta el mes en curso; el primero prorrateado
    rec = sorted(client.get(f"/api/garajes/recibos?lease_id={c['id']}", headers=admin).json(), key=lambda x: x["periodo"])
    assert [x["periodo"] for x in rec] == recibos.periodos(inicio, HOY)
    assert rec[0]["importe"] < 121 and rec[1]["importe"] == 121 and rec[0]["fecha_vencimiento"] == inicio.isoformat()
    assert rec[0]["vencido"] and not c["al_corriente"]
    lista = client.get(f"/api/garajes/contratos?asset_id={sae}", headers=admin).json()
    mio = next(x for x in lista if x["id"] == c["id"])
    assert mio["recibos_vencidos"] >= 1 and mio["deuda_vencida"] > 0
    assert client.get(f"/api/garajes/recibos?asset_id={sae}&estado=vencido", headers=admin).json()

    # cobro: factura a 21 % con el concepto de la plaza
    pago = client.post(f"/api/garajes/recibos/{rec[1]['id']}/cobro", headers=admin,
                       json={"importe": 121, "forma_pago": "transferencia"}).json()
    assert pago["estado"] == "pagado"
    f = client.get(f"/api/facturas/{pago['factura']['id']}", headers=admin).json()
    assert f["codigo"].startswith("SA/") and f["cliente"]["nombre"] == "Talleres Ruiz SL"
    assert [(x["tipo"], x["tipo_iva"], x["base"]) for x in f["lineas"]] == [("renta", 21, 100)]
    assert f["lineas"][0]["concepto"].startswith("Alquiler de plaza de garaje · ")
    assert "Garaje exterior plaza 40 · Matrícula 1234ABC" in f["lineas"][0]["concepto"]

    # la plaza no se puede reservar ni alquilar otra vez mientras dure el alquiler
    dis = client.get(f"/api/turistico/disponibilidad?asset_id={sae}&desde={HOY}&hasta={HOY + timedelta(days=1)}"
                     "&uso=garaje", headers=admin).json()
    assert plaza["id"] not in [u["id"] for u in dis["unidades"]]
    assert client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": plaza["id"], "fecha_entrada": HOY.isoformat(), "fecha_salida": (HOY + timedelta(days=2)).isoformat(),
        "guest": {"nombre": "Otro"}}).status_code == 400
    assert client.post("/api/garajes/contratos", headers=admin, json={
        "unit_id": plaza["id"], "cliente": CLIENTE, "fecha_inicio": HOY.isoformat(),
        "renta_mensual": 90}).status_code == 400
    # en el plano y en la ficha figura como alquilada al cliente externo
    p = client.get(f"/api/plano/{sae}", headers=admin).json()
    celda = next(x for x in p["plantas"][0]["celdas"] if x.get("codigo") == "EXT-40")
    assert celda["estado"] == "alquilado"
    ficha = client.get(f"/api/plano/unidades/{plaza['id']}/ficha", headers=admin).json()
    assert ficha["alquiler"]["cliente"] == "Talleres Ruiz SL" and ficha["puede"]["alquilar"]
    assert ficha["facturas"][0]["id"] == pago["factura"]["id"]
    panel = {a["codigo"]: a for a in client.get("/api/panel", headers=admin).json()["activos"]}
    assert panel["SAE"]["garajes_alquiler_mensual"] >= 1

    # aviso diario a recepción: recibos de garaje vencidos
    with SessionLocal() as db:
        datos = avisos._datos_resumen(db, HOY)
    assert any(f[1] == "EXT-40" for _, f in datos["garajes_impagados"])
    assert not any(f[1] == "EXT-40" for _, f in datos["recibos_impagados"])

    # baja: anula los recibos posteriores sin cobrar y libera la plaza
    baja = client.post(f"/api/garajes/contratos/{c['id']}/finalizar", headers=admin,
                       json={"fecha_fin": HOY.isoformat(), "motivo": "Deja la plaza"}).json()
    assert baja["estado"] == "finalizado"
    assert _plaza(client, admin, sae, "EXT-40")["estado"] == "disponible"


def test_solo_garajes_turisticos(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    apto = _plaza(client, admin, sae, "B-101")
    assert client.post("/api/garajes/contratos", headers=admin, json={
        "unit_id": apto["id"], "cliente": CLIENTE, "fecha_inicio": HOY.isoformat(),
        "renta_mensual": 90}).status_code == 400
