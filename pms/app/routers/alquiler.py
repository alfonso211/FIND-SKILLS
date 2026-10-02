"""Alquiler residencial de larga estancia: contratos (LAU) y recibos."""
import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MODALIDADES_CONTRATO, Asset, Charge, Contact, Lease, Unit
from ..schemas import ChargeGenerate, LeaseIn, LeaseUpdate, Payment, RentUpdate
from ..security import Scope, audit, get_scope
from ..utils import apply, bad_request, get_or_404, scoped

router = APIRouter(prefix="/api/alquiler", tags=["alquiler residencial"])

ESTADOS_CONTRATO = {"borrador", "vigente", "finalizado", "rescindido"}
ESTADOS_ACTIVOS = ("borrador", "vigente")


def _money(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _lease_out(l: Lease) -> dict:
    d = l.to_dict()
    d["unidad"] = l.unit.codigo
    d["asset_id"] = l.unit.asset_id
    d["inquilino"] = f"{l.tenant.nombre} {l.tenant.apellidos or ''}".strip()
    return d


def _charge_out(c: Charge) -> dict:
    d = c.to_dict()
    d["unidad"] = c.lease.unit.codigo
    d["asset_id"] = c.lease.unit.asset_id
    d["inquilino"] = f"{c.lease.tenant.nombre} {c.lease.tenant.apellidos or ''}".strip()
    d["pendiente"] = float(_money(c.importe) - _money(c.importe_pagado))
    return d


# --------------------------------------------------------------------------- contratos
@router.get("/contratos")
def list_leases(asset_id: int | None = None, estado: str | None = None,
                scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ids = scope.asset_ids("alquiler.ver")
    stmt = scoped(select(Lease).join(Unit), Unit.asset_id, ids).order_by(Unit.asset_id, Unit.codigo)
    if asset_id:
        stmt = stmt.where(Unit.asset_id == asset_id)
    if estado:
        stmt = stmt.where(Lease.estado == estado)
    return [_lease_out(l) for l in db.scalars(stmt)]


def _overlaps(db: Session, unit_id: int, start: date, end: date | None, exclude_id: int | None = None) -> bool:
    stmt = select(Lease.id).where(
        Lease.unit_id == unit_id, Lease.estado.in_(ESTADOS_ACTIVOS),
        or_(Lease.fecha_fin.is_(None), Lease.fecha_fin >= start))
    if end is not None:
        stmt = stmt.where(Lease.fecha_inicio <= end)
    if exclude_id:
        stmt = stmt.where(Lease.id != exclude_id)
    return db.scalar(stmt) is not None


@router.post("/contratos", status_code=201)
def create_lease(data: LeaseIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    unit = get_or_404(db, Unit, data.unit_id)
    scope.require_asset("alquiler.editar", unit.asset_id)
    asset: Asset = unit.asset
    if asset.modalidad not in MODALIDADES_CONTRATO:
        bad_request("Este activo no admite contratos de alquiler residencial")
    if data.estado not in ESTADOS_CONTRATO:
        bad_request("Estado de contrato no válido")
    if data.fecha_fin and data.fecha_fin <= data.fecha_inicio:
        bad_request("La fecha de fin debe ser posterior a la de inicio")
    if _overlaps(db, unit.id, data.fecha_inicio, data.fecha_fin):
        bad_request("La unidad ya tiene un contrato vigente o en borrador en esas fechas")

    if data.tenant_id:
        tenant = get_or_404(db, Contact, data.tenant_id)
        if tenant.company_id != asset.company_id or tenant.tipo != "inquilino":
            bad_request("El inquilino no pertenece a la sociedad del activo")
    elif data.tenant:
        tenant = Contact(company_id=asset.company_id, tipo="inquilino", **data.tenant.model_dump())
        db.add(tenant)
        db.flush()
    else:
        bad_request("Indique tenant_id o los datos del inquilino")

    lease = Lease(**data.model_dump(exclude={"tenant", "tenant_id"}), tenant_id=tenant.id)
    db.add(lease)
    if lease.estado == "vigente" and lease.fecha_inicio <= date.today():
        unit.estado = "ocupada"
    db.flush()
    audit(db, scope.user, "crear", "contrato", lease.id, {"unidad": unit.codigo, "renta": data.renta_mensual})
    db.commit()
    db.refresh(lease)
    return _lease_out(lease)


@router.put("/contratos/{lid}")
def update_lease(lid: int, data: LeaseUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    lease = get_or_404(db, Lease, lid)
    scope.require_asset("alquiler.editar", lease.unit.asset_id)
    if data.estado is not None and data.estado not in ESTADOS_CONTRATO:
        bad_request("Estado de contrato no válido")
    if "fecha_fin" in data.model_fields_set and data.fecha_fin is not None:
        if data.fecha_fin <= lease.fecha_inicio:
            bad_request("La fecha de fin debe ser posterior a la de inicio")
        if _overlaps(db, lease.unit_id, lease.fecha_inicio, data.fecha_fin, exclude_id=lid):
            bad_request("Las nuevas fechas solapan con otro contrato")
    ch = apply(lease, data)
    if "estado" in ch:
        if lease.estado in ("finalizado", "rescindido") and lease.unit.estado == "ocupada":
            lease.unit.estado = "disponible"
        elif lease.estado == "vigente" and lease.fecha_inicio <= date.today():
            lease.unit.estado = "ocupada"
    audit(db, scope.user, "editar", "contrato", lid, ch)
    db.commit()
    return _lease_out(lease)


@router.post("/contratos/{lid}/actualizar-renta")
def update_rent(lid: int, data: RentUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Actualización anual de renta (IRAV / IPC / pactada). El % lo indica el usuario."""
    lease = get_or_404(db, Lease, lid)
    scope.require_asset("alquiler.editar", lease.unit.asset_id)
    if lease.estado != "vigente":
        bad_request("Solo se actualiza la renta de contratos vigentes")
    old = _money(lease.renta_mensual)
    new = _money(old * (1 + Decimal(str(data.porcentaje)) / 100))
    lease.renta_mensual = new
    audit(db, scope.user, "actualizar_renta", "contrato", lid,
          {"anterior": float(old), "nueva": float(new), "porcentaje": data.porcentaje,
           "indice": lease.indice_actualizacion, "motivo": data.motivo})
    db.commit()
    return _lease_out(lease)


# --------------------------------------------------------------------------- recibos
@router.get("/recibos")
def list_charges(asset_id: int | None = None, periodo: str | None = None, estado: str | None = None,
                 scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ids = scope.asset_ids("alquiler.ver")
    stmt = scoped(select(Charge).join(Lease).join(Unit), Unit.asset_id, ids)
    if asset_id:
        stmt = stmt.where(Unit.asset_id == asset_id)
    if periodo:
        stmt = stmt.where(Charge.periodo == periodo)
    if estado:
        stmt = stmt.where(Charge.estado == estado)
    stmt = stmt.order_by(Charge.periodo.desc(), Unit.codigo)
    return [_charge_out(c) for c in db.scalars(stmt.limit(2000))]


@router.post("/recibos/generar")
def generate_charges(data: ChargeGenerate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Emite el recibo de renta del mes para cada contrato vigente (prorrateado si entra/sale a mitad de mes).
    Idempotente: no duplica recibos ya emitidos."""
    y, m = map(int, data.periodo.split("-"))
    days = calendar.monthrange(y, m)[1]
    first, last = date(y, m, 1), date(y, m, days)
    ids = scope.asset_ids("alquiler.editar")
    if data.asset_id:
        scope.require_asset("alquiler.editar", data.asset_id)
        ids = {data.asset_id}
    stmt = scoped(select(Lease).join(Unit), Unit.asset_id, ids).where(
        Lease.estado == "vigente", Lease.fecha_inicio <= last,
        or_(Lease.fecha_fin.is_(None), Lease.fecha_fin >= first))
    created = 0
    for lease in db.scalars(stmt):
        exists = db.scalar(select(Charge.id).where(Charge.lease_id == lease.id, Charge.periodo == data.periodo,
                                                   Charge.concepto == "Renta"))
        if exists:
            continue
        start = max(first, lease.fecha_inicio)
        end = min(last, lease.fecha_fin) if lease.fecha_fin else last
        dias = (end - start).days + 1
        importe = _money(lease.renta_mensual) if dias == days else _money(
            Decimal(str(lease.renta_mensual)) * dias / days)
        db.add(Charge(lease_id=lease.id, periodo=data.periodo, concepto="Renta", importe=importe,
                      fecha_vencimiento=date(y, m, min(lease.dia_pago, days))))
        created += 1
    audit(db, scope.user, "generar_recibos", "recibo", None, {"periodo": data.periodo, "creados": created})
    db.commit()
    return {"creados": created}


@router.post("/recibos/{rid}/cobro")
def register_payment(rid: int, data: Payment, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    c = get_or_404(db, Charge, rid)
    scope.require_asset("alquiler.editar", c.lease.unit.asset_id)
    if c.estado in ("pagado", "anulado"):
        bad_request(f"El recibo ya está {c.estado}")
    pagado = _money(c.importe_pagado) + _money(data.importe)
    if pagado > _money(c.importe):
        bad_request("El cobro supera el importe pendiente")
    c.importe_pagado = pagado
    c.fecha_pago = data.fecha_pago or date.today()
    c.estado = "pagado" if pagado == _money(c.importe) else "parcial"
    audit(db, scope.user, "cobro", "recibo", rid, {"importe": data.importe})
    db.commit()
    return _charge_out(c)


@router.post("/recibos/{rid}/anular")
def cancel_charge(rid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    c = get_or_404(db, Charge, rid)
    scope.require_asset("alquiler.editar", c.lease.unit.asset_id)
    if _money(c.importe_pagado) > 0:
        bad_request("No se puede anular un recibo con cobros registrados")
    c.estado = "anulado"
    audit(db, scope.user, "anular", "recibo", rid)
    db.commit()
    return _charge_out(c)
