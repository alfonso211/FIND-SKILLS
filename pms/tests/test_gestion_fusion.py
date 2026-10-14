"""Fusión con gestión (contrato «fusion1»): facturas recibidas con sus documentos, solo lectura de lo que ya está en
gestión, avisos de gestión aplicados sin eco e idempotentes, casilla por activo, inventario y botón «PMS» de gestión."""
import base64
import hashlib
import hmac
import json
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from app import fusion, gestion
from app.database import SessionLocal
from app.models import AuditLog, Expense, FusionDocumento, FusionEntrada, GestionEvento, Supplier

CLAVE = "clave-de-prueba-fusion-0123456789abcdef"
SSO = "clave-sso-de-prueba-fusion-0123456789"
HOY = date.today()
AYER = HOY - timedelta(days=1)


@pytest.fixture(autouse=True)
def _fusion_activa(monkeypatch):
    monkeypatch.setattr(fusion, "SYNC", True)
    monkeypatch.setattr(gestion, "EVENTOS_SECRET", CLAVE)
    monkeypatch.setattr(gestion, "SSO_SECRET", SSO)
    yield


@pytest.fixture()
def enviados(monkeypatch):
    """Lo que el PMS manda a gestión (gestión contesta 200 con su identificador)."""
    lista = []

    def enviar(ev):
        lista.append(json.loads(fusion.cuerpo(ev) if (ev.datos or {}).get("version") == "fusion1"
                                else json.dumps({"tipo": ev.tipo, "datos": ev.datos})))
        return True, json.dumps({"ok": True, "resultado": {"id": f"G-{ev.id}"}})
    monkeypatch.setattr(gestion, "_enviar", enviar)
    return lista


def _cola():
    with SessionLocal() as db:
        gestion.procesar_cola(db, limite=500)


def _pdf(texto: str) -> bytes:
    return b"%PDF-1.4\n% " + texto.encode() + b"\n%%EOF\n"


def _activar(client, admin, aid, valor=True):
    r = client.put(f"/api/gestion/fusion/activos/{aid}", headers=admin, json={"sync_facturas": valor})
    assert r.status_code == 200, r.text


def _factura(client, admin, aid, numero, total=121.0, pdf=None):
    gasto = {"fecha": AYER.isoformat(), "categoria": "mantenimiento", "concepto": f"Reparación {numero}",
             "total": total, "tipo_iva": 21, "proveedor": "Fontanería Fusión SL", "numero_factura": numero,
             "forma_pago": "transferencia", "naturaleza": "OPEX", "confirmar_duplicado": True}
    r = client.post("/api/documentos-recibidos", headers=admin,
                    data={"asset_id": str(aid), "tipo": "factura", "fecha": AYER.isoformat(), "gasto": json.dumps(gasto)},
                    files=[("ficheros", (f"{numero}.pdf", pdf or _pdf(numero), "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()["gasto"]


def _firmado(client, metodo, ruta, cuerpo: bytes = b"", firmar: bytes | None = None, ts=None, **headers):
    ts = str(int(ts if ts is not None else time.time()))
    return client.request(metodo, ruta, content=cuerpo, headers={
        "Content-Type": "application/json", "X-PMS-Fecha": ts,
        "X-PMS-Firma": gestion.firmar(CLAVE, ts, cuerpo if firmar is None else firmar), **headers})


def _aviso(client, ev: dict):
    return _firmado(client, "POST", "/api/gestion/eventos", json.dumps(ev).encode())


def _de(lista, tipo, pms_id=None):
    return [x for x in lista if x.get("tipo") == tipo and (pms_id is None or (x.get("datos") or {}).get("pms_id") == pms_id
                                                           or ((x.get("datos") or {}).get("vinculo") or {}).get("pms_id") == pms_id)]


def _eventos_de(gid):
    with SessionLocal() as db:
        return [e.tipo for e in db.query(GestionEvento).filter(GestionEvento.id_evento.like(f"pms-f1-%-{gid}-%"))]


# --------------------------------------------------------------------------- PMS → gestión
def test_recibida_con_dos_pdf_viaja_con_sus_documentos(client, admin, ids, enviados):
    sfl = ids["assets"]["SFL"]["id"]
    _activar(client, admin, sfl)
    p1, p2 = _pdf("factura FUS-1"), _pdf("albaran FUS-1")
    g = _factura(client, admin, sfl, "FUS-1", pdf=p1)
    r = client.post(f"/api/gestion/fusion/recibida/{g['id']}/documento", headers=admin, data={"categoria": "ALBARAN"},
                    files=[("ficheros", ("albaran.pdf", p2, "application/pdf"))])
    assert r.status_code == 201, r.text
    _cola()
    creada = _de(enviados, "factura_recibida.creada", f"gasto-{g['id']}")
    assert len(creada) == 1  # el adjunto añadido enseguida va en el mismo aviso
    assert not _de(enviados, "documento.adjuntado", f"gasto-{g['id']}")
    ev = creada[0]
    assert ev["version"] == "fusion1" and ev["origen"] == "PMS" and ev["activo"] == "SFLORIDA" and ev["sociedad"] == "INV"
    assert ev["id_evento_causa"] is None and ev["emitido"].endswith("Z")
    d = ev["datos"]
    assert d["numero"] == "FUS-1" and d["total"] == 121.0 and d["base"] == 100.0 and d["cuota_iva"] == 21.0
    assert d["estado"] == "REGISTRADA" and d["forma_pago"] == "TRANSFERENCIA" and d["categoria"] == "MANTENIMIENTO"
    docs = ev["documentos"]
    assert [x["categoria"] for x in docs] == ["FACTURA", "ALBARAN"]
    assert [x["sha256"] for x in docs] == [hashlib.sha256(p1).hexdigest(), hashlib.sha256(p2).hexdigest()]
    assert all(x["tipo_mime"] == "application/pdf" and x["tamano"] > 0 for x in docs)
    # gestión descarga cada documento con su firma; el PMS lo descifra y manda su sha256
    for x, contenido in zip(docs, (p1, p2)):
        r = _firmado(client, "GET", f"/api/gestion/documento/{x['doc_id']}", firmar=x["doc_id"].encode())
        assert r.status_code == 200, r.text
        assert r.content == contenido and r.headers["X-Sha256"] == x["sha256"]
    # sin firma → 401; desde internet (con X-Forwarded-For) → 403
    assert client.get(f"/api/gestion/documento/{docs[0]['doc_id']}").status_code == 401
    r = _firmado(client, "GET", f"/api/gestion/documento/{docs[0]['doc_id']}", firmar=docs[0]["doc_id"].encode(),
                 **{"X-Forwarded-For": "1.2.3.4"})
    assert r.status_code == 403
    # firma de otro documento → 401
    assert _firmado(client, "GET", f"/api/gestion/documento/{docs[0]['doc_id']}", firmar=b"rd-999999").status_code == 401


def test_factura_en_gestion_solo_lectura_y_pedir_correccion(client, admin, ids, enviados):
    sfl = ids["assets"]["SFL"]["id"]
    _activar(client, admin, sfl)
    g = _factura(client, admin, sfl, "FUS-2", total=242)
    # aún no ha llegado a gestión: se edita con normalidad (y el cambio sale en el mismo aviso de alta)
    base = {k: g[k] for k in ("fecha", "categoria", "concepto", "proveedor", "numero_factura", "tipo_iva",
                              "forma_pago", "naturaleza")}
    r = client.put(f"/api/gastos/{g['id']}", headers=admin, json={**base, "total": 363})
    assert r.status_code == 200, r.text
    _cola()
    assert _de(enviados, "factura_recibida.creada", f"gasto-{g['id']}")[0]["datos"]["total"] == 363.0
    gasto = client.get(f"/api/gastos?asset_id={sfl}", headers=admin).json()["gastos"]
    gasto = next(x for x in gasto if x["id"] == g["id"])
    assert gasto["fusion"]["gestionada"] is True
    # ya en gestión: el importe no se puede cambiar en el PMS
    r = client.put(f"/api/gastos/{g['id']}", headers=admin, json={**base, "total": 400})
    assert r.status_code == 409 and "INVERGESTION" in r.json()["detail"]
    assert client.delete(f"/api/gastos/{g['id']}", headers=admin).status_code == 409
    # lo que no es contable sí (el concepto)
    r = client.put(f"/api/gastos/{g['id']}", headers=admin, json={**base, "total": 363, "concepto": "Reparación grifo"})
    assert r.status_code == 200, r.text
    # «Pedir corrección» manda factura_recibida.actualizada con el importe corregido; el PMS no cambia nada
    r = client.post(f"/api/gestion/fusion/recibida/{g['id']}/correccion", headers=admin,
                    json={"cambios": {"total": 400, "base": 330.58, "cuota_iva": 69.42}, "nota": "Error de importe"})
    assert r.status_code == 200, r.text
    _cola()
    act = _de(enviados, "factura_recibida.actualizada", f"gasto-{g['id']}")
    assert act and act[-1]["datos"]["total"] == 400.0 and act[-1]["datos"]["gestion_id"]
    with SessionLocal() as db:
        assert float(db.get(Expense, g["id"]).total) == 363.0
    gasto = next(x for x in client.get(f"/api/gastos?asset_id={sfl}", headers=admin).json()["gastos"] if x["id"] == g["id"])
    assert gasto["fusion"]["solicitud"] == "correccion"
    # «Pedir anulación»
    r = client.post(f"/api/gestion/fusion/recibida/{g['id']}/anulacion", headers=admin, json={"motivo": "Duplicada"})
    assert r.status_code == 200, r.text
    _cola()
    an = _de(enviados, "factura_recibida.anulacion_pedida", f"gasto-{g['id']}")
    assert an and an[-1]["datos"]["motivo"] == "Duplicada"
    with SessionLocal() as db:
        assert db.get(Expense, g["id"]) is not None  # nunca anula por su cuenta


def test_aviso_de_gestion_cambia_el_importe_sin_eco(client, admin, ids, enviados):
    sfl = ids["assets"]["SFL"]["id"]
    _activar(client, admin, sfl)
    g = _factura(client, admin, sfl, "FUS-3", total=121)
    _cola()
    antes = _eventos_de(g["id"])
    ev = {"id_evento": f"invg-act-{g['id']}", "tipo": "factura_recibida.actualizada", "version": "fusion1",
          "emitido": datetime.now(timezone.utc).isoformat(), "origen": "GESTION", "id_evento_causa": None,
          "activo": "SFLORIDA", "sociedad": "INV", "documentos": [],
          "datos": {"pms_id": f"gasto-{g['id']}", "gestion_id": "REC-77", "proveedor_nombre": "Fontanería Fusión SL",
                    "numero": "FUS-3", "fecha_factura": AYER.isoformat(), "base": 200, "cuota_iva": 42, "total": 242,
                    "lineas": [{"base": 200, "tipo_iva": 21, "cuota_iva": 42}], "estado": "REGISTRADA",
                    "estado_pago": "PENDIENTE", "clase": "CAPEX", "respuesta": None}}
    r = _aviso(client, ev)
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    with SessionLocal() as db:
        x = db.get(Expense, g["id"])
        assert float(x.total) == 242.0 and float(x.base) == 200.0 and x.naturaleza == "CAPEX"
    assert _eventos_de(g["id"]) == antes  # no vuelve a gestión como eco
    _cola()
    assert not _de(enviados, "factura_recibida.actualizada", f"gasto-{g['id']}")
    # un aviso nuestro que vuelve (origen PMS) no se aplica
    eco = {**ev, "id_evento": f"eco-{g['id']}", "origen": "PMS", "datos": {**ev["datos"], "total": 999}}
    assert _aviso(client, eco).status_code == 200
    with SessionLocal() as db:
        assert float(db.get(Expense, g["id"]).total) == 242.0
        assert db.query(FusionEntrada).filter_by(id_evento=f"eco-{g['id']}").one().estado == "eco"


def test_mismo_aviso_cinco_veces_un_unico_cambio(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    _activar(client, admin, sfl)
    ev = {"id_evento": "invg-rec-5veces", "tipo": "factura_recibida.creada", "version": "fusion1",
          "emitido": datetime.now(timezone.utc).isoformat(), "origen": "GESTION", "id_evento_causa": None,
          "activo": "SFLORIDA", "sociedad": "INV", "documentos": [],
          "datos": {"pms_id": None, "gestion_id": "REC-500", "proveedor_nombre": "Electricidad Cinco SL",
                    "proveedor_nif": "B11223344", "numero": "E-5", "fecha_factura": AYER.isoformat(),
                    "base": 50, "cuota_iva": 10.5, "total": 60.5, "estado": "REGISTRADA", "forma_pago": "DOMICILIACION",
                    "categoria": "SUMINISTROS", "estado_pago": "PENDIENTE", "clase": "OPEX"}}
    respuestas = [_aviso(client, ev) for _ in range(5)]
    assert all(r.status_code == 200 for r in respuestas)
    pms_ids = {r.json().get("pms_id") for r in respuestas}
    assert len(pms_ids) == 1 and next(iter(pms_ids)).startswith("gasto-")  # el alta devuelve su identificador
    with SessionLocal() as db:
        assert db.query(Expense).filter(Expense.numero_factura == "E-5").count() == 1
        assert db.query(FusionEntrada).filter_by(id_evento="invg-rec-5veces").count() == 1
        assert sum(1 for a in db.query(AuditLog).filter_by(accion="aviso_de_gestion")
                   if (a.detalle or {}).get("id_evento") == "invg-rec-5veces") == 1
        g = db.query(Expense).filter(Expense.numero_factura == "E-5").one()
        assert g.forma_pago == "domiciliacion" and g.categoria == "suministros" and float(g.total) == 60.5
        assert db.query(Supplier).filter_by(nif="B11223344").count() == 1


def test_activo_sin_casilla_no_manda_nada(client, admin, ids, enviados):
    sae = ids["assets"]["SAE"]["id"]
    _activar(client, admin, sae, False)
    g = _factura(client, admin, sae, "FUS-SAE-1")
    assert _eventos_de(g["id"]) == []
    _cola()
    assert not [x for x in enviados if f"gasto-{g['id']}" in json.dumps(x)]
    # y un aviso de gestión de ese activo se guarda «sin_tratar» (200) sin aplicarse
    r = _aviso(client, {"id_evento": "invg-sae-1", "tipo": "factura_recibida.creada", "origen": "GESTION",
                        "activo": "SAEROPUERTO", "datos": {"numero": "X-1", "fecha_factura": AYER.isoformat(),
                                                           "base": 1, "cuota_iva": 0, "total": 1}, "documentos": []})
    assert r.status_code == 200
    with SessionLocal() as db:
        assert db.query(FusionEntrada).filter_by(id_evento="invg-sae-1").one().estado == "sin_tratar"
        assert not db.query(Expense).filter(Expense.numero_factura == "X-1").count()


# --------------------------------------------------------------------------- gestión → PMS: pagos y documentos
def test_pago_de_gestion_con_justificante_y_sha256(client, admin, ids, enviados, monkeypatch):
    sfl = ids["assets"]["SFL"]["id"]
    _activar(client, admin, sfl)
    g = _factura(client, admin, sfl, "FUS-4")
    _cola()
    bueno, malo = _pdf("justificante FUS-4"), _pdf("documento alterado")
    almacen = {"J-1": bueno, "J-2": malo}
    monkeypatch.setattr(fusion, "descargar", lambda doc_id: (almacen[doc_id], hashlib.sha256(almacen[doc_id]).hexdigest()))
    # pago de una factura que aún no está en el PMS → 400 (gestión lo reintenta)
    r = _aviso(client, {"id_evento": "invg-pag-x", "tipo": "pago.registrado", "origen": "GESTION", "activo": "SFLORIDA",
                        "datos": {"factura_pms_id": None, "factura_gestion_id": "NO-EXISTE", "fecha": HOY.isoformat(),
                                  "importe": 10}, "documentos": []})
    assert r.status_code == 400
    with SessionLocal() as db:
        assert not db.query(FusionEntrada).filter_by(id_evento="invg-pag-x").count()  # se podrá aplicar al reintentar
    r = _aviso(client, {"id_evento": "invg-pag-1", "tipo": "pago.registrado", "origen": "GESTION", "activo": "SFLORIDA",
                        "datos": {"pms_id": None, "gestion_id": "PAG-9", "factura_pms_id": f"gasto-{g['id']}",
                                  "fecha": HOY.isoformat(), "importe": 121, "forma_pago": "TRANSFERENCIA"},
                        "documentos": [{"doc_id": "J-1", "nombre": "justificante.pdf", "tipo_mime": "application/pdf",
                                        "tamano": len(bueno), "sha256": hashlib.sha256(bueno).hexdigest(),
                                        "categoria": "JUSTIFICANTE"}]})
    assert r.status_code == 200 and r.json()["pms_id"] == f"pago-{g['id']}", r.text
    with SessionLocal() as db:
        x = db.get(Expense, g["id"])
        assert x.pagado and x.fecha_pago == HOY and x.justificante_id
    # documento con la sha256 alterada: no se adjunta y queda «A revisar»
    r = _aviso(client, {"id_evento": "invg-doc-1", "tipo": "documento.adjuntado", "origen": "GESTION",
                        "activo": "SFLORIDA", "datos": {"vinculo": {"tipo": "factura_recibida",
                                                                    "pms_id": f"gasto-{g['id']}", "gestion_id": None}},
                        "documentos": [{"doc_id": "J-2", "nombre": "albaran.pdf", "tipo_mime": "application/pdf",
                                        "tamano": 10, "sha256": "0" * 64, "categoria": "ALBARAN"}]})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        f = db.query(FusionDocumento).filter_by(doc_id_gestion="J-2").one()
        assert f.estado == "a_revisar" and f.documento_id is None
    estado = client.get("/api/gestion/fusion/estado", headers=admin).json()
    assert any(x["motivo"] and "sha256" in x["motivo"] for x in estado["a_revisar"])
    # el pago que llega de gestión no se devuelve como eco
    _cola()
    assert not _de(enviados, "pago.registrado", f"pago-{g['id']}")


def test_pago_en_el_pms_viaja_con_su_justificante(client, admin, ids, enviados):
    sfl = ids["assets"]["SFL"]["id"]
    _activar(client, admin, sfl)
    g = _factura(client, admin, sfl, "FUS-5")
    just = _pdf("justificante FUS-5")
    r = client.post(f"/api/gastos/{g['id']}/pagar", headers=admin,
                    files=[("ficheros", ("justificante.pdf", just, "application/pdf"))])
    assert r.status_code == 200, r.text
    _cola()
    pago = _de(enviados, "pago.registrado", f"pago-{g['id']}")
    assert len(pago) == 1
    assert pago[0]["datos"]["factura_pms_id"] == f"gasto-{g['id']}" and pago[0]["datos"]["importe"] == 121.0
    assert [d["categoria"] for d in pago[0]["documentos"]] == ["JUSTIFICANTE"]
    assert pago[0]["documentos"][0]["sha256"] == hashlib.sha256(just).hexdigest()
    # el pago ya está en gestión: no se desmarca en el PMS (se pide la anulación)
    gasto = next(x for x in client.get(f"/api/gastos?asset_id={sfl}", headers=admin).json()["gastos"] if x["id"] == g["id"])
    base = {k: gasto[k] for k in ("fecha", "categoria", "concepto", "proveedor", "numero_factura", "tipo_iva",
                                  "forma_pago", "naturaleza", "total")}
    assert client.put(f"/api/gastos/{g['id']}", headers=admin, json={**base, "pagado": False}).status_code == 409
    assert client.post(f"/api/gestion/fusion/pago/{g['id']}/anulacion", headers=admin,
                       json={"motivo": "Pago duplicado"}).status_code == 200
    _cola()
    assert _de(enviados, "pago.anulado", f"pago-{g['id']}")[-1]["datos"]["motivo"] == "Pago duplicado"


def test_tipo_desconocido_y_sin_firma(client):
    assert client.post("/api/gestion/eventos", json={"id_evento": "x", "tipo": "y"}).status_code == 401
    r = _aviso(client, {"id_evento": "invg-raro-1", "tipo": "algo.nuevo", "origen": "GESTION", "datos": {}})
    assert r.status_code == 200 and r.json() == {"ok": True}
    with SessionLocal() as db:
        assert db.query(FusionEntrada).filter_by(id_evento="invg-raro-1").one().estado == "sin_tratar"
    assert _aviso(client, {"id_evento": "mal id con espacios", "tipo": "pago.registrado"}).status_code == 400


# --------------------------------------------------------------------------- carga inicial y SSO inverso
def test_inventario_firmado(client, admin, ids, enviados):
    sfl = ids["assets"]["SFL"]["id"]
    _activar(client, admin, sfl)
    _factura(client, admin, sfl, "FUS-INV-1")
    q = f"activo=SFLORIDA&desde={AYER.isoformat()}"
    r = _firmado(client, "GET", f"/api/gestion/fusion/inventario?{q}", firmar=q.encode())
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d) == {"recibidas", "emitidas", "pagos", "proveedores", "productos"}
    assert any(x["numero"] == "FUS-INV-1" and x["pms_id"].startswith("gasto-") for x in d["recibidas"])
    assert all(x["tipo"] in ("PAGO", "COBRO") for x in d["pagos"])
    assert client.get(f"/api/gestion/fusion/inventario?{q}").status_code == 401
    otra = f"activo=SFLORIDA&desde={(AYER - timedelta(days=400)).isoformat()}"
    assert _firmado(client, "GET", f"/api/gestion/fusion/inventario?{otra}", firmar=q.encode()).status_code == 401


def _pase(email, destino="recibida", id_=None, emitido=None, nonce=None):
    datos = {"email": email, "nombre": "Dirección", "usuario": "admin", "destino": destino, "id": id_,
             "activo": "SFLORIDA", "emitido": (emitido or datetime.now(timezone.utc)).isoformat(),
             "nonce": nonce or base64.b16encode(time.time_ns().to_bytes(8, "big")).decode() + "abcdefgh"}
    p = base64.urlsafe_b64encode(json.dumps(datos).encode()).decode().rstrip("=")
    return p, hmac.new(SSO.encode(), p.encode(), hashlib.sha256).hexdigest()


def test_sso_inverso_60_segundos_un_solo_uso(client, admin):
    p, f = _pase("admin@inversiete.com", "recibida", "gasto-1")
    r = client.get(f"/sso/gestion?pase={p}&firma={f}", follow_redirects=False)
    assert r.status_code == 303, r.text
    loc = r.headers["location"]
    assert loc.startswith("/#sso=") and "destino=recibida" in loc and "id=gasto-1" in loc
    token = loc.split("sso=")[1].split("&")[0]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["email"] == "admin@inversiete.com"
    assert client.get(f"/sso/gestion?pase={p}&firma={f}", follow_redirects=False).status_code == 403  # un solo uso
    p2, f2 = _pase("admin@inversiete.com", emitido=datetime.now(timezone.utc) - timedelta(seconds=90))
    assert client.get(f"/sso/gestion?pase={p2}&firma={f2}", follow_redirects=False).status_code == 403  # caducado
    p3, _ = _pase("admin@inversiete.com")
    assert client.get(f"/sso/gestion?pase={p3}&firma={'0' * 64}", follow_redirects=False).status_code == 403
    p4, f4 = _pase("nadie@inversiete.com")
    assert client.get(f"/sso/gestion?pase={p4}&firma={f4}", follow_redirects=False).status_code == 403


# --------------------------------------------------------------------------- emitidas, cobros, proveedores y catálogo
def test_emitida_con_pdf_y_cobro(client, admin, ids, enviados):
    from conftest import domicilio_fiscal
    domicilio_fiscal(client, admin)
    sfl = ids["assets"]["SFL"]["id"]
    _activar(client, admin, sfl)
    f = client.post("/api/facturas/servicios", headers=admin, json={
        "asset_id": sfl, "cliente": {"nombre": "Empresa Fusión SL", "nif": "B11223344", "domicilio": "Calle 1, Madrid"},
        "lineas": [{"concepto": "Plaza de garaje", "precio": 121}], "forma_pago": "transferencia"})
    assert f.status_code == 201, f.text
    f = f.json()
    _cola()
    em = _de(enviados, "factura_emitida.emitida", f"factura-{f['id']}")
    assert len(em) == 1
    d = em[0]["datos"]
    assert d["serie"] == f["serie"] and d["numero"] == f["codigo"].replace("/", "-") and d["total"] == 121.0
    assert d["tipo_factura"] == "COMPLETA" and d["lineas"][0]["tipo_iva"] == 21 and em[0]["sociedad"] == "INV"
    doc = em[0]["documentos"][0]
    assert doc["categoria"] == "FACTURA" and doc["doc_id"].startswith("fd-")
    r = _firmado(client, "GET", f"/api/gestion/documento/{doc['doc_id']}", firmar=doc["doc_id"].encode())
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert hashlib.sha256(r.content).hexdigest() == doc["sha256"] == r.headers["X-Sha256"]  # la misma copia siempre
    if f.get("cobro") == "cobrada":
        cobro = _de(enviados, "cobro.registrado", f"cobro-{f['id']}")
        assert len(cobro) == 1 and cobro[0]["datos"]["factura_pms_id"] == f"factura-{f['id']}"


def test_proveedor_y_producto_en_los_dos_sentidos(client, admin, ids, enviados):
    sfl = ids["assets"]["SFL"]["id"]
    _activar(client, admin, sfl)
    r = client.post("/api/proveedores", headers=admin, json={"nombre": "Climatización Fusión SL", "nif": "B76543214",
                                                              "pais": "España"})
    assert r.status_code == 201, r.text
    s = r.json()
    _cola()
    alta = _de(enviados, "proveedor.alta", f"proveedor-{s['id']}")
    assert len(alta) == 1 and alta[0]["datos"]["nif"] == "B76543214" and alta[0]["activo"] is None
    # ya en gestión: el NIF y el nombre solo se cambian allí; gestión manda (IBAN incluido)
    body = {"nombre": "Climatización Fusión SL", "nif": "B76543214", "pais": "España", "email": "a@b.es"}
    assert client.put(f"/api/proveedores/{s['id']}", headers=admin, json={**body, "nombre": "Otro nombre"}).status_code == 409
    assert client.put(f"/api/proveedores/{s['id']}", headers=admin, json=body).status_code == 200
    r = _aviso(client, {"id_evento": "invg-prov-1", "tipo": "proveedor.actualizado", "origen": "GESTION", "activo": None,
                        "datos": {"pms_id": f"proveedor-{s['id']}", "nif": "B76543214", "nombre": "Climatización Fusión S.L.",
                                  "iban": "ES12 3456 7890 1234 5678 9012", "forma_pago": "TRANSFERENCIA"}, "documentos": []})
    assert r.status_code == 200 and r.json()["pms_id"] == f"proveedor-{s['id']}"
    with SessionLocal() as db:
        x = db.get(Supplier, s["id"])
        assert x.nombre == "Climatización Fusión S.L." and x.iban == "ES1234567890123456789012"
    _cola()
    assert len(_de(enviados, "proveedor.actualizado", f"proveedor-{s['id']}")) == 1  # el del PUT; el de gestión no vuelve
    # catálogo: alta en gestión → producto en el PMS
    r = _aviso(client, {"id_evento": "invg-prod-1", "tipo": "producto.alta", "origen": "GESTION", "activo": None,
                        "datos": {"referencia": "INV-FUS-1", "articulo": "Termostato", "familia": "Climatización",
                                  "unidad": "ud"}, "documentos": []})
    assert r.status_code == 200 and r.json()["pms_id"].startswith("producto-")
    prods = client.get("/api/productos?q=INV-FUS-1", headers=admin).json()
    lista = prods if isinstance(prods, list) else prods.get("productos", [])
    assert any(p["referencia"] == "INV-FUS-1" and p["familia"] == "CLIMATIZACIÓN" for p in lista)
