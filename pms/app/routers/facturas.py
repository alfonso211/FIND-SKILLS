"""Facturas emitidas: consulta, PDF, rectificativas y libro registro para la gestoría.
Las facturas se emiten solas al registrar un cobro (recibos de alquiler y reservas turísticas)."""
import csv
import io
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from .. import factura_pdf
from ..database import get_db
from ..facturacion import (FORMAS_PAGO, datos_cliente, desglose, dinero, emitir, factura_out, lineas_de,
                           lineas_servicios, serie_activo)
from ..models import Asset, Charge, Company, Contact, Invoice, Reservation, Service
from ..schemas import InvoiceRectify, ServiceIn, ServiceInvoiceIn
from ..security import Scope, audit, get_scope
from ..utils import apply, bad_request, get_or_404, scoped

router = APIRouter(prefix="/api/facturas", tags=["facturación"])
router_servicios = APIRouter(prefix="/api/servicios", tags=["facturación"])


def _filtrar(scope: Scope, asset_id, anio, serie, q, company_id=None):
    stmt = scoped(select(Invoice), Invoice.asset_id, scope.asset_ids("facturas.ver"))
    if asset_id:
        stmt = stmt.where(Invoice.asset_id == asset_id)
    if company_id:
        stmt = stmt.where(Invoice.company_id == company_id)
    if anio:
        stmt = stmt.where(Invoice.anio == anio)
    if serie:
        stmt = stmt.where(Invoice.serie == serie.upper())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Invoice.codigo.ilike(like), cast(Invoice.cliente, String).ilike(like),
                              Invoice.concepto.ilike(like)))
    return stmt


def _rectificadas(db: Session, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    return dict(db.execute(select(Invoice.rectifica_id, Invoice.codigo).where(Invoice.rectifica_id.in_(ids))).all())


@router.get("")
def list_invoices(asset_id: int | None = None, anio: int | None = None, serie: str | None = None,
                  q: str | None = None, reservation_id: int | None = None, charge_id: int | None = None,
                  scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    stmt = _filtrar(scope, asset_id, anio, serie, q)
    if reservation_id:
        stmt = stmt.where(Invoice.reservation_id == reservation_id)
    if charge_id:
        stmt = stmt.where(Invoice.charge_id == charge_id)
    rows = list(db.scalars(stmt.order_by(Invoice.fecha_expedicion.desc(), Invoice.id.desc()).limit(2000)))
    rect = _rectificadas(db, [f.id for f in rows])
    return [factura_out(f, rect.get(f.id)) for f in rows]


@router.get("/libro.csv")
def invoice_book(anio: int | None = None, asset_id: int | None = None, company_id: int | None = None,
                 serie: str | None = None, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Libro registro de facturas emitidas (CSV para Excel / gestoría)."""
    scope.require_any("facturas.ver")
    rows = db.scalars(_filtrar(scope, asset_id, anio, serie, None, company_id)
                      .order_by(Invoice.company_id, Invoice.serie, Invoice.anio, Invoice.numero))
    codigos = dict(db.execute(select(Invoice.id, Invoice.codigo)).all())
    num = lambda x: f"{Decimal(str(x)):.2f}".replace(".", ",")  # noqa: E731
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Emisor", "CIF emisor", "Serie", "Número", "Factura", "Fecha expedición", "Fecha operación", "Tipo",
                "Rectifica a", "Cliente", "NIF cliente", "Domicilio cliente", "Concepto", "Base imponible", "% IVA",
                "Cuota IVA", "Total", "Exención", "Forma de pago"])
    for f in rows:  # una fila por factura y tipo de IVA (con varios tipos, una fila por cada uno)
        for d in desglose(lineas_de(f)):
            w.writerow([f.emisor["nombre"], f.emisor["nif"], f.serie, f.numero, f.codigo,
                        f.fecha_expedicion.strftime("%d/%m/%Y"), f.fecha_operacion.strftime("%d/%m/%Y"), f.tipo,
                        codigos.get(f.rectifica_id, ""), f.cliente.get("nombre"), f.cliente.get("nif") or "",
                        f.cliente.get("domicilio") or "", f.concepto.replace("\n", " / "), num(d["base"]),
                        num(d["tipo_iva"]), num(d["cuota"]), num(d["base"] + d["cuota"]),
                        "Exenta" if d["tipo_iva"] == 0 else "", FORMAS_PAGO.get(f.forma_pago or "", f.forma_pago or "")])
    nombre = f"libro_facturas_emitidas_{anio or 'todas'}.csv"
    return Response("﻿" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


def _factura(db: Session, scope: Scope, fid: int, perm: str = "facturas.ver") -> Invoice:
    f = get_or_404(db, Invoice, fid)
    scope.require_asset(perm, f.asset_id)
    return f


@router.get("/{fid}")
def get_invoice(fid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    f = _factura(db, scope, fid)
    return factura_out(f, _rectificadas(db, [f.id]).get(f.id))


@router.get("/{fid}/pdf")
def invoice_pdf(fid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    f = _factura(db, scope, fid)
    original = db.get(Invoice, f.rectifica_id) if f.rectifica_id else None
    pdf = factura_pdf.generar(f, f.asset, original)
    nombre = f"Factura_{f.codigo.replace('/', '-')}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@router.post("/{fid}/rectificar", status_code=201)
def rectify_invoice(fid: int, data: InvoiceRectify, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Anula una factura con una rectificativa (importes en negativo, serie R) y deshace el cobro que la originó."""
    f = _factura(db, scope, fid, "facturas.rectificar")
    if f.tipo == "rectificativa":
        bad_request("Una factura rectificativa no se puede rectificar")
    if db.scalar(select(Invoice.id).where(Invoice.rectifica_id == f.id)):
        bad_request(f"La factura {f.codigo} ya está rectificada")
    # se deshace el cobro de la renta o del alojamiento (los servicios no cuentan en lo cobrado)
    cobrado = lambda tipo: sum((dinero(x["total"]) for x in lineas_de(f) if x["tipo"] == tipo), Decimal(0))  # noqa: E731
    if f.charge_id and cobrado("renta"):
        c = db.get(Charge, f.charge_id)
        c.importe_pagado = dinero(c.importe_pagado) - cobrado("renta")
        c.estado = "pendiente" if c.importe_pagado <= 0 else "parcial"
        if c.importe_pagado <= 0:
            c.fecha_pago = None
    if f.reservation_id and cobrado("alojamiento"):
        r = db.get(Reservation, f.reservation_id)
        r.importe_pagado = max(Decimal(0), dinero(r.importe_pagado) - cobrado("alojamiento"))
    rect = emitir(db, scope.user, company=db.get(Company, f.company_id), serie=f"{f.serie}R", asset_id=f.asset_id,
                  cliente=f.cliente, contact_id=f.contact_id, lineas=None, fecha_operacion=f.fecha_operacion,
                  forma_pago=f.forma_pago, charge_id=f.charge_id, reservation_id=f.reservation_id, rectifica=f,
                  motivo=data.motivo, fecha=date.today())
    audit(db, scope.user, "rectificar", "factura", f.id, {"factura": f.codigo, "rectificativa": rect.codigo,
                                                          "motivo": data.motivo})
    db.commit()
    return factura_out(rect)


# --------------------------------------------------------------------------- factura de servicios
@router.post("/servicios", status_code=201)
def service_invoice(data: ServiceInvoiceIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Factura solo de servicios (21 % salvo que se indique otro IVA): a un huésped, a un inquilino o a un
    cliente externo (p.ej. alquiler de una plaza de aparcamiento)."""
    if not (scope.can_asset("reservas.editar", data.asset_id) or scope.can_asset("alquiler.editar", data.asset_id)):
        raise HTTPException(403, "Sin permiso para facturar en este activo")
    a = get_or_404(db, Asset, data.asset_id)
    r = None
    if data.reservation_id:
        r = get_or_404(db, Reservation, data.reservation_id)
        if r.unit.asset_id != a.id:
            bad_request("La reserva no es de este activo")
        contacto = r.guest
    elif data.contact_id:
        contacto = get_or_404(db, Contact, data.contact_id)
        if contacto.company_id != a.company_id:
            bad_request("El cliente no pertenece a la sociedad del activo")
    else:
        contacto = None
        if not data.cliente:
            bad_request("Indique el cliente (nombre, NIF y domicilio) o la reserva")
    f = emitir(db, scope.user, company=a.company, serie=serie_activo(a), asset_id=a.id,
               cliente=datos_cliente(contacto, data.cliente), contact_id=contacto.id if contacto else None,
               lineas=lineas_servicios(db, a.id, data.lineas), fecha_operacion=data.fecha_operacion or date.today(),
               forma_pago=data.forma_pago, reservation_id=r.id if r else None)
    audit(db, scope.user, "factura_servicios", "factura", f.id, {"factura": f.codigo, "total": float(f.total)})
    db.commit()
    return factura_out(f)


# --------------------------------------------------------------------------- catálogo de servicios
def _puede_catalogo(scope: Scope, asset_id: int | None) -> None:
    ok = scope.can_asset("activos.editar", asset_id) if asset_id else scope.is_group_level("activos.editar")
    if not ok:
        raise HTTPException(403, "Sin permiso para gestionar el catálogo de servicios" +
                            ("" if asset_id else " de todos los activos"))


@router_servicios.get("")
def list_services(asset_id: int | None = None, todos: bool = False, scope: Scope = Depends(get_scope),
                  db: Session = Depends(get_db)):
    """Servicios disponibles: los generales y los del activo indicado (con `todos`, también los inactivos)."""
    stmt = select(Service).order_by(Service.nombre, Service.unidad)
    if asset_id:
        scope.require_asset("activos.ver", asset_id)
        stmt = stmt.where(or_(Service.asset_id.is_(None), Service.asset_id == asset_id))
    else:
        ids = scope.asset_ids("activos.ver")
        if ids is not None:
            stmt = stmt.where(or_(Service.asset_id.is_(None), Service.asset_id.in_(ids or {-1})))
    if not todos:
        stmt = stmt.where(Service.activo)
    return [s.to_dict() for s in db.scalars(stmt)]


@router_servicios.post("", status_code=201)
def create_service(data: ServiceIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _puede_catalogo(scope, data.asset_id)
    s = Service(**data.model_dump())
    db.add(s)
    db.flush()
    audit(db, scope.user, "crear", "servicio", s.id, data.model_dump())
    db.commit()
    return s.to_dict()


@router_servicios.put("/{sid}")
def update_service(sid: int, data: ServiceIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    s = get_or_404(db, Service, sid)
    _puede_catalogo(scope, s.asset_id)
    _puede_catalogo(scope, data.asset_id)
    ch = apply(s, data)
    audit(db, scope.user, "editar", "servicio", sid, ch)
    db.commit()
    return s.to_dict()
