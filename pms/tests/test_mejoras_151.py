"""Versión 1.51: hora de Madrid, partes de trabajo editables y dotación estándar obligatoria al reservar."""
import time
from datetime import date, datetime, timedelta, timezone

from app import corregir_hora
from app.database import SessionLocal
from app.models import DotacionHabitual, EmailLog, Reservation, TimeEntry
from test_adjuntos_ot import _usuario

HOY = date.today()


# --------------------------------------------------------------------------- reloj
def test_hora_de_madrid(client, admin):
    assert time.tzname[0] in ("CET", "CEST")  # el programa fija la zona de Madrid aunque el sistema esté en UTC
    r = client.get("/api/auth/reloj", headers=admin).json()
    assert r["zona"] == "Europe/Madrid" and r["correcta"] and r["horas_sobre_utc"] in (1.0, 2.0)
    assert abs((datetime.fromisoformat(r["hora"]) - datetime.now()).total_seconds()) < 5


def test_correccion_de_horas_utc(client, admin, ids):
    with SessionLocal() as db:
        from app.models import StaffMember
        st = StaffMember(asset_id=ids["assets"]["SFL"]["id"], area="mantenimiento", nombre="Fichaje UTC Prueba")
        db.add(st)
        db.flush()
        viejo = TimeEntry(staff_id=st.id, entrada=datetime(2026, 7, 1, 6, 0), salida=datetime(2026, 7, 1, 14, 0))
        a_mano = TimeEntry(staff_id=st.id, entrada=datetime(2026, 7, 2, 8, 0), editado_en=datetime(2026, 7, 2, 9, 0))
        nuevo = TimeEntry(staff_id=st.id, entrada=datetime(2026, 10, 14, 8, 0))
        db.add_all([viejo, a_mano, nuevo])
        db.commit()
        ids_ = (viejo.id, a_mano.id, nuevo.id)
    assert corregir_hora.main(["--hasta", "2026-10-13 14:51"]) == 0  # solo enseña: no cambia nada
    with SessionLocal() as db:
        assert db.get(TimeEntry, ids_[0]).entrada == datetime(2026, 7, 1, 6, 0)
    assert corregir_hora.main(["--hasta", "2026-10-13 14:51", "--aplicar"]) == 0
    with SessionLocal() as db:
        v, m, n = (db.get(TimeEntry, i) for i in ids_)
        assert (v.entrada, v.salida) == (datetime(2026, 7, 1, 8, 0), datetime(2026, 7, 1, 16, 0))  # verano: +2 h
        assert m.entrada == datetime(2026, 7, 2, 8, 0) and n.entrada == datetime(2026, 10, 14, 8, 0)
    assert corregir_hora.main(["--hasta", "2026-10-13 14:51", "--aplicar"]) == 1  # una sola vez
    with SessionLocal() as db:
        db.query(EmailLog).filter(EmailLog.clave == corregir_hora.MARCA).delete()
        db.commit()


# --------------------------------------------------------------------------- partes de trabajo
def test_editar_lineas_del_parte(client, admin, ids):
    sfl = ids["assets"]["SAE"]["id"]  # otro activo: no se mezcla con el parte de test_partes_trabajo
    tec = _usuario(client, admin, ids, "tecnico.editar151@inversiete.com", "Técnico Mantenimiento", "SAE")
    otro = _usuario(client, admin, ids, "tecnico.otro151@inversiete.com", "Técnico Mantenimiento", "SAE")
    rec = _usuario(client, admin, ids, "recepcion.editar151@inversiete.com", "Recepción", "SAE")
    hoy = HOY.isoformat()
    q = {"asset_id": sfl, "area": "mantenimiento", "fecha": hoy}
    p = client.post("/api/partes-trabajo/actuaciones", headers=tec, json={
        **q, "descripcion": "Revisión bombas", "ubicacion": "Sala de máquinas", "horas": 1, "hora": "08:15"}).json()
    a = next(x for x in p["lineas"] if x["origen"] == "actuacion" and x["trabajo"] == "Revisión bombas")
    assert a["hora"] == "08:15" and a["editable"]
    # la corrige quien la anotó (con motivo); otro técnico no
    body = {"origen": "actuacion", "id": a["id"], "descripcion": "Revisión de las bombas de ACS", "hora": "09:00",
            "horas": 2, "motivo": "Hora y trabajo mal anotados"}
    assert client.put("/api/partes-trabajo/lineas", headers=otro, params=q, json=body).status_code == 403
    assert client.put("/api/partes-trabajo/lineas", headers=tec, params=q, json={**body, "motivo": ""}).status_code == 422
    r = client.put("/api/partes-trabajo/lineas", headers=tec, params=q, json=body)
    assert r.status_code == 200, r.text
    x = next(x for x in r.json()["lineas"] if x["id"] == a["id"] and x["origen"] == "actuacion")
    assert (x["trabajo"], x["hora"], x["horas"]) == ("Revisión de las bombas de ACS", "09:00", 2.0)
    # línea de una OT: se corrige la hora y la persona en el parte, sin tocar la OT
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={"asset_id": sfl, "titulo": "Grifo 151"}).json()
    client.post(f"/api/mantenimiento/ordenes/{w['id']}/confirmar-mantenimiento", headers=admin, json={"solucion": "Hecho"})
    r = client.put("/api/partes-trabajo/lineas", headers=rec, params=q, json={
        "origen": "ot", "id": w["id"], "hora": "11:30", "persona": "Pedro", "motivo": "Se confirmó más tarde"})
    assert r.status_code == 200, r.text
    o = next(x for x in r.json()["lineas"] if x["origen"] == "ot" and x["id"] == w["id"])
    assert (o["hora"], o["persona"], o["corregida"]) == ("11:30", "Pedro", True)
    assert client.get(f"/api/mantenimiento/ordenes?abiertas=false", headers=admin).status_code == 200
    # validado: no se edita hasta reabrirlo
    client.post("/api/partes-trabajo/validar", headers=rec, json=q)
    assert client.put("/api/partes-trabajo/lineas", headers=rec, params=q, json={**body, "hora": "10:00"}).status_code == 400
    v = client.get("/api/partes-trabajo", headers=rec, params=q).json()
    assert any(x["hora"] == "11:30" and x["origen"] == "ot" for x in v["lineas"])  # congelado con la corrección
    aud = client.get("/api/admin/auditoria?entidad=parte_trabajo", headers=admin).json()
    assert any(e["accion"] == "corregir_linea" for e in aud)
    client.post("/api/partes-trabajo/reabrir", headers=rec, json=q)  # se deja abierto para las demás pruebas


# --------------------------------------------------------------------------- dotación al reservar
def test_dotacion_estandar_obligatoria_y_extraordinaria(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    aptos = [u for u in client.get(f"/api/unidades?asset_id={sae}", headers=admin).json() if u["uso"] == "apartamento"]
    u = aptos[-7]
    with SessionLocal() as db:  # este tipo de apartamento sin dotación estándar fijada
        db.query(DotacionHabitual).filter(DotacionHabitual.asset_id == sae,
                                          DotacionHabitual.tipologia == (u["tipologia"] or "")).delete()
        db.commit()
    alta = {"unit_id": u["id"], "fecha_entrada": (HOY + timedelta(days=40)).isoformat(),
            "fecha_salida": (HOY + timedelta(days=43)).isoformat(), "importe_total": 300,
            "guest": {"nombre": "Cliente Dotación"}}
    # desde la pantalla (dotacion_extra presente) sin dotación estándar: no se crea
    r = client.post("/api/turistico/reservas", headers=admin, json={**alta, "dotacion_extra": []})
    assert r.status_code == 409 and r.json()["detail"].startswith("DOTACION_ESTANDAR")
    # se fija la estándar del tipo y se reserva con dotación extraordinaria
    est = client.get(f"/api/dotacion/unidad/{u['id']}", headers=admin).json()
    assert client.put("/api/dotacion/habitual", headers=admin, json={
        "asset_id": sae, "tipologia": u["tipologia"] or "", "perfil": est["perfil"], "items": est["items"]}).status_code == 200
    base = est["items"][0]
    r = client.post("/api/turistico/reservas", headers=admin, json={**alta, "dotacion_extra": [
        {"codigo": base["codigo"], "zona": base["zona"], "articulo": base["articulo"], "cantidad": "9"},
        {"codigo": "OTRCUNA", "zona": "dormitorio", "articulo": "Cuna de viaje", "cantidad": "1"}]})
    assert r.status_code == 201, r.text
    d = client.get(f"/api/turistico/reservas/{r.json()['id']}/dotacion", headers=admin).json()
    items = {x["codigo"]: x for x in d["items"]}
    assert items[base["codigo"]]["cantidad"] == "9" and items["OTRCUNA"]["especial"] and d["especial"]
    # sin dotación extraordinaria: la estándar
    r2 = client.post("/api/turistico/reservas", headers=admin, json={
        **alta, "fecha_entrada": (HOY + timedelta(days=50)).isoformat(),
        "fecha_salida": (HOY + timedelta(days=52)).isoformat(), "dotacion_extra": []})
    assert r2.status_code == 201
    with SessionLocal() as db:
        assert db.get(Reservation, r2.json()["id"]).dotacion is None
