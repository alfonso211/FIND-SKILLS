"""Versión 1.53: dotación estándar obligatoria y dotación extraordinaria al importar reservas desde Excel."""
from contextlib import contextmanager
from datetime import date, timedelta
from io import BytesIO

from openpyxl import Workbook

from app import dotacion
from app.database import SessionLocal
from app.models import DotacionArticulo, DotacionHabitual, DotacionUnidad, Reservation

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HOY = date.today()


def _xlsx(filas: list[list]) -> bytes:
    wb = Workbook()
    for f in filas:
        wb.active.append(f)
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


@contextmanager
def dotacion_fijada(client, admin, asset_id: int, tipologias: set[str] | None = None):
    """Fija la dotación estándar de los tipos de apartamento del activo y, al terminar, la deja como estaba."""
    aptos = [u for u in client.get(f"/api/unidades?asset_id={asset_id}", headers=admin).json() if u["uso"] != "garaje"]
    with SessionLocal() as db:
        antes = {h.tipologia for h in db.query(DotacionHabitual).filter(DotacionHabitual.asset_id == asset_id)}
    nuevas = set()
    for u in aptos:
        t = u["tipologia"] or ""
        if t in antes or t in nuevas or (tipologias is not None and t not in tipologias):
            continue
        est = client.get(f"/api/dotacion/unidad/{u['id']}", headers=admin).json()
        assert client.put("/api/dotacion/habitual", headers=admin, json={
            "asset_id": asset_id, "tipologia": t, "perfil": est["perfil"], "items": est["items"]}).status_code == 200
        nuevas.add(t)
    try:
        yield
    finally:
        with SessionLocal() as db:
            db.query(DotacionHabitual).filter(DotacionHabitual.asset_id == asset_id,
                                              DotacionHabitual.tipologia.in_(nuevas or {"-"})).delete()
            db.commit()


def test_importar_exige_dotacion_estandar_y_lee_la_extraordinaria(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    ent, sal = HOY + timedelta(days=200), HOY + timedelta(days=203)
    with SessionLocal() as db:  # un apartamento sin dotación propia, con 2 plazas y libre esas fechas
        propias = {x.unit_id for x in db.query(DotacionUnidad)}
        ocupadas = {x.unit_id for x in db.query(Reservation).filter(Reservation.fecha_entrada < sal + timedelta(days=2),
                                                                    Reservation.fecha_salida > ent)}
    aptos = [u for u in client.get(f"/api/unidades?asset_id={sfl}", headers=admin).json() if u["uso"] == "apartamento"]
    u = next(x for x in reversed(aptos) if x["id"] not in propias | ocupadas and (x["capacidad"] or 2) >= 2
             and x["estado"] not in ("bloqueada", "fuera_servicio", "mantenimiento"))
    tipo = u["tipologia"] or ""
    with SessionLocal() as db:  # este tipo de apartamento, sin dotación estándar fijada
        db.query(DotacionHabitual).filter(DotacionHabitual.asset_id == sfl, DotacionHabitual.tipologia == tipo).delete()
        db.commit()
    fichero = _xlsx([
        ["Localizador", "Unidad", "Entrada", "Salida", "Adultos", "Nombre", "Dotación extraordinaria"],
        ["IMPD153-1", u["codigo"], ent, sal, 2, "Cliente Uno", "Cuna de viaje 153 x1; Toallas de baño x4; 2 almohadas"],
        ["IMPD153-2", u["codigo"], sal, sal + timedelta(days=2), 1, "Cliente Dos", ""],
    ])
    enviar = lambda **d: client.post("/api/turistico/importar", headers=admin,  # noqa: E731
                                     data={"asset_id": sfl, **d}, files={"fichero": ("r.xlsx", fichero, XLSX)}).json()
    # sin dotación estándar fijada: esas reservas no se importan y la pantalla sabe qué tipo hay que fijar
    prev = enviar()
    assert prev["errores"] == 2 and prev["sin_dotacion"] == [tipo or "sin tipología"], prev["filas"]
    assert "dotación estándar" in prev["filas"][0]["motivo"]
    assert enviar(confirmar="true")["importadas"] == 0
    # fijada la estándar: se importan, con la extraordinaria pedida
    with dotacion_fijada(client, admin, sfl, {tipo}):
        prev = enviar()
        assert prev["validas"] == 2 and prev["sin_dotacion"] == []
        d1 = prev["filas"][0]["dotacion"]
        assert d1.startswith("Estándar + ") and "Cuna de viaje 153 ×1 (nuevo)" in d1 and "Almohadas ×2" in d1
        assert prev["filas"][1]["dotacion"] == "Estándar"
        with SessionLocal() as db:  # la vista previa no da de alta nada
            assert not db.query(DotacionArticulo).filter(DotacionArticulo.articulo == "Cuna de viaje 153").count()
        r = enviar(confirmar="true")
        assert r["importadas"] == 2
        with SessionLocal() as db:
            cuna = db.query(DotacionArticulo).filter(DotacionArticulo.articulo == "Cuna de viaje 153").one()
            assert cuna.asset_id == sfl
            r1 = db.query(Reservation).filter(Reservation.localizador == "IMPD153-1").one()
            r2 = db.query(Reservation).filter(Reservation.localizador == "IMPD153-2").one()
            assert r2.dotacion is None  # sin extraordinaria: la estándar
            assert [x["codigo"] for x in r1.dotacion["extra"]] == [cuna.codigo]
            base = {x["codigo"] for x in dotacion.base_unidad(db, db.get(Reservation, r1.id).unit)[0]}
            toallas = next(x["codigo"] for x in dotacion.CATALOGO if x["articulo"].startswith("Toallas de baño"))
            if toallas in base:  # ya está en la estándar: queda la cantidad total para esta reserva
                assert r1.dotacion["cambios"][toallas] == "4"
        # la hoja de dotación de la reserva la muestra como especial
        d = client.get(f"/api/turistico/reservas/{r1.id}/dotacion", headers=admin).json()
        assert d["especial"] and any(x["articulo"] == "Cuna de viaje 153" for x in d["items"])
    _borrar_importadas(("IMPD153-1", "IMPD153-2"), "Cuna de viaje 153")


def _borrar_importadas(localizadores, articulo):
    """Deja la base como estaba: las demás pruebas cuentan reservas, clientes y artículos de dotación."""
    from app.models import Contact, ReservationGuest
    with SessionLocal() as db:
        for r in db.query(Reservation).filter(Reservation.localizador.in_(localizadores)):
            db.query(ReservationGuest).filter(ReservationGuest.reservation_id == r.id).delete()
            guest_id = r.guest_id
            db.delete(r)
            db.flush()
            db.query(Contact).filter(Contact.id == guest_id).delete()
        db.query(DotacionArticulo).filter(DotacionArticulo.articulo == articulo).delete()
        db.commit()


def test_asignacion_automatica_prefiere_apartamentos_con_dotacion(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    ent = HOY + timedelta(days=260)
    fichero = _xlsx([["Entrada", "Salida", "Adultos", "Nombre"], [ent, ent + timedelta(days=2), 1, "Sin Unidad"]])
    aptos = [u for u in client.get(f"/api/unidades?asset_id={sfl}", headers=admin).json() if u["uso"] == "apartamento"]
    tipo = aptos[-1]["tipologia"] or ""
    with SessionLocal() as db:
        guardadas = [(h.tipologia, h.perfil, h.items) for h in db.query(DotacionHabitual).filter(
            DotacionHabitual.asset_id == sfl)]
        db.query(DotacionHabitual).filter(DotacionHabitual.asset_id == sfl).delete()
        db.commit()
    try:
        with dotacion_fijada(client, admin, sfl, {tipo}):
            prev = client.post("/api/turistico/importar", headers=admin, data={"asset_id": sfl},
                               files={"fichero": ("r.xlsx", fichero, XLSX)}).json()
            fila = prev["filas"][0]
            assert fila["estado"] == "valida" and fila["asignada"]
            asignado = next(u for u in aptos if u["codigo"] == fila["unidad"])
            assert (asignado["tipologia"] or "") == tipo
    finally:
        with SessionLocal() as db:
            for t, p, items in guardadas:
                db.add(DotacionHabitual(asset_id=sfl, tipologia=t, perfil=p, items=items))
            db.commit()


def test_lectura_del_texto_de_dotacion():
    cat = dotacion.CATALOGO
    items = dotacion.de_texto("Toallas de lavabo 4; Toallas de baño (100x150) x2, 3 almohadas | Plancha: 1; cuna", cat)
    assert [(x["articulo"].split(" (")[0], x["cantidad"], x["nuevo"]) for x in items] == [
        ("Toallas de lavabo", "4", False), ("Toallas de baño", "2", False), ("Almohadas", "3", False),
        ("Plancha de vapor y tabla de planchar", "1", False), ("Cuna", "1", True)]
    assert dotacion.de_texto("", cat) == [] and dotacion.de_texto(None, cat) == []
    assert dotacion.de_texto("Almohadas x0", cat) == []  # cantidad 0: no se pide nada
