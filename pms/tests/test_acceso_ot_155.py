"""Versión 1.55: autorización del acceso con llave (quién, cómo, para qué estancia) y llegadas próximas en las OT."""
from datetime import date, timedelta

from app.database import SessionLocal
from app.models import Reservation, WorkOrder
from test_adjuntos_ot import _usuario

HOY = date.today()


def _apto_libre(client, admin, aid, indice):
    aptos = [u for u in client.get(f"/api/unidades?asset_id={aid}", headers=admin).json() if u["uso"] == "apartamento"]
    with SessionLocal() as db:
        ocupados = {r.unit_id for r in db.query(Reservation).filter(
            Reservation.estado.in_(("confirmada", "checkin")), Reservation.fecha_salida >= HOY - timedelta(days=2),
            Reservation.fecha_entrada <= HOY + timedelta(days=30))}
    return [u for u in aptos if u["id"] not in ocupados and u["estado"] in ("disponible", "pendiente_limpieza")][indice]


def _reserva(client, admin, u, entra, sale, nombre, tel):
    r = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": u["id"], "fecha_entrada": entra.isoformat(), "fecha_salida": sale.isoformat(), "importe_total": 100,
        "guest": {"nombre": nombre, "telefono": tel}})
    assert r.status_code == 201, r.text
    return r.json()


def _checkin(rid):  # sin pasar por el registro de viajeros (no es lo que se prueba aquí)
    with SessionLocal() as db:
        r = db.get(Reservation, rid)
        r.estado = "checkin"
        db.commit()


def test_llave_exige_quien_autoriza_y_caduca_con_otro_cliente(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    u = _apto_libre(client, admin, sfl, -3)
    r1 = _reserva(client, admin, u, HOY - timedelta(days=2), HOY + timedelta(days=1), "Primer Cliente", "611000155")
    _checkin(r1["id"])
    a = client.get("/api/mantenimiento/acceso", headers=admin, params={"unit_id": u["id"]}).json()
    assert a["situacion"] == "alojado" and a["huesped"] == "Primer Cliente" and a["telefono"] == "611000155"
    base = {"asset_id": sfl, "unit_id": u["id"], "titulo": "Grifo 155", "acceso": "llave"}
    r = client.post("/api/mantenimiento/ordenes", headers=admin, json=base)
    assert r.status_code == 400 and "quién autoriza" in r.json()["detail"]
    r = client.post("/api/mantenimiento/ordenes", headers=admin, json={**base, "acceso_autoriza": "Primer Cliente"})
    assert r.status_code == 400 and "cómo" in r.json()["detail"]
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        **base, "acceso_autoriza": "Primer Cliente", "acceso_medio": "telefono"}).json()
    assert w["acceso_estado"]["estado"] == "vigente"
    assert "autoriza Primer Cliente por teléfono" in w["acceso_texto"] and "anotó" in w["acceso_texto"]
    with SessionLocal() as db:
        x = db.get(WorkOrder, w["id"])
        assert x.acceso_reserva_id == r1["id"] and x.acceso_user_id and x.acceso_fecha
    # el técnico ve que hay permiso, pero no quién lo dio
    from app.routers.mantenimiento import acceso_texto
    with SessionLocal() as db:
        externo = acceso_texto(db, db.get(WorkOrder, w["id"]))
    assert externo.startswith("Llave de recepción") and "Primer Cliente" not in externo
    # sale el cliente y entra otro con la OT abierta: la autorización ya no vale
    with SessionLocal() as db:
        db.get(Reservation, r1["id"]).estado = "checkout"
        db.commit()
    r2 = _reserva(client, admin, u, HOY, HOY + timedelta(days=3), "Segundo Cliente", "622000155")
    ck = client.post(f"/api/turistico/reservas/{r2['id']}/checkin", headers=admin)
    if ck.status_code == 200:  # con el registro de viajeros completo: el check-in avisa de la OT
        assert any(o["id"] == w["id"] for o in ck.json()["ot_acceso"])
    else:
        _checkin(r2["id"])
    ots = {o["id"]: o for o in client.get("/api/mantenimiento/ordenes", headers=admin,
                                          params={"asset_id": sfl, "abiertas": True}).json()}
    assert ots[w["id"]]["acceso_estado"]["estado"] == "caducado"
    with SessionLocal() as db:
        assert "otro cliente" in acceso_texto(db, db.get(WorkOrder, w["id"]))
    # recepción lo vuelve a pedir y lo anota
    rec = _usuario(client, admin, ids, "recepcion.acceso155@inversiete.com", "Recepción", "SFL")
    r = client.put(f"/api/mantenimiento/ordenes/{w['id']}/acceso", headers=rec,
                   json={"acceso": "llave", "autoriza": "Segundo Cliente", "medio": "whatsapp"})
    assert r.status_code == 200, r.text
    assert r.json()["acceso_estado"]["estado"] == "vigente" and "por WhatsApp" in r.json()["acceso_texto"]
    # o cambia a contactar: sale el teléfono del cliente de ahora
    r = client.put(f"/api/mantenimiento/ordenes/{w['id']}/acceso", headers=rec, json={"acceso": "contactar"})
    assert "622000155" in r.json()["acceso_texto"]
    aud = client.get("/api/admin/auditoria", headers=admin, params={"entidad": "orden_trabajo"}).json()
    assert any(e["accion"] == "acceso_ot" for e in aud)


def test_checkin_con_ot_abierta_pide_acceso(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    u = _apto_libre(client, admin, sfl, -4)
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sfl, "unit_id": u["id"], "titulo": "Persiana 155"}).json()
    assert w["acceso_estado"] is None
    from test_fianza_dotacion import COMPLETO  # registro de viajeros completo, como lo deja recepción
    r = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": u["id"], "fecha_entrada": HOY.isoformat(), "fecha_salida": (HOY + timedelta(days=2)).isoformat(),
        "importe_total": 100, "guest": {**COMPLETO, "documento_num": "71234567N", "telefono": "633000155"}})
    assert r.status_code == 201, r.text
    r = r.json()
    ck = client.post(f"/api/turistico/reservas/{r['id']}/checkin", headers=admin)
    assert ck.status_code == 200, ck.text
    d = ck.json()
    assert [o["id"] for o in d["ot_acceso"]] == [w["id"]] and d["huesped_telefono"] == "633000155"
    assert d["ot_acceso"][0]["estado_acceso"] == "falta"


def test_llegada_proxima(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    u = _apto_libre(client, admin, sae, -5)
    _reserva(client, admin, u, HOY + timedelta(days=3), HOY + timedelta(days=6), "Cliente Llega", "644000155")
    a = client.get("/api/mantenimiento/acceso", headers=admin, params={"unit_id": u["id"]}).json()
    assert a["situacion"] == "llegada" and a["dias"] == 3 and not a["alojado"]
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sae, "unit_id": u["id"], "titulo": "Revisar aire 155"}).json()
    assert w["acceso_estado"]["estado"] == "llegada" and "Llega un cliente" in w["acceso_estado"]["texto"]
    # sin cliente dentro no se anota el acceso a una OT ya abierta
    lejos = _apto_libre(client, admin, sae, -6)
    assert client.get("/api/mantenimiento/acceso", headers=admin,
                      params={"unit_id": lejos["id"]}).json()["situacion"] == "libre"
