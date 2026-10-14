"""Versión 1.56: las listas no hacen una consulta por fila (el número de consultas no crece con las reservas u OT)."""
from contextlib import contextmanager
from datetime import date, timedelta

from sqlalchemy import event

from app.database import SessionLocal, engine
from app.models import Contact, Reservation, ReservationGuest, Unit, WorkOrder

HOY = date.today()


@contextmanager
def consultas():
    n = {"n": 0}

    def contar(*_):
        n["n"] += 1
    event.listen(engine, "before_cursor_execute", contar)
    try:
        yield n
    finally:
        event.remove(engine, "before_cursor_execute", contar)


def _datos(aid: int, cuantas: int, marca: str) -> None:
    """`cuantas` reservas lejanas (no chocan con otras pruebas) y otras tantas OT abiertas en apartamentos distintos."""
    with SessionLocal() as db:
        a_units = list(db.query(Unit).filter(Unit.asset_id == aid, Unit.uso == "apartamento").order_by(Unit.id))[:cuantas]
        from app.models import Asset
        cid = db.get(Asset, aid).company_id
        for i, u in enumerate(a_units):
            g = Contact(company_id=cid, asset_id=aid, tipo="huesped", nombre=f"{marca}{i}", apellidos="Rendimiento")
            db.add(g)
            db.flush()
            r = Reservation(unit_id=u.id, guest_id=g.id, localizador=f"{marca}-{i}", canal="directo",
                            fecha_entrada=HOY + timedelta(days=900), fecha_salida=HOY + timedelta(days=903), adultos=1,
                            ninos=0, importe_total=100, importe_pagado=0, estado="confirmada")
            r.ocupantes.append(ReservationGuest(contact_id=g.id, titular=True, orden=0))
            db.add(r)
            db.add(WorkOrder(asset_id=aid, unit_id=u.id, titulo=f"{marca} OT {i}", abierta_por=1))
        db.commit()


def _borrar(marca: str) -> None:
    with SessionLocal() as db:
        for r in db.query(Reservation).filter(Reservation.localizador.like(f"{marca}-%")):
            db.query(ReservationGuest).filter(ReservationGuest.reservation_id == r.id).delete()
            g = r.guest_id
            db.delete(r)
            db.flush()
            db.query(Contact).filter(Contact.id == g).delete()
        db.query(WorkOrder).filter(WorkOrder.titulo.like(f"{marca} OT %")).delete(synchronize_session=False)
        db.commit()


def test_listas_sin_una_consulta_por_fila(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    pantallas = [("/api/turistico/reservas", {"asset_id": sae, "desde": (HOY + timedelta(days=890)).isoformat()}),
                 ("/api/turistico/planning", {"asset_id": sae, "desde": (HOY + timedelta(days=899)).isoformat(),
                                              "dias": 14}),
                 ("/api/mantenimiento/ordenes", {"asset_id": sae, "abiertas": True}),
                 (f"/api/plano/{sae}", {"fecha": (HOY + timedelta(days=901)).isoformat()})]
    medidas = {}
    try:
        for marca, n in (("REND5", 5), ("REND40", 35)):
            _datos(sae, n, marca)
            for url, q in pantallas:
                client.get(url, headers=admin, params=q)  # la primera vez carga catálogos
                with consultas() as c:
                    r = client.get(url, headers=admin, params=q)
                assert r.status_code == 200, (url, r.text)
                medidas.setdefault(url, []).append(c["n"])
    finally:
        _borrar("REND5")
        _borrar("REND40")
    for url, (pocas, muchas) in medidas.items():
        # con 7 veces más reservas y OT, las consultas casi no cambian (antes: 2-3 más por cada fila)
        assert muchas - pocas <= 4, (url, pocas, muchas)
