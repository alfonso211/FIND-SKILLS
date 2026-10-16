"""Plazas de garaje unidas al alquiler de una vivienda (Babilonia y demás alquiler residencial).

El inquilino de la vivienda tiene su plaza en el mismo contrato: la plaza queda ocupada mientras el contrato esté en
borrador o vigente, no se puede alquilar aparte ni unir a otro contrato, y se libera sola al terminar o anular el
contrato. No lleva renta propia: va en la del contrato.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Lease, Unit
from .utils import bad_request

ACTIVOS = ("borrador", "vigente")


def _solapa(l: Lease, inicio: date, fin: date | None) -> bool:
    return (l.fecha_fin is None or l.fecha_fin >= inicio) and (fin is None or l.fecha_inicio <= fin)


def contrato_de_plaza(db: Session, unit_id: int, inicio: date, fin: date | None,
                      excluir: int | None = None) -> Lease | None:
    """Contrato (de otra unidad) que tiene unida esta plaza en esas fechas."""
    u = db.get(Unit, unit_id)
    if u is None or u.uso != "garaje":
        return None
    for l in db.scalars(select(Lease).join(Unit, Unit.id == Lease.unit_id).where(
            Unit.asset_id == u.asset_id, Lease.estado.in_(ACTIVOS), Lease.plazas.is_not(None))):
        if l.id != excluir and unit_id in (l.plazas or []) and _solapa(l, inicio, fin):
            return l
    return None


def validar(db: Session, vivienda: Unit, plazas: list[int], inicio: date, fin: date | None,
            excluir: int | None = None) -> list[int]:
    """Comprueba las plazas que se unen al contrato de `vivienda` y devuelve la lista limpia."""
    out = []
    for pid in dict.fromkeys(plazas or []):
        p = db.get(Unit, pid)
        if p is None or p.asset_id != vivienda.asset_id:
            bad_request("La plaza de garaje no es de este edificio")
        if p.uso != "garaje":
            bad_request(f"{p.codigo} no es una plaza de garaje")
        if p.id == vivienda.id:
            bad_request("La plaza no puede ser la propia unidad del contrato")
        if p.baja:
            bad_request(f"La plaza {p.codigo} está dada de baja")
        otro = contrato_de_plaza(db, p.id, inicio, fin, excluir)
        if otro:
            bad_request(f"La plaza {p.codigo} ya va unida al contrato de {otro.unit.codigo}")
        propio = db.scalar(select(Lease.id).where(
            Lease.unit_id == p.id, Lease.estado.in_(ACTIVOS),
            or_(Lease.fecha_fin.is_(None), Lease.fecha_fin >= inicio),
            *([Lease.fecha_inicio <= fin] if fin else [])))
        if propio:
            bad_request(f"La plaza {p.codigo} tiene su propio contrato de alquiler en esas fechas")
        out.append(p.id)
    return out


def ocupar(db: Session, l: Lease) -> None:
    if l.estado == "vigente" and l.fecha_inicio <= date.today():
        for u in db.scalars(select(Unit).where(Unit.id.in_(l.plazas or [-1]))):
            if u.estado in ("disponible", "bloqueada"):
                u.estado = "ocupada"


def liberar(db: Session, l: Lease, plazas: list[int] | None = None) -> None:
    for u in db.scalars(select(Unit).where(Unit.id.in_((l.plazas if plazas is None else plazas) or [-1]))):
        if u.estado == "ocupada":
            u.estado = "disponible"


def codigos(db: Session, l: Lease) -> list[str]:
    if not l.plazas:
        return []
    return list(db.scalars(select(Unit.codigo).where(Unit.id.in_(l.plazas)).order_by(Unit.codigo)))
