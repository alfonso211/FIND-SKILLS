"""Pedidos de material: catálogo de productos, numeración, autorización, PDF e intercambio con INVERGESTION.

Intercambio del catálogo (acordado con INVERGESTION el 8/10/2026). Mismas reglas que la exportación de facturas:
UTF-8 sin BOM, fin de línea LF, separador «;», comillas dobles cuando el campo lo necesite, decimales con punto y
fechas AAAA-MM-DD.
- De INVERGESTION al PMS: INVERGESTION_PRODUCTOS_<AAAAMMDD_HHMMSS>.zip con productos.csv y manifest.json (tipo
  CAMBIOS o COMPLETA, fecha, filas, altas y modificaciones). Por referencia: si no existe, alta; si existe, se
  actualizan el precio y los datos. No se borra nada y volver a cargar el mismo fichero no duplica.
- Del PMS a INVERGESTION: PRODUCTOS_PMS_<ACTIVO>_<AAAAMMDD>.zip con productos.csv: ALTA de los productos creados
  en el PMS («PMS-000001», siempre la misma) y PEDIDO de las líneas con precio de los productos que ya existían.
  Solo lo nuevo desde el último envío.
"""
import csv
import io
import json
import re
import unicodedata
import zipfile
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import nif
from .models import (FAMILIAS_PRODUCTO, Asset, Product, PurchaseOrder, PurchaseOrderLine, Supplier, User)

COLUMNAS_IMPORTACION = ["referencia", "articulo", "familia", "unidad", "precio", "tipo_iva", "marca", "ref_proveedor",
                        "proveedor", "proveedor_nif", "fecha_factura", "num_factura", "accion"]
COLUMNAS_EXPORTACION = ["referencia", "articulo", "familia", "unidad", "precio", "tipo_iva", "marca", "ref_proveedor",
                        "proveedor", "proveedor_nif", "fecha_pedido", "num_pedido", "cantidad", "activo", "accion"]
ESTADOS_EXPORTABLES = ("autorizado", "enviado", "recibido")
PREFIJO_PMS = "PMS-"
TAM_MAX = 20 * 1024 * 1024


def _plano(s: str | None) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w ]", " ", t.upper()).split())


_FAMILIAS = {_plano(f): f for f in FAMILIAS_PRODUCTO}


def familia(s: str | None) -> str:
    """Una de las familias acordadas (sin importar tildes ni mayúsculas); si no coincide, OTROS."""
    return _FAMILIAS.get(_plano(s), "OTROS")


def dec(x, nd: int = 4) -> Decimal | None:
    if x is None or str(x).strip() == "":
        return None
    try:
        return Decimal(str(x).strip().replace(",", ".")).quantize(Decimal(10) ** -nd, ROUND_HALF_UP)
    except InvalidOperation as e:
        raise ValueError(f"número no válido: {x}") from e


def num_txt(x, minimo: int = 2) -> str:
    """Decimal con punto, al menos `minimo` decimales y sin ceros sobrantes (12.50, 0.0350, 3)."""
    if x is None:
        return ""
    d = Decimal(str(x))
    s = f"{d:f}"
    if "." in s:
        ent, fr = s.split(".")
        fr = fr.rstrip("0").ljust(minimo, "0")
        return f"{ent}.{fr}" if fr else ent
    return s + ("." + "0" * minimo if minimo else "")


# --------------------------------------------------------------------------- catálogo
def nueva_referencia(db: Session) -> str:
    """Referencia automática de un producto creado en el PMS: PMS-000001, PMS-000002… (nunca cambia)."""
    usadas = db.scalars(select(Product.referencia).where(Product.referencia.like(f"{PREFIJO_PMS}%")))
    ultimo = max((int(m.group(1)) for r in usadas if (m := re.fullmatch(r"PMS-(\d+)", r or ""))), default=0)
    return f"{PREFIJO_PMS}{ultimo + 1:06d}"


def proveedor_por_nif(db: Session, nif_: str | None, nombre: str | None = None) -> Supplier | None:
    n = nif.normalizar(nif_)
    if n:
        s = db.scalar(select(Supplier).where(Supplier.nif == n))
        if s:
            return s
    if nombre:
        clave = nif.nombre_clave(nombre)
        return next((s for s in db.scalars(select(Supplier)) if nif.nombre_clave(s.nombre) == clave), None)
    return None


def producto_out(p: Product) -> dict:
    d = p.to_dict()
    d["precio_iva"] = float((Decimal(str(p.precio)) * (1 + Decimal(str(p.tipo_iva)) / 100)).quantize(
        Decimal("0.01"), ROUND_HALF_UP)) if p.precio is not None else None
    return d


# --------------------------------------------------------------------------- pedidos
def numero_pedido(db: Session, asset: Asset, dia: date) -> str:
    pre = f"PED-{(asset.serie_factura or asset.codigo)[:4].upper()}-{dia:%Y}-"
    usados = db.scalars(select(PurchaseOrder.numero).where(PurchaseOrder.numero.like(f"{pre}%")))
    ultimo = max((int(x[len(pre):]) for x in usados if x[len(pre):].isdigit()), default=0)
    return f"{pre}{ultimo + 1:04d}"


def totales(p: PurchaseOrder) -> dict:
    base = cuota = Decimal(0)
    sin_precio = 0
    for x in p.lineas:
        if x.precio is None:
            sin_precio += 1
            continue
        b = (Decimal(str(x.cantidad)) * Decimal(str(x.precio))).quantize(Decimal("0.01"), ROUND_HALF_UP)
        base += b
        cuota += (b * Decimal(str(x.tipo_iva)) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return {"base": float(base), "iva": float(cuota), "total": float(base + cuota), "sin_precio": sin_precio}


def recepcion_1(db: Session, asset: Asset) -> User | None:
    """Quien autoriza los pedidos del activo: «Recepción 1» (el responsable del informe a presidencia)."""
    from .routers.presidencia import responsable
    return responsable(db, asset)


def puede_autorizar(scope, db: Session, asset: Asset) -> bool:
    """Dirección (permiso «pedidos.autorizar») o Recepción 1 del activo."""
    if scope.can_asset("pedidos.autorizar", asset.id):
        return True
    r1 = recepcion_1(db, asset)
    return r1 is not None and r1.id == scope.user.id


# --------------------------------------------------------------------------- PDF del pedido
def pdf(db: Session, p: PurchaseOrder) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from . import marca
    from .models import Company

    a = p.asset
    comp = db.get(Company, a.company_id)
    prov = db.get(Supplier, p.supplier_id) if p.supplier_id else None
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=12 * mm,
                            bottomMargin=14 * mm, title=f"Pedido {p.numero}")
    st = getSampleStyleSheet()
    t9 = ParagraphStyle("t9", parent=st["BodyText"], fontSize=9, leading=11.5)
    h = ParagraphStyle("h", parent=st["Title"], fontSize=16, alignment=0, spaceAfter=2)
    esc = lambda s: str(s or "").replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
    ancho = A4[0] - 32 * mm
    el = []
    cab = marca.cabecera_pdf(marca.clave_sociedad(comp.cif if comp else None), marca.clave_activo(a.codigo), ancho,
                             16 * mm)
    if cab is not None:
        el += [cab, Spacer(1, 4 * mm)]
    el.append(Paragraph(f"Pedido de material {esc(p.numero)}", h))
    emisor = (f"<b>{esc(comp.nombre if comp else '')}</b> · CIF {esc(comp.cif if comp else '')}<br/>"
              f"{esc(a.nombre)} · {esc(a.direccion or '')}")
    destino = (f"<b>{esc(prov.nombre if prov else p.proveedor or 'Proveedor')}</b>"
               + (f" · NIF {esc(prov.nif)}" if prov and prov.nif else "")
               + (f"<br/>{esc(prov.email)}" if prov and prov.email else "")
               + (f" · {esc(prov.telefono)}" if prov and prov.telefono else ""))
    datos = Table([[Paragraph(f"<font color='#7a5c1e'>PIDE</font><br/>{emisor}", t9),
                    Paragraph(f"<font color='#7a5c1e'>PROVEEDOR</font><br/>{destino}", t9)]],
                  colWidths=[ancho / 2, ancho / 2])
    datos.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#cfc6b4")),
                               ("INNERGRID", (0, 0), (-1, -1), .5, colors.HexColor("#cfc6b4"))]))
    el += [datos, Spacer(1, 3 * mm),
           Paragraph(f"Fecha del pedido: <b>{p.fecha:%d/%m/%Y}</b>"
                     + (f" · Entrega deseada: <b>{p.fecha_entrega:%d/%m/%Y}</b>" if p.fecha_entrega else "")
                     + f" · Entrega en: {esc(a.nombre)}{', ' + esc(a.direccion) if a.direccion else ''}", t9),
           Spacer(1, 3 * mm)]
    filas = [["Referencia", "Artículo", "Cantidad", "Unidad", "Precio s/IVA", "Importe s/IVA"]]
    for x in p.lineas:
        pr = x.producto
        imp = (Decimal(str(x.cantidad)) * Decimal(str(x.precio))).quantize(Decimal("0.01")) if x.precio is not None else None
        filas.append([Paragraph(esc(pr.ref_proveedor or pr.referencia), t9),
                      Paragraph(esc(pr.articulo) + (f"<br/><font color='#666'>{esc(pr.marca)}</font>" if pr.marca else "")
                                + (f"<br/><i>{esc(x.nota)}</i>" if x.nota else ""), t9),
                      num_txt(x.cantidad, 0), esc(pr.unidad),
                      f"{Decimal(str(x.precio)):.2f} €".replace(".", ",") if x.precio is not None else "—",
                      f"{imp:.2f} €".replace(".", ",") if imp is not None else "—"])
    tot = totales(p)
    eur = lambda v: f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
    filas += [["", "", "", "", "Base", eur(tot["base"])], ["", "", "", "", "IVA", eur(tot["iva"])],
              ["", "", "", "", "Total estimado", eur(tot["total"])]]
    n = len(filas)
    t = Table(filas, colWidths=[28 * mm, ancho - 112 * mm, 18 * mm, 16 * mm, 24 * mm, 26 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(marca.NEGRO)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, n - 4), .4, colors.HexColor("#cfc6b4")),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (4, n - 1), (-1, n - 1), "Helvetica-Bold"), ("LINEABOVE", (4, n - 3), (-1, n - 3), .6, colors.black)]))
    el += [t, Spacer(1, 4 * mm)]
    if tot["sin_precio"]:
        el.append(Paragraph(f"{tot['sin_precio']} línea(s) sin precio: indiquen su precio al confirmar el pedido.", t9))
    el.append(Paragraph("Importes estimados según los últimos precios conocidos. Si el precio ha cambiado, "
                        "rogamos lo indiquen antes de servir el pedido. En la factura indiquen el nº de pedido.", t9))
    if p.notas:
        el += [Spacer(1, 2 * mm), Paragraph(f"<b>Observaciones:</b> {esc(p.notas)}", t9)]
    doc.build(el)
    return out.getvalue()


# --------------------------------------------------------------------------- INVERGESTION → PMS
def leer_paquete(datos: bytes) -> tuple[list[dict], dict, list[str]]:
    """(filas de productos.csv, manifest, avisos). Acepta el ZIP o directamente el productos.csv."""
    avisos: list[str] = []
    manifest: dict = {}
    if datos[:2] == b"PK":
        try:
            z = zipfile.ZipFile(io.BytesIO(datos))
        except zipfile.BadZipFile as e:
            raise ValueError("El fichero ZIP está dañado") from e
        nombres = {n.split("/")[-1].lower(): n for n in z.namelist()}
        if "productos.csv" not in nombres:
            raise ValueError("El ZIP no trae productos.csv")
        if z.getinfo(nombres["productos.csv"]).file_size > TAM_MAX:
            raise ValueError("productos.csv es demasiado grande")
        csv_bytes = z.read(nombres["productos.csv"])
        if "manifest.json" in nombres:
            try:
                manifest = json.loads(z.read(nombres["manifest.json"]).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                avisos.append("manifest.json no se ha podido leer: se importa productos.csv igualmente.")
        else:
            avisos.append("El ZIP no trae manifest.json.")
    else:
        csv_bytes = datos
    if csv_bytes.startswith(b"\xef\xbb\xbf"):
        avisos.append("productos.csv lleva BOM (no debería): se ha ignorado.")
        csv_bytes = csv_bytes[3:]
    try:
        texto = csv_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError("productos.csv no está en UTF-8") from e
    lector = csv.DictReader(io.StringIO(texto, newline=""), delimiter=";", quotechar='"')
    cab = [c.strip().lower() for c in (lector.fieldnames or [])]
    faltan = [c for c in ("referencia", "articulo") if c not in cab]
    if faltan:
        raise ValueError(f"productos.csv no tiene las columnas: {', '.join(faltan)}")
    otras = [c for c in COLUMNAS_IMPORTACION if c not in cab]
    if otras:
        avisos.append(f"Columnas que no vienen (se dejan como estaban): {', '.join(otras)}.")
    filas = [{(k or "").strip().lower(): (v or "").strip() for k, v in f.items()} for f in lector]
    n = manifest.get("filas")
    if isinstance(n, int) and n != len(filas):
        avisos.append(f"El manifest indica {n} filas y productos.csv trae {len(filas)}.")
    return filas, manifest, avisos


def importar(db: Session, user: User | None, datos: bytes, confirmar: bool) -> dict:
    filas, manifest, avisos = leer_paquete(datos)
    existentes = {p.referencia: p for p in db.scalars(select(Product))}
    res = {"altas": 0, "modificaciones": 0, "sin_cambios": 0, "errores": [], "avisos": avisos,
           "tipo": manifest.get("tipo"), "fecha": manifest.get("fecha"), "filas": len(filas)}
    vistas: set[str] = set()
    ahora = datetime.now()
    proveedores: dict[tuple, Supplier | None] = {}
    for i, f in enumerate(filas, start=2):
        ref = f.get("referencia", "").strip()
        try:
            if not ref:
                raise ValueError("sin referencia")
            if not f.get("articulo"):
                raise ValueError("sin artículo")
            if ref in vistas:
                raise ValueError("referencia repetida en el fichero")
            vistas.add(ref)
            nuevos = {"articulo": f["articulo"][:250]}
            if "familia" in f:
                nuevos["familia"] = familia(f["familia"])
            if f.get("unidad"):
                nuevos["unidad"] = f["unidad"][:20]
            if "precio" in f:
                nuevos["precio"] = dec(f["precio"])
            if f.get("tipo_iva"):
                nuevos["tipo_iva"] = dec(f["tipo_iva"], 2)
            for k, largo in (("marca", 100), ("ref_proveedor", 60), ("proveedor", 200), ("num_factura", 60)):
                if k in f:
                    nuevos[k] = f[k][:largo] or None
            if "proveedor_nif" in f:
                nuevos["proveedor_nif"] = nif.normalizar(f["proveedor_nif"])
            if f.get("fecha_factura"):
                nuevos["fecha_factura"] = date.fromisoformat(f["fecha_factura"])
            clave = (nuevos.get("proveedor_nif"), nuevos.get("proveedor"))
            if clave not in proveedores:
                proveedores[clave] = proveedor_por_nif(db, *clave)
            if proveedores[clave]:
                nuevos["supplier_id"] = proveedores[clave].id
        except ValueError as e:
            res["errores"].append({"fila": i, "referencia": ref, "motivo": str(e)})
            continue
        p = existentes.get(ref)
        if p is None:
            res["altas"] += 1
            if confirmar:
                p = Product(referencia=ref[:60], origen="INVERGESTION", familia="OTROS", unidad="ud", tipo_iva=21,
                            activo=True, user_id=user.id if user else None)
                for k, v in nuevos.items():
                    setattr(p, k, v)
                db.add(p)
                existentes[ref] = p
            continue
        cambia = {k: v for k, v in nuevos.items() if _distinto(getattr(p, k), v)}
        if not cambia:
            res["sin_cambios"] += 1
            continue
        res["modificaciones"] += 1
        if confirmar:
            for k, v in cambia.items():
                setattr(p, k, v)
            p.actualizado = ahora
    if confirmar:
        db.flush()
    return res


def _distinto(a, b) -> bool:
    if isinstance(b, Decimal) or isinstance(a, (Decimal, float)):
        return (Decimal(str(a)) if a is not None else None) != (Decimal(str(b)) if b is not None else None)
    return (a or None) != (b or None)


# --------------------------------------------------------------------------- PMS → INVERGESTION
def pendientes_exportar(db: Session, asset: Asset) -> tuple[list[dict], list, list]:
    """(filas, productos a marcar, líneas a marcar) de lo nuevo desde el último envío de este activo."""
    from .export_invergestion import codigo_activo
    activo = codigo_activo(asset)
    filas, productos, lineas = [], [], []
    altas_en_pedido: set[int] = set()
    q = select(PurchaseOrderLine, PurchaseOrder).join(PurchaseOrder).where(
        PurchaseOrder.asset_id == asset.id, PurchaseOrder.estado.in_(ESTADOS_EXPORTABLES),
        PurchaseOrderLine.exportado.is_(None)).order_by(PurchaseOrder.fecha, PurchaseOrder.id, PurchaseOrderLine.orden)
    for x, ped in db.execute(q).all():
        pr = x.producto
        alta = pr.origen == "PMS" and pr.alta_exportada is None and pr.id not in altas_en_pedido
        if not alta and x.precio is None:
            continue  # sin precio no se informa: el pedido no aporta coste
        prov = db.get(Supplier, ped.supplier_id) if ped.supplier_id else None
        filas.append(_fila(pr, activo, "ALTA" if alta else "PEDIDO", precio=x.precio if x.precio is not None else pr.precio,
                           proveedor=(prov.nombre if prov else ped.proveedor) or pr.proveedor,
                           proveedor_nif=(prov.nif if prov else None) or pr.proveedor_nif,
                           fecha_pedido=ped.fecha.isoformat(), num_pedido=ped.numero, cantidad=num_txt(x.cantidad, 0)))
        lineas.append(x)
        if alta:
            altas_en_pedido.add(pr.id)
            productos.append(pr)
    for pr in db.scalars(select(Product).where(Product.origen == "PMS", Product.alta_exportada.is_(None),
                                               Product.asset_id == asset.id).order_by(Product.id)):
        if pr.id in altas_en_pedido:
            continue
        filas.append(_fila(pr, activo, "ALTA", precio=pr.precio, proveedor=pr.proveedor,
                           proveedor_nif=pr.proveedor_nif))
        productos.append(pr)
    return filas, productos, lineas


def _fila(pr: Product, activo: str, accion: str, precio, proveedor, proveedor_nif, fecha_pedido="", num_pedido="",
          cantidad="") -> dict:
    return {"referencia": pr.referencia, "articulo": pr.articulo, "familia": familia(pr.familia), "unidad": pr.unidad,
            "precio": num_txt(precio), "tipo_iva": num_txt(pr.tipo_iva), "marca": pr.marca,
            "ref_proveedor": pr.ref_proveedor, "proveedor": proveedor, "proveedor_nif": proveedor_nif,
            "fecha_pedido": fecha_pedido, "num_pedido": num_pedido, "cantidad": cantidad, "activo": activo,
            "accion": accion}


def paquete(filas: list[dict]) -> bytes:
    from .export_invergestion import a_csv
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("productos.csv", a_csv(COLUMNAS_EXPORTACION, filas))
    return out.getvalue()


def nombre_paquete(asset: Asset, dia: date) -> str:
    from .export_invergestion import codigo_activo
    return f"PRODUCTOS_PMS_{codigo_activo(asset)}_{dia:%Y%m%d}.zip"
