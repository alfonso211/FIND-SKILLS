"""Facturas emitidas: consulta, PDF, rectificativas y libro registro para la gestoría.
Las facturas se emiten solas al registrar un cobro (recibos de alquiler y reservas turísticas)."""
import csv
import io
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Response
from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from .. import factura_pdf
from ..database import get_db
from ..facturacion import FORMAS_PAGO, dinero, emitir, factura_out
from ..models import Charge, Company, Invoice, Reservation
from ..schemas import InvoiceRectify
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404, scoped

router = APIRouter(prefix="/api/facturas", tags=["facturación"])


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
    for f in rows:
        w.writerow([f.emisor["nombre"], f.emisor["nif"], f.serie, f.numero, f.codigo,
                    f.fecha_expedicion.strftime("%d/%m/%Y"), f.fecha_operacion.strftime("%d/%m/%Y"), f.tipo,
                    codigos.get(f.rectifica_id, ""), f.cliente.get("nombre"), f.cliente.get("nif") or "",
                    f.cliente.get("domicilio") or "", f.concepto, num(f.base_imponible), num(f.tipo_iva),
                    num(f.cuota_iva), num(f.total), "Exenta" if f.exencion else "",
                    FORMAS_PAGO.get(f.forma_pago or "", f.forma_pago or "")])
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
    total = dinero(f.total)
    if f.charge_id:
        c = db.get(Charge, f.charge_id)
        c.importe_pagado = dinero(c.importe_pagado) - total
        c.estado = "pendiente" if c.importe_pagado <= 0 else "parcial"
        if c.importe_pagado <= 0:
            c.fecha_pago = None
    if f.reservation_id:
        r = db.get(Reservation, f.reservation_id)
        r.importe_pagado = max(Decimal(0), dinero(r.importe_pagado) - total)
    rect = emitir(db, scope.user, company=db.get(Company, f.company_id), serie=f"{f.serie}R", asset_id=f.asset_id,
                  cliente=f.cliente, contact_id=f.contact_id, concepto=f"Anulación de la factura {f.codigo}. {f.concepto}",
                  total=None, tipo_iva=f.tipo_iva, fecha_operacion=f.fecha_operacion, forma_pago=f.forma_pago,
                  charge_id=f.charge_id, reservation_id=f.reservation_id, rectifica=f, motivo=data.motivo,
                  fecha=date.today())
    audit(db, scope.user, "rectificar", "factura", f.id, {"factura": f.codigo, "rectificativa": rect.codigo,
                                                          "motivo": data.motivo})
    db.commit()
    return factura_out(rect)
