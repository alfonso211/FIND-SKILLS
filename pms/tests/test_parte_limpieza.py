"""Servicios extra y limpieza contratada en la reserva, parte diario de limpieza y revisión de salida."""
from datetime import date, timedelta

from app import limpiezas
from app.database import SessionLocal
from app.models import Reservation, WorkOrder

HOY = date.today()
D = date(2031, 3, 1)


def test_fechas_plan():
    ent, sal = date(2031, 3, 1), date(2031, 3, 15)
    f = lambda **p: [x.day for x in limpiezas.fechas_plan(p, ent, sal)]  # noqa: E731
    assert f(periodicidad="unica", inicio="2031-03-05") == [5]
    assert f(periodicidad="cada_3", inicio="2031-03-03") == [3, 6, 9, 12]
    assert f(periodicidad="semanal", inicio="2031-03-02") == [2, 9]
    assert f(periodicidad="diaria", inicio="2031-03-12") == [12, 13, 14]
    assert f(periodicidad="otra", texto="Martes y viernes", fechas=["2031-03-04", "2031-03-07", "2031-03-20"]) == [4, 7]
    assert f(periodicidad="unica", inicio="2031-03-15") == []  # el día de salida ya se limpia por la salida


def _aptos(client, admin, sae):
    return [u for u in client.get(f"/api/unidades?asset_id={sae}", headers=admin).json() if u["uso"] != "garaje"]


def _reserva(client, admin, unit_id, ent, sal, **extra):
    r = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": unit_id, "fecha_entrada": ent.isoformat(), "fecha_salida": sal.isoformat(), "importe_total": 700,
        "guest": {"nombre": "Cliente Limpieza"}, **extra})
    return r


def test_extras_y_parte(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    aptos = _aptos(client, admin, sae)
    u1, u2 = aptos[-50], aptos[-51]
    limpieza = {"periodicidad": "cada_3", "inicio": "2031-03-03", "concepto": "Limpieza", "precio": 30}
    assert _reserva(client, admin, u1["id"], D, D + timedelta(days=14), limpieza={
        **limpieza, "inicio": "2031-03-15"}).status_code == 400  # fuera de la estancia
    assert _reserva(client, admin, u1["id"], D, D + timedelta(days=14), limpieza={
        "periodicidad": "otra", "fechas": ["2031-03-04"], "precio": 30}).status_code == 400  # sin decir cuál
    r = _reserva(client, admin, u1["id"], D, D + timedelta(days=14), limpieza=limpieza,
                 extras=[{"concepto": "Cama supletoria", "precio": 20, "cantidad": 2, "tipo_iva": 10}])
    assert r.status_code == 201, r.text
    res = r.json()
    assert res["extras_pendientes"] == 160 and res["limpieza_fechas"] == [
        "2031-03-03", "2031-03-06", "2031-03-09", "2031-03-12"]
    assert any(e["limpieza"] and e["cantidad"] == 4 for e in res["extras"])
    # al cambiar las fechas cambia el número de limpiezas
    res = client.put(f"/api/turistico/reservas/{res['id']}", headers=admin,
                     json={"fecha_salida": "2031-03-10"}).json()
    assert res["limpieza_fechas"] == ["2031-03-03", "2031-03-06", "2031-03-09"] and res["extras_pendientes"] == 130
    # los extras van a la factura de la estancia
    fac = client.post(f"/api/turistico/reservas/{res['id']}/facturar", headers=admin, json={}).json()
    assert fac["extras_pendientes"] == 0 and all(e["factura"] == fac["factura"]["codigo"] for e in fac["extras"])
    lineas = client.get(f"/api/facturas/{fac['factura']['id']}", headers=admin).json()["lineas"]
    assert [x["concepto"] for x in lineas if x["tipo"] == "servicio"] == [
        "Cama supletoria", "Limpieza · 3 limpiezas (Cada 3 días desde el 03/03/2031)"]
    assert client.post(f"/api/turistico/reservas/{res['id']}/extras/factura", headers=admin,
                       json={}).status_code == 400  # nada pendiente
    # un extra pedido después: se factura aparte
    client.put(f"/api/turistico/reservas/{res['id']}", headers=admin,
               json={"extras": [{"concepto": "Toallas extra", "precio": 5}]})
    f2 = client.post(f"/api/turistico/reservas/{res['id']}/extras/factura", headers=admin, json={"forma_pago": "tarjeta"})
    assert f2.status_code == 200, f2.text
    assert f2.json()["extras_pendientes"] == 0 and len(f2.json()["extras"]) == 3

    # parte del día de una limpieza contratada
    p = client.get("/api/limpieza/parte", headers=admin, params={"asset_id": sae, "fecha": "2031-03-06"}).json()
    x = next(x for x in p["limpiezas"] if x["unit_id"] == u1["id"])
    assert x["tipo"] == "contratada" and x["motivo"].startswith("Limpieza contratada")
    # salida con llegada el mismo día en el apartamento: va primero y pide tenerlo antes
    assert _reserva(client, admin, u1["id"], date(2031, 3, 10), date(2031, 3, 12)).status_code == 201
    p = client.get("/api/limpieza/parte", headers=admin, params={"asset_id": sae, "fecha": "2031-03-10"}).json()
    sal = next(x for x in p["limpiezas"] if x["unit_id"] == u1["id"])
    assert sal["tipo"] == "salida" and sal["urgente"] and sal["antes_de"] == "2031-03-10"
    assert p["limpiezas"][0]["urgente"]
    # extra de recepción; lo no validado pasa al día siguiente
    e = client.post("/api/limpieza/extra", headers=admin, json={"asset_id": sae, "unit_id": u2["id"],
                                                                "fecha": "2031-03-10", "nota": "Repaso a fondo"})
    assert e.status_code == 201
    p = client.get("/api/limpieza/parte", headers=admin, params={"asset_id": sae, "fecha": "2031-03-11"}).json()
    ex = next(x for x in p["limpiezas"] if x["id"] == e.json()["id"])
    assert ex["arrastrada"] and ex["motivo"] == "Limpieza extra: Repaso a fondo"
    assert client.post(f"/api/limpieza/{ex['id']}/hecha", headers=admin).status_code == 200
    p = client.get("/api/limpieza/parte", headers=admin, params={"asset_id": sae, "fecha": "2031-03-12"}).json()
    assert not any(x["id"] == ex["id"] for x in p["limpiezas"])
    # PDF e impresión: el Excel del día queda en los documentos del activo (uno por día)
    for _ in range(2):
        pdf = client.get("/api/limpieza/parte.pdf", headers=admin, params={"asset_id": sae, "fecha": "2031-03-10"})
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    docs = client.get("/api/documentos-recibidos", headers=admin, params={"asset_id": sae, "tipo": "limpieza",
                                                                           "desde": "2031-03-10"}).json()
    assert [d["nombre"] for d in docs if d["nombre"].startswith("Parte_limpieza")] == [
        "Parte_limpieza_SAE_2031-03-10.xlsx"]
    env = client.post("/api/limpieza/parte/enviar", headers=admin, json={
        "asset_id": sae, "fecha": "2031-03-10", "canal": "whatsapp", "telefono": "600 111 222"})
    assert env.status_code == 200, env.text
    assert env.json()["enviados"][0]["whatsapp"].startswith("https://wa.me/34600111222?text=")
    # reserva cancelada: sus limpiezas contratadas pendientes se anulan
    otra = _reserva(client, admin, u2["id"], date(2031, 4, 1), date(2031, 4, 8),
                    limpieza={"periodicidad": "unica", "inicio": "2031-04-04", "precio": 25}).json()
    p = client.get("/api/limpieza/parte", headers=admin, params={"asset_id": sae, "fecha": "2031-04-04"}).json()
    assert any(x["unit_id"] == u2["id"] and x["tipo"] == "contratada" for x in p["limpiezas"])
    client.put(f"/api/turistico/reservas/{otra['id']}", headers=admin, json={"estado": "cancelada"})
    p = client.get("/api/limpieza/parte", headers=admin, params={"asset_id": sae, "fecha": "2031-04-04"}).json()
    assert not any(x["unit_id"] == u2["id"] for x in p["limpiezas"])


def test_salida_revision_y_validacion(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    u = _aptos(client, admin, sae)[-52]
    r = _reserva(client, admin, u["id"], HOY - timedelta(days=3), HOY)
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        db.get(Reservation, r.json()["id"]).estado = "checkin"
        db.commit()
    assert client.post(f"/api/turistico/reservas/{r.json()['id']}/checkout", headers=admin).status_code == 200
    titulo = f"Revisión de salida · Apartamento {u['codigo']}"
    with SessionLocal() as db:
        ots = db.query(WorkOrder).filter(WorkOrder.unit_id == u["id"], WorkOrder.titulo == titulo).all()
        assert len(ots) == 1 and ots[0].tipo == "preventivo"
        from app.routers.turistico import revision_salida
        assert revision_salida(db, db.get(Reservation, r.json()["id"]), None) is None  # no se duplica
    p = client.get("/api/limpieza/parte", headers=admin, params={"asset_id": sae}).json()
    sal = next(x for x in p["limpiezas"] if x["unit_id"] == u["id"])
    assert sal["tipo"] == "salida" and sal["motivo"] == "Salida realizada"
    assert client.post(f"/api/limpieza/{sal['id']}/hecha", headers=admin).json()["unidad_estado"] == "disponible"
    assert client.post(f"/api/limpieza/{sal['id']}/deshacer", headers=admin).status_code == 200
    assert client.delete(f"/api/limpieza/{sal['id']}", headers=admin).status_code == 400  # solo las extra
