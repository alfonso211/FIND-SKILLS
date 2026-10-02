"""Cuadro de mando por activo."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MODALIDADES, Asset, Charge, Lease, Reservation, Unit, WorkOrder
from ..security import Scope, get_scope
from ..utils import scoped

router = APIRouter(prefix="/api", tags=["panel"])


@router.get("/panel")
def panel(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    hoy = date.today()
    ini_mes = hoy.replace(day=1)
    fin_mes = (ini_mes + timedelta(days=32)).replace(day=1)
    ids = scope.asset_ids("activos.ver")
    assets = list(db.scalars(scoped(select(Asset).where(Asset.activo), Asset.id, ids).order_by(Asset.codigo)))
    out = []
    for a in assets:
        estados = dict(db.execute(select(Unit.estado, func.count()).where(Unit.asset_id == a.id)
                                  .group_by(Unit.estado)).all())
        total = sum(estados.values())
        operativas = total - estados.get("fuera_servicio", 0)
        k = {"id": a.id, "codigo": a.codigo, "nombre": a.nombre, "sociedad": a.company.nombre,
             "modalidad": a.modalidad, "modalidad_nombre": MODALIDADES.get(a.modalidad, a.modalidad),
             "unidades": total, "estados": estados}
        ver_fin = scope.can_asset("finanzas.ver", a.id)

        if a.modalidad == "apartamentos_turisticos" and scope.can_asset("reservas.ver", a.id):
            base = select(func.count()).select_from(Reservation).join(Unit).where(Unit.asset_id == a.id)
            ocupadas = db.scalar(base.where(Reservation.estado.in_(("confirmada", "checkin")),
                                            Reservation.fecha_entrada <= hoy, Reservation.fecha_salida > hoy))
            k["ocupacion_hoy"] = round(100 * ocupadas / operativas, 1) if operativas else 0
            k["llegadas_hoy"] = db.scalar(base.where(Reservation.fecha_entrada == hoy,
                                                     Reservation.estado.in_(("confirmada", "checkin"))))
            k["salidas_hoy"] = db.scalar(base.where(Reservation.fecha_salida == hoy,
                                                    Reservation.estado.in_(("checkin", "checkout"))))
            if ver_fin:
                k["produccion_mes"] = float(db.scalar(
                    select(func.coalesce(func.sum(Reservation.importe_total), 0)).join(Unit).where(
                        Unit.asset_id == a.id, Reservation.estado.not_in(("cancelada",)),
                        Reservation.fecha_entrada >= ini_mes, Reservation.fecha_entrada < fin_mes)) or 0)

        if a.modalidad == "alquiler_residencial" and scope.can_asset("alquiler.ver", a.id):
            vig = db.scalar(select(func.count()).select_from(Lease).join(Unit).where(
                Unit.asset_id == a.id, Lease.estado == "vigente"))
            k["contratos_vigentes"] = vig
            k["ocupacion_hoy"] = round(100 * vig / operativas, 1) if operativas else 0
            if ver_fin:
                k["renta_mensual"] = float(db.scalar(select(func.coalesce(func.sum(Lease.renta_mensual), 0))
                                                     .join(Unit).where(Unit.asset_id == a.id,
                                                                       Lease.estado == "vigente")) or 0)
                k["deuda_vencida"] = float(db.scalar(
                    select(func.coalesce(func.sum(Charge.importe - Charge.importe_pagado), 0))
                    .join(Lease).join(Unit).where(Unit.asset_id == a.id, Charge.estado.in_(("pendiente", "parcial")),
                                                  Charge.fecha_vencimiento < hoy)) or 0)

        if scope.can_asset("mantenimiento.ver", a.id):
            wo = select(func.count()).select_from(WorkOrder).where(
                WorkOrder.asset_id == a.id, WorkOrder.estado.in_(("abierta", "asignada", "en_curso",
                                                                  "pendiente_material")))
            k["ot_abiertas"] = db.scalar(wo)
            k["ot_urgentes"] = db.scalar(wo.where(WorkOrder.prioridad == "urgente"))
        out.append(k)
    return {"fecha": hoy.isoformat(), "activos": out}
