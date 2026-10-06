"""Documentos recibidos (carpeta de cada activo) y cuenta de gastos.

Recepción y dirección suben los documentos escaneados que llegan (facturas, tickets, cartas…): se guardan cifrados
en la carpeta del activo. Si el documento es un gasto, se anota en la cuenta de gastos del activo, general o de un
apartamento concreto. Cada activo ve solo lo suyo; quien gestiona la sociedad o el grupo, todo. Limpieza y
mantenimiento no tienen acceso.
"""
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import adjuntos, documentos
from ..database import get_db
from ..facturacion import FORMAS_PAGO, dinero
from ..models import (AMBITOS_GASTO, CATEGORIAS_GASTO, TIPOS_DOCUMENTO, Asset, Expense, ReceivedDocument, Supplier,
                      Unit, User)
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404, scoped

router = APIRouter(prefix="/api", tags=["documentos y gastos"])

IVAS = (0, 4, 5, 10, 21)
# Cómo se paga la factura del proveedor (obligatorio): por transferencia nuestra o cargada en cuenta por él
FORMAS_PAGO_GASTO = {"transferencia": "Transferencia", "domiciliacion": "Cargo en cuenta (domiciliación)",
                     **{k: v for k, v in FORMAS_PAGO.items() if k not in ("transferencia", "domiciliacion")}}


class ExpenseIn(BaseModel):
    asset_id: int | None = None  # al crear el gasto sin documento
    documento_id: int | None = None
    fecha: date
    categoria: str
    concepto: str = Field(min_length=2, max_length=300)
    ambito: str = "general"
    unit_id: int | None = None
    ambito_detalle: str | None = Field(default=None, max_length=200)
    proveedor: str | None = Field(default=None, max_length=200)
    numero_factura: str | None = Field(default=None, max_length=60)
    vencimiento: date | None = None  # vencimiento de la factura (tal como figura en ella)
    total: float = Field(gt=-1_000_000, lt=1_000_000)  # IVA incluido (negativo: abono)
    tipo_iva: float = 21
    base: float | None = None  # si se indica (varios tipos de IVA), la cuota es total - base
    forma_pago: str | None = None
    pagado: bool = False
    fecha_pago: date | None = None
    notas: str | None = None


def _ver(scope: Scope, asset_id: int) -> None:
    scope.require_asset("documentos.ver", asset_id)


def _unidad(db: Session, asset_id: int, unit_id: int | None) -> Unit | None:
    if not unit_id:
        return None
    u = get_or_404(db, Unit, unit_id)
    if u.asset_id != asset_id:
        bad_request("La unidad no pertenece al activo")
    return u


def _valores_gasto(db: Session, asset_id: int, data: ExpenseIn) -> dict:
    if data.categoria not in CATEGORIAS_GASTO:
        bad_request(f"Categoría no válida. Opciones: {', '.join(CATEGORIAS_GASTO)}")
    if data.ambito not in AMBITOS_GASTO:
        bad_request("Ámbito no válido: general, apartamento u otro")
    if data.ambito == "apartamento" and not data.unit_id:
        bad_request("Indique el apartamento del gasto")
    if data.tipo_iva not in IVAS:
        bad_request(f"Tipo de IVA no válido: {', '.join(map(str, IVAS))} %")
    if data.fecha > date.today():
        bad_request("La fecha de la factura no puede ser posterior a hoy: ponga la que figura en la factura")
    if data.vencimiento and data.vencimiento < data.fecha:
        bad_request("El vencimiento no puede ser anterior a la fecha de la factura")
    if not data.forma_pago:
        bad_request("Indique cómo se paga la factura: transferencia o cargo en cuenta (domiciliación)")
    if data.forma_pago not in FORMAS_PAGO_GASTO:
        bad_request("Forma de pago no válida")
    _unidad(db, asset_id, data.unit_id)
    total = dinero(data.total)
    if data.base is not None:
        base = dinero(data.base)
        if abs(base) > abs(total):
            bad_request("La base no puede ser mayor que el total")
    else:
        base = dinero(total / (1 + Decimal(str(data.tipo_iva)) / 100))
    prov = " ".join((data.proveedor or "").split()) or None
    supplier = db.scalar(select(Supplier).where(Supplier.nombre == prov)) if prov else None
    return {"fecha": data.fecha, "categoria": data.categoria, "concepto": data.concepto.strip(),
            "ambito": data.ambito, "unit_id": data.unit_id if data.ambito == "apartamento" else None,
            "ambito_detalle": data.ambito_detalle if data.ambito == "otro" else None, "proveedor": prov,
            "supplier_id": supplier.id if supplier else None, "numero_factura": data.numero_factura,
            "vencimiento": data.vencimiento,
            "total": total, "base": base, "cuota": total - base, "tipo_iva": data.tipo_iva,
            "forma_pago": data.forma_pago, "pagado": data.pagado,
            "fecha_pago": (data.fecha_pago or date.today()) if data.pagado else None, "notas": data.notas}


def _nombres(db: Session, ids_unidades: set[int], ids_usuarios: set[int]) -> tuple[dict, dict]:
    unidades = dict(db.execute(select(Unit.id, Unit.codigo).where(Unit.id.in_(ids_unidades or {-1}))).all())
    usuarios = dict(db.execute(select(User.id, User.nombre).where(User.id.in_(ids_usuarios or {-1}))).all())
    return unidades, usuarios


def _gasto_out(g: Expense, unidades: dict, usuarios: dict, activos: dict) -> dict:
    d = g.to_dict()
    d["activo"] = activos.get(g.asset_id)
    d["unidad"] = unidades.get(g.unit_id)
    d["categoria_nombre"] = CATEGORIAS_GASTO.get(g.categoria, g.categoria)
    d["lugar"] = (f"Apartamento {d['unidad']}" if g.ambito == "apartamento"
                  else g.ambito_detalle or "Otro" if g.ambito == "otro" else "General")
    d["usuario"] = usuarios.get(g.user_id)
    return d


def _doc_out(x: ReceivedDocument, gasto: Expense | None, unidades: dict, usuarios: dict, activos: dict) -> dict:
    d = x.to_dict(exclude=("fichero", "sha256"))
    d["activo"] = activos.get(x.asset_id)
    d["tipo_nombre"] = TIPOS_DOCUMENTO.get(x.tipo, x.tipo)
    d["unidad"] = unidades.get(x.unit_id)
    d["usuario"] = usuarios.get(x.user_id)
    d["gasto"] = _gasto_out(gasto, unidades, usuarios, activos) if gasto else None
    return d


def _activos(db: Session) -> dict:
    return dict(db.execute(select(Asset.id, Asset.nombre)).all())


# --------------------------------------------------------------------------- documentos recibidos (carpeta)
@router.get("/documentos-recibidos")
def list_documents(asset_id: int | None = None, tipo: str | None = None, desde: date | None = None,
                   hasta: date | None = None, q: str | None = None, scope: Scope = Depends(get_scope),
                   db: Session = Depends(get_db)):
    scope.require_any("documentos.ver")
    stmt = scoped(select(ReceivedDocument), ReceivedDocument.asset_id, scope.asset_ids("documentos.ver"))
    if asset_id:
        stmt = stmt.where(ReceivedDocument.asset_id == asset_id)
    if tipo:
        stmt = stmt.where(ReceivedDocument.tipo == tipo)
    if desde:
        stmt = stmt.where(ReceivedDocument.fecha >= desde)
    if hasta:
        stmt = stmt.where(ReceivedDocument.fecha <= hasta)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(ReceivedDocument.emisor.ilike(like), ReceivedDocument.referencia.ilike(like),
                              ReceivedDocument.descripcion.ilike(like), ReceivedDocument.nombre.ilike(like)))
    docs = list(db.scalars(stmt.order_by(ReceivedDocument.fecha.desc(), ReceivedDocument.id.desc()).limit(3000)))
    gastos = {g.documento_id: g for g in db.scalars(select(Expense).where(
        Expense.documento_id.in_([x.id for x in docs] or [-1])))}
    unidades, usuarios = _nombres(db, {x.unit_id for x in docs if x.unit_id} | {g.unit_id for g in gastos.values()
                                                                                  if g.unit_id},
                                  {x.user_id for x in docs if x.user_id})
    activos = _activos(db)
    return [_doc_out(x, gastos.get(x.id), unidades, usuarios, activos) for x in docs]


@router.post("/documentos-recibidos", status_code=201)
def upload_document(ficheros: list[UploadFile] = File(...), asset_id: int = Form(...), tipo: str = Form(...),
                    fecha: date = Form(...), vencimiento: date | None = Form(None),
                    emisor: str | None = Form(None), referencia: str | None = Form(None),
                    descripcion: str | None = Form(None), unit_id: int | None = Form(None),
                    gasto: str | None = Form(None), scope: Scope = Depends(get_scope),
                    db: Session = Depends(get_db)):
    """Sube un documento escaneado (foto o PDF) a la carpeta del activo. Con `gasto` (JSON con los datos del
    gasto) se anota además en la cuenta de gastos."""
    scope.require_asset("documentos.editar", asset_id)
    get_or_404(db, Asset, asset_id)
    if tipo not in TIPOS_DOCUMENTO:
        bad_request(f"Tipo de documento no válido. Opciones: {', '.join(TIPOS_DOCUMENTO)}")
    _unidad(db, asset_id, unit_id)
    if vencimiento and vencimiento < fecha:
        bad_request("El vencimiento no puede ser anterior a la fecha del documento")
    datos, mime, nombre = _fichero(ficheros)
    gasto_in = None
    if gasto:
        try:
            gasto_in = ExpenseIn(**json.loads(gasto))
        except (ValueError, ValidationError) as e:
            bad_request(f"Datos del gasto no válidos: {str(e)[:300]}")
    x = ReceivedDocument(asset_id=asset_id, unit_id=unit_id, tipo=tipo, fecha=fecha, vencimiento=vencimiento,
                         emisor=" ".join((emisor or "").split()) or None, referencia=referencia or None,
                         descripcion=descripcion or None, nombre=nombre, fichero=documentos.guardar(datos), mime=mime,
                         tamano=len(datos), sha256=documentos.huella(datos), user_id=scope.user.id)
    db.add(x)
    db.flush()
    g = None
    if gasto_in:
        g = Expense(asset_id=asset_id, documento_id=x.id, user_id=scope.user.id,
                    **_valores_gasto(db, asset_id, gasto_in))
        db.add(g)
        db.flush()
    audit(db, scope.user, "subir", "documento_recibido", x.id, {"tipo": tipo, "emisor": x.emisor,
                                                                 "gasto": g.id if g else None})
    db.commit()
    unidades, usuarios = _nombres(db, {i for i in (x.unit_id, g.unit_id if g else None) if i}, {scope.user.id})
    return _doc_out(x, g, unidades, usuarios, _activos(db))


def _fichero(ficheros: list[UploadFile]) -> tuple[bytes, str, str]:
    """Un PDF o una o varias fotos. Varias fotos (páginas del mismo documento) se unen en un PDF."""
    if not ficheros:
        bad_request("Adjunte el documento escaneado")
    if len(ficheros) > 20:
        bad_request("Máximo 20 páginas por documento")
    partes = []
    for f in ficheros:
        try:
            partes.append(adjuntos.normalizar(f.file.read(adjuntos.TAM_MAX + 1), (f.filename or "documento")[-150:]))
        except ValueError as e:
            bad_request(f"{f.filename}: {e}")
    if len(partes) == 1:
        return partes[0]
    if any(m != "image/jpeg" for _, m, _ in partes):
        bad_request("Para varias páginas adjunte solo fotos, o un único PDF con todas")
    from PIL import Image
    paginas = [Image.open(BytesIO(d)).convert("RGB") for d, _, _ in partes]
    out = BytesIO()
    paginas[0].save(out, "PDF", save_all=True, append_images=paginas[1:], resolution=150)
    base = partes[0][2].rsplit(".", 1)[0]
    return out.getvalue(), "application/pdf", f"{base}.pdf"


@router.get("/documentos-recibidos/{did}/fichero")
def view_document(did: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    x = get_or_404(db, ReceivedDocument, did)
    _ver(scope, x.asset_id)
    audit(db, scope.user, "ver", "documento_recibido", did)
    db.commit()
    return Response(documentos.leer(x.fichero), media_type=x.mime, headers={
        "Content-Disposition": f'inline; filename="{x.nombre}"', "Cache-Control": "private, no-store"})


def _puede_borrar(scope: Scope, asset_id: int, autor: int | None, cuando: datetime) -> None:
    """Para que el control sea fiable, solo borra quien lo subió el mismo día, o la dirección."""
    scope.require_asset("documentos.editar", asset_id)
    if scope.company_level_ids("documentos.editar") is None:
        return
    a = scope.db.get(Asset, asset_id)
    if a.company_id in (scope.company_level_ids("documentos.editar") or set()):
        return
    if autor != scope.user.id or cuando.date() != date.today():
        raise HTTPException(403, "Solo la dirección, o quien lo registró el mismo día, puede borrarlo")


@router.delete("/documentos-recibidos/{did}")
def delete_document(did: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    x = get_or_404(db, ReceivedDocument, did)
    _puede_borrar(scope, x.asset_id, x.user_id, x.subido)
    for g in db.scalars(select(Expense).where(Expense.documento_id == did)):
        g.documento_id = None  # el apunte del gasto se conserva
    documentos.borrar(x.fichero)
    audit(db, scope.user, "borrar", "documento_recibido", did, {"tipo": x.tipo, "emisor": x.emisor,
                                                                 "nombre": x.nombre})
    db.delete(x)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- cuenta de gastos
def _gastos_q(scope: Scope, asset_id, desde, hasta, categoria, unit_id, pagado):
    stmt = scoped(select(Expense), Expense.asset_id, scope.asset_ids("documentos.ver"))
    if asset_id:
        stmt = stmt.where(Expense.asset_id == asset_id)
    if desde:
        stmt = stmt.where(Expense.fecha >= desde)
    if hasta:
        stmt = stmt.where(Expense.fecha <= hasta)
    if categoria:
        stmt = stmt.where(Expense.categoria == categoria)
    if unit_id:
        stmt = stmt.where(Expense.unit_id == unit_id)
    if pagado is not None:
        stmt = stmt.where(Expense.pagado.is_(pagado))
    return stmt.order_by(Expense.fecha.desc(), Expense.id.desc())


def _gastos(db, scope, asset_id, desde, hasta, categoria, unit_id, pagado) -> list[dict]:
    scope.require_any("documentos.ver")
    filas = list(db.scalars(_gastos_q(scope, asset_id, desde, hasta, categoria, unit_id, pagado).limit(10000)))
    unidades, usuarios = _nombres(db, {g.unit_id for g in filas if g.unit_id}, {g.user_id for g in filas if g.user_id})
    activos = _activos(db)
    docs = dict(db.execute(select(ReceivedDocument.id, ReceivedDocument.tipo).where(
        ReceivedDocument.id.in_([g.documento_id for g in filas if g.documento_id] or [-1]))).all())
    out = []
    for g in filas:
        d = _gasto_out(g, unidades, usuarios, activos)
        d["documento_tipo"] = TIPOS_DOCUMENTO.get(docs.get(g.documento_id)) if g.documento_id else None
        out.append(d)
    return out


@router.get("/gastos")
def list_expenses(asset_id: int | None = None, desde: date | None = None, hasta: date | None = None,
                  categoria: str | None = None, unit_id: int | None = None, pagado: bool | None = None,
                  scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    filas = _gastos(db, scope, asset_id, desde, hasta, categoria, unit_id, pagado)
    por_cat = defaultdict(float)
    for g in filas:
        por_cat[g["categoria_nombre"]] += g["base"]
    return {"gastos": filas, "totales": {
        "base": round(sum(g["base"] for g in filas), 2), "cuota": round(sum(g["cuota"] for g in filas), 2),
        "total": round(sum(g["total"] for g in filas), 2),
        "pendiente_pago": round(sum(g["total"] for g in filas if not g["pagado"]), 2),
        "sin_documento": sum(1 for g in filas if not g["documento_id"]),
        "por_categoria": {k: round(v, 2) for k, v in sorted(por_cat.items(), key=lambda x: -x[1])}}}


@router.post("/gastos", status_code=201)
def create_expense(data: ExpenseIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Gasto sin documento escaneado (p. ej. un recibo domiciliado) o enlazado a un documento ya subido."""
    if data.documento_id:
        doc = get_or_404(db, ReceivedDocument, data.documento_id)
        asset_id = doc.asset_id
        if db.scalar(select(Expense.id).where(Expense.documento_id == doc.id)):
            bad_request("Ese documento ya tiene su gasto anotado: edítelo")
    elif data.asset_id:
        asset_id = data.asset_id
        get_or_404(db, Asset, asset_id)
    else:
        bad_request("Indique el activo del gasto")
    scope.require_asset("documentos.editar", asset_id)
    g = Expense(asset_id=asset_id, documento_id=data.documento_id, user_id=scope.user.id,
                **_valores_gasto(db, asset_id, data))
    db.add(g)
    db.flush()
    audit(db, scope.user, "crear", "gasto", g.id, {"concepto": g.concepto, "total": float(g.total)})
    db.commit()
    return _uno(db, scope, g.id)


def _uno(db: Session, scope: Scope, gid: int) -> dict:
    g = db.get(Expense, gid)
    unidades, usuarios = _nombres(db, {g.unit_id} if g.unit_id else set(), {g.user_id} if g.user_id else set())
    return _gasto_out(g, unidades, usuarios, _activos(db))


@router.put("/gastos/{gid}")
def update_expense(gid: int, data: ExpenseIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    g = get_or_404(db, Expense, gid)
    scope.require_asset("documentos.editar", g.asset_id)
    antes = {k: str(v) for k, v in g.to_dict().items()}
    for k, v in _valores_gasto(db, g.asset_id, data).items():
        setattr(g, k, v)
    audit(db, scope.user, "editar", "gasto", gid,
          {k: [antes.get(k), str(v)] for k, v in g.to_dict().items() if antes.get(k) != str(v)})
    db.commit()
    return _uno(db, scope, gid)


@router.delete("/gastos/{gid}")
def delete_expense(gid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    g = get_or_404(db, Expense, gid)
    _puede_borrar(scope, g.asset_id, g.user_id, g.creado)
    audit(db, scope.user, "borrar", "gasto", gid, {"concepto": g.concepto, "total": float(g.total)})
    db.delete(g)
    db.commit()
    return {"ok": True}


@router.get("/gastos/excel")
def expenses_excel(asset_id: int | None = None, desde: date | None = None, hasta: date | None = None,
                   categoria: str | None = None, unit_id: int | None = None, scope: Scope = Depends(get_scope),
                   db: Session = Depends(get_db)):
    """Cuenta de gastos en Excel: detalle, resumen por categoría y mes, y gasto por apartamento."""
    from openpyxl import Workbook

    from .informes import ENTERO, EUR, FECHA, _hoja
    filas = _gastos(db, scope, asset_id, desde, hasta, categoria, unit_id, None)
    wb = Workbook()
    wb.remove(wb.active)
    periodo = f"{desde:%d/%m/%Y} – {hasta:%d/%m/%Y}" if desde and hasta else "todo el periodo"
    _hoja(wb, "Gastos", ["Fecha factura", "Activo", "Ámbito", "Categoría", "Concepto", "Proveedor", "Nº factura",
                         "Vencimiento", "Base", "IVA %", "Cuota IVA", "Total", "Pagado", "Fecha pago", "Forma de pago",
                         "Documento", "Registrado por"],
          [[date.fromisoformat(g["fecha"]), g["activo"], g["lugar"], g["categoria_nombre"], g["concepto"],
            g["proveedor"] or "", g["numero_factura"] or "",
            date.fromisoformat(g["vencimiento"]) if g["vencimiento"] else None, g["base"], g["tipo_iva"], g["cuota"],
            g["total"],
            "Sí" if g["pagado"] else "No", date.fromisoformat(g["fecha_pago"]) if g["fecha_pago"] else None,
            FORMAS_PAGO_GASTO.get(g["forma_pago"], ""), g["documento_tipo"] or "SIN DOCUMENTO", g["usuario"] or ""]
           for g in sorted(filas, key=lambda x: (x["fecha"], x["id"]))],
          {7: FECHA, 8: EUR, 9: ENTERO, 10: EUR, 11: EUR, 13: FECHA}, totales=[8, 10, 11],
          nota=f"Cuenta de gastos · {periodo}. Fecha y vencimiento tal como figuran en la factura recibida.")
    res = defaultdict(lambda: defaultdict(float))
    for g in filas:
        res[(g["activo"], g["categoria_nombre"])][g["fecha"][:7]] += g["base"]
    meses = sorted({m for v in res.values() for m in v})
    _hoja(wb, "Por categoría", ["Activo", "Categoría", *meses, "Total"],
          [[a, c, *[round(v.get(m, 0), 2) for m in meses], round(sum(v.values()), 2)]
           for (a, c), v in sorted(res.items())],
          {i: EUR for i in range(2, len(meses) + 3)}, totales=list(range(2, len(meses) + 3)),
          nota="Base imponible (sin IVA) por categoría y mes")
    por_apto = defaultdict(float)
    for g in filas:
        if g["unidad"]:
            por_apto[(g["activo"], g["unidad"])] += g["base"]
    _hoja(wb, "Por apartamento", ["Activo", "Apartamento", "Gasto (base)"],
          [[a, u, round(v, 2)] for (a, u), v in sorted(por_apto.items())], {2: EUR}, totales=[2],
          nota="Gastos imputados a un apartamento concreto")
    out = BytesIO()
    wb.save(out)
    audit(db, scope.user, "exportar", "gastos", None, {"desde": str(desde), "hasta": str(hasta),
                                                       "asset_id": asset_id})
    db.commit()
    return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="Cuenta_de_gastos.xlsx"'})


@router.get("/gastos/catalogos")
def catalogs(scope: Scope = Depends(get_scope)):
    return {"tipos_documento": TIPOS_DOCUMENTO, "categorias": CATEGORIAS_GASTO, "ambitos": AMBITOS_GASTO,
            "formas_pago": FORMAS_PAGO_GASTO, "ivas": IVAS}
