"""Recibos mensuales de los contratos de alquiler (viviendas, locales y plazas de garaje) y su cobro.

Lo comparten el alquiler residencial y el alquiler de plazas de garaje a clientes externos."""
import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .facturacion import datos_cliente, emitir, iva_contrato, linea, lineas_servicios, mes_es, serie_activo
from .models import MODALIDADES_RESERVA, Charge, Lease, Unit
from .security import audit


def dinero(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def generar(db: Session, lease: Lease, periodo: str) -> Charge | None:
    """Recibo de renta del mes (prorrateado si el contrato empieza o termina a mitad de mes).
    Idempotente: si ya existe no hace nada. La renta del contrato es sin IVA; el recibo lo incluye."""
    y, m = map(int, periodo.split("-"))
    dias_mes = calendar.monthrange(y, m)[1]
    first, last = date(y, m, 1), date(y, m, dias_mes)
    if lease.fecha_inicio > last or (lease.fecha_fin and lease.fecha_fin < first):
        return None
    if db.scalar(select(Charge.id).where(Charge.lease_id == lease.id, Charge.periodo == periodo,
                                         Charge.concepto == "Renta")):
        return None
    start = max(first, lease.fecha_inicio)
    end = min(last, lease.fecha_fin) if lease.fecha_fin else last
    dias = (end - start).days + 1
    base = dinero(lease.renta_mensual) if dias == dias_mes else dinero(
        Decimal(str(lease.renta_mensual)) * dias / dias_mes)
    iva = iva_contrato(lease)
    c = Charge(lease_id=lease.id, periodo=periodo, concepto="Renta", importe=dinero(base * (1 + iva / 100)),
               tipo_iva=iva, fecha_vencimiento=max(start, date(y, m, min(lease.dia_pago, dias_mes))))
    db.add(c)
    return c


def periodos(desde: date, hasta: date) -> list[str]:
    out, y, m = [], desde.year, desde.month
    while (y, m) <= (hasta.year, hasta.month):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def es_garaje_turistico(lease: Lease) -> bool:
    return lease.unit.uso == "garaje" and lease.unit.asset.modalidad in MODALIDADES_RESERVA


def garajes_al_dia(db: Session, asset_ids: set[int] | None = None, hoy: date | None = None) -> int:
    """Emite los recibos que falten, hasta el mes en curso, de los alquileres de plazas de garaje vigentes de los
    apartamentos turísticos. Así nunca se queda un mes sin recibo aunque nadie lo genere a mano."""
    hoy = hoy or date.today()
    stmt = select(Lease).join(Unit).where(Lease.estado == "vigente", Unit.uso == "garaje", Lease.fecha_inicio <= hoy)
    if asset_ids is not None:
        stmt = stmt.where(Unit.asset_id.in_(asset_ids or {-1}))
    creados = 0
    for lease in db.scalars(stmt):
        if not es_garaje_turistico(lease):
            continue
        fin = min(hoy, lease.fecha_fin) if lease.fecha_fin else hoy
        for p in periodos(lease.fecha_inicio, fin):
            creados += generar(db, lease, p) is not None
    if creados:
        db.flush()
    return creados


def cobrar(db: Session, user, c: Charge, data):
    """Registra el cobro de un recibo (o solo servicios) y emite la factura con la serie del activo."""
    from fastapi import HTTPException
    if c.estado in ("pagado", "anulado") and data.importe:
        raise HTTPException(400, f"El recibo ya está {c.estado}")
    lease, unit = c.lease, c.lease.unit
    asset = unit.asset
    lineas = []
    fecha_op = data.fecha_pago or date.today()
    if data.importe:
        pagado = dinero(c.importe_pagado) + dinero(data.importe)
        if pagado > dinero(c.importe):
            raise HTTPException(400, "El cobro supera el importe pendiente")
        c.importe_pagado = pagado
        c.fecha_pago = fecha_op
        c.estado = "pagado" if pagado == dinero(c.importe) else "parcial"
        if es_garaje_turistico(lease):
            plaza = unit.codigo.split("-")[-1]
            concepto = (f"Alquiler de plaza de garaje · {mes_es(c.periodo)} · {asset.nombre} · "
                        f"{unit.bloque or 'Garaje'} plaza {plaza}"
                        + (f" · Matrícula {lease.matricula}" if lease.matricula else ""))
        else:
            concepto = (f"{c.concepto} {mes_es(c.periodo)} · {unit.uso.capitalize()} {unit.codigo} · "
                        f"{asset.direccion or asset.nombre}")
        concepto += f" · Contrato {lease.referencia}" if lease.referencia else ""
        if c.estado == "parcial" or dinero(data.importe) < dinero(c.importe):
            concepto = "Pago parcial · " + concepto
        lineas.append(linea("renta", concepto, data.importe,
                            c.tipo_iva if c.tipo_iva is not None else iva_contrato(lease)))
    lineas += lineas_servicios(db, asset.id, data.servicios)
    f = emitir(db, user, company=asset.company, serie=serie_activo(asset), asset_id=asset.id,
               cliente=datos_cliente(lease.tenant, data.facturar_a), contact_id=lease.tenant_id, lineas=lineas,
               fecha_operacion=fecha_op, forma_pago=data.forma_pago, charge_id=c.id)
    audit(db, user, "cobro", "recibo", c.id, {"importe": data.importe, "factura": f.codigo})
    return f


def solapa_contrato(db: Session, unit_id: int, inicio: date, fin: date | None, excluir: int | None = None) -> bool:
    stmt = select(Lease.id).where(Lease.unit_id == unit_id, Lease.estado.in_(("borrador", "vigente")),
                                  or_(Lease.fecha_fin.is_(None), Lease.fecha_fin >= inicio))
    if fin is not None:
        stmt = stmt.where(Lease.fecha_inicio <= fin)
    if excluir:
        stmt = stmt.where(Lease.id != excluir)
    return db.scalar(stmt) is not None


def anular_contrato(db: Session, user, lease: Lease, motivo: str) -> None:
    """Anula un contrato de alquiler (vivienda, local o plaza de garaje) hecho por error o que no sigue adelante.
    No se anula si tiene cobros o facturas sin rectificar: entonces se da de baja o se rescinde. Los recibos
    pendientes se anulan y la unidad queda disponible."""
    from .models import Invoice
    from .utils import bad_request
    if lease.estado not in ("borrador", "vigente"):
        bad_request("Solo se anulan contratos en borrador o vigentes")
    recibos = list(db.scalars(select(Charge).where(Charge.lease_id == lease.id)))
    if any(dinero(c.importe_pagado) > 0 for c in recibos):
        bad_request("El contrato tiene recibos cobrados: no se puede anular. Dele de baja (o rescíndalo) con su fecha.")
    facturado = sum((dinero(f.total) for f in db.scalars(select(Invoice).where(
        Invoice.charge_id.in_([c.id for c in recibos] or [-1])))), Decimal(0))
    if facturado:
        bad_request(f"El contrato tiene facturas por {facturado:.2f} €: emita antes la rectificativa y vuelva a anularlo.")
    for c in recibos:
        if c.estado in ("pendiente", "parcial"):
            c.estado = "anulado"
    lease.estado = "anulado"
    if lease.unit.estado == "ocupada":
        lease.unit.estado = "disponible"
    lease.notas = f"{lease.notas + chr(10) if lease.notas else ''}Anulado el {date.today():%d/%m/%Y}: {motivo}"
    audit(db, user, "anular", "contrato", lease.id, {"motivo": motivo})
