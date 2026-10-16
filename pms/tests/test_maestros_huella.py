"""1.73 · La huella del cuadre nocturno se calcula con los mismos valores que viajan en maestro.unidad.

Gestión rehace la huella con lo que recibe en maestro.unidad (pms_id|codigo|uso|situacion). Si el PMS la calculara con
otra fuente, el cuadre no coincidiría nunca. Datos ZZ-PRUEBA-MAEH, que se borran al terminar.
"""
import hashlib
from datetime import datetime

import pytest
from sqlalchemy import delete, select

from app import gestion, maestros
from app.database import SessionLocal
from app.models import Ajuste, FusionEntrada, GestionEvento, Unit

from test_maestros_171 import CLAVE, _aviso, _casilla, _entrada

Z = "ZZ-PRUEBA-MAEH"


@pytest.fixture(autouse=True)
def _pasarela(monkeypatch):
    monkeypatch.setattr(gestion, "EVENTOS_SECRET", CLAVE)
    yield


@pytest.fixture(scope="module", autouse=True)
def _borrar_al_terminar():
    yield
    with SessionLocal() as db:
        db.execute(delete(Ajuste).where(Ajuste.clave == maestros.AJUSTE))
        db.execute(delete(GestionEvento).where(GestionEvento.id_evento.like("pms-mae-%")))
        db.execute(delete(FusionEntrada).where(FusionEntrada.id_evento.like("ZZMAE-%")))
        for u in db.scalars(select(Unit).where(Unit.codigo.like(f"{Z}%"))):
            db.delete(u)
        db.commit()
        assert not db.scalar(select(Unit.id).where(Unit.codigo.like(f"{Z}%")))


def _huella_gestion(unidades: dict) -> str:
    """Lo que hace gestión con lo recibido: punto 8 del contrato, campo a campo de maestro.unidad."""
    lineas = []
    for pid in sorted(unidades):
        d = unidades[pid]
        if d["accion"] == "baja":
            continue
        lineas.append("|".join("" if d.get(c) is None else str(d[c]) for c in ("pms_id", "codigo", "uso", "situacion")))
    return hashlib.sha256("\n".join(lineas).encode("utf-8")).hexdigest()


def _pedir_todo(client) -> dict:
    """gestión pide el detalle de SFL y se queda con el último maestro.unidad de cada unidad."""
    with SessionLocal() as db:
        antes = db.scalar(select(GestionEvento.id).order_by(GestionEvento.id.desc())) or 0
    ide = _aviso(client, "maestro.pedir", {"activo_pms": "SFL", "pms_ids": "todos"})
    assert _entrada(ide)[0] == "aplicado"
    with SessionLocal() as db:
        evs = db.scalars(select(GestionEvento).where(GestionEvento.tipo == "maestro.unidad", GestionEvento.id > antes)
                         .order_by(GestionEvento.id))
        return {e.datos["datos"]["pms_id"]: e.datos["datos"] for e in evs}


def _huella_pms() -> str:
    with SessionLocal() as db:
        return next(x for x in maestros.datos_cuadre(db)["activos"] if x["activo_pms"] == "SFL")["huella"]


def test_huella_igual_a_lo_enviado(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    assert _casilla(client, admin, True)["activo"]
    # una ocupada sin situación, una disponible con situación y una con uso en mayúsculas
    u1 = client.post("/api/unidades", headers=admin, json={"asset_id": sfl, "codigo": f"{Z}-1", "uso": "apartamento"}).json()
    u2 = client.post("/api/unidades", headers=admin, json={"asset_id": sfl, "codigo": f"{Z}-2", "uso": "garaje"}).json()
    u3 = client.post("/api/unidades", headers=admin, json={"asset_id": sfl, "codigo": f"{Z}-3", "uso": "vivienda"}).json()
    with SessionLocal() as db:
        db.get(Unit, u1["id"]).estado = "ocupada"
        x = db.get(Unit, u2["id"])
        x.estado, x.uso, x.situacion = "disponible", "Garaje", "vacia"
        x.situacion_fecha = datetime(2026, 10, 16, 9, 0)
        db.commit()

    recibido = _pedir_todo(client)
    assert {u1["id"], u2["id"], u3["id"]} <= set(recibido)
    # «ocupada/disponible» viaja en estado; situacion viaja con el mismo valor que entra en la huella
    assert recibido[u1["id"]]["estado"] == "ocupada" and recibido[u1["id"]]["situacion"] is None
    assert recibido[u2["id"]]["situacion"] == "vacia" and recibido[u2["id"]]["uso"] == "garaje"
    assert _huella_pms() == _huella_gestion(recibido)

    # cambia la situación: cambia lo enviado y la huella, y siguen cuadrando
    huella_antes = _huella_pms()
    with SessionLocal() as db:
        db.get(Unit, u1["id"]).situacion = "alquilada"
        db.commit()
    assert _huella_pms() != huella_antes
    recibido = _pedir_todo(client)
    assert recibido[u1["id"]]["situacion"] == "alquilada"
    assert _huella_pms() == _huella_gestion(recibido)

    # cada línea de la huella sale de datos_unidad, la misma función que arma maestro.unidad
    with SessionLocal() as db:
        u = db.get(Unit, u2["id"])
        assert maestros.linea_huella(maestros.datos_unidad(u, "SFL", "actualizada")) == f"{u.id}|{Z}-2|garaje|vacia"
