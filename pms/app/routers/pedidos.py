"""Pedidos de material (Mantenimiento → Pedidos): catálogo de productos, pedidos con autorización de Recepción 1,
PDF y envío al proveedor, e intercambio del catálogo con INVERGESTION (ver app/pedidos.py)."""
import hashlib
import hmac
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import avisos
from .. import pedidos as pd
from ..config import settings
from ..database import get_db
from ..models import ESTADOS_PEDIDO, FAMILIAS_PRODUCTO, Asset, Product, PurchaseOrder, PurchaseOrderLine, Supplier, User
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404

router = APIRouter(prefix="/api", tags=["pedidos"])
publico = APIRouter(prefix="/api/publico", tags=["público"])


def _puede_pedir(scope: Scope, asset_id: int) -> bool:
    return scope.can_asset("pedidos.crear", asset_id) or scope.can_asset("pedidos.autorizar", asset_id)


def _activos_pedidos(scope: Scope) -> set[int] | None:
    a, b = scope.asset_ids("pedidos.crear"), scope.asset_ids("pedidos.autorizar")
    return None if a is None or b is None else a | b


def _requiere_catalogo(scope: Scope) -> None:
    if not (scope.has_any("pedidos.crear") or scope.has_any("pedidos.autorizar")):
        raise HTTPException(403, "Sin permiso para pedidos de material")


# --------------------------------------------------------------------------- catálogo de productos
class ProductIn(BaseModel):
    referencia: str | None = Field(default=None, max_length=60)  # vacía: PMS-000001…
    articulo: str = Field(min_length=2, max_length=250)
    familia: str = "OTROS"
    unidad: str = Field(default="ud", max_length=20)
    precio: float | None = Field(default=None, ge=0)  # sin IVA
    tipo_iva: float = Field(default=21, ge=0, le=21)
    marca: str | None = Field(default=None, max_length=100)
    ref_proveedor: str | None = Field(default=None, max_length=60)
    supplier_id: int | None = None
    proveedor: str | None = Field(default=None, max_length=200)
    asset_id: int | None = None  # activo que lo da de alta (para enviarlo a INVERGESTION)


def _datos_proveedor(db: Session, supplier_id: int | None, nombre: str | None) -> dict:
    s = db.get(Supplier, supplier_id) if supplier_id else None
    if s is None and nombre:
        s = pd.proveedor_por_nif(db, None, nombre)
    if s is not None:
        return {"supplier_id": s.id, "proveedor": s.nombre, "proveedor_nif": s.nif}
    return {"supplier_id": None, "proveedor": (nombre or "").strip() or None, "proveedor_nif": None}


def crear_producto(db: Session, scope: Scope, data: ProductIn, asset_id: int | None) -> Product:
    ref = (data.referencia or "").strip().upper()
    if ref:
        if db.scalar(select(Product.id).where(func.upper(Product.referencia) == ref)):
            bad_request(f"Ya existe un producto con la referencia {ref}: búsquelo en el catálogo")
    else:
        ref = pd.nueva_referencia(db)
    p = Product(referencia=ref, articulo=data.articulo.strip(), familia=pd.familia(data.familia),
                unidad=(data.unidad or "ud").strip() or "ud", precio=data.precio, tipo_iva=data.tipo_iva,
                marca=data.marca, ref_proveedor=data.ref_proveedor, origen="PMS", activo=True,
                asset_id=asset_id, user_id=scope.user.id, **_datos_proveedor(db, data.supplier_id, data.proveedor))
    db.add(p)
    db.flush()
    audit(db, scope.user, "crear", "producto", p.id, {"referencia": p.referencia, "articulo": p.articulo})
    return p


@router.get("/productos/familias")
def families():
    return FAMILIAS_PRODUCTO


@router.get("/productos")
def list_products(q: str | None = None, familia: str | None = None, limit: int = 50, scope: Scope = Depends(get_scope),
                  db: Session = Depends(get_db)):
    """Busca en el catálogo por referencia, artículo, marca, referencia del proveedor o proveedor (todas las
    palabras). Para el buscador del pedido: las sugerencias según se escribe."""
    _requiere_catalogo(scope)
    stmt = select(Product).where(Product.activo.is_(True))
    for palabra in (q or "").split():
        like = f"%{palabra}%"
        stmt = stmt.where(or_(Product.referencia.ilike(like), Product.articulo.ilike(like), Product.marca.ilike(like),
                              Product.ref_proveedor.ilike(like), Product.proveedor.ilike(like)))
    if familia:
        stmt = stmt.where(Product.familia == pd.familia(familia))
    return [pd.producto_out(p) for p in db.scalars(stmt.order_by(Product.articulo).limit(min(max(limit, 1), 500)))]


@router.post("/productos", status_code=201)
def create_product(data: ProductIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _requiere_catalogo(scope)
    if data.asset_id is not None and not _puede_pedir(scope, data.asset_id):
        raise HTTPException(403, "Sin permiso de pedidos en ese activo")
    p = crear_producto(db, scope, data, data.asset_id)
    db.commit()
    return pd.producto_out(p)


@router.put("/productos/{pid}")
def update_product(pid: int, data: ProductIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Corrige un producto (la referencia no cambia: es la clave con INVERGESTION)."""
    if not scope.has_any("pedidos.autorizar"):
        raise HTTPException(403, "Solo dirección corrige el catálogo")
    p = get_or_404(db, Product, pid)
    for k in ("articulo", "unidad", "precio", "tipo_iva", "marca", "ref_proveedor"):
        setattr(p, k, getattr(data, k))
    p.familia = pd.familia(data.familia)
    for k, v in _datos_proveedor(db, data.supplier_id, data.proveedor).items():
        setattr(p, k, v)
    p.actualizado = datetime.now()
    audit(db, scope.user, "editar", "producto", pid, {"referencia": p.referencia})
    db.commit()
    return pd.producto_out(p)


@router.post("/productos/importar")
def import_products(fichero: UploadFile = File(...), confirmar: bool = Form(False), scope: Scope = Depends(get_scope),
                    db: Session = Depends(get_db)):
    """Catálogo de INVERGESTION (INVERGESTION_PRODUCTOS_….zip). Sin confirmar: resumen de altas y cambios."""
    if not scope.has_any("pedidos.autorizar"):
        raise HTTPException(403, "Solo dirección importa el catálogo de INVERGESTION")
    datos = fichero.file.read(pd.TAM_MAX + 1)
    if len(datos) > pd.TAM_MAX:
        bad_request("El fichero supera 20 MB")
    try:
        res = pd.importar(db, scope.user, datos, confirmar)
    except ValueError as e:
        bad_request(str(e))
    if confirmar:
        audit(db, scope.user, "importar_catalogo", "producto", None,
              {"fichero": fichero.filename, **{k: res[k] for k in ("tipo", "filas", "altas", "modificaciones")},
               "errores": len(res["errores"])})
        db.commit()
    return {**res, "importado": confirmar}


def _activo_por_codigo(db: Session, scope: Scope, activo: str) -> Asset:
    from ..export_invergestion import codigo_activo
    a = next((a for a in db.scalars(select(Asset)) if codigo_activo(a) == activo.upper() or a.codigo == activo.upper()),
             None)
    if a is None:
        bad_request("Activo no válido")
    scope.require_asset("pedidos.autorizar", a.id)
    return a


@router.get("/productos/exportar/resumen")
def export_summary(activo: str, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a = _activo_por_codigo(db, scope, activo)
    filas, _, _ = pd.pendientes_exportar(db, a)
    return {"filas": len(filas), "altas": sum(1 for f in filas if f["accion"] == "ALTA"),
            "pedidos": sum(1 for f in filas if f["accion"] == "PEDIDO"), "fichero": pd.nombre_paquete(a, date.today())}


@router.get("/productos/exportar")
def export_products(activo: str, prueba: bool = False, scope: Scope = Depends(get_scope),
                    db: Session = Depends(get_db)):
    """PRODUCTOS_PMS_<ACTIVO>_<AAAAMMDD>.zip con lo nuevo desde el último envío. `prueba`: no lo marca como enviado
    (se puede volver a sacar)."""
    a = _activo_por_codigo(db, scope, activo)
    filas, productos, lineas = pd.pendientes_exportar(db, a)
    contenido = pd.paquete(filas)
    if not prueba:
        ahora = datetime.now()
        for p in productos:
            p.alta_exportada = ahora
        for x in lineas:
            x.exportado = ahora
    audit(db, scope.user, "exportar_catalogo", "producto", None, {"activo": activo, "filas": len(filas), "prueba": prueba})
    db.commit()
    return Response(contenido, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{pd.nombre_paquete(a, date.today())}"', "Cache-Control": "no-store"})


# --------------------------------------------------------------------------- pedidos
class LineIn(BaseModel):
    product_id: int | None = None
    nuevo: ProductIn | None = None  # producto que no está en el catálogo: se da de alta con el pedido
    cantidad: float = Field(gt=0)
    precio: float | None = Field(default=None, ge=0)  # sin IVA; vacío = el del catálogo
    nota: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _uno(self):
        if (self.product_id is None) == (self.nuevo is None):
            raise ValueError("Cada línea lleva un producto del catálogo o uno nuevo")
        return self


class OrderIn(BaseModel):
    asset_id: int
    supplier_id: int | None = None
    proveedor: str | None = Field(default=None, max_length=200)
    fecha_entrega: date | None = None
    notas: str | None = Field(default=None, max_length=2000)
    lineas: list[LineIn] = Field(min_length=1, max_length=200)


def _pedido(db: Session, scope: Scope, oid: int) -> PurchaseOrder:
    p = get_or_404(db, PurchaseOrder, oid)
    if not _puede_pedir(scope, p.asset_id) and not pd.puede_autorizar(scope, db, p.asset):
        raise HTTPException(403, "Sin permiso sobre los pedidos de este activo")
    return p


def _out(db: Session, scope: Scope, p: PurchaseOrder, detalle: bool = True) -> dict:
    d = p.to_dict()
    nombres = dict(db.execute(select(User.id, User.nombre).where(User.id.in_(
        [x for x in (p.user_id, p.autorizado_por) if x] or [-1]))).all())
    prov = db.get(Supplier, p.supplier_id) if p.supplier_id else None
    autoriza = pd.puede_autorizar(scope, db, p.asset)
    d.update(activo=p.asset.nombre, estado_nombre=ESTADOS_PEDIDO.get(p.estado, p.estado),
             proveedor_nombre=prov.nombre if prov else p.proveedor, proveedor_email=prov.email if prov else None,
             proveedor_telefono=prov.telefono if prov else None, creado_por=nombres.get(p.user_id),
             autorizado_por_nombre=nombres.get(p.autorizado_por), n_lineas=len(p.lineas), **pd.totales(p),
             puede_autorizar=autoriza and p.estado == "pendiente",
             puede_editar=p.estado in ("pendiente", "autorizado") and (autoriza or p.user_id == scope.user.id),
             puede_enviar=p.estado in ("autorizado", "enviado") and autoriza,
             r1=getattr(pd.recepcion_1(db, p.asset), "nombre", None))
    if detalle:
        d["lineas"] = [{**x.to_dict(), "producto": pd.producto_out(x.producto),
                        "importe": float((Decimal(str(x.cantidad)) * Decimal(str(x.precio))).quantize(Decimal("0.01")))
                        if x.precio is not None else None} for x in p.lineas]
    return d


def _poner_lineas(db: Session, scope: Scope, p: PurchaseOrder, lineas: list[LineIn]) -> None:
    p.lineas.clear()
    db.flush()
    for i, x in enumerate(lineas):
        if x.nuevo is not None:
            nuevo = x.nuevo.model_copy(update={"supplier_id": x.nuevo.supplier_id or p.supplier_id,
                                               "proveedor": x.nuevo.proveedor or p.proveedor,
                                               "precio": x.nuevo.precio if x.nuevo.precio is not None else x.precio})
            prod = crear_producto(db, scope, nuevo, p.asset_id)
        else:
            prod = get_or_404(db, Product, x.product_id)
        precio = x.precio if x.precio is not None else prod.precio
        if prod.origen == "PMS" and x.precio is not None and prod.precio != x.precio:
            prod.precio, prod.actualizado = x.precio, datetime.now()  # nuestro último precio conocido
        p.lineas.append(PurchaseOrderLine(product_id=prod.id, orden=i, cantidad=x.cantidad, precio=precio,
                                          tipo_iva=prod.tipo_iva, nota=x.nota))


def _avisar_r1(db: Session, p: PurchaseOrder) -> None:
    """Aviso por correo a Recepción 1 de que tiene un pedido por autorizar (si el correo está configurado)."""
    r1 = pd.recepcion_1(db, p.asset)
    if r1 is None or not r1.email or not avisos.configurado():
        return
    t = pd.totales(p)
    texto = (f"Pedido {p.numero} de {p.asset.nombre} pendiente de autorizar: {len(p.lineas)} línea(s), "
             f"{t['total']:.2f} € con IVA (estimado). Autorícelo en Mantenimiento → Pedidos.")
    try:
        avisos.enviar(r1.email, f"Pedido por autorizar · {p.numero}", texto, avisos._html("Pedido por autorizar", f"<p>{texto}</p>"))
    except Exception:  # noqa: BLE001 — el aviso no impide guardar el pedido
        pass


@router.get("/pedidos")
def list_orders(asset_id: int | None = None, estado: str | None = None, scope: Scope = Depends(get_scope),
                db: Session = Depends(get_db)):
    ids = _activos_pedidos(scope)
    stmt = select(PurchaseOrder)
    if ids is not None:
        stmt = stmt.where(PurchaseOrder.asset_id.in_(ids or {-1}))
    if asset_id:
        stmt = stmt.where(PurchaseOrder.asset_id == asset_id)
    if estado:
        stmt = stmt.where(PurchaseOrder.estado == estado)
    return [_out(db, scope, p, False) for p in db.scalars(stmt.order_by(PurchaseOrder.fecha.desc(), PurchaseOrder.id.desc()).limit(500))]


@router.post("/pedidos", status_code=201)
def create_order(data: OrderIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Lo hace dirección o Recepción 1: queda autorizado. Lo hace otra persona (recepción 2, mantenimiento,
    limpieza…): queda pendiente de que lo autorice Recepción 1."""
    asset = get_or_404(db, Asset, data.asset_id)
    if not _puede_pedir(scope, asset.id):
        raise HTTPException(403, "Sin permiso para hacer pedidos en este activo")
    hoy = date.today()
    prov = _datos_proveedor(db, data.supplier_id, data.proveedor)
    p = PurchaseOrder(numero=pd.numero_pedido(db, asset, hoy), asset_id=asset.id, supplier_id=prov["supplier_id"],
                      proveedor=prov["proveedor"], fecha=hoy, fecha_entrega=data.fecha_entrega, notas=data.notas,
                      user_id=scope.user.id, estado="pendiente")
    db.add(p)
    db.flush()
    _poner_lineas(db, scope, p, data.lineas)
    if pd.puede_autorizar(scope, db, asset):
        p.estado, p.autorizado_por, p.autorizado_en = "autorizado", scope.user.id, datetime.now()
    db.flush()
    db.refresh(p)
    audit(db, scope.user, "crear", "pedido", p.id, {"numero": p.numero, "estado": p.estado, **pd.totales(p)})
    if p.estado == "pendiente":
        _avisar_r1(db, p)
    db.commit()
    return _out(db, scope, p)


@router.get("/pedidos/{oid}")
def get_order(oid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return _out(db, scope, _pedido(db, scope, oid))


@router.put("/pedidos/{oid}")
def update_order(oid: int, data: OrderIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Cambia un pedido aún no enviado. Si lo cambia quien no autoriza, vuelve a quedar pendiente de autorizar."""
    p = _pedido(db, scope, oid)
    autoriza = pd.puede_autorizar(scope, db, p.asset)
    if p.estado not in ("pendiente", "autorizado") or not (autoriza or p.user_id == scope.user.id):
        bad_request("Este pedido ya no se puede modificar")
    if data.asset_id != p.asset_id:
        bad_request("No se puede cambiar el activo del pedido")
    prov = _datos_proveedor(db, data.supplier_id, data.proveedor)
    p.supplier_id, p.proveedor = prov["supplier_id"], prov["proveedor"]
    p.fecha_entrega, p.notas = data.fecha_entrega, data.notas
    _poner_lineas(db, scope, p, data.lineas)
    if not autoriza:
        p.estado, p.autorizado_por, p.autorizado_en = "pendiente", None, None
    db.flush()
    db.refresh(p)
    audit(db, scope.user, "editar", "pedido", oid, {"estado": p.estado, **pd.totales(p)})
    db.commit()
    return _out(db, scope, p)


class MotivoIn(BaseModel):
    motivo: str = Field(min_length=3, max_length=300)


@router.post("/pedidos/{oid}/autorizar")
def authorize(oid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = _pedido(db, scope, oid)
    if not pd.puede_autorizar(scope, db, p.asset):
        raise HTTPException(403, "Los pedidos los autoriza Recepción 1 del activo (o dirección)")
    if p.estado != "pendiente":
        bad_request("El pedido no está pendiente de autorizar")
    p.estado, p.autorizado_por, p.autorizado_en = "autorizado", scope.user.id, datetime.now()
    audit(db, scope.user, "autorizar", "pedido", oid)
    db.commit()
    return _out(db, scope, p)


@router.post("/pedidos/{oid}/rechazar")
def reject(oid: int, data: MotivoIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = _pedido(db, scope, oid)
    if not pd.puede_autorizar(scope, db, p.asset):
        raise HTTPException(403, "Los pedidos los autoriza Recepción 1 del activo (o dirección)")
    if p.estado != "pendiente":
        bad_request("El pedido no está pendiente de autorizar")
    p.estado, p.motivo_rechazo = "rechazado", data.motivo
    audit(db, scope.user, "rechazar", "pedido", oid, {"motivo": data.motivo})
    db.commit()
    return _out(db, scope, p)


@router.post("/pedidos/{oid}/anular")
def void_order(oid: int, data: MotivoIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = _pedido(db, scope, oid)
    if p.estado in ("recibido", "anulado", "rechazado"):
        bad_request("Este pedido no se puede anular")
    if not (pd.puede_autorizar(scope, db, p.asset) or (p.user_id == scope.user.id and p.estado == "pendiente")):
        raise HTTPException(403, "Lo anula Recepción 1 (o quien lo hizo, mientras esté pendiente)")
    p.estado, p.motivo_rechazo = "anulado", data.motivo
    audit(db, scope.user, "anular", "pedido", oid, {"motivo": data.motivo})
    db.commit()
    return _out(db, scope, p)


@router.post("/pedidos/{oid}/recibido")
def received(oid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = _pedido(db, scope, oid)
    if p.estado not in ("autorizado", "enviado"):
        bad_request("Solo se reciben pedidos autorizados o enviados")
    p.estado, p.recibido_en = "recibido", datetime.now()
    audit(db, scope.user, "recibido", "pedido", oid)
    db.commit()
    return _out(db, scope, p)


@router.get("/pedidos/{oid}/pdf")
def order_pdf(oid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = _pedido(db, scope, oid)
    return Response(pd.pdf(db, p), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Pedido_{p.numero}.pdf"'})


DIAS_ENLACE = 30


def _firma(oid: int, caduca: int) -> str:
    return hmac.new(settings.secret_key.encode(), f"pedido:{oid}:{caduca}".encode(), hashlib.sha256).hexdigest()[:32]


def enlace_pdf(oid: int) -> str | None:
    if not settings.url:
        return None
    caduca = int(time.time()) + DIAS_ENLACE * 86400
    return f"{settings.url}/api/publico/pedido/{oid}?c={caduca}&f={_firma(oid, caduca)}"


@publico.get("/pedido/{oid}")
def public_pdf(oid: int, c: int, f: str, db: Session = Depends(get_db)):
    if c < time.time() or not hmac.compare_digest(f, _firma(oid, c)):
        raise HTTPException(404, "Enlace no válido o caducado. Pida el pedido de nuevo.")
    p = get_or_404(db, PurchaseOrder, oid)
    return Response(pd.pdf(db, p), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Pedido_{p.numero}.pdf"'})


class EnvioIn(BaseModel):
    canales: list[Literal["email", "whatsapp"]] = Field(min_length=1)
    nota: str | None = Field(default=None, max_length=1000)


@router.post("/pedidos/{oid}/enviar")
def send_order(oid: int, data: EnvioIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Envía el pedido autorizado al proveedor: por correo con el PDF y/o por WhatsApp con enlace al PDF."""
    from .mantenimiento import _destino
    p = _pedido(db, scope, oid)
    if not pd.puede_autorizar(scope, db, p.asset):
        raise HTTPException(403, "El pedido lo envía Recepción 1 (o dirección)")
    if p.estado not in ("autorizado", "enviado"):
        bad_request("Solo se envían pedidos autorizados")
    s = db.get(Supplier, p.supplier_id) if p.supplier_id else None
    if s is None:
        bad_request("El proveedor del pedido no está en Proveedores: dele de alta con su correo o teléfono")
    t = pd.totales(p)
    asunto = f"Pedido {p.numero} · {p.asset.nombre}"
    texto = (f"Buenos días, les enviamos el pedido {p.numero} de {p.asset.nombre} ({len(p.lineas)} artículo(s), "
             f"{t['base']:.2f} € sin IVA estimados). Si algún precio ha cambiado, rogamos nos lo indiquen antes de "
             "servirlo. En la factura indiquen el nº de pedido." + (f"\n\n{data.nota}" if data.nota else "")
             + "\n\nUn saludo.")
    url = enlace_pdf(p.id)
    texto_wa = texto + (f"\n\nPedido en PDF: {url}" if url else "")
    html = avisos._html(f"Pedido {p.numero}", "".join(f"<p>{x}</p>" for x in texto.split("\n\n")))
    adj = [(f"Pedido_{p.numero}.pdf", pd.pdf(db, p), "application/pdf")]
    res = _destino(s.nombre, s.email, s.telefono, data.canales, asunto, texto_wa, html, adj, db, f"pedido:{p.id}", True)
    if any(r["ok"] for r in res):
        p.estado, p.enviado_en = "enviado", datetime.now()
    audit(db, scope.user, "enviar", "pedido", oid, {"canales": data.canales, "destinos": [r["destino"] for r in res]})
    db.commit()
    return {"enviados": res, "pedido": _out(db, scope, p)}


@router.get("/proveedores-pedido")
def suppliers_for_orders(q: str | None = None, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Proveedores para el pedido (nombre, NIF y si tiene correo o teléfono para enviárselo)."""
    _requiere_catalogo(scope)
    stmt = select(Supplier).where(Supplier.activo.is_(True))
    for palabra in (q or "").split():
        stmt = stmt.where(or_(Supplier.nombre.ilike(f"%{palabra}%"), Supplier.nif.ilike(f"%{palabra}%")))
    return [{"id": s.id, "nombre": s.nombre, "nif": s.nif, "email": s.email, "telefono": s.telefono}
            for s in db.scalars(stmt.order_by(Supplier.nombre).limit(30))]

