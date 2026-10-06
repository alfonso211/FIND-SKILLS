"""Exportación de facturas emitidas y recibidas a INVERGESTION (especificación v1.0 del 6/10/2026).

Dos CSV (UTF-8 con BOM, separador «;», fechas AAAA-MM-DD, importes con punto y 2 decimales) y, junto a cada uno,
un .zip con los PDF de las facturas. Una fila por factura y tipo de IVA; el total se repite en cada fila.

Qué facturas entran en un periodo (envío semanal, con reenvíos sin duplicados en INVERGESTION):
- Emitidas: las emitidas en el periodo (día real de emisión: la fecha de la factura es el último día del mes) y
  las que se han cobrado en el periodo (para informar el cobro).
- Recibidas: las de fecha de factura, registro o pago dentro del periodo.
El PMS no calcula vencimientos ni estados: solo informa lo que tiene registrado.
"""
import csv
import io
import re
import zipfile
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from . import documentos, factura_pdf, nif
from .facturacion import desglose, dinero, lineas_de
from .models import (Asset, Charge, Contact, Expense, Invoice, Lease, ReceivedDocument, Reservation, Supplier,
                     Unit)

ACTIVOS = {"SFL": "SFLORIDA", "SAE": "SAEROPUERTO", "BAB35": "BABILONIA35"}

COLUMNAS_EMITIDAS = [
    "activo", "nif_emisor", "serie", "numero", "tipo_factura", "numero_rectificada", "fecha_expedicion",
    "fecha_operacion", "cliente_nombre", "cliente_nif", "cliente_pais", "cliente_email", "unidad", "reserva_id",
    "canal", "fecha_entrada", "fecha_salida", "concepto", "base", "tipo_iva", "causa_exencion", "cuota_iva",
    "retencion", "total", "forma_pago", "fecha_vencimiento", "importe_cobrado", "fecha_cobro", "estado", "archivo_pdf"]
COLUMNAS_RECIBIDAS = [
    "activo", "nif_receptor", "proveedor_nombre", "proveedor_nif", "proveedor_pais", "proveedor_iban", "numero",
    "tipo_factura", "numero_rectificada", "fecha_factura", "fecha_recepcion", "concepto", "categoria", "unidad",
    "base", "tipo_iva", "cuota_iva", "inversion_sujeto_pasivo", "retencion", "total", "forma_pago", "dias_pago",
    "fecha_vencimiento", "importe_pagado", "fecha_pago", "estado", "archivo_pdf"]
OBLIGATORIAS_EMITIDAS = ["activo", "nif_emisor", "serie", "numero", "tipo_factura", "fecha_expedicion",
                         "cliente_nombre", "cliente_nif", "concepto", "base", "tipo_iva", "cuota_iva", "total",
                         "forma_pago", "importe_cobrado", "estado", "archivo_pdf"]
OBLIGATORIAS_RECIBIDAS = ["activo", "nif_receptor", "proveedor_nombre", "proveedor_nif", "numero", "tipo_factura",
                          "fecha_factura", "concepto", "categoria", "base", "tipo_iva", "cuota_iva",
                          "inversion_sujeto_pasivo", "total", "forma_pago", "importe_pagado", "estado",
                          "archivo_pdf"]

FORMAS_EMITIDAS = {"efectivo": "EFECTIVO", "tarjeta": "TARJETA", "transferencia": "TRANSFERENCIA",
                   "domiciliacion": "DOMICILIACION", "bizum": "TRANSFERENCIA", "plataforma": "OTA"}
FORMAS_RECIBIDAS = {"efectivo": "EFECTIVO", "tarjeta": "TARJETA", "transferencia": "TRANSFERENCIA",
                    "domiciliacion": "DOMICILIACION", "bizum": "TRANSFERENCIA", "plataforma": "COMPENSACION_OTA"}
CATEGORIAS = {"suministros": "SUMINISTROS", "telecom": "SUMINISTROS", "mantenimiento": "MANTENIMIENTO",
              "limpieza": "LIMPIEZA", "amenities": "AMENITIES", "comunidad": "COMUNIDAD", "seguros": "SEGUROS",
              "comisiones": "COMISION_CANAL"}  # el resto: OTROS
CANALES = {"directo": "DIRECTO", "booking": "BOOKING", "airbnb": "AIRBNB", "expedia": "EXPEDIA", "agencia": "AGENCIA",
           "web": "DIRECTO"}


# --------------------------------------------------------------------------- formato
def importe(x) -> str:
    return f"{dinero(x or 0):.2f}"


def porcentaje(x) -> str:
    d = Decimal(str(x or 0))
    return str(int(d)) if d == d.to_integral_value() else f"{d.normalize()}"


def fecha(x) -> str:
    if not x:
        return ""
    return (x.date() if isinstance(x, datetime) else x).isoformat()


def codigo_activo(a: Asset) -> str:
    return ACTIVOS.get(a.codigo, a.codigo.upper())


def _paises() -> dict[str, str]:
    import gettext

    import pycountry
    try:
        es = gettext.translation("iso3166-1", pycountry.LOCALES_DIR, languages=["es"]).gettext
    except OSError:
        def es(s):
            return s
    out = {}
    for c in pycountry.countries:
        for n in (c.name, getattr(c, "common_name", None), getattr(c, "official_name", None), es(c.name)):
            if n:
                out[nif.nombre_clave(n)] = c.alpha_2
        out[c.alpha_3] = out[c.alpha_2] = c.alpha_2
    out.update({nif.nombre_clave("Espana"): "ES", "ESP": "ES"})
    return out


_PAISES: dict[str, str] | None = None


def iso2(pais: str | None) -> str:
    """«España», «Spain», «ESP» o «ES» -> «ES». Vacío si no se reconoce."""
    global _PAISES
    if not pais:
        return ""
    if _PAISES is None:
        _PAISES = _paises()
    p = pais.strip()
    return _PAISES.get(p.upper()) or _PAISES.get(nif.nombre_clave(p), "")


def nombre_fichero(prefijo: str, activo: str, desde: date, hasta: date, ext: str) -> str:
    return f"{prefijo}_{activo}_{desde:%Y%m%d}_{hasta:%Y%m%d}.{ext}"


def a_csv(columnas: list[str], filas: list[dict]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, delimiter=";", quotechar='"', quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow(columnas)
    for f in filas:
        w.writerow(["" if f.get(c) is None else f.get(c) for c in columnas])
    return ("﻿" + out.getvalue()).encode("utf-8")


def _limpio(s: str | None, largo: int = 200) -> str:
    return " ".join((s or "").split())[:largo]


def _nombre_pdf(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", texto).strip("-")


# --------------------------------------------------------------------------- emitidas
def emitidas(db: Session, asset_ids: set[int], desde: date, hasta: date) -> tuple[list[dict], list[tuple], list[str]]:
    """(filas, [(nombre_pdf, factura)], avisos)."""
    ini, fin = datetime.combine(desde, time.min), datetime.combine(hasta, time.max)
    facturas = list(db.scalars(select(Invoice).where(
        Invoice.asset_id.in_(asset_ids or {-1}),
        or_(and_(Invoice.creada >= ini, Invoice.creada <= fin),
            and_(Invoice.cobro_marcado >= ini, Invoice.cobro_marcado <= fin))).order_by(Invoice.creada, Invoice.id)))
    originales = {f.id: f for f in db.scalars(select(Invoice).where(
        Invoice.id.in_({f.rectifica_id for f in facturas if f.rectifica_id} or {-1})))}
    reservas = {r.id: r for r in db.scalars(select(Reservation).where(
        Reservation.id.in_({f.reservation_id for f in facturas if f.reservation_id} or {-1})))}
    recibos = {c.id: c for c in db.scalars(select(Charge).where(
        Charge.id.in_({f.charge_id for f in facturas if f.charge_id} or {-1})))}
    contactos = {c.id: c for c in db.scalars(select(Contact).where(
        Contact.id.in_({f.contact_id for f in facturas if f.contact_id} or {-1})))}
    filas, pdfs, avisos = [], [], []
    for f in facturas:
        r, c = reservas.get(f.reservation_id), recibos.get(f.charge_id)
        lease: Lease | None = c.lease if c else None
        unidad: Unit | None = r.unit if r else (lease.unit if lease else None)
        cliente = contactos.get(f.contact_id)
        rect = f.tipo == "rectificativa"
        original = originales.get(f.rectifica_id)
        pdf = _nombre_pdf(f"{f.codigo}.pdf")
        if f.cobro == "pendiente" or f.cobro == "anulada":
            cobrado, f_cobro = Decimal(0), None
        elif rect:  # devolución de lo cobrado con la original (si se llegó a cobrar)
            cobrado = dinero(f.total) if original is not None and original.cobro != "anulada" else Decimal(0)
            f_cobro = f.creada if cobrado else None
        else:
            cobrado, f_cobro = dinero(f.total), f.cobro_fecha or f.fecha_operacion
        forma = FORMAS_EMITIDAS.get(f.cobro_forma or f.forma_pago or "")
        if not forma:
            forma = "TRANSFERENCIA"
            avisos.append(f"{f.codigo}: sin forma de pago registrada; se envía TRANSFERENCIA")
        canal = "CONTRATO" if lease else CANALES.get((r.canal or "").lower(), (r.canal or "").upper()) if r else ""
        pais = iso2(cliente.pais if cliente else None) or ("ES" if nif.tipo(f.cliente.get("nif") or "") else "")
        cab = {
            "activo": codigo_activo(f.asset), "nif_emisor": f.emisor.get("nif"), "serie": f.serie,
            "numero": f"{f.numero:05d}/{f.anio}",
            "tipo_factura": "RECTIFICATIVA" if rect else "COMPLETA",
            "numero_rectificada": f"{original.serie} {original.numero:05d}/{original.anio}" if original else "",
            "fecha_expedicion": fecha(f.fecha_expedicion),
            "fecha_operacion": fecha(f.fecha_operacion) if f.fecha_operacion != f.fecha_expedicion else "",
            "cliente_nombre": _limpio(f.cliente.get("nombre")), "cliente_nif": f.cliente.get("nif") or "",
            "cliente_pais": pais, "cliente_email": (cliente.email if cliente else "") or "",
            "unidad": unidad.codigo if unidad else "",
            "reserva_id": (r.localizador or f"R-{r.id}") if r else ((lease.referencia or f"CT-{lease.id}") if lease else ""),
            "canal": canal, "fecha_entrada": fecha(r.fecha_entrada) if r else "",
            "fecha_salida": fecha(r.fecha_salida) if r else "",
            "retencion": "", "total": importe(f.total), "forma_pago": forma,
            "fecha_vencimiento": fecha(c.fecha_vencimiento) if c else "",
            "importe_cobrado": importe(cobrado), "fecha_cobro": fecha(f_cobro),
            "estado": "EMITIDA", "archivo_pdf": pdf,
        }
        lineas = lineas_de(f)
        for g in desglose(lineas):
            conceptos = [x["concepto"] for x in lineas if x["tipo_iva"] == g["tipo_iva"]]
            filas.append({**cab, "concepto": _limpio(conceptos[0] if conceptos else f.concepto) +
                          (f" (+{len(conceptos) - 1})" if len(conceptos) > 1 else ""),
                          "base": importe(g["base"]), "tipo_iva": porcentaje(g["tipo_iva"]),
                          "causa_exencion": (f.exencion or "") if g["tipo_iva"] == 0 else "",
                          "cuota_iva": importe(g["cuota"])})
        pdfs.append((pdf, f))
    avisos += validar(filas, OBLIGATORIAS_EMITIDAS, "numero", "cliente_nif", "cliente_pais")
    return filas, pdfs, avisos


# --------------------------------------------------------------------------- recibidas
def recibidas(db: Session, asset_ids: set[int], desde: date, hasta: date) -> tuple[list[dict], list[tuple], list[str]]:
    """(filas, [(nombre_fichero, documento)], avisos). Se exportan los apuntes de la cuenta de gastos."""
    ini, fin = datetime.combine(desde, time.min), datetime.combine(hasta, time.max)
    gastos = list(db.scalars(select(Expense).where(
        Expense.asset_id.in_(asset_ids or {-1}),
        or_(and_(Expense.fecha >= desde, Expense.fecha <= hasta), and_(Expense.creado >= ini, Expense.creado <= fin),
            and_(Expense.fecha_pago >= desde, Expense.fecha_pago <= hasta))).order_by(Expense.fecha, Expense.id)))
    activos = {a.id: a for a in db.scalars(select(Asset))}
    proveedores = {s.id: s for s in db.scalars(select(Supplier).where(
        Supplier.id.in_({g.supplier_id for g in gastos if g.supplier_id} or {-1})))}
    docs = {d.id: d for d in db.scalars(select(ReceivedDocument).where(
        ReceivedDocument.id.in_({g.documento_id for g in gastos if g.documento_id} or {-1})))}
    unidades = {u.id: u.codigo for u in db.scalars(select(Unit).where(
        Unit.id.in_({g.unit_id for g in gastos if g.unit_id} or {-1})))}
    filas, ficheros, avisos = [], [], []
    for g in gastos:
        a, s, d = activos[g.asset_id], proveedores.get(g.supplier_id), docs.get(g.documento_id)
        prov_nif = (s.nif if s else "") or ""
        pais = iso2(s.pais if s else None) or ("ES" if not prov_nif or nif.tipo(prov_nif) else "")
        extranjero = bool(prov_nif) and not nif.tipo(prov_nif) and re.match(r"^[A-Z]{2}", prov_nif or "") \
            and not prov_nif.upper().startswith("ES")
        if extranjero and not pais:
            pais = prov_nif[:2].upper()
        numero = g.numero_factura or f"SN-{g.id}"
        if not g.numero_factura:
            avisos.append(f"Gasto {g.id} ({_limpio(g.proveedor, 40)}, {g.fecha:%d/%m/%Y}): sin nº de factura; se envía {numero}")
        archivo = ""
        if d:  # siempre PDF: las fotos se convierten al empaquetar (zip_documentos)
            archivo = _nombre_pdf(f"{prov_nif or 'SINNIF'}-{numero}.pdf")
            ficheros.append((archivo, d))
            if g.fecha == (d.subido or g.creado).date():
                avisos.append(f"{_limpio(g.proveedor, 40)} nº {numero}: la fecha de la factura ({g.fecha:%d/%m/%Y}) es "
                              "la del día en que se registró; compruebe que es la que figura en la factura")
        forma = FORMAS_RECIBIDAS.get(g.forma_pago or "")
        if not forma:
            forma = "TRANSFERENCIA"
            avisos.append(f"{_limpio(g.proveedor, 40)} nº {numero}: sin forma de pago (transferencia o cargo en "
                          "cuenta); se envía TRANSFERENCIA. Indíquela en Cuenta de gastos → Editar")
        liquido = dinero(g.total) - dinero(g.retencion or 0)  # total de la factura: base + IVA − retención
        isp = "S" if Decimal(str(g.tipo_iva)) == 0 and pais and pais != "ES" else "N"
        filas.append({
            "activo": codigo_activo(a), "nif_receptor": a.company.cif, "proveedor_nombre": _limpio(g.proveedor),
            "proveedor_nif": prov_nif, "proveedor_pais": pais if pais != "ES" else "", "proveedor_iban": "",
            "numero": numero, "tipo_factura": "RECTIFICATIVA" if dinero(g.total) < 0 else "ORDINARIA",
            "numero_rectificada": "", "fecha_factura": fecha(g.fecha), "fecha_recepcion": fecha(d.subido if d else g.creado),
            "concepto": _limpio(g.concepto), "categoria": CATEGORIAS.get(g.categoria, "OTROS"),
            "unidad": unidades.get(g.unit_id, ""), "base": importe(g.base), "tipo_iva": porcentaje(g.tipo_iva),
            "cuota_iva": importe(g.cuota), "inversion_sujeto_pasivo": isp,
            "retencion": importe(g.retencion) if g.retencion else "", "total": importe(liquido),
            "forma_pago": forma, "dias_pago": "", "fecha_vencimiento": fecha(g.vencimiento),
            "importe_pagado": importe(liquido if g.pagado else 0), "fecha_pago": fecha(g.fecha_pago) if g.pagado else "",
            "estado": "REGISTRADA", "archivo_pdf": archivo})
    avisos += validar(filas, OBLIGATORIAS_RECIBIDAS, "numero", "proveedor_nif", "proveedor_pais")
    return filas, ficheros, avisos


# --------------------------------------------------------------------------- comprobaciones (las de INVERGESTION)
def validar(filas: list[dict], obligatorias: list[str], clave: str, campo_nif: str, campo_pais: str) -> list[str]:
    """Lo que INVERGESTION rechazaría: campos obligatorios vacíos, NIF español con letra de control errónea y
    descuadres de base + cuota − retención frente al total (tolerancia 0,02 €)."""
    avisos, vistos = [], set()
    sumas: dict[str, Decimal] = {}
    for x in filas:
        ref = f"{x.get('serie', '') + ' ' if x.get('serie') else ''}{x[clave]}"
        faltan = [c for c in obligatorias if x.get(c) in (None, "")]
        if faltan and (ref, "faltan") not in vistos:
            vistos.add((ref, "faltan"))
            avisos.append(f"{ref}: falta {', '.join(faltan)}")
        n = x.get(campo_nif) or ""
        espanol = x.get(campo_pais) in ("", "ES")
        if n and espanol and not nif.tipo(n) and (ref, "nif") not in vistos:
            vistos.add((ref, "nif"))
            avisos.append(f"{ref}: NIF «{n}» no válido (INVERGESTION rechazará la fila)")
        k = f"{x.get('nif_emisor') or x.get('proveedor_nif')}|{ref}"
        sumas[k] = sumas.get(k, Decimal(0)) + Decimal(x["base"]) + Decimal(x["cuota_iva"]) - Decimal(x.get("retencion") or 0)
        sumas[k + "|total"] = Decimal(x["total"])
    for k, v in sumas.items():
        if not k.endswith("|total") and abs(v - sumas[k + "|total"]) > Decimal("0.02"):
            avisos.append(f"{k.split('|', 1)[1]}: base + IVA ({v}) no cuadra con el total ({sumas[k + '|total']})")
    return avisos


# --------------------------------------------------------------------------- paquete
def zip_pdfs_emitidas(db: Session, pdfs: list[tuple]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, f in pdfs:
            original = db.get(Invoice, f.rectifica_id) if f.rectifica_id else None
            z.writestr(nombre, factura_pdf.generar(f, f.asset, original))
    return out.getvalue()


def zip_documentos(ficheros: list[tuple]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        hechos = set()
        for nombre, d in ficheros:
            if nombre in hechos:
                continue
            hechos.add(nombre)
            z.writestr(nombre, a_pdf(documentos.leer(d.fichero), d.mime))
    return out.getvalue()


def a_pdf(datos: bytes, mime: str) -> bytes:
    """El documento como PDF (INVERGESTION solo admite PDF): las fotos escaneadas se convierten."""
    if mime == "application/pdf" or not mime.startswith("image/"):
        return datos
    from PIL import Image
    out = io.BytesIO()
    Image.open(io.BytesIO(datos)).convert("RGB").save(out, "PDF", resolution=150)
    return out.getvalue()
