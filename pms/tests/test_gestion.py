"""Pasarela con INVERGESTION (fase 4): cola de avisos con reintentos, bloqueo desde gestión, liquidación y pase."""
import base64
import hashlib
import hmac
import json
import threading
import time
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

from app import gestion
from app.database import SessionLocal
from app.models import Asset, GestionEvento, Reservation, Unit, WorkOrder

CLAVE = "clave-de-prueba-eventos-0123456789abcdef"
HOY = date.today()


def _aptos(client, admin, aid):
    return [u for u in client.get(f"/api/unidades?asset_id={aid}", headers=admin).json() if u["uso"] != "garaje"]


def _reserva(client, admin, unit_id, ent, sal, canal="directo", importe=700):
    r = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": unit_id, "fecha_entrada": ent.isoformat(), "fecha_salida": sal.isoformat(), "importe_total": importe,
        "canal": canal, "guest": {"nombre": "Cliente Pasarela"}})
    assert r.status_code == 201, r.text
    return r.json()


def _eventos(tipo=None, **filtro):
    with SessionLocal() as db:
        out = []
        for e in db.query(GestionEvento).order_by(GestionEvento.id):
            if tipo and e.tipo != tipo:
                continue
            if all((e.datos or {}).get(k) == v for k, v in filtro.items()):
                out.append(e)
        return out


def _firmado(client, metodo, ruta, cuerpo: dict | None = None, clave=CLAVE, ts=None):
    b = json.dumps(cuerpo or {}).encode() if cuerpo is not None else b""
    ts = str(int(ts if ts is not None else time.time()))
    return client.request(metodo, ruta, content=b, headers={"Content-Type": "application/json", "X-PMS-Fecha": ts,
                                                             "X-PMS-Firma": gestion.firmar(clave, ts, b)})


def test_reservas_checkout_e_incidencias_generan_avisos(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    u = _aptos(client, admin, sae)[-60]
    r = _reserva(client, admin, u["id"], HOY - timedelta(days=2), HOY, canal="booking")
    assert [e.datos["canal"] for e in _eventos("reserva.creada", reserva_id=r["id"])] == ["booking"]
    ev = _eventos("reserva.creada", reserva_id=r["id"])[0].datos
    assert ev["activo"] == "SAEROPUERTO" and ev["unidad_codigo"] == u["codigo"] and ev["unidad_pms_id"] == u["id"]
    with SessionLocal() as db:
        db.get(Reservation, r["id"]).estado = "checkin"
        db.commit()
    assert client.post(f"/api/turistico/reservas/{r['id']}/checkout", headers=admin).status_code == 200
    assert len(_eventos("checkout", reserva_id=r["id"])) == 1
    with SessionLocal() as db:  # decisión 5: sin orden «Revisión de salida»
        assert not db.query(WorkOrder).filter(WorkOrder.unit_id == u["id"], WorkOrder.titulo.like("Revisión de salida%")).count()
    # limpieza de salida «hecha con incidencia» → orden de trabajo + aviso con origen PMS_CHECKOUT
    p = client.get("/api/limpieza/parte", headers=admin, params={"asset_id": sae}).json()
    sal = next(x for x in p["limpiezas"] if x["unit_id"] == u["id"] and x["tipo"] == "salida")
    res = client.post(f"/api/limpieza/{sal['id']}/hecha", headers=admin, json={"incidencia": "Gotea el grifo del baño", "bloquea": True})
    assert res.status_code == 200, res.text
    ot = res.json()["orden_trabajo"]
    assert res.json()["unidad_estado"] == "mantenimiento"
    inc = _eventos("incidencia.reportada", ot_pms_id=ot)
    assert len(inc) == 1 and inc[0].datos["origen"] == "PMS_CHECKOUT" and inc[0].datos["bloquea_unidad"] is True
    # cancelación
    r2 = _reserva(client, admin, _aptos(client, admin, sae)[-67]["id"], HOY + timedelta(days=40), HOY + timedelta(days=42))
    client.post(f"/api/turistico/reservas/{r2['id']}/cancelar", headers=admin)
    assert len(_eventos("reserva.cancelada", reserva_id=r2["id"])) == 1
    # incidencia abierta por recepción
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={"asset_id": sae, "unit_id": u["id"], "titulo": "Persiana rota"})
    assert w.status_code == 201, w.text
    assert _eventos("incidencia.reportada", ot_pms_id=w.json()["id"])[0].datos["origen"] == "PMS_INCIDENCIA"


class _Gestion(BaseHTTPRequestHandler):
    recibidos: list = []
    fallar = False

    def do_POST(self):  # noqa: N802
        cuerpo = self.rfile.read(int(self.headers["Content-Length"]))
        ok = hmac.compare_digest(gestion.firmar(CLAVE, self.headers["X-PMS-Fecha"], cuerpo), self.headers["X-PMS-Firma"])
        if _Gestion.fallar or not ok:
            self.send_response(503 if ok else 401)
            self.end_headers()
            return
        _Gestion.recibidos.append(json.loads(cuerpo))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *a):
        pass


def test_cola_reintenta_hasta_entregar(client, admin, ids, monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _Gestion)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(gestion, "EVENTOS_SECRET", CLAVE)
    monkeypatch.setattr(gestion, "GESTION_URL", f"http://127.0.0.1:{srv.server_port}")
    with SessionLocal() as db:
        db.query(GestionEvento).filter(GestionEvento.estado != "enviado").update({"estado": "enviado"})
        ev = gestion.encolar(db, "liquidacion.periodo", {"prueba": 1})
        db.commit()
        eid = ev.id
    _Gestion.fallar = True  # gestión parada
    with SessionLocal() as db:
        assert gestion.procesar_cola(db)["fallidos"] == 1
        e = db.get(GestionEvento, eid)
        assert e.estado == "pendiente" and e.intentos == 1 and e.proximo > datetime.now() + timedelta(seconds=50)
        assert gestion.procesar_cola(db)["fallidos"] == 0  # aún no le toca
        for n in range(2, 5):
            assert gestion.procesar_cola(db, ahora=datetime.now() + timedelta(hours=3 * n))["fallidos"] == 1
        db.refresh(e)
        assert e.intentos == 4 and e.estado == "aviso"  # tras 1 min, 5 min, 30 min y 2 h: aviso
    _Gestion.fallar = False  # vuelve gestión: llega
    with SessionLocal() as db:
        assert gestion.procesar_cola(db, ahora=datetime.now() + timedelta(days=1))["enviados"] == 1
        assert db.get(GestionEvento, eid).estado == "enviado"
    assert [x["datos"] for x in _Gestion.recibidos if x["tipo"] == "liquidacion.periodo"] == [{"prueba": 1}]
    srv.shutdown()


def test_bloqueo_desde_gestion(client, admin, ids, monkeypatch):
    monkeypatch.setattr(gestion, "EVENTOS_SECRET", CLAVE)
    sae = ids["assets"]["SAE"]["id"]
    u = _aptos(client, admin, sae)[-61]
    r = _reserva(client, admin, u["id"], HOY + timedelta(days=5), HOY + timedelta(days=8))
    cuerpo = {"accion": "cerrar", "ot": "OT-PRUEBA-1", "unidad_pms_id": u["id"], "motivo": "Fuga de agua"}
    assert _firmado(client, "POST", "/api/gestion/bloqueo", cuerpo, clave="otra").status_code == 401
    assert _firmado(client, "POST", "/api/gestion/bloqueo", cuerpo, ts=time.time() - 600).status_code == 401
    x = _firmado(client, "POST", "/api/gestion/bloqueo", cuerpo)
    assert x.status_code == 200, x.text
    assert x.json()["estado"] == "cerrada" and x.json()["unidad_estado"] == "bloqueada"
    assert [a["id"] for a in x.json()["reservas_afectadas"]] == [r["id"]]
    with SessionLocal() as db:
        assert db.get(Reservation, r["id"]).estado == "confirmada"  # no se cancela
    assert _firmado(client, "POST", "/api/gestion/bloqueo", cuerpo).json()["ya_estaba"] is True
    assert client.post(f"/api/plano/unidades/{u['id']}/desbloquear", headers=admin, json={}).status_code == 400
    y = _firmado(client, "POST", "/api/gestion/bloqueo", {**cuerpo, "accion": "abrir"})
    assert y.json()["estado"] == "abierta" and y.json()["unidad_estado"] == "disponible"
    # huésped alojado: queda apuntado y se cierra al hacer el check-out
    v = _aptos(client, admin, sae)[-62]
    r2 = _reserva(client, admin, v["id"], HOY - timedelta(days=1), HOY + timedelta(days=1))
    with SessionLocal() as db:
        db.get(Reservation, r2["id"]).estado = "checkin"
        db.get(Unit, v["id"]).estado = "ocupada"
        db.commit()
    z = _firmado(client, "POST", "/api/gestion/bloqueo", {"accion": "cerrar", "ot": "OT-PRUEBA-2", "activo": "SAEROPUERTO",
                                                         "unidad_codigo": v["codigo"], "motivo": "Sin agua caliente"})
    assert z.json()["estado"] == "pendiente_huesped" and z.json()["unidad_estado"] == "ocupada"
    client.post(f"/api/turistico/reservas/{r2['id']}/checkout", headers=admin)
    with SessionLocal() as db:
        assert db.get(Unit, v["id"]).estado == "bloqueada"
    _firmado(client, "POST", "/api/gestion/bloqueo", {"accion": "abrir", "ot": "OT-PRUEBA-2", "unidad_pms_id": v["id"]})
    lista = _firmado(client, "GET", "/api/gestion/unidades", None)
    assert lista.status_code == 200 and any(x["id"] == v["id"] and x["activo"] == "SAEROPUERTO" for x in lista.json())


def test_liquidacion_por_canal(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    aptos = _aptos(client, admin, sae)
    assert client.put(f"/api/gestion/activos/{sae}/comisiones", headers=admin, json={"comisiones": {"booking": 15, "airbnb": 3}}).status_code == 200
    _reserva(client, admin, aptos[-63]["id"], date(2032, 1, 30), date(2032, 2, 3), canal="booking", importe=440)  # 2 de 4 noches en enero
    _reserva(client, admin, aptos[-64]["id"], date(2032, 1, 10), date(2032, 1, 12), canal="airbnb", importe=220)
    _reserva(client, admin, aptos[-65]["id"], date(2032, 1, 5), date(2032, 1, 6), canal="directo", importe=110)
    l = client.post("/api/gestion/liquidacion/previa", headers=admin, json={"asset_id": sae, "periodo": "2032-01"}).json()
    c = {x["canal"]: x for x in l["canales"]}
    assert c["booking"]["bruto"] == 220 and c["booking"]["comision"] == 33 and c["booking"]["neto"] == 187
    assert c["airbnb"]["comision"] == 6.6 and c["directo"]["comision"] == 0 and c["directo"]["base"] == 100
    assert l["totales"]["bruto"] == 550 and l["noches_ocupadas"] == 5 and l["activo"] == "SAEROPUERTO"
    assert client.post("/api/gestion/liquidacion/enviar", headers=admin, json={"asset_id": sae, "periodo": "2032-01"}).status_code == 200
    assert _eventos("liquidacion.periodo", periodo="2032-01")[-1].datos["totales"]["neto"] == 510.4


def test_pase_para_gestion(client, admin, ids, monkeypatch):
    sae = ids["assets"]["SAE"]["id"]
    u = _aptos(client, admin, sae)[-66]
    monkeypatch.setattr(gestion, "SSO_SECRET", "")
    r = client.get("/api/gestion/pase", headers=admin, params={"destino": "unidad", "unit_id": u["id"]}).json()
    assert r["nivel"] == 1 and "activo=SAEROPUERTO" in r["url"]
    monkeypatch.setattr(gestion, "SSO_SECRET", "clave-sso-de-prueba-0123456789abcdefghij")
    r = client.get("/api/gestion/pase", headers=admin, params={"destino": "unidad", "unit_id": u["id"]}).json()
    assert r["nivel"] == 2 and r["url"].startswith("https://gestion.inversiete.es/sso/pms?pase=")
    p = r["url"].split("pase=")[1].split("&")[0]
    f = r["url"].split("firma=")[1]
    assert hmac.compare_digest(hmac.new(b"clave-sso-de-prueba-0123456789abcdefghij", p.encode(), hashlib.sha256).hexdigest(), f)
    datos = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    assert datos["destino"] == "unidad" and datos["unidad"] == u["codigo"] and datos["activo"] == "SAEROPUERTO"
    assert len(datos["nonce"]) == 32 and datos["email"]
    assert client.get("/api/gestion/pase", headers=admin, params={"destino": "x"}).status_code == 400


def test_liquidacion_automatica_solo_si_esta_activada(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    with SessionLocal() as db:
        a = db.get(Asset, sae)
        a.comisiones_canal = {"booking": 15}
        db.commit()
        assert gestion.liquidaciones_automaticas(db, date(2032, 3, 5)) == 0
    assert client.put(f"/api/gestion/activos/{sae}/comisiones", headers=admin, json={"comisiones": {"booking": 15}, "auto": True}).status_code == 200
    with SessionLocal() as db:
        assert gestion.liquidaciones_automaticas(db, date(2032, 3, 5)) == 1
        assert gestion.liquidaciones_automaticas(db, date(2032, 3, 6)) == 0  # una sola vez por mes


def test_ot_por_roturas_al_dar_la_salida_llega_a_gestion(client, admin, ids):
    """Las OT por roturas que se abren al dar la salida (fianza) siguen existiendo y llegan a gestión como incidencia;
    lo que va al pedido de reposición no abre OT."""
    sae = ids["assets"]["SAE"]["id"]
    u = _aptos(client, admin, sae)[-68]
    r = _reserva(client, admin, u["id"], HOY - timedelta(days=3), HOY)
    with SessionLocal() as db:
        db.get(Reservation, r["id"]).estado = "checkin"
        db.commit()
    client.post(f"/api/turistico/reservas/{r['id']}/contrato", headers=admin, json={
        "fecha_firma": HOY.isoformat(), "fianza": 100, "motivo": ["turismo"], "acreditacion": ["dni"], "solo_guardar": True})
    x = client.post(f"/api/turistico/reservas/{r['id']}/checkout", headers=admin, json={"fianza": {"forma": "efectivo", "cargos": [
        {"codigo": "SAL01", "articulo": "Smart TV", "precio": 450, "ot": True},
        {"codigo": "MEN04", "articulo": "Vasos de agua / refresco", "cantidad": 2, "precio": 2.5, "pedido": True}]}})
    assert x.status_code == 200, x.text
    ots = x.json()["ots"]
    assert len(ots) == 1
    inc = _eventos("incidencia.reportada", ot_pms_id=ots[0])
    assert len(inc) == 1 and inc[0].datos["unidad_codigo"] == u["codigo"] and "Smart TV" in inc[0].datos["titulo"]
    assert len(_eventos("checkout", reserva_id=r["id"])) == 1
    with SessionLocal() as db:  # sin la orden automática «Revisión de salida»
        assert not db.query(WorkOrder).filter(WorkOrder.unit_id == u["id"], WorkOrder.titulo.like("Revisión de salida%")).count()
