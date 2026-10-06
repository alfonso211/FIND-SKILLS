"""Cuadro de mando por activo."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import hitos
from ..database import get_db
from ..facturacion import bases_por_tipo
from ..models import MODALIDADES, Asset, Charge, Invoice, Lease, Reservation, Unit, WorkOrder
from ..security import Scope, get_scope
from . import historico
from .mantenimiento import ABIERTAS
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
        # estado de los alojamientos: las plazas de garaje no computan en los datos del edificio
        estados = dict(db.execute(select(Unit.estado, func.count()).where(Unit.asset_id == a.id, Unit.uso != "garaje")
                                  .group_by(Unit.estado)).all())
        total = sum(estados.values())
        operativas = total - estados.get("fuera_servicio", 0)
        k = {"id": a.id, "codigo": a.codigo, "nombre": a.nombre, "sociedad": a.company.nombre,
             "propietaria": a.propietaria.nombre if a.propietaria else a.company.nombre,
             "modalidad": a.modalidad, "modalidad_nombre": MODALIDADES.get(a.modalidad, a.modalidad),
             "unidades": total, "estados": estados}
        ver_fin = scope.can_asset("finanzas.ver", a.id)

        if a.modalidad == "apartamentos_turisticos" and scope.can_asset("reservas.ver", a.id):
            # la ocupación es de los alojamientos; las plazas de garaje se cuentan aparte
            base = select(func.count()).select_from(Reservation).join(Unit).where(Unit.asset_id == a.id,
                                                                                  Unit.uso != "garaje")
            # los alojados con la salida ya pasada (estancia vencida) siguen ocupando hasta el check-out
            hoy_activas = (Reservation.estado.in_(("confirmada", "checkin")), Reservation.fecha_entrada <= hoy,
                           or_(Reservation.fecha_salida > hoy, Reservation.estado == "checkin"))
            ocupadas = db.scalar(base.where(*hoy_activas))
            alojamientos = db.scalar(select(func.count()).select_from(Unit).where(
                Unit.asset_id == a.id, Unit.uso != "garaje", Unit.estado != "fuera_servicio"))
            k["ocupacion_hoy"] = round(100 * ocupadas / alojamientos, 1) if alojamientos else 0
            garajes = db.scalar(select(func.count()).select_from(Unit).where(Unit.asset_id == a.id, Unit.uso == "garaje"))
            if garajes:
                por_reserva = set(db.scalars(select(Reservation.unit_id).join(Unit).where(
                    Unit.asset_id == a.id, Unit.uso == "garaje", *hoy_activas)))
                por_meses = set(db.scalars(select(Lease.unit_id).join(Unit).where(  # clientes externos
                    Unit.asset_id == a.id, Unit.uso == "garaje", Lease.estado == "vigente", Lease.fecha_inicio <= hoy,
                    or_(Lease.fecha_fin.is_(None), Lease.fecha_fin >= hoy))))
                k["garajes_ocupados"] = len(por_reserva | por_meses)
                k["garajes_alquiler_mensual"] = len(por_meses)
                k["garajes"] = garajes
            k["estancias_vencidas"] = db.scalar(base.where(Reservation.estado == "checkin",  # salida pasada, siguen
                                                           Reservation.fecha_salida < hoy))
            k["llegadas_hoy"] = db.scalar(base.where(Reservation.fecha_entrada == hoy,
                                                     Reservation.estado.in_(("confirmada", "checkin"))))
            k["salidas_hoy"] = db.scalar(base.where(Reservation.fecha_salida == hoy,
                                                    Reservation.estado.in_(("checkin", "checkout"))))

        usos = dict(db.execute(select(Unit.uso, func.count()).where(Unit.asset_id == a.id)
                               .group_by(Unit.uso)).all())
        k["usos"] = usos

        if a.modalidad == "alquiler_residencial" and scope.can_asset("alquiler.ver", a.id):
            alquiladas = dict(db.execute(select(Unit.uso, func.count(func.distinct(Unit.id))).join(Lease).where(
                Unit.asset_id == a.id, Lease.estado == "vigente").group_by(Unit.uso)).all())
            k["contratos_vigentes"] = sum(alquiladas.values())
            k["alquiladas_por_uso"] = alquiladas
            # ocupación sobre viviendas (los garajes/trasteros se informan aparte)
            base_uso = "vivienda" if usos.get("vivienda") else None
            denom = usos.get(base_uso, 0) if base_uso else operativas
            num = alquiladas.get(base_uso, 0) if base_uso else sum(n for u, n in alquiladas.items() if u != "garaje")
            k["ocupacion_hoy"] = round(100 * num / denom, 1) if denom else 0
            if ver_fin:
                k["renta_mensual"] = float(db.scalar(select(func.coalesce(func.sum(Lease.renta_mensual), 0))
                                                     .join(Unit).where(Unit.asset_id == a.id,
                                                                       Lease.estado == "vigente")) or 0)
                k["deuda_vencida"] = float(db.scalar(
                    select(func.coalesce(func.sum(Charge.importe - Charge.importe_pagado), 0))
                    .join(Lease).join(Unit).where(Unit.asset_id == a.id, Charge.estado.in_(("pendiente", "parcial")),
                                                  Charge.fecha_vencimiento < hoy)) or 0)

        if ver_fin:  # producción = facturado en el mes (fecha de factura), sin IVA y sin las plazas de garaje
            base = garaje = 0.0
            for f, bases in bases_por_tipo(db, list(db.scalars(select(Invoice).where(
                    Invoice.asset_id == a.id, Invoice.fecha_expedicion >= ini_mes,
                    Invoice.fecha_expedicion < fin_mes)))):
                base += float(f.base_imponible)
                garaje += bases.get("garaje", 0)
            externo = historico.mensual(db, [a.id], ini_mes, fin_mes - timedelta(days=1)).get(
                (a.id, f"{ini_mes:%Y-%m}"), {}).get("base", 0)
            k["produccion_mes"] = round(base - garaje + externo, 2)
            k["produccion_mes_externa"] = round(externo, 2)  # parte importada del programa anterior (SYADE)
            k["garajes_facturado_mes"] = round(garaje, 2)

        if scope.can_asset("mantenimiento.ver", a.id):
            wo = select(func.count()).select_from(WorkOrder).where(
                WorkOrder.asset_id == a.id, WorkOrder.estado.in_(ABIERTAS))
            k["ot_abiertas"] = db.scalar(wo)
            k["ot_urgentes"] = db.scalar(wo.where(WorkOrder.prioridad == "urgente"))
            k["ot_pendientes_cierre"] = db.scalar(wo.where(WorkOrder.estado == "pendiente_cierre"))
        out.append(k)
    return {"fecha": hoy.isoformat(), "activos": out, "hitos": hitos.para(scope, hoy)}
