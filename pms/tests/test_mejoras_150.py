"""Versión 1.50: sesiones y enlaces revocables, calendario sin saldos para colaboradores, cobro de la fianza, saldo de la
reserva, caja por turno, CAE de subcontratas, plazos de las OT, preventivo automático, aviso de la víspera, informe
diario de dirección y los avisos nuevos a gestión (en espera hasta activarlos)."""
from datetime import date, datetime, timedelta

from app import automatismos, avisos, gestion, informe_vacaciones
from app.database import SessionLocal
from app.models import GestionEvento, PreventivePlan, Reservation, User, WorkOrder
from conftest import login
from test_pms import _new_user
from test_tecnico_ot import _api, _enlace

HOY = date.today()


def _eventos(tipo, **filtro):
    with SessionLocal() as db:
        return [e for e in db.query(GestionEvento).filter(GestionEvento.tipo == tipo).order_by(GestionEvento.id)
                if all((e.datos or {}).get(k) == v for k, v in filtro.items())]


def _apto_libre(client, h, aid, ent, sal, guest=None, importe=300):
    for u in reversed([u for u in client.get(f"/api/unidades?asset_id={aid}", headers=h).json() if u["uso"] == "apartamento"]):
        r = client.post("/api/turistico/reservas", headers=h, json={
            "unit_id": u["id"], "fecha_entrada": ent.isoformat(), "fecha_salida": sal.isoformat(), "importe_total": importe,
            "guest": guest or {"nombre": "Cliente Mejoras"}})
        if r.status_code == 201:
            return r.json()
    raise AssertionError("sin apartamento libre")


# --------------------------------------------------------------------------- sesiones
def test_cambio_de_contrasena_y_baja_cierran_las_sesiones(client, admin, ids):
    email = "sesiones.150@inversiete.com"
    uid = client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": "Sesiones", "password": "Provisional1",
        "asignaciones": [{"role_id": ids["roles"]["Consulta"]}]}).json()["id"]
    h = login(client, email, "Provisional1")
    otro = dict(h)  # la misma sesión abierta en otro dispositivo
    r = client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "ClaveDefinitiva2026"})
    assert r.status_code == 200 and r.json()["token"]
    assert client.get("/api/auth/me", headers=otro).status_code == 401  # la otra sesión queda cerrada
    nuevo = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/api/auth/me", headers=nuevo).status_code == 200  # esta sigue con el token nuevo
    # al desactivarlo, y aunque se reactive, el token anterior ya no vale
    client.put(f"/api/admin/usuarios/{uid}", headers=admin, json={"activo": False})
    client.put(f"/api/admin/usuarios/{uid}", headers=admin, json={"activo": True})
    assert client.get("/api/auth/me", headers=nuevo).status_code == 401
    # contraseña restablecida por el administrador: también
    h2 = login(client, email, "ClaveDefinitiva2026")
    client.put(f"/api/admin/usuarios/{uid}", headers=admin, json={"password": "OtraProvisional1"})
    assert client.get("/api/auth/me", headers=h2).status_code == 401


# --------------------------------------------------------------------------- enlace del técnico y CAE
def test_enlace_del_tecnico_revocable_y_cae_vencida(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    rec = _new_user(client, admin, "rec.enlace150@inversiete.com", [{"role_id": ids["roles"]["Recepción"], "asset_id": sfl}])
    p1 = client.post("/api/personal", headers=admin, json={"asset_id": sfl, "area": "mantenimiento",
                                                           "nombre": "Técnico Uno", "telefono": "600111001"}).json()
    p2 = client.post("/api/personal", headers=admin, json={"asset_id": sfl, "area": "mantenimiento",
                                                           "nombre": "Técnico Dos", "telefono": "600111002"}).json()
    w = client.post("/api/mantenimiento/ordenes", headers=rec, json={
        "asset_id": sfl, "titulo": "Revisar bomba", "categoria": "fontaneria", "prioridad": "urgente"}).json()
    assert w["plazo"] and not w["plazo"]["vencido"]  # urgente: 4 horas para responder
    client.post(f"/api/mantenimiento/ordenes/{w['id']}/asignar", headers=rec, json={"asignacion": "propio", "personal_id": p1["id"]})
    e1 = _enlace(client, rec, w["id"])
    assert client.get(_api(e1, "/datos")).status_code == 200
    # se reasigna: el enlace del primero deja de valer; el nuevo sí vale
    client.post(f"/api/mantenimiento/ordenes/{w['id']}/asignar", headers=rec, json={"asignacion": "propio", "personal_id": p2["id"]})
    assert client.get(_api(e1, "/datos")).status_code == 404
    e2 = _enlace(client, rec, w["id"])
    assert client.get(_api(e2, "/datos")).status_code == 200
    # «Revocar enlace»
    assert client.post(f"/api/mantenimiento/ordenes/{w['id']}/revocar-enlace", headers=rec).status_code == 200
    assert client.get(_api(e2, "/datos")).status_code == 404
    # subcontrata con la documentación CAE/PRL vencida: no se le asigna
    s = client.post("/api/proveedores", headers=admin, json={"nombre": "Subcontrata CAE Vencida SL", "telefono": "600999888",
                                                             "cae_vence": (HOY - timedelta(days=1)).isoformat()}).json()
    assert s["cae_vencida"] is True
    r = client.post(f"/api/mantenimiento/ordenes/{w['id']}/asignar", headers=rec,
                    json={"asignacion": "subcontrata", "proveedor_id": s["id"]})
    assert r.status_code == 400 and "CAE" in r.json()["detail"]
    client.put(f"/api/proveedores/{s['id']}", headers=admin, json={"nombre": s["nombre"], "telefono": "600999888",
                                                                  "cae_vence": (HOY + timedelta(days=180)).isoformat()})
    assert client.post(f"/api/mantenimiento/ordenes/{w['id']}/asignar", headers=rec,
                       json={"asignacion": "subcontrata", "proveedor_id": s["id"]}).status_code == 200


# --------------------------------------------------------------------------- calendario de vacaciones
def test_calendario_sin_saldos_para_colaboradores(client, admin, ids, monkeypatch):
    from reportlab import rl_config
    monkeypatch.setattr(rl_config, "pageCompression", 0)  # texto legible en el PDF
    with SessionLocal() as db:
        completo = informe_vacaciones.pdf(db, HOY.year)
        externo = informe_vacaciones.pdf(db, HOY.year, saldos=False)
    assert completo[:4] == externo[:4] == b"%PDF"
    assert b"SALDOS POR PERSONA" in completo and b"SALDOS POR PERSONA" not in externo
    assert b"Consumido el" in completo and b"Consumido el" not in externo  # la tabla de saldos


# --------------------------------------------------------------------------- fianza, saldo y caja
def test_fianza_cobrada_saldo_y_caja_del_turno(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    r = _apto_libre(client, admin, sfl, HOY - timedelta(days=1), HOY + timedelta(days=2), importe=300)
    client.put(f"/api/turistico/reservas/{r['id']}", headers=admin, json={"estado": "checkin"})
    # saldo: toda la estancia pendiente
    assert client.get(f"/api/turistico/reservas/{r['id']}", headers=admin).json()["saldo"]["total"] == 300
    c = client.post(f"/api/turistico/reservas/{r['id']}/cobro", headers=admin, json={"importe": 200, "forma_pago": "efectivo"})
    assert c.status_code == 200, c.text
    info = client.get(f"/api/turistico/reservas/{r['id']}/fianza", headers=admin).json()
    assert info["saldo"]["total"] == 100 and info["fianza"] == 0
    # fianza cobrada al llegar, sin contrato guardado: es la que se devuelve
    f = client.post(f"/api/turistico/reservas/{r['id']}/fianza/cobro", headers=admin, json={"importe": 150, "forma": "efectivo"})
    assert f.status_code == 200, f.text
    assert client.post(f"/api/turistico/reservas/{r['id']}/fianza/cobro", headers=admin,
                       json={"importe": 150, "forma": "efectivo"}).status_code == 400  # una sola vez
    info = client.get(f"/api/turistico/reservas/{r['id']}/fianza", headers=admin).json()
    assert info["fianza"] == 150 and info["procede"] and info["cobro"]["forma"] == "efectivo"
    assert _eventos("fianza.cobrada", reserva_id=r["id"])[0].datos["fianza"] == 150
    # caja del turno: 200 de la factura + 150 de la fianza en efectivo
    t = client.get(f"/api/caja/turno?asset_id={sfl}", headers=admin).json()
    assert t["efectivo_esperado"] >= 350
    esperado = t["efectivo_esperado"]
    # salida con devolución en efectivo: resta de la caja
    out = client.post(f"/api/turistico/reservas/{r['id']}/checkout", headers=admin,
                      json={"fianza": {"forma": "efectivo"}})
    assert out.status_code == 200, out.text
    ev = _eventos("fianza.devolucion", reserva_id=r["id"])[0].datos
    assert ev["fianza"] == 150 and ev["devuelto"] == 150 and ev["forma"] == "efectivo" and "iban" not in ev
    t = client.get(f"/api/caja/turno?asset_id={sfl}", headers=admin).json()
    assert round(t["efectivo_esperado"], 2) == round(esperado - 150, 2)
    # cierre con descuadre: hace falta el motivo y se avisa a la Dirección
    falta = round(t["efectivo_esperado"] - 5, 2)
    assert client.post("/api/caja/cierre", headers=admin, json={"asset_id": sfl, "efectivo_contado": falta}).status_code == 400
    avisos.BANDEJA.clear()
    c = client.post("/api/caja/cierre", headers=admin, json={"asset_id": sfl, "efectivo_contado": falta,
                                                             "nota": "Cambio mal dado"})
    assert c.status_code == 201 and c.json()["diferencia"] == -5
    assert sorted(m["para"] for m in avisos.BANDEJA) == ["alfonso@inversiete.es", "barbara@inversiete.es"]
    assert _eventos("caja.cierre", cierre_id=c.json()["id"])[0].datos["diferencia"] == -5
    # el turno siguiente empieza en el cierre
    assert client.get(f"/api/caja/turno?asset_id={sfl}", headers=admin).json()["movimientos"] == []
    assert any(x["id"] == c.json()["id"] for x in client.get("/api/caja/cierres", headers=admin).json())


# --------------------------------------------------------------------------- gestión
def test_ampliacion_no_es_salida_para_gestion(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    from test_fianza_dotacion import COMPLETO
    r = _apto_libre(client, admin, sae, HOY - timedelta(days=3), HOY,
                    guest={**COMPLETO, "documento_num": "71234567T", "email": "amplia@example.com"})
    client.put(f"/api/turistico/reservas/{r['id']}", headers=admin, json={"estado": "checkin"})
    n = client.post(f"/api/turistico/reservas/{r['id']}/renovar", headers=admin,
                    json={"fecha_salida": (HOY + timedelta(days=4)).isoformat(), "importe_total": 200})
    assert n.status_code == 201, n.text
    assert _eventos("checkout", reserva_id=r["id"]) == []  # no es un check-out
    amp = _eventos("reserva.ampliada", reserva_id=r["id"])
    assert len(amp) == 1 and amp[0].datos["continua_en"]["salida"] == (HOY + timedelta(days=4)).isoformat()


def test_avisos_nuevos_esperan_hasta_activarlos(client, admin, ids, monkeypatch):
    enviados = []
    monkeypatch.setattr(gestion, "EVENTOS_SECRET", "clave-de-prueba")
    monkeypatch.setattr(gestion, "_enviar", lambda ev: (enviados.append(ev.tipo), (True, "ok"))[1])
    monkeypatch.setattr(gestion, "V2", False)
    with SessionLocal() as db:
        gestion.encolar(db, "kpi.diario", {"activo_pms": "SFL", "fecha": HOY.isoformat()})
        db.commit()
        gestion.procesar_cola(db, ahora=datetime.now() + timedelta(days=1), limite=500)
    assert "kpi.diario" not in enviados
    monkeypatch.setattr(gestion, "V2", True)
    with SessionLocal() as db:
        gestion.procesar_cola(db, ahora=datetime.now() + timedelta(days=1), limite=500)
    assert "kpi.diario" in enviados


# --------------------------------------------------------------------------- automatismos
def test_automatismos_del_programador(client, admin, ids, monkeypatch):
    sfl = ids["assets"]["SFL"]["id"]
    # aviso de la víspera al cliente con correo
    r = _apto_libre(client, admin, sfl, HOY + timedelta(days=1), HOY + timedelta(days=3),
                    guest={"nombre": "Llega Mañana", "email": "llega.manana@example.com"})
    avisos.BANDEJA.clear()
    with SessionLocal() as db:
        assert automatismos.avisos_llegada(db, HOY) >= 1
        assert automatismos.avisos_llegada(db, HOY) == 0  # una sola vez
        assert db.get(Reservation, r["id"]).aviso_llegada is not None
    m = next(m for m in avisos.BANDEJA if m["para"] == "llega.manana@example.com")
    assert "933/2021" in m["texto"] and "15:00" in m["texto"]
    # OT urgente sin respuesta pasadas 4 horas: aviso al director técnico, una vez
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sfl, "titulo": "Sin agua caliente", "categoria": "fontaneria", "prioridad": "urgente"}).json()
    with SessionLocal() as db:
        db.get(WorkOrder, w["id"]).creada = datetime.now() - timedelta(hours=5)
        db.commit()
    avisos.BANDEJA.clear()
    with SessionLocal() as db:
        assert automatismos.avisar_plazos(db) >= 1
        assert automatismos.avisar_plazos(db) == 0
    assert any("fuera de plazo" in m["asunto"] for m in avisos.BANDEJA)
    assert client.get("/api/mantenimiento/ordenes?abiertas=true", headers=admin).json()
    o = next(x for x in client.get("/api/mantenimiento/ordenes?abiertas=true", headers=admin).json() if x["id"] == w["id"])
    assert o["plazo"]["vencido"] is True
    # preventivo automático: el plan que vence genera su OT y avanza
    with SessionLocal() as db:
        p = PreventivePlan(asset_id=sfl, titulo="Revisión extintores (prueba 1.50)", categoria="pci", periodicidad_dias=90,
                           proxima_fecha=HOY + timedelta(days=3))
        db.add(p)
        db.commit()
        pid = p.id
        assert automatismos.preventivo_automatico(db, HOY) >= 1
        assert db.get(PreventivePlan, pid).proxima_fecha == HOY + timedelta(days=93)
        assert db.query(WorkOrder).filter(WorkOrder.plan_id == pid).count() == 1
    # informe diario de dirección: una vez al día, a la Dirección, y los indicadores a gestión
    avisos.BANDEJA.clear()
    with SessionLocal() as db:
        assert automatismos.informe_direccion(db, HOY) == 2
        assert automatismos.informe_direccion(db, HOY) == 0
    m = avisos.BANDEJA[0]
    assert "Informe diario de dirección" in m["asunto"] and "RevPAR" in m["texto"] and "ADR" in m["texto"]
    assert _eventos("kpi.diario", fecha=HOY.isoformat())
