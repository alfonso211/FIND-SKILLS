"""Activos y unidades sincronizados con gestión (1.71, contrato «fusion1», tipos maestro.*): alta, cambio y baja de
unidad hacia gestión; catastro y petición de detalle desde gestión; aviso repetido = un solo cambio; sin eco; campo no
permitido ignorado y anotado; catastro de solo lectura en el PMS; cuadre nocturno con su huella; casilla apagada =
sin tratar y nada en la cola. Datos ZZ-PRUEBA-MAE, borrados al terminar."""
import hashlib
import json
import time
import uuid
from datetime import datetime

import pytest
from sqlalchemy import delete, select

from app import fusion, gestion, maestros
from app.database import SessionLocal
from app.models import Ajuste, Asset, AuditLog, FusionEntrada, GestionEvento, Unit

CLAVE = "clave-de-prueba-maestros-0123456789abcdef"
Z = "ZZ-PRUEBA-MAE"


@pytest.fixture(autouse=True)
def _pasarela(monkeypatch):
    monkeypatch.setattr(gestion, "EVENTOS_SECRET", CLAVE)
    yield


@pytest.fixture(scope="module", autouse=True)
def _borrar_al_terminar():
    yield
    with SessionLocal() as db:  # todo lo de prueba fuera: unidades, cola, avisos recibidos, catastro y casilla
        db.execute(delete(Ajuste).where(Ajuste.clave == maestros.AJUSTE))
        db.commit()
        db.execute(delete(GestionEvento).where(GestionEvento.id_evento.like("pms-mae-%")))
        db.execute(delete(FusionEntrada).where(FusionEntrada.id_evento.like("ZZMAE-%")))
        for u in db.scalars(select(Unit).where(Unit.codigo.like(f"{Z}%"))):
            db.delete(u)
        for a in db.scalars(select(Asset).where(Asset.catastro.is_not(None))):
            a.catastro = None
        db.commit()
        for a in db.scalars(select(Asset).where(Asset.codigo == "ZZMAE")):  # activo de prueba que no se sincroniza
            db.delete(a)
        db.commit()
        assert not db.scalar(select(Unit.id).where(Unit.codigo.like(f"{Z}%")))
        assert not db.scalar(select(GestionEvento.id).where(GestionEvento.id_evento.like("pms-mae-%")))


def _casilla(client, h, valor):
    r = client.put("/api/maestros/config", headers=h, json={"activo": valor})
    assert r.status_code == 200, r.text
    return r.json()


def _aviso(client, tipo, datos, ide=None, origen="GESTION"):
    ide = ide or f"ZZMAE-{uuid.uuid4().hex}"
    cuerpo = json.dumps({"id_evento": ide, "tipo": tipo, "version": "fusion1", "emitido": "2026-10-15T00:00:00Z",
                         "origen": origen, "activo": "SFLORIDA", "sociedad": "CDC", "datos": datos,
                         "documentos": []}).encode()
    ts = str(int(time.time()))
    r = client.post("/api/gestion/eventos", content=cuerpo, headers={
        "Content-Type": "application/json", "X-PMS-Fecha": ts, "X-PMS-Firma": gestion.firmar(CLAVE, ts, cuerpo)})
    assert r.status_code == 200, r.text
    return ide


def _entrada(ide):
    with SessionLocal() as db:
        e = db.scalar(select(FusionEntrada).where(FusionEntrada.id_evento == ide))
        return e.estado, e.resultado


def _cola(uid=None, tipo="maestro.unidad"):
    with SessionLocal() as db:
        q = select(GestionEvento).where(GestionEvento.tipo == tipo).order_by(GestionEvento.id)
        if uid is not None:
            q = q.where(GestionEvento.id_evento.like(f"pms-mae-u{uid}-%"))
        return [{"id_evento": e.id_evento, **e.datos} for e in db.scalars(q)]


def _procesar():
    """Procesa la cola con el envío simulado sin tocar los avisos de otras pruebas (vuelven a quedar como estaban)."""
    with SessionLocal() as db:
        otros = {e.id: (e.estado, e.intentos, e.enviado, e.proximo, e.ultimo_error) for e in db.scalars(
            select(GestionEvento).where(GestionEvento.tipo.not_in(maestros.TIPOS_SALIDA),
                                        GestionEvento.estado.in_(("pendiente", "aviso"))))}
        gestion.procesar_cola(db, limite=5000)
        for e in db.scalars(select(GestionEvento).where(GestionEvento.id.in_(list(otros) or [-1]))):
            e.estado, e.intentos, e.enviado, e.proximo, e.ultimo_error = otros[e.id]
        db.commit()


def _catastro(uid, version, **extra):
    return {"ambito": "unidad", "pms_id": uid, "activo_pms": "SFL", "propietaria": "CDC",
            "ref_catastral": f"9{version:04d}01VK4790S0001XX", "valor_suelo": 41000.5, "valor_construccion": 62000,
            "valor_catastral": 103000.5, "uso": "Residencial", "ibi_2026": 480.12, "trua_2026": 95.4,
            "version": version, **extra}


def test_maestros_en_los_dos_sentidos(client, admin, ids, monkeypatch):
    sfl = ids["assets"]["SFL"]["id"]

    # casilla apagada (al desplegar): no se manda nada y lo que llega se guarda «sin tratar»
    assert not _casilla(client, admin, False)["activo"]
    u1 = client.post("/api/unidades", headers=admin, json={"asset_id": sfl, "codigo": f"{Z}-1", "uso": "apartamento",
                                                           "bloque": "ZZ", "tarifa_base_noche": 80}).json()
    assert u1["maestro_version"] == 1
    assert not _cola(u1["id"])
    previo = _aviso(client, "maestro.catastro", _catastro(u1["id"], 1))
    assert _entrada(previo)[0] == "sin_tratar"
    assert client.get("/api/maestros/config", headers=admin).json()["sin_tratar"] >= 1

    # solo la superadministración toca la casilla
    from test_pms import _new_user
    rec = _new_user(client, admin, "rec.maestros@inversiete.com", [{"role_id": ids["roles"]["Recepción"], "asset_id": sfl}])
    assert client.put("/api/maestros/config", headers=rec, json={"activo": True}).status_code == 403

    # al encender: se aplica lo que llegó apagada y se mandan todas las unidades y activos
    r = _casilla(client, admin, True)
    assert r["activo"] and r["sin_tratar_aplicados"] >= 1 and r["carga_inicial"] >= 1
    assert _entrada(previo)[0] == "aplicado"
    carga = _cola(u1["id"])
    assert carga and carga[-1]["datos"]["accion"] == "actualizada" and carga[-1]["datos"]["version"] == 1
    assert _cola(tipo="maestro.activo")

    # alta: maestro.unidad «creada», versión 1, con el contrato del punto 8
    u2 = client.post("/api/unidades", headers=admin, json={"asset_id": sfl, "codigo": f"{Z}-2", "uso": "garaje",
                                                           "planta": "-1", "superficie_m2": 12.5}).json()
    ev = _cola(u2["id"])
    assert len(ev) == 1
    d = ev[0]["datos"]
    assert ev[0]["origen"] == "PMS" and ev[0]["version"] == "fusion1"
    assert d["accion"] == "creada" and d["version"] == 1 and d["pms_id"] == u2["id"] and d["activo_pms"] == "SFL"
    assert d["uso"] == "garaje" and d["superficie_m2"] == 12.5 and d["cambiado"]
    assert set(d) == {"pms_id", "accion", "version", "activo_pms", "cambiado", *maestros.OPERATIVOS}

    # cambio operativo: «actualizada» con la versión siguiente; un cambio no operativo (notas) no sale
    client.put(f"/api/unidades/{u2['id']}", headers=admin, json={"renta_base": 95})
    client.put(f"/api/unidades/{u2['id']}", headers=admin, json={"notas": "sin importancia para gestión"})
    ev = _cola(u2["id"])
    assert [x["datos"]["accion"] for x in ev] == ["creada", "actualizada"]
    assert ev[-1]["datos"]["version"] == 2 and ev[-1]["datos"]["renta_base"] == 95

    # baja: solo la superadministración; no se borra; sale «baja», deja de listarse y no se reserva
    assert client.post(f"/api/maestros/unidades/{u2['id']}/baja", headers=rec, json={"motivo": "Plaza anulada"}).status_code == 403
    assert client.post(f"/api/maestros/unidades/{u2['id']}/baja", headers=admin, json={"motivo": "x"}).status_code == 422
    b = client.post(f"/api/maestros/unidades/{u2['id']}/baja", headers=admin, json={"motivo": "Plaza anulada"}).json()
    assert b["baja"] and b["estado"] == "fuera_servicio"
    ev = _cola(u2["id"])
    assert ev[-1]["datos"]["accion"] == "baja" and ev[-1]["datos"]["version"] == 3
    assert all(x["id"] != u2["id"] for x in client.get(f"/api/unidades?asset_id={sfl}", headers=admin).json())
    assert any(x["id"] == u2["id"] for x in client.get(f"/api/unidades?asset_id={sfl}&bajas=true", headers=admin).json())
    assert client.put(f"/api/unidades/{u2['id']}", headers=admin, json={"estado": "disponible"}).status_code == 400

    # lo que se manda a gestión: cabecera fusion1, origen PMS y sin claves internas
    enviados = []

    def falso(ev):
        enviados.append(json.loads(fusion.cuerpo(ev)))
        return True, "{}"
    monkeypatch.setattr(gestion, "_enviar", falso)
    _procesar()
    nuestros = [x for x in enviados if x["tipo"] == "maestro.unidad" and x["datos"]["pms_id"] == u2["id"]]
    assert [x["datos"]["version"] for x in nuestros] == [1, 2, 3]
    assert all(not k.startswith("_") for x in nuestros for k in x)

    # solo los activos que gestión conoce (SFL, SAE y BAB35): otro activo no manda nada ni entra en el cuadre
    otro = client.post("/api/activos", headers=admin, json={
        "company_id": ids["companies"]["COMERCIAL DEL CAMPO S.A."], "codigo": "ZZMAE", "nombre": f"{Z} activo",
        "modalidad": "apartamentos_turisticos"})
    assert otro.status_code == 201, otro.text
    ux = client.post("/api/unidades", headers=admin, json={"asset_id": otro.json()["id"], "codigo": f"{Z}-X",
                                                           "uso": "apartamento"}).json()
    client.put(f"/api/activos/{otro.json()['id']}", headers=admin, json={"nombre": f"{Z} activo 2"})
    assert not _cola(ux["id"])
    assert all(x["datos"]["activo_pms"] != "ZZMAE" for x in _cola(tipo="maestro.activo"))
    with SessionLocal() as db:
        assert {x["activo_pms"] for x in maestros.datos_cuadre(db)["activos"]} <= {"SFL", "SAE", "BAB35"}
    assert _entrada(_aviso(client, "maestro.pedir", {"activo_pms": "ZZMAE", "pms_ids": "todos"}))[0] == "sin_tratar"
    with SessionLocal() as db:
        db.delete(db.get(Unit, ux["id"]))
        db.commit()
    assert not _cola(ux["id"])  # borrado físico en un activo no sincronizado: tampoco sale

    # catastro de gestión: guarda la referencia y el resto en el JSON; un aviso repetido es un solo cambio
    antes = len(_cola(u1["id"]))
    ide = _aviso(client, "maestro.catastro", _catastro(u1["id"], 2, codigo="HACK", renta_base=1))
    _aviso(client, "maestro.catastro", _catastro(u1["id"], 2, codigo="HACK", renta_base=1), ide=ide)
    assert _entrada(ide)[0] == "aplicado"
    with SessionLocal() as db:
        x = db.get(Unit, u1["id"])
        assert x.ref_catastral == "9000201VK4790S0001XX" and x.codigo == f"{Z}-1"
        assert x.renta_base is None and x.catastro["version"] == 2 and x.catastro["ibi_2026"] == 480.12
        assert x.catastro["propietaria"] == "CDC" and x.catastro["uso"] == "Residencial"
        assert "codigo" not in x.catastro and "renta_base" not in x.catastro
        anotado = db.scalar(select(AuditLog).where(AuditLog.accion == "campo_ignorado")
                            .order_by(AuditLog.id.desc()).limit(1))
        assert anotado.detalle["id_evento"] == ide and anotado.detalle["campos"] == ["codigo", "renta_base"]
    assert len(_cola(u1["id"])) == antes  # sin eco: lo que llega de gestión no se reenvía
    # misma versión con otro id, o anterior: se ignora
    assert _entrada(_aviso(client, "maestro.catastro", _catastro(u1["id"], 2)))[0] == "ignorado"
    assert _entrada(_aviso(client, "maestro.catastro", _catastro(u1["id"], 1)))[0] == "ignorado"
    # unidad que no está en el PMS: sin tratar
    assert _entrada(_aviso(client, "maestro.catastro", _catastro(99999999, 5)))[0] == "sin_tratar"

    # solo lectura en el PMS: la referencia catastral no se cambia aquí; lo demás sí
    r = client.put(f"/api/unidades/{u1['id']}", headers=admin, json={"ref_catastral": "OTRA"})
    assert r.status_code == 400 and "gestión" in r.json()["detail"]
    assert client.put(f"/api/unidades/{u1['id']}", headers=admin, json={"tipologia": "Estudio"}).status_code == 200
    ficha = client.get(f"/api/unidades?asset_id={sfl}&q={Z}-1", headers=rec).json()[0]
    assert ficha["catastro"]["valor_catastral"] == 103000.5 and ficha["ref_catastral"]

    # catastro del activo (finca principal con resumen del edificio)
    ide = _aviso(client, "maestro.catastro", {"ambito": "activo", "activo_pms": "SFL", "propietaria": "CDC",
                                              "ref_catastral": "1234567VK4713S", "valor_catastral": 5000000,
                                              "resumen": {"fincas": 672, "ibi": 41000}, "version": 1})
    assert _entrada(ide)[0] == "aplicado"
    a = client.get("/api/activos", headers=admin).json()
    a = next(x for x in a if x["id"] == sfl)
    assert a["catastro"]["resumen"]["fincas"] == 672 and a["ref_catastral"] == "1234567VK4713S"
    assert client.put(f"/api/activos/{sfl}", headers=admin, json={"ref_catastral": "X"}).status_code == 400

    # lo operativo lo manda el PMS: maestro.unidad de gestión se ignora y se anota; un aviso nuestro de vuelta, eco
    assert _entrada(_aviso(client, "maestro.unidad", {"pms_id": u1["id"], "codigo": "OTRO"}))[0] == "ignorado"
    assert client.get(f"/api/unidades?asset_id={sfl}&q={Z}-1", headers=admin).json()[0]["codigo"] == f"{Z}-1"
    assert _entrada(_aviso(client, "maestro.catastro", _catastro(u1["id"], 9), origen="PMS"))[0] == "eco"

    # cuadre nocturno: por uso y huella del punto 8; una vez al día a partir de las 03:30
    with SessionLocal() as db:
        assert maestros.cuadre(db, datetime(2026, 10, 16, 3, 0)) is None
        assert maestros.cuadre(db, datetime(2026, 10, 16, 3, 31)) is not None
        assert maestros.cuadre(db, datetime(2026, 10, 16, 4, 0)) is None  # ya salió hoy
        c = next(x for x in maestros.datos_cuadre(db)["activos"] if x["activo_pms"] == "SFL")
        vivas = sorted((u for u in db.scalars(select(Unit).where(Unit.asset_id == sfl)) if not u.baja), key=lambda u: u.id)
        texto = "\n".join(f"{u.id}|{u.codigo}|{u.uso.lower()}|{u.situacion or ''}" for u in vivas)
        assert c["huella"] == hashlib.sha256(texto.encode()).hexdigest()
        assert sum(c["por_uso"].values()) == len(vivas) and u2["id"] not in [u.id for u in vivas]
        huella_gestion = c["huella"]  # lo que tiene gestión
    # el PMS cambia un código: la huella ya no cuadra y gestión pide el detalle del activo
    assert client.put(f"/api/unidades/{u1['id']}", headers=admin, json={"codigo": f"{Z}-1B"}).status_code == 200
    with SessionLocal() as db:
        assert next(x for x in maestros.datos_cuadre(db)["activos"] if x["activo_pms"] == "SFL")["huella"] != huella_gestion
    antes = len(_cola())
    ide = _aviso(client, "maestro.pedir", {"activo_pms": "SFL", "pms_ids": "todos"})
    estado, res = _entrada(ide)
    assert estado == "aplicado" and res["unidades"] >= 2
    nuevos = _cola()[antes:]
    assert len(nuevos) == res["unidades"] and all(x["id_evento_causa"] == ide for x in nuevos)
    ultimo = next(x for x in reversed(nuevos) if x["datos"]["pms_id"] == u1["id"])
    assert ultimo["datos"]["accion"] == "actualizada" and ultimo["datos"]["codigo"] == f"{Z}-1B"
    assert next(x for x in nuevos if x["datos"]["pms_id"] == u2["id"])["datos"]["accion"] == "baja"

    # reactivar: vuelve a salir como «actualizada» con la versión siguiente
    assert client.post(f"/api/maestros/unidades/{u2['id']}/reactivar", headers=admin).json()["estado"] == "disponible"
    assert _cola(u2["id"])[-1]["datos"]["accion"] == "actualizada"

    # al apagar: lo nuevo no se encola y lo que quede en la cola espera
    _casilla(client, admin, False)
    n = len(_cola(u1["id"]))
    client.put(f"/api/unidades/{u1['id']}", headers=admin, json={"capacidad": 3})
    assert len(_cola(u1["id"])) == n
    enviados.clear()
    _procesar()
    assert not [x for x in enviados if x["tipo"].startswith("maestro.")]
    assert _entrada(_aviso(client, "maestro.pedir", {"activo_pms": "SFL", "pms_ids": "todos"}))[0] == "sin_tratar"
