"""Calendario común PMS ↔ gestión (1.66, contrato «fusion1», tipos calendario.*): alta, cambio y cancelación en los
dos sentidos, idempotencia, sin eco, conflicto (manda gestión), vencimientos y fiscal solo para administración y
dirección (pantalla y Outlook), solo lectura, agenda privada que no sale, casilla apagada = sin tratar, enlace .ics
válido, cambio de enlace y corte por exceso de peticiones. Datos ZZ-PRUEBA-CAL en 2031, borrados al terminar."""
import json
import time
import uuid

import icalendar
import pytest
from sqlalchemy import delete, select

from app import calendario_comun as calendario, gestion
from app.database import SessionLocal
from app.models import (AgendaEvent, Ajuste, AuditLog, CalendarioEnlace, CalendarioEntrada, CleaningTask, FusionEntrada,
                        GestionEvento, Unit)
from conftest import login

CLAVE = "clave-de-prueba-calendario-0123456789abcdef"
Z = "ZZ-PRUEBA-CAL"


@pytest.fixture(autouse=True)
def _pasarela(monkeypatch):
    monkeypatch.setattr(gestion, "EVENTOS_SECRET", CLAVE)
    yield


@pytest.fixture(scope="module", autouse=True)
def _borrar_al_terminar():
    yield
    with SessionLocal() as db:  # todo lo de prueba fuera: entradas, citas, enlaces, cola y avisos recibidos
        ids = list(db.scalars(select(AgendaEvent.id).where(AgendaEvent.titulo.like(f"{Z}%"))))
        db.execute(delete(CalendarioEntrada).where(CalendarioEntrada.titulo.like(f"{Z}%") |
                                                   CalendarioEntrada.uid.like("INVG-ZZ%") |
                                                   CalendarioEntrada.uid.like("PMS-LIM-%")))
        db.execute(delete(GestionEvento).where(GestionEvento.id_evento.like("cal-%")))
        db.execute(delete(FusionEntrada).where(FusionEntrada.id_evento.like("ZZCAL-%")))
        db.execute(delete(CalendarioEnlace))
        db.execute(delete(CleaningTask).where(CleaningTask.nota.like(f"{Z}%")))
        for e in db.scalars(select(AgendaEvent).where(AgendaEvent.id.in_(ids or [-1]))):
            db.delete(e)
        db.execute(delete(Ajuste).where(Ajuste.clave == calendario.AJUSTE))
        db.commit()
        assert not db.scalar(select(CalendarioEntrada.id).where(CalendarioEntrada.titulo.like(f"{Z}%")))


def _casilla(client, admin, valor):
    r = client.put("/api/calendario/config", headers=admin, json={"activo": valor})
    assert r.status_code == 200, r.text
    return r.json()


def _usuario(client, admin, ids, email, rol, codigo="SFL", sociedad=None):
    asig = {"role_id": ids["roles"][rol], **({"company_id": ids["companies"][sociedad]} if sociedad
                                            else {"asset_id": ids["assets"][codigo]["id"]})}
    r = client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": f"{rol} calendario", "password": "Provisional1", "asignaciones": [asig]})
    assert r.status_code == 201, r.text
    h = login(client, email, "Provisional1")
    r = client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "CalendarioComun2031!"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def gente(client, admin, ids):
    return {"recepcion": _usuario(client, admin, ids, "recepcion.cal@inversiete.com", "Recepción"),
            "tecnico": _usuario(client, admin, ids, "tecnico.cal@inversiete.es", "Técnico Mantenimiento"),
            "administracion": _usuario(client, admin, ids, "admon.cal@inversiete.es", "Administración / Finanzas"),
            "gestor": _usuario(client, admin, ids, "gestor.cal@inversiete.es", "Gestor Alquiler Residencial"),
            "dir_cdc": _usuario(client, admin, ids, "dircdc.cal@inversiete.es", "Dirección Sociedad",
                                sociedad="COMERCIAL DEL CAMPO S.A.")}


def _aviso(client, tipo, datos, ide=None, origen="GESTION"):
    cuerpo = json.dumps({"id_evento": ide or f"ZZCAL-{uuid.uuid4().hex}", "tipo": tipo, "version": "fusion1",
                         "emitido": "2031-01-01T00:00:00Z", "origen": origen, "activo": datos.get("activo"),
                         "sociedad": datos.get("sociedad"), "datos": datos, "documentos": []}).encode()
    ts = str(int(time.time()))
    return client.post("/api/gestion/eventos", content=cuerpo, headers={
        "Content-Type": "application/json", "X-PMS-Fecha": ts, "X-PMS-Firma": gestion.firmar(CLAVE, ts, cuerpo)})


def _entrada(uid, version=1, **kw):
    d = {"uid": uid, "version": version, "tipo": "CITA", "subtipo": "reunion", "titulo": f"{Z} reunión de obra",
         "descripcion": "Revisión", "lugar": "Oficina", "inicio": "2031-03-10T10:00", "fin": "2031-03-10T11:00",
         "todo_el_dia": False, "activo": "SFLORIDA", "unidad": None, "sociedad": "CDC",
         "responsables": ["alfonso@inversiete.com"], "invitados": ["recepcion.cal@inversiete.es"], "estado": "PENDIENTE",
         "recordatorio": 30, "repeticion": None, "repetir_hasta": None, "importe": None, "prioridad": "normal",
         "origen": "GESTION", "origen_col": "agenda", "origen_id": 7, "editable_en": "AMBOS", "solo_lectura": False,
         "roles": None, "url_gestion": "https://gestion.inversiete.es/agenda/7"}
    d.update(kw)
    return d


def _fiscal(uid="INVG-ZZ-FIS-1", version=1):
    return _entrada(uid, version, tipo="FISCAL", subtipo="modelo_303", titulo=f"{Z} IVA 1T", inicio="2031-04-20", sociedad="INV",
                    fin="2031-04-20", todo_el_dia=True, importe=12345.67, editable_en="GESTION", solo_lectura=True,
                    roles=["superadmin", "administracion", "direccion"], responsables=[], invitados=[],
                    recordatorio=None)


def _agenda(client, h, desde="2031-01-01", hasta="2031-12-31"):
    r = client.get("/api/calendario/agenda", headers=h, params={"desde": desde, "hasta": hasta})
    assert r.status_code == 200, r.text
    return r.json()


def _cola(tipo=None):
    with SessionLocal() as db:
        q = select(GestionEvento).where(GestionEvento.id_evento.like("cal-%"))
        return [(e.tipo, e.datos["datos"]["uid"], e.datos["datos"]["version"], e.estado, e.datos)
                for e in db.scalars(q.order_by(GestionEvento.id)) if tipo is None or e.tipo == tipo]


def test_casilla_apagada_sin_tratar(client, admin, gente):
    assert _casilla(client, admin, False)["activo"] is False
    assert client.put("/api/calendario/config", headers=gente["administracion"], json={"activo": True}).status_code == 403
    r = _aviso(client, "calendario.creada", _entrada("INVG-ZZ-OFF"), ide="ZZCAL-off-1")
    assert r.status_code == 200 and r.json()["ok"] is True
    with SessionLocal() as db:
        assert db.scalar(select(FusionEntrada.estado).where(FusionEntrada.id_evento == "ZZCAL-off-1")) == "sin_tratar"
        assert db.scalar(select(CalendarioEntrada.id).where(CalendarioEntrada.uid == "INVG-ZZ-OFF")) is None
    antes = len(_cola())
    r = client.post("/api/agenda", headers=admin, json={"tipo": "reunion", "titulo": f"{Z} apagada", "inicio": "2031-02-02T09:00",
                                                         "visibilidad": "publica"})
    assert r.status_code == 201 and len(_cola()) == antes  # con la casilla apagada no se manda nada
    assert client.get("/api/calendario/config", headers=admin).json()["sin_tratar"] >= 1


def test_gestion_a_pms_alta_cambio_cancelacion_e_idempotencia(client, admin, gente):
    _casilla(client, admin, True)
    antes = len(_cola())
    assert _aviso(client, "calendario.creada", _entrada("INVG-ZZ-1"), ide="ZZCAL-1-v1").status_code == 200
    vis = [x for x in _agenda(client, gente["recepcion"]) if x["uid"] == "INVG-ZZ-1"]  # invitada por correo (.com = .es)
    assert len(vis) == 1 and vis[0]["titulo"] == f"{Z} reunión de obra" and vis[0]["editable"]
    assert not [x for x in _agenda(client, gente["tecnico"]) if x["uid"] == "INVG-ZZ-1"]  # cita: solo invitados
    # el mismo aviso otra vez (mismo id_evento) o con la misma versión: un solo cambio
    assert _aviso(client, "calendario.creada", _entrada("INVG-ZZ-1"), ide="ZZCAL-1-v1").status_code == 200
    r = _aviso(client, "calendario.actualizada", _entrada("INVG-ZZ-1", 1, titulo=f"{Z} NO"), ide="ZZCAL-1-v1-bis")
    assert r.json().get("ignorado") == "version"
    _aviso(client, "calendario.actualizada", _entrada("INVG-ZZ-1", 2, titulo=f"{Z} reunión movida",
                                                      inicio="2031-03-11T12:00", fin="2031-03-11T13:00"))
    x = [x for x in _agenda(client, gente["recepcion"]) if x["uid"] == "INVG-ZZ-1"][0]
    assert x["titulo"] == f"{Z} reunión movida" and x["ocurrencia"].startswith("2031-03-11T12:00") and x["version"] == 2
    _aviso(client, "calendario.cancelada", _entrada("INVG-ZZ-1", 3, titulo=f"{Z} reunión movida"))
    x = [x for x in _agenda(client, gente["recepcion"]) if x["uid"] == "INVG-ZZ-1"][0]
    assert x["estado"] == "CANCELADA" and not x["editable"]  # no se borra: Outlook la quita
    assert len(_cola()) == antes  # sin eco: lo de gestión no vuelve a gestión
    with SessionLocal() as db:
        assert db.scalar(select(CalendarioEntrada).where(CalendarioEntrada.uid == "INVG-ZZ-1")).version == 3
        assert db.scalar(select(AuditLog.id).where(AuditLog.accion == "aviso_de_gestion",
                                                   AuditLog.detalle["id_evento"].as_string() == "ZZCAL-1-v1"))
    # mantenimiento: según el activo del usuario
    _aviso(client, "calendario.creada", _entrada("INVG-ZZ-OT", tipo="OT", subtipo=None, titulo=f"{Z} OT caldera",
                                                 editable_en="GESTION", responsables=[], invitados=[]))
    assert [x for x in _agenda(client, gente["tecnico"]) if x["uid"] == "INVG-ZZ-OT"]
    _aviso(client, "calendario.creada", _entrada("INVG-ZZ-OT2", tipo="OT", subtipo=None, activo="SAEROPUERTO",
                                                 titulo=f"{Z} OT otro activo", editable_en="GESTION"))
    assert not [x for x in _agenda(client, gente["tecnico"]) if x["uid"] == "INVG-ZZ-OT2"]


def test_fiscal_solo_administracion_y_direccion(client, admin, gente):
    _casilla(client, admin, True)
    _aviso(client, "calendario.creada", _fiscal())
    _aviso(client, "calendario.creada", _entrada("INVG-ZZ-RES", titulo=f"{Z} comité", invitados=["recepcion.cal@inversiete.es"],
                                                 roles=["direccion", "administracion"]))
    for quien in ("recepcion", "tecnico"):
        uids = {x["uid"] for x in _agenda(client, gente[quien])}
        assert "INVG-ZZ-FIS-1" not in uids and "INVG-ZZ-RES" not in uids, quien
    for h in (admin, gente["administracion"]):
        f = [x for x in _agenda(client, h) if x["uid"] == "INVG-ZZ-FIS-1"][0]
        assert f["importe"] == 12345.67 and f["solo_lectura"] and not f["editable"]
        assert f["url_gestion"].startswith("https://")


def test_solo_lectura_no_se_edita_y_fiscal_nunca_sale(client, admin, gente):
    _casilla(client, admin, True)
    _aviso(client, "calendario.creada", _entrada("INVG-ZZ-RO", titulo=f"{Z} solo gestión", editable_en="GESTION"))
    with SessionLocal() as db:
        ro = db.scalar(select(CalendarioEntrada).where(CalendarioEntrada.uid == "INVG-ZZ-RO"))
        fis = db.scalar(select(CalendarioEntrada).where(CalendarioEntrada.uid == "INVG-ZZ-FIS-1"))
        assert ro.solo_lectura and fis.solo_lectura
        with pytest.raises(ValueError):
            calendario.encolar(db, fis, "calendario.actualizada")
    cambio = {"titulo": f"{Z} intento", "inicio": "2031-03-12T10:00", "estado": "PENDIENTE"}
    assert client.put(f"/api/calendario/entradas/{ro.id}", headers=gente["recepcion"], json=cambio).status_code == 403
    assert client.put(f"/api/calendario/entradas/{fis.id}", headers=admin, json=cambio).status_code == 403
    assert client.put(f"/api/calendario/entradas/{fis.id}", headers=gente["recepcion"], json=cambio).status_code == 404
    assert not [x for x in _cola() if x[1] in ("INVG-ZZ-RO", "INVG-ZZ-FIS-1")]


def test_pms_a_gestion_alta_cambio_cancelacion_y_privada(client, admin, gente, monkeypatch):
    _casilla(client, admin, True)
    r = client.post("/api/agenda", headers=admin, json={"tipo": "recordatorio", "titulo": f"{Z} privada",
                                                         "inicio": "2031-05-05T09:00", "visibilidad": "privada"})
    priv = r.json()["id"]
    assert not [x for x in _cola() if x[1] == f"PMS-AG-{priv}"]  # la privada no sale
    uid_rec = client.get("/api/auth/me", headers=gente["recepcion"]).json()["id"]
    r = client.post("/api/agenda", headers=admin, json={
        "tipo": "reunion", "titulo": f"{Z} reunión del PMS", "inicio": "2031-05-06T10:00", "fin": "2031-05-06T11:00",
        "visibilidad": "compartida", "participantes": [uid_rec], "aviso_min": 15})
    eid = r.json()["id"]
    uid = f"PMS-AG-{eid}"
    alta = [x for x in _cola() if x[1] == uid]
    assert [(t, v) for t, _, v, _, _ in alta] == [("calendario.creada", 1)]
    d = alta[0][4]
    assert d["origen"] == "PMS" and d["version"] == "fusion1" and d["datos"]["tipo"] == "CITA"
    assert d["datos"]["subtipo"] == "reunion" and d["datos"]["invitados"] == ["recepcion.cal@inversiete.es"]
    assert d["datos"]["inicio"] == "2031-05-06T10:00" and d["datos"]["editable_en"] == "AMBOS"
    client.put(f"/api/agenda/{eid}", headers=admin, json={
        "tipo": "reunion", "titulo": f"{Z} reunión del PMS (cambio)", "inicio": "2031-05-06T12:00",
        "visibilidad": "compartida", "participantes": [uid_rec]})
    assert client.delete(f"/api/agenda/{eid}", headers=admin).status_code == 200
    assert [(t, v) for t, u, v, _e, _d in _cola() if u == uid] == [
        ("calendario.creada", 1), ("calendario.actualizada", 2), ("calendario.cancelada", 3)]
    # envío en orden por uid: si gestión rechaza el primero, los siguientes de la misma entrada esperan
    enviados = []

    def enviar(ev):
        if not ev.tipo.startswith("calendario."):
            return True, "{}"  # el resto de avisos de la cola (otras pruebas) no interesan aquí
        enviados.append((ev.tipo, ev.datos["datos"]["uid"], ev.datos["datos"]["version"]))
        return (False, "HTTP 400: prueba") if ev.datos["datos"]["version"] == 1 and ev.datos["datos"]["uid"] == uid \
            else (True, '{"ok": true}')
    monkeypatch.setattr(gestion, "_enviar", enviar)
    with SessionLocal() as db:
        gestion.procesar_cola(db, limite=500)
    assert [x for x in enviados if x[1] == uid] == [("calendario.creada", uid, 1)]
    monkeypatch.setattr(gestion, "_enviar", lambda ev: (ev.tipo.startswith("calendario.") and enviados.append(
        (ev.tipo, ev.datos["datos"]["uid"], ev.datos["datos"]["version"]))) or (True, "{}"))
    with SessionLocal() as db:
        for ev in db.scalars(select(GestionEvento).where(GestionEvento.id_evento.like("cal-%"))):
            ev.proximo = ev.creado
        db.commit()
        gestion.procesar_cola(db, limite=500)
        assert db.scalar(select(CalendarioEntrada).where(CalendarioEntrada.uid == uid)).cambio_local is False
    assert [x[2] for x in enviados if x[1] == uid] == [1, 1, 2, 3]
    assert all(x[0] != "calendario.creada" or not x[1].startswith("INVG-") for x in enviados)


def test_conflicto_manda_gestion(client, admin, gente):
    _casilla(client, admin, True)
    _aviso(client, "calendario.creada", _entrada("INVG-ZZ-CONF", titulo=f"{Z} visita"))
    cid = [x for x in _agenda(client, gente["recepcion"]) if x["uid"] == "INVG-ZZ-CONF"][0]["id"]
    r = client.put(f"/api/calendario/entradas/{cid}", headers=gente["recepcion"], json={
        "titulo": f"{Z} visita (cambio del PMS)", "inicio": "2031-03-10T16:00", "estado": "PENDIENTE"})
    assert r.status_code == 200 and r.json()["version"] == 2
    assert [(t, v, e) for t, u, v, e, _ in _cola() if u == "INVG-ZZ-CONF"] == [("calendario.actualizada", 2, "pendiente")]
    _aviso(client, "calendario.actualizada", _entrada("INVG-ZZ-CONF", 3, titulo=f"{Z} visita (gestión)"))
    with SessionLocal() as db:
        c = db.scalar(select(CalendarioEntrada).where(CalendarioEntrada.uid == "INVG-ZZ-CONF"))
        assert c.titulo == f"{Z} visita (gestión)" and c.version == 3 and not c.cambio_local
        assert c.historial[-1]["datos"]["titulo"] == f"{Z} visita (cambio del PMS)"
        assert c.historial[-1]["pendiente_de_enviar"] is True
    assert [(v, e) for t, u, v, e, _ in _cola() if u == "INVG-ZZ-CONF"] == [(2, "descartado")]


def test_limpieza_programada_sale(client, admin, ids):
    _casilla(client, admin, True)
    sfl = ids["assets"]["SFL"]["id"]
    from datetime import date
    with SessionLocal() as db:
        u = db.scalar(select(Unit).where(Unit.asset_id == sfl).limit(1))
        t = CleaningTask(asset_id=sfl, unit_id=u.id, fecha=date(2031, 6, 1), tipo="extra", nota=f"{Z} limpieza a fondo")
        db.add(t)
        db.commit()
        tid = t.id
        t.estado = "anulada"
        db.commit()
    lim = [(tp, v, d["datos"]) for tp, uid, v, _, d in _cola() if uid == f"PMS-LIM-{tid}"]
    assert [(tp, v) for tp, v, _ in lim] == [("calendario.creada", 1), ("calendario.cancelada", 2)]
    assert lim[0][2]["tipo"] == "LIMPIEZA" and lim[0][2]["activo"] == "SFLORIDA" and lim[0][2]["editable_en"] == "PMS"
    assert lim[0][2]["inicio"] == "2031-06-01" and lim[0][2]["todo_el_dia"] and lim[0][2]["unidad"] == u.codigo


def test_outlook_ics(client, admin, gente):
    _casilla(client, admin, True)
    _aviso(client, "calendario.creada", _fiscal("INVG-ZZ-FIS-2"))
    _aviso(client, "calendario.creada", _entrada("INVG-ZZ-ICS", titulo=f"{Z} reunión con un título muy largo para "
                                                 "comprobar que las líneas se pliegan a 75 octetos, con tildes: áéíóú ñ",
                                                 repeticion="laborables", repetir_hasta="2031-03-31"))
    assert client.get("/api/calendario/outlook", headers=admin).json()["existe"] is False
    r = client.post("/api/calendario/outlook", headers=admin)
    assert r.status_code == 201
    url = r.json()["url"]
    assert r.json()["webcal"].startswith("webcal://") and "/cal/" in url
    ruta = url[url.index("/cal/"):]
    clave = ruta[5:-4]
    with SessionLocal() as db:  # en la base solo la sha256
        assert not db.scalar(select(CalendarioEnlace.id).where(CalendarioEnlace.clave_sha256 == clave))
    resp = client.get(ruta)
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/calendar")
    crudo = resp.content
    assert all(len(linea) <= 75 for linea in crudo.split(b"\r\n")) and b"\r\n " in crudo
    cal = icalendar.Calendar.from_ical(crudo)
    ev = {str(e["UID"]): e for e in cal.walk("VEVENT")}
    fis = ev["INVG-ZZ-FIS-2@pms.inversiete.es"]
    assert "12.345,67" not in str(fis["SUMMARY"])  # importes ocultos por defecto
    assert fis["DTSTART"].params.get("VALUE") == "DATE" and str(fis["DTEND"].to_ical().decode()) == "20310421"
    assert [str(a["TRIGGER"].to_ical().decode()) for a in fis.walk("VALARM")] == ["-PT15H"]
    rep = ev["INVG-ZZ-ICS@pms.inversiete.es"]
    assert "BYDAY=MO,TU,WE,TH,FR" in rep["RRULE"].to_ical().decode() and rep["DTSTART"].to_ical().decode().endswith("Z")
    assert int(ev["INVG-ZZ-1@pms.inversiete.es"]["SEQUENCE"]) == 3 and str(ev["INVG-ZZ-1@pms.inversiete.es"]["STATUS"]) == "CANCELLED"
    assert client.put("/api/calendario/outlook", headers=admin, json={"mostrar_importes": True}).status_code == 200
    ev2 = {str(e["UID"]): e for e in icalendar.Calendar.from_ical(client.get(ruta).content).walk("VEVENT")}
    assert str(ev2["INVG-ZZ-FIS-2@pms.inversiete.es"]["SUMMARY"]).endswith("· 12.345,67 €")
    # recepción: su Outlook nunca lleva fiscal ni importes
    rec = client.post("/api/calendario/outlook", headers=gente["recepcion"]).json()["url"]
    assert client.put("/api/calendario/outlook", headers=gente["recepcion"], json={"mostrar_importes": True}).status_code == 403
    txt = client.get(rec[rec.index("/cal/"):]).content.decode()
    assert "INVG-ZZ-FIS" not in txt and "IVA 1T" not in txt and "INVG-ZZ-ICS@" in txt
    # cambiar el enlace: el anterior da 404
    nueva = client.post("/api/calendario/outlook", headers=admin).json()["url"]
    assert client.get(ruta).status_code == 404 and client.get(nueva[nueva.index("/cal/"):]).status_code == 200
    assert client.get("/cal/no-existe.ics").status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog.id).where(AuditLog.accion == "acceso_ics", AuditLog.detalle["ip"].as_string() != ""))
    # corte a las 61 peticiones en la hora
    ruta2 = nueva[nueva.index("/cal/"):]
    codigos = [client.get(ruta2).status_code for _ in range(61)]
    assert codigos[:59].count(200) == 59 and codigos[-1] == 429  # ya hubo 1 petición antes
    assert client.delete("/api/calendario/outlook", headers=admin).status_code == 200
    assert client.get(ruta2).status_code == 404


def _ics(client, h):
    url = client.post("/api/calendario/outlook", headers=h).json()["url"]
    cal = icalendar.Calendar.from_ical(client.get(url[url.index("/cal/"):]).content)
    return {str(e["UID"]).split("@")[0] for e in cal.walk("VEVENT")}


def test_fiscal_no_lo_ve_quien_solo_tiene_finanzas_ver(client, admin, gente):
    """El Gestor Alquiler Residencial tiene «finanzas.ver», pero no es dirección ni administración."""
    _casilla(client, admin, True)
    _aviso(client, "calendario.creada", _fiscal("INVG-ZZ-FIS-G"))
    assert "INVG-ZZ-FIS-G" not in {x["uid"] for x in _agenda(client, gente["gestor"])}
    assert "INVG-ZZ-FIS-G" not in _ics(client, gente["gestor"])
    assert client.get("/api/calendario/outlook", headers=gente["gestor"]).json()["puede_importes"] is False
    r = client.put("/api/calendario/outlook", headers=gente["gestor"], json={"mostrar_importes": True})
    assert r.status_code == 403
    assert "INVG-ZZ-FIS-G" in {x["uid"] for x in _agenda(client, gente["administracion"])}  # INV: su sociedad


def test_financiero_solo_de_sus_sociedades_y_activos(client, admin, gente):
    """Dirección de Comercial del Campo: su fiscal sí, el de INVERSIETE no; sin sociedad, por el activo."""
    _casilla(client, admin, True)
    _aviso(client, "calendario.creada", _fiscal("INVG-ZZ-AMB-CDC") | {"sociedad": "CDC", "activo": None})
    _aviso(client, "calendario.creada", _fiscal("INVG-ZZ-AMB-INV") | {"sociedad": "INV", "activo": None})
    _aviso(client, "calendario.creada", _fiscal("INVG-ZZ-AMB-BAB") | {"sociedad": None, "activo": "BABILONIA35"})
    _aviso(client, "calendario.creada", _fiscal("INVG-ZZ-AMB-SFL") | {"sociedad": None, "activo": "SFLORIDA"})
    _aviso(client, "calendario.creada", _fiscal("INVG-ZZ-AMB-NADA") | {"sociedad": None, "activo": None})
    amb = {"INVG-ZZ-AMB-CDC", "INVG-ZZ-AMB-INV", "INVG-ZZ-AMB-BAB", "INVG-ZZ-AMB-SFL", "INVG-ZZ-AMB-NADA"}
    esperado = {
        "dir_cdc": {"INVG-ZZ-AMB-CDC", "INVG-ZZ-AMB-BAB"},
        "administracion": {"INVG-ZZ-AMB-INV", "INVG-ZZ-AMB-SFL"},  # rol en Suite Florida (de INVERSIETE)
    }
    for quien, uids in esperado.items():
        assert {x["uid"] for x in _agenda(client, gente[quien])} & amb == uids, quien  # pantalla
        assert _ics(client, gente[quien]) & amb == uids, quien  # Outlook
    assert {x["uid"] for x in _agenda(client, admin)} & amb == amb  # superadministración: todo
    assert _ics(client, admin) & amb == amb
    # importes en Outlook: solo de lo suyo
    assert client.put("/api/calendario/outlook", headers=gente["dir_cdc"], json={"mostrar_importes": True}).status_code == 200
    url = client.post("/api/calendario/outlook", headers=gente["dir_cdc"]).json()["url"]
    client.put("/api/calendario/outlook", headers=gente["dir_cdc"], json={"mostrar_importes": True})
    ev = {str(e["UID"]).split("@")[0]: str(e["SUMMARY"]) for e in
          icalendar.Calendar.from_ical(client.get(url[url.index("/cal/"):]).content).walk("VEVENT")}
    assert ev["INVG-ZZ-AMB-CDC"].endswith("12.345,67 €") and "INVG-ZZ-AMB-INV" not in ev
