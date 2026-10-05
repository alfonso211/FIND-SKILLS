"""Alquiler mensual de plazas de garaje de los apartamentos turísticos a clientes externos.

El cliente no es huésped ni ocupante del edificio: no lleva parte de viajeros ni contrato de alojamiento.
Funciona como un alquiler: contrato con renta mensual (21 % de IVA) y día de pago, un recibo cada mes que se
emite solo, aviso de los recibos vencidos y del fin de contrato, y factura al cobrar. Lo gestiona quien
lleva las reservas del activo (recepción)."""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import clientes, recibos
from ..database import get_db
from ..facturacion import IVA_GENERAL
from ..models import MODALIDADES_RESERVA, Charge, Contact, Lease, Reservation, Unit
from ..schemas import GarageLeaseEnd, GarageLeaseIn, GarageLeaseUpdate, Payment
from ..security import Scope, audit, get_scope
from ..utils import apply, bad_request, get_or_404, scoped
from .documentos import adjuntar_pendientes

router = APIRouter(prefix="/api/garajes", tags=["alquiler de garajes"])
TIPO_CLIENTE = "cliente_garaje"


def _nombre(c: Contact) -> str:
    return f"{c.nombre} {c.apellidos or ''}".strip()


def _pendiente(c: Charge) -> float:
    return float(recibos.dinero(c.importe) - recibos.dinero(c.importe_pagado))


def _recibo_out(c: Charge, hoy: date) -> dict:
    d = c.to_dict()
    u = c.lease.unit
    d.update(unidad=u.codigo, bloque=u.bloque, asset_id=u.asset_id, cliente=_nombre(c.lease.tenant),
             lease_id=c.lease_id, pendiente=_pendiente(c),
             vencido=c.estado in ("pendiente", "parcial") and c.fecha_vencimiento < hoy)
    return d


def _contrato_out(db: Session, l: Lease, hoy: date) -> dict:
    d = l.to_dict()
    t, u = l.tenant, l.unit
    d.update(unidad=u.codigo, bloque=u.bloque, asset_id=u.asset_id, cliente=_nombre(t), cliente_id=t.id,
             telefono=t.telefono, email=t.email, documento=t.documento_num,
             renta_con_iva=float(recibos.dinero(float(l.renta_mensual) * (1 + float(IVA_GENERAL) / 100))))
    pend = list(db.scalars(select(Charge).where(Charge.lease_id == l.id, Charge.estado.in_(("pendiente", "parcial")))
                           .order_by(Charge.fecha_vencimiento)))
    d["deuda_vencida"] = round(sum(_pendiente(c) for c in pend if c.fecha_vencimiento < hoy), 2)
    d["recibos_vencidos"] = sum(1 for c in pend if c.fecha_vencimiento < hoy)
    d["proximo_recibo"] = _recibo_out(pend[0], hoy) if pend else None
    d["al_corriente"] = d["recibos_vencidos"] == 0
    return d


def _activos(scope: Scope, accion: str) -> set[int] | None:
    return scope.asset_ids(f"reservas.{accion}")


def _plaza(db: Session, scope: Scope, unit_id: int) -> Unit:
    u = get_or_404(db, Unit, unit_id)
    scope.require_asset("reservas.editar", u.asset_id)
    if u.uso != "garaje" or u.asset.modalidad not in MODALIDADES_RESERVA:
        bad_request("Solo se alquilan así las plazas de garaje de los apartamentos turísticos")
    return u


def _contrato(db: Session, scope: Scope, lid: int, accion: str = "editar") -> Lease:
    l = get_or_404(db, Lease, lid)
    scope.require_asset(f"reservas.{accion}", l.unit.asset_id)
    if not recibos.es_garaje_turistico(l):
        bad_request("No es un alquiler de plaza de garaje")
    return l


def reservada(db: Session, unit_id: int, inicio: date, fin: date | None) -> bool:
    stmt = select(Reservation.id).where(Reservation.unit_id == unit_id,
                                        Reservation.estado.in_(("confirmada", "checkin")),
                                        Reservation.fecha_salida > inicio)
    if fin is not None:
        stmt = stmt.where(Reservation.fecha_entrada <= fin)
    return db.scalar(stmt) is not None


def _base(scope: Scope, asset_id: int | None):
    stmt = scoped(select(Lease).join(Unit), Unit.asset_id, _activos(scope, "ver")).where(Unit.uso == "garaje")
    if asset_id:
        stmt = stmt.where(Unit.asset_id == asset_id)
    return stmt


@router.get("/contratos")
def list_garage_leases(asset_id: int | None = None, estado: str | None = None, q: str | None = None,
                       scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Alquileres de plazas de garaje. Al consultarlos se emiten los recibos que falten del mes en curso."""
    hoy = date.today()
    recibos.garajes_al_dia(db, _activos(scope, "ver"))
    db.commit()
    stmt = _base(scope, asset_id).join(Contact, Contact.id == Lease.tenant_id)
    if estado:
        stmt = stmt.where(Lease.estado == estado)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Unit.codigo.ilike(like), Contact.nombre.ilike(like), Contact.apellidos.ilike(like),
                              Lease.matricula.ilike(like)))
    return [_contrato_out(db, l, hoy) for l in db.scalars(stmt.order_by(Lease.estado.desc(), Unit.codigo))
            if recibos.es_garaje_turistico(l)]


@router.post("/contratos", status_code=201)
def create_garage_lease(data: GarageLeaseIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    u = _plaza(db, scope, data.unit_id)
    if data.fecha_fin and data.fecha_fin <= data.fecha_inicio:
        bad_request("La fecha de fin debe ser posterior a la de inicio")
    if recibos.solapa_contrato(db, u.id, data.fecha_inicio, data.fecha_fin):
        bad_request(f"La plaza {u.codigo} ya está alquilada en esas fechas")
    if reservada(db, u.id, data.fecha_inicio, data.fecha_fin):
        bad_request(f"La plaza {u.codigo} tiene reservas en esas fechas")
    if data.cliente_id:
        cliente = clientes.del_activo(db, scope, data.cliente_id, u.asset, TIPO_CLIENTE)
    elif data.cliente:
        cliente = clientes.nueva(u.asset, TIPO_CLIENTE, **data.cliente.model_dump())
        db.add(cliente)
        db.flush()
    else:
        bad_request("Indique los datos del cliente")
    if data.documentos:
        adjuntar_pendientes(db, scope.user, data.documentos, cliente)
    l = Lease(unit_id=u.id, tenant_id=cliente.id, estado="vigente", indice_actualizacion="NINGUNO",
              tipo_iva=IVA_GENERAL, **data.model_dump(exclude={"unit_id", "cliente_id", "cliente", "documentos"}))
    if l.matricula:
        l.matricula = l.matricula.upper().replace(" ", "")
    db.add(l)
    db.flush()
    if l.fecha_inicio <= date.today():
        u.estado = "ocupada"
    recibos.garajes_al_dia(db, {u.asset_id})
    audit(db, scope.user, "alquilar_garaje", "contrato", l.id,
          {"plaza": u.codigo, "cliente": _nombre(cliente), "renta": data.renta_mensual})
    db.commit()
    return _contrato_out(db, l, date.today())


@router.put("/contratos/{lid}")
def update_garage_lease(lid: int, data: GarageLeaseUpdate, scope: Scope = Depends(get_scope),
                        db: Session = Depends(get_db)):
    l = _contrato(db, scope, lid)
    if "fecha_fin" in data.model_fields_set and data.fecha_fin is not None:
        if data.fecha_fin <= l.fecha_inicio:
            bad_request("La fecha de fin debe ser posterior a la de inicio")
        if recibos.solapa_contrato(db, l.unit_id, l.fecha_inicio, data.fecha_fin, excluir=lid):
            bad_request("Las nuevas fechas solapan con otro alquiler de la plaza")
    ch = apply(l, data)
    audit(db, scope.user, "editar", "contrato", lid, ch)
    db.commit()
    return _contrato_out(db, l, date.today())


@router.post("/contratos/{lid}/finalizar")
def end_garage_lease(lid: int, data: GarageLeaseEnd, scope: Scope = Depends(get_scope),
                     db: Session = Depends(get_db)):
    """Baja del alquiler: fija la fecha de fin y anula los recibos posteriores que no tengan cobros."""
    l = _contrato(db, scope, lid)
    if data.fecha_fin < l.fecha_inicio:
        bad_request("La fecha de baja es anterior al inicio del alquiler")
    l.fecha_fin = data.fecha_fin
    periodo_fin = f"{data.fecha_fin:%Y-%m}"
    for c in db.scalars(select(Charge).where(Charge.lease_id == l.id, Charge.periodo > periodo_fin,
                                             Charge.estado == "pendiente")):
        c.estado = "anulado"
    if data.fecha_fin <= date.today():
        l.estado = "finalizado"
        if l.unit.estado == "ocupada":
            l.unit.estado = "disponible"
    audit(db, scope.user, "baja_garaje", "contrato", lid, {"fecha_fin": str(data.fecha_fin), "motivo": data.motivo})
    db.commit()
    return _contrato_out(db, l, date.today())


@router.get("/recibos")
def list_garage_charges(asset_id: int | None = None, estado: str | None = None, lease_id: int | None = None,
                        scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Recibos de los alquileres de garaje. `estado=vencido`: pendientes con el vencimiento pasado."""
    hoy = date.today()
    recibos.garajes_al_dia(db, _activos(scope, "ver"))
    db.commit()
    stmt = scoped(select(Charge).join(Lease).join(Unit), Unit.asset_id, _activos(scope, "ver")).where(
        Unit.uso == "garaje")
    if asset_id:
        stmt = stmt.where(Unit.asset_id == asset_id)
    if lease_id:
        stmt = stmt.where(Charge.lease_id == lease_id)
    if estado == "vencido":
        stmt = stmt.where(Charge.estado.in_(("pendiente", "parcial")), Charge.fecha_vencimiento < hoy)
    elif estado:
        stmt = stmt.where(Charge.estado == estado)
    rows = db.scalars(stmt.order_by(Charge.fecha_vencimiento.desc(), Unit.codigo).limit(2000))
    return [_recibo_out(c, hoy) for c in rows if recibos.es_garaje_turistico(c.lease)]


@router.post("/recibos/{rid}/cobro")
def pay_garage_charge(rid: int, data: Payment, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    c = get_or_404(db, Charge, rid)
    _contrato(db, scope, c.lease_id)
    f = recibos.cobrar(db, scope.user, c, data)
    db.commit()
    return {**_recibo_out(c, date.today()), "factura": {"id": f.id, "codigo": f.codigo}}
