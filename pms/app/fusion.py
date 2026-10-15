"""Fusión PMS ↔ gestión (INVERGESTION) · contrato «fusion1» (14/10/2026). Ver docs/pasarela_v2.md, apartado «Fusión:
facturas, pagos, proveedores y catálogo», y las instrucciones originales en docs/fusion/.

Lo que se registra en uno pasa solo al otro, con sus documentos: facturas recibidas (cuenta de gastos), sus pagos,
facturas emitidas y sus cobros, proveedores y catálogo de productos. Las fianzas no: siguen su circuito (fianza.*).

- PMS → gestión: cada alta o cambio deja un aviso en la cola `gestion_cola` (la de la fase 4: mismos reintentos y
  aviso por correo). El aviso guarda solo qué registro es; sus datos y documentos se toman al mandarlo por primera vez,
  así un gasto creado y completado enseguida sale en un solo aviso. Solo de los activos con la casilla «Sincronizar
  facturas» y con PMS_GESTION_SYNC_FACTURAS=1 en el .env del servidor (0 por defecto: no se manda nada nuevo).
- Gestión → PMS: POST /api/gestion/eventos (firma HMAC de la fase 4). Lo que manda gestión se aplica SIEMPRE: gestión
  manda en los datos contables. Idempotente por id_evento y sin eco (lo que llega de gestión no genera avisos).
- Documentos: no viajan en el aviso. Cada parte descarga los del otro por la red interna con una petición firmada y
  comprueba la sha256. Los del PMS se descifran aquí con PMS_DOCS_KEY: la clave nunca sale del PMS.
- Carga inicial: GET /api/gestion/fusion/inventario (firmado sobre la consulta), para «Emparejar facturas» de gestión.
- Botón «PMS» de gestión: GET /sso/gestion?pase=…&firma=… (60 s, un solo uso, usuario por email; el PMS decide los
  permisos). El botón «Abrir en gestión» del PMS usa el /sso/pms de siempre con destino e id de gestión.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from . import calendario_comun, documentos, gestion, maestros, nif
from . import export_invergestion as ei
from .database import SessionLocal, get_db
from .facturacion import desglose, dinero, lineas_de
from .models import (Asset, AuditLog, Charge, Company, Contact, Expense, ExternalInvoice, FusionDocumento, FusionEnlace,
                     FusionEntrada, GestionEvento, Invoice, Lease, Product, PurchaseOrder, PurchaseOrderLine,
                     ReceivedDocument, Reservation, Supplier, Unit, User)
from .security import Scope, audit, create_token, get_scope
from .utils import bad_request, get_or_404

log = logging.getLogger("pms.fusion")

SYNC = (os.environ.get("PMS_GESTION_SYNC_FACTURAS") or "0") == "1"
VERSION = "fusion1"
SSO_VALIDEZ = 60  # segundos
DESDE_GESTION = "fusion_desde_gestion"  # marca de la sesión mientras se aplica un aviso de gestión (sin eco)
ID_EVENTO = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")

TIPOS = ("factura_recibida.creada", "factura_recibida.actualizada", "factura_recibida.anulacion_pedida",
         "factura_recibida.anulada", "factura_emitida.emitida", "factura_emitida.rectificada", "documento.adjuntado",
         "pago.registrado", "pago.anulado", "cobro.registrado", "cobro.anulado", "proveedor.alta",
         "proveedor.actualizado", "producto.alta", "producto.actualizado", "precio.pedido")
# identificador del PMS en los avisos (pms_id): «gasto-12», «factura-34», «pago-12»…
PREFIJO = {"recibida": "gasto", "emitida": "factura", "externa": "externa", "pago": "pago", "cobro": "cobro",
           "proveedor": "proveedor", "producto": "producto"}
DESTINOS = {"recibida", "emitida", "pago", "proveedor"}  # «Abrir en gestión» y botón «PMS» de gestión
CATEGORIAS_DOC = {"FACTURA": "factura", "JUSTIFICANTE": "justificante", "ALBARAN": "albaran", "OTRO": "otro"}
VINCULO = {"recibida": "factura_recibida", "emitida": "factura_emitida", "pago": "pago", "cobro": "cobro"}
# Campos contables del gasto: con la factura ya en gestión solo se cambian allí («Pedir corrección»)
CONTABLES = ("fecha", "proveedor", "numero_factura", "vencimiento", "base", "tipo_iva", "cuota", "total", "retencion",
             "retencion_pct", "forma_pago", "naturaleza")
CONTABLES_PROVEEDOR = ("nombre", "nif", "pais")
CORREGIBLES = ("proveedor_nombre", "proveedor_nif", "numero", "fecha_factura", "fecha_vencimiento", "concepto", "base",
               "cuota_iva", "retencion", "total", "forma_pago")


class NoAplicable(Exception):
    """El aviso todavía no se puede aplicar (p. ej., el pago de una factura que aún no ha llegado): 400 y gestión lo
    reintenta con su calendario normal."""


def pid(ent: str, n: int) -> str:
    return f"{PREFIJO[ent]}-{n}"


def ref_de(pms_id, ent: str) -> int | None:
    m = re.fullmatch(rf"{PREFIJO[ent]}-(\d+)", str(pms_id or ""))
    return int(m.group(1)) if m else None


def _iso(d) -> str | None:
    if not d:
        return None
    return (d.date() if isinstance(d, datetime) else d).isoformat()


def _n(x) -> float | None:
    return None if x is None else float(dinero(x))


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sociedad(c: Company | None) -> str | None:
    """Código de la sociedad en gestión: INV, CDC, EC o ETH."""
    if not c:
        return None
    t = "".join(x for x in unicodedata.normalize("NFD", c.nombre.upper()) if unicodedata.category(x) != "Mn")
    for clave, cod in (("INVERSIETE", "INV"), ("COMERCIAL DEL CAMPO", "CDC"), ("EDIFICIOS CAMERANOS", "EC"),
                       ("TURISTICA HOTELERA", "ETH"), ("ETHOSA", "ETH")):
        if clave in t:
            return cod
    return None


def _activo_pms(db: Session, codigo: str | None) -> Asset | None:
    if not codigo:
        return None
    inv = {v: k for k, v in gestion.ACTIVOS.items()}
    return db.scalar(select(Asset).where(Asset.codigo == inv.get(codigo, codigo)))


def sincroniza(db: Session, asset_id: int | None) -> bool:
    if not SYNC or not asset_id:
        return False
    a = db.get(Asset, asset_id)
    return bool(a and a.sync_facturas)


def alguno_sincroniza(db: Session) -> bool:
    return SYNC and bool(db.scalar(select(Asset.id).where(Asset.sync_facturas.is_(True)).limit(1)))


def enlace(db: Session, ent: str, ref: int) -> FusionEnlace | None:
    return db.scalar(select(FusionEnlace).where(FusionEnlace.tipo == ent, FusionEnlace.pms_ref == ref))


def _enlazar(db: Session, ent: str, ref: int, gestion_id=None, asset_id=None, origen="PMS",
             estado="sincronizada") -> FusionEnlace:
    e = enlace(db, ent, ref)
    if e is None:
        e = FusionEnlace(tipo=ent, pms_ref=ref, asset_id=asset_id, origen=origen, estado=estado)
        db.add(e)
    if gestion_id:
        e.gestion_id = str(gestion_id)[:120]
    if estado and e.estado != "anulada":
        e.estado = estado
    e.actualizado = datetime.now()
    return e


def gestionada(db: Session, ent: str, ref: int) -> FusionEnlace | None:
    """El registro ya está en gestión (gestión manda en sus datos contables)."""
    e = enlace(db, ent, ref)
    return e if e is not None and e.estado == "sincronizada" else None


# --------------------------------------------------------------------------- avisos al PMS → gestión (cola)
def _pendiente(db: Session, tipo: str, ent: str, ref: int) -> GestionEvento | None:
    """Aviso del mismo registro aún sin intentar (sus datos se tomarán al mandarlo: no hace falta otro)."""
    patron = f"pms-f1-{tipo}-{ent}-{ref}-".replace("_", "\\_")
    return db.scalar(select(GestionEvento).where(GestionEvento.id_evento.like(patron + "%", escape="\\"),
                                                 GestionEvento.intentos == 0,
                                                 GestionEvento.estado == "pendiente").limit(1))


def encolar(db: Session, tipo: str, ent: str, ref: int, extra: dict | None = None,
            agrupar: bool = True) -> GestionEvento | None:
    if agrupar and _pendiente(db, tipo, ent, ref):
        return None
    if tipo in ("factura_recibida.actualizada", "documento.adjuntado") and ent == "recibida" and \
            _pendiente(db, "factura_recibida.creada", "recibida", ref) and not (extra or {}).get("cambios"):
        return None  # el alta aún no ha salido: llevará los datos y documentos actuales
    ev = GestionEvento(id_evento=f"pms-f1-{tipo}-{ent}-{ref}-{uuid.uuid4().hex[:12]}", tipo=tipo,
                       datos={"_fusion": {"ent": ent, "ref": ref, **(extra or {})}}, estado="pendiente", intentos=0,
                       proximo=datetime.now())
    db.add(ev)
    return ev


GASTO_CAMBIOS = CONTABLES + ("concepto", "categoria", "unit_id", "supplier_id")
PROVEEDOR_CAMBIOS = ("nombre", "nif", "pais", "email", "telefono", "iban", "forma_pago")
PRODUCTO_CAMBIOS = ("articulo", "familia", "unidad")


@event.listens_for(SessionLocal, "after_flush")
def _detectar(session: Session, _ctx) -> None:
    if not SYNC or session.info.get(DESDE_GESTION):
        return
    from sqlalchemy import inspect as sa_inspect
    pend = session.info.setdefault("fusion_pend", [])
    for obj in list(session.new):
        if isinstance(obj, Expense):
            pend.append(("factura_recibida.creada", "recibida", obj, None))
        elif isinstance(obj, Invoice):
            rect = obj.tipo == "rectificativa"
            pend.append(("factura_emitida.rectificada" if rect else "factura_emitida.emitida", "emitida", obj, None))
            if obj.cobro == "cobrada" and not rect:
                pend.append(("cobro.registrado", "cobro", obj, None))
        elif isinstance(obj, Supplier):
            pend.append(("proveedor.alta", "proveedor", obj, None))
        elif isinstance(obj, Product):
            pend.append(("producto.alta", "producto", obj, None))
    for obj in list(session.dirty):
        if obj in session.new or obj in session.deleted:
            continue
        st = sa_inspect(obj)

        def cambio(*campos):
            return any(st.attrs[c].history.has_changes() for c in campos)
        if isinstance(obj, Expense):
            if cambio("pagado"):
                pend.append(("pago.registrado" if obj.pagado else "pago.anulado", "pago", obj, None))
            cambiados = {c for c in GASTO_CAMBIOS if cambio(c)}
            if cambio("pagado"):
                cambiados.discard("forma_pago")  # cómo se pagó va en el aviso del pago
            if cambiados:
                pend.append(("factura_recibida.actualizada", "recibida", obj, None))
            if cambio("documento_id") and obj.documento_id:
                pend.append(("documento.adjuntado", "recibida", obj, {"rd": obj.documento_id, "cat": "FACTURA"}))
        elif isinstance(obj, Invoice) and cambio("cobro"):
            antes = st.attrs["cobro"].history.deleted
            if obj.cobro == "cobrada":
                pend.append(("cobro.registrado", "cobro", obj, None))
            elif antes and antes[0] == "cobrada":
                pend.append(("cobro.anulado", "cobro", obj, None))
        elif isinstance(obj, Supplier) and cambio(*PROVEEDOR_CAMBIOS):
            pend.append(("proveedor.actualizado", "proveedor", obj, None))
        elif isinstance(obj, Product) and cambio(*PRODUCTO_CAMBIOS):
            pend.append(("producto.actualizado", "producto", obj, None))
        elif isinstance(obj, PurchaseOrder) and cambio("estado"):
            from .pedidos import ESTADOS_EXPORTABLES
            antes = st.attrs["estado"].history.deleted
            if obj.estado in ESTADOS_EXPORTABLES and not (antes and antes[0] in ESTADOS_EXPORTABLES):
                pend.append(("precio.pedido", "pedido", obj, None))


@event.listens_for(SessionLocal, "after_flush_postexec")
def _encolar_detectados(session: Session, _ctx) -> None:
    pend = session.info.pop("fusion_pend", [])
    if not pend:
        return
    vistos = set()
    for tipo, ent, obj, extra in pend:
        k = (tipo, ent, obj.id, json.dumps(extra, sort_keys=True))
        if k in vistos:
            continue
        vistos.add(k)
        try:
            if ent in ("recibida", "pago", "emitida", "cobro"):
                if not sincroniza(session, obj.asset_id):
                    continue
            elif ent == "pedido":
                if not sincroniza(session, obj.asset_id):
                    continue
                for x in session.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.pedido_id == obj.id,
                                                                         PurchaseOrderLine.precio.is_not(None))):
                    encolar(session, "precio.pedido", "linea", x.id, agrupar=False)
                continue
            elif not alguno_sincroniza(session):
                continue
            if tipo == "pago.anulado" and gestionada(session, "pago", obj.id) is None and \
                    _pendiente(session, "pago.registrado", "pago", obj.id):
                continue  # el pago aún no había salido: no hay nada que anular en gestión
            encolar(session, tipo, ent, obj.id, extra)
        except Exception:  # noqa: BLE001 — un fallo al preparar el aviso no debe impedir la operación
            log.exception("No se pudo preparar el aviso %s para gestión", tipo)


# --------------------------------------------------------------------------- datos de cada aviso (al mandarlo)
def _desc_rd(x: ReceivedDocument, categoria: str) -> dict:
    return {"doc_id": f"rd-{x.id}", "nombre": x.nombre, "tipo_mime": x.mime, "tamano": x.tamano, "sha256": x.sha256,
            "categoria": categoria}


def _desc_fd(x: FusionDocumento) -> dict:
    return {"doc_id": f"fd-{x.id}", "nombre": x.nombre, "tipo_mime": x.mime, "tamano": x.tamano, "sha256": x.sha256,
            "categoria": x.categoria}


def _de_gestion(db: Session, documento_id: int | None) -> bool:
    """El documento vino de gestión: no se le devuelve."""
    return bool(documento_id and db.scalar(select(FusionDocumento.id).where(
        FusionDocumento.documento_id == documento_id, FusionDocumento.origen == "GESTION")))


def documentos_recibida(db: Session, g: Expense) -> list[dict]:
    out = []
    if g.documento_id and not _de_gestion(db, g.documento_id):
        x = db.get(ReceivedDocument, g.documento_id)
        if x:
            out.append(_desc_rd(x, "FACTURA"))
    for f in db.scalars(select(FusionDocumento).where(FusionDocumento.tipo == "recibida", FusionDocumento.pms_ref == g.id,
                                                      FusionDocumento.origen == "PMS", FusionDocumento.estado == "ok")
                        .order_by(FusionDocumento.id)):
        x = db.get(ReceivedDocument, f.documento_id) if f.documento_id else None
        if x:
            out.append(_desc_rd(x, f.categoria))
    return out


def datos_recibida(db: Session, g: Expense) -> dict:
    s = db.get(Supplier, g.supplier_id) if g.supplier_id else None
    pnif = s.nif if s else None
    pais = ei.pais_iso(s.pais if s else None, nif_=pnif)[0]
    doc = db.get(ReceivedDocument, g.documento_id) if g.documento_id else None
    u = db.get(Unit, g.unit_id) if g.unit_id else None
    liquido = dinero(g.total) - dinero(g.retencion or 0)
    e = enlace(db, "recibida", g.id)
    return {
        "pms_id": pid("recibida", g.id), "gestion_id": e.gestion_id if e else None,
        "proveedor_nombre": g.proveedor, "proveedor_nif": pnif, "proveedor_pais": pais,
        "proveedor_iban": s.iban if s else None, "numero": g.numero_factura or f"SN-{g.id}",
        "tipo_factura": "RECTIFICATIVA" if liquido < 0 else "ORDINARIA", "numero_rectificada": None,
        "fecha_factura": _iso(g.fecha), "fecha_recepcion": _iso(doc.subido if doc else g.creado),
        "fecha_vencimiento": _iso(g.vencimiento), "dias_pago": None, "concepto": g.concepto,
        "categoria": ei.CATEGORIAS.get(g.categoria, "OTROS"), "unidad": u.codigo if u else None,
        "lineas": [{"base": _n(g.base), "tipo_iva": float(g.tipo_iva), "cuota_iva": _n(g.cuota)}],
        "base": _n(g.base), "cuota_iva": _n(g.cuota), "retencion": _n(g.retencion) if g.retencion else None,
        "total": float(liquido), "inversion_sujeto_pasivo": Decimal(str(g.tipo_iva)) == 0 and pais != "ES",
        "forma_pago": ei.FORMAS_RECIBIDAS.get(g.forma_pago or ""), "estado": "REGISTRADA"}


def datos_pago(db: Session, g: Expense) -> dict:
    ep, ef = enlace(db, "pago", g.id), enlace(db, "recibida", g.id)
    return {"pms_id": pid("pago", g.id), "gestion_id": ep.gestion_id if ep else None,
            "factura_pms_id": pid("recibida", g.id), "factura_gestion_id": ef.gestion_id if ef else None,
            "fecha": _iso(g.fecha_pago), "importe": float(dinero(g.total) - dinero(g.retencion or 0)),
            "forma_pago": ei.FORMAS_RECIBIDAS.get(g.forma_pago or ""), "concepto": g.concepto,
            "referencia": g.numero_factura, "contraparte": g.proveedor}


def _pdf_emitida(db: Session, f: Invoice) -> FusionDocumento:
    """Copia del PDF de la factura emitida (cifrada): la misma que se descarga, con su sha256."""
    x = db.scalar(select(FusionDocumento).where(FusionDocumento.tipo == "emitida", FusionDocumento.pms_ref == f.id,
                                                FusionDocumento.origen == "PMS", FusionDocumento.fichero.is_not(None)))
    if x:
        return x
    from . import factura_pdf
    original = db.get(Invoice, f.rectifica_id) if f.rectifica_id else None
    pdf = factura_pdf.generar(f, db.get(Asset, f.asset_id), original)
    x = FusionDocumento(tipo="emitida", pms_ref=f.id, origen="PMS", categoria="FACTURA", fichero=documentos.guardar(pdf),
                        nombre=f"Factura_{ei.numero_factura(f)}.pdf", mime="application/pdf", tamano=len(pdf),
                        sha256=documentos.huella(pdf), estado="ok")
    db.add(x)
    db.flush()
    return x


def datos_emitida(db: Session, f: Invoice) -> dict:
    r = db.get(Reservation, f.reservation_id) if f.reservation_id else None
    c = db.get(Charge, f.charge_id) if f.charge_id else None
    lease = db.get(Lease, c.lease_id) if c and c.lease_id else None
    uid = r.unit_id if r else (lease.unit_id if lease else None)
    u = db.get(Unit, uid) if uid else None
    cliente = db.get(Contact, f.contact_id) if f.contact_id else None
    original = db.get(Invoice, f.rectifica_id) if f.rectifica_id else None
    e = enlace(db, "emitida", f.id)
    canal = "CONTRATO" if lease else (ei.CANALES.get((r.canal or "").lower(), (r.canal or "").upper()) if r else None)
    lineas = [{"base": g["base"], "tipo_iva": g["tipo_iva"], "cuota_iva": g["cuota"],
               "causa_exencion": (f.exencion or None) if g["tipo_iva"] == 0 else None} for g in desglose(lineas_de(f))]
    return {
        "pms_id": pid("emitida", f.id), "gestion_id": e.gestion_id if e else None, "nif_emisor": f.emisor.get("nif"),
        "serie": f.serie, "numero": ei.numero_factura(f),
        "tipo_factura": "RECTIFICATIVA" if f.tipo == "rectificativa" else "COMPLETA",
        "numero_rectificada": ei.numero_factura(original) if original else None,
        "fecha_expedicion": _iso(f.fecha_expedicion), "fecha_operacion": _iso(f.fecha_operacion),
        "fecha_vencimiento": _iso(c.fecha_vencimiento) if c else None,
        "cliente_nombre": f.cliente.get("nombre"), "cliente_nif": f.cliente.get("nif"),
        "cliente_pais": ei.pais_iso(cliente.pais if cliente else None, nif_=f.cliente.get("nif"))[0],
        "cliente_email": cliente.email if cliente else None, "unidad": u.codigo if u else None,
        "reserva_id": (r.localizador or f"R-{r.id}") if r else ((lease.referencia or f"CT-{lease.id}") if lease else None),
        "canal": canal, "fecha_entrada": _iso(r.fecha_entrada) if r else None,
        "fecha_salida": _iso(r.fecha_salida) if r else None, "concepto": f.concepto, "lineas": lineas,
        "base": _n(f.base_imponible), "cuota_iva": _n(f.cuota_iva), "retencion": None, "total": _n(f.total),
        "forma_pago": ei.FORMAS_EMITIDAS.get(f.cobro_forma or f.forma_pago or ""), "estado": "EMITIDA",
        "importe_cobrado": _n(f.total) if f.cobro == "cobrada" else 0.0}


def datos_cobro(db: Session, f: Invoice) -> dict:
    ec, ef = enlace(db, "cobro", f.id), enlace(db, "emitida", f.id)
    return {"pms_id": pid("cobro", f.id), "gestion_id": ec.gestion_id if ec else None,
            "factura_pms_id": pid("emitida", f.id), "factura_gestion_id": ef.gestion_id if ef else None,
            "fecha": _iso(f.cobro_fecha or f.fecha_operacion), "importe": _n(f.total),
            "forma_pago": ei.FORMAS_EMITIDAS.get(f.cobro_forma or f.forma_pago or ""), "concepto": f.concepto,
            "referencia": f.cobro_ref, "contraparte": f.cliente.get("nombre")}


def datos_proveedor(db: Session, s: Supplier) -> dict:
    return {"pms_id": pid("proveedor", s.id), "nif": s.nif, "nombre": s.nombre, "pais": ei.iso2(s.pais) or None,
            "iban": s.iban, "email": s.email, "telefono": s.telefono, "forma_pago": s.forma_pago}


def datos_producto(p: Product) -> dict:
    return {"pms_id": pid("producto", p.id), "referencia": p.referencia, "articulo": p.articulo, "familia": p.familia,
            "unidad": p.unidad}


def _sobre(asset: Asset | None, company: Company | None, datos: dict, docs: list[dict], causa=None) -> dict:
    return {"version": VERSION, "emitido": _utc(), "origen": "PMS", "id_evento_causa": causa,
            "activo": gestion._codigo_gestion(asset) if asset else None, "sociedad": sociedad(company),
            "datos": datos, "documentos": docs}


def materializar(db: Session, ev: GestionEvento) -> bool:
    """Toma los datos y documentos actuales del registro y los fija en el aviso (se mandan siempre los mismos en los
    reintentos). False si el registro ya no existe: el aviso se descarta."""
    f = (ev.datos or {}).get("_fusion")
    if not f:
        return True
    ent, ref, tipo = f["ent"], f["ref"], ev.tipo
    sobre = None
    if ent in ("recibida", "pago"):
        g = db.get(Expense, ref)
        if g is None:
            return False
        a = db.get(Asset, g.asset_id)
        c = db.get(Company, a.company_id)
        if tipo == "factura_recibida.anulacion_pedida":
            e = enlace(db, "recibida", g.id)
            sobre = _sobre(a, c, {"pms_id": pid("recibida", g.id), "gestion_id": e.gestion_id if e else None,
                                  "motivo": f.get("motivo")}, [])
        elif tipo == "pago.anulado":
            e = enlace(db, "pago", g.id)
            sobre = _sobre(a, c, {"pms_id": pid("pago", g.id), "gestion_id": e.gestion_id if e else None,
                                  "motivo": f.get("motivo") or "Pago desmarcado en el PMS"}, [])
        elif tipo == "pago.registrado":
            if not g.pagado:
                return False
            j = db.get(ReceivedDocument, g.justificante_id) if g.justificante_id else None
            docs = [_desc_rd(j, "JUSTIFICANTE")] if j and not _de_gestion(db, j.id) else []
            sobre = _sobre(a, c, datos_pago(db, g), docs)
        elif tipo == "documento.adjuntado":
            x = db.get(ReceivedDocument, f.get("rd")) if f.get("rd") else None
            if x is None:
                return False
            e = enlace(db, ent, g.id)
            sobre = _sobre(a, c, {"vinculo": {"tipo": VINCULO[ent], "pms_id": pid(ent, g.id),
                                              "gestion_id": e.gestion_id if e else None}},
                           [_desc_rd(x, f.get("cat") or "OTRO")])
        else:  # creada / actualizada (con los cambios pedidos, si es una corrección)
            d = datos_recibida(db, g)
            d.update({k: v for k, v in (f.get("cambios") or {}).items() if k in CORREGIBLES})
            sobre = _sobre(a, c, d, documentos_recibida(db, g))
    elif ent in ("emitida", "cobro"):
        x = db.get(Invoice, ref)
        if x is None:
            return False
        a, c = db.get(Asset, x.asset_id), db.get(Company, x.company_id)
        if tipo.startswith("factura_emitida."):
            sobre = _sobre(a, c, datos_emitida(db, x), [_desc_fd(_pdf_emitida(db, x))])
        elif tipo == "cobro.registrado":
            sobre = _sobre(a, c, datos_cobro(db, x), [])
        else:
            e = enlace(db, "cobro", x.id)
            sobre = _sobre(a, c, {"pms_id": pid("cobro", x.id), "gestion_id": e.gestion_id if e else None,
                                  "motivo": f.get("motivo") or "Cobro anulado en el PMS"}, [])
    elif ent == "proveedor":
        s = db.get(Supplier, ref)
        if s is None:
            return False
        sobre = _sobre(None, None, datos_proveedor(db, s), [])
    elif ent == "producto":
        p = db.get(Product, ref)
        if p is None:
            return False
        sobre = _sobre(None, None, datos_producto(p), [])
    elif ent == "linea":
        x = db.get(PurchaseOrderLine, ref)
        if x is None or x.precio is None:
            return False
        po, p = db.get(PurchaseOrder, x.pedido_id), x.producto
        s = db.get(Supplier, po.supplier_id) if po.supplier_id else None
        a = db.get(Asset, po.asset_id)
        sobre = _sobre(a, db.get(Company, a.company_id), {
            "referencia": p.referencia, "articulo": p.articulo, "familia": p.familia, "unidad": p.unidad,
            "precio": float(x.precio), "cantidad": float(x.cantidad), "tipo_iva": float(x.tipo_iva),
            "proveedor": (s.nombre if s else po.proveedor), "proveedor_nif": s.nif if s else None,
            "fecha_pedido": _iso(po.fecha), "num_pedido": po.numero, "marca": p.marca, "ref_proveedor": p.ref_proveedor}, [])
    if sobre is None:
        return False
    sobre["_ent"], sobre["_ref"] = ent, ref
    ev.datos = sobre
    return True


def cuerpo(ev: GestionEvento) -> bytes:
    d = {k: v for k, v in (ev.datos or {}).items() if not k.startswith("_")}
    return json.dumps({"id_evento": ev.id_evento, "tipo": ev.tipo, **d}, ensure_ascii=False, default=str).encode()


def entregado(db: Session, ev: GestionEvento, respuesta: str) -> None:
    """Gestión lo ha recibido: el registro queda «en gestión» (solo lectura en lo contable) y, si gestión devuelve
    su identificador, se guarda el enlace."""
    d = ev.datos or {}
    ent, ref = d.get("_ent"), d.get("_ref")
    if not ent or ref is None or ev.tipo in ("documento.adjuntado", "precio.pedido", "factura_recibida.anulacion_pedida"):
        return
    try:
        r = json.loads(respuesta or "{}")
    except ValueError:
        r = {}
    gid = (r.get("resultado") or {}).get("id") if isinstance(r.get("resultado"), dict) else None
    if ev.tipo == "pago.anulado" or ev.tipo == "cobro.anulado":
        return  # en gestión queda como solicitud para administración
    a = None
    if ent in ("recibida", "pago"):
        g = db.get(Expense, ref)
        a = g.asset_id if g else None
    elif ent in ("emitida", "cobro"):
        x = db.get(Invoice, ref)
        a = x.asset_id if x else None
    e = _enlazar(db, ent, ref, gid, a)
    if ev.tipo == "factura_recibida.actualizada" and e.solicitud == "correccion":
        e.solicitud_datos = {**(e.solicitud_datos or {}), "entregada": _utc()}


def resumen(e: GestionEvento) -> str:
    d = e.datos or {}
    x = d.get("datos") or {}
    if "_fusion" in d:
        f = d["_fusion"]
        return f"{f['ent']} {f['ref']} · se prepara al mandarlo"
    if e.tipo.startswith("factura_recibida"):
        return f"{d.get('activo')} · {x.get('proveedor_nombre') or ''} nº {x.get('numero') or ''} · {x.get('total')} €"
    if e.tipo.startswith("factura_emitida"):
        return f"{d.get('activo')} · {x.get('numero')} · {x.get('total')} €"
    if e.tipo.startswith(("pago.", "cobro.")):
        return f"{d.get('activo')} · {x.get('pms_id')} · {x.get('importe') or x.get('motivo') or ''}"
    if e.tipo.startswith("proveedor."):
        return f"{x.get('nombre')} · {x.get('nif') or 'sin NIF'}"
    if e.tipo.startswith(("producto.", "precio.")):
        return f"{x.get('referencia')} · {x.get('articulo')}"
    if e.tipo == "documento.adjuntado":
        v = x.get("vinculo") or {}
        return f"{v.get('tipo')} {v.get('pms_id')} · {len(d.get('documentos') or [])} documento(s)"
    return ""


# --------------------------------------------------------------------------- rutas firmadas para gestión (red interna)
router = APIRouter(prefix="/api/gestion", tags=["gestion"])
publico = APIRouter(tags=["gestion"])


def _red_interna(request: Request) -> None:
    """Solo responde a peticiones de la red interna (gestión llama a pms-app-1:8000): por internet llegan a través
    de Caddy, que añade X-Forwarded-For."""
    if request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip"):
        raise HTTPException(403, "Solo desde la red interna")


def _doc_sincronizado(db: Session, x: ReceivedDocument) -> bool:
    """Solo documentos de registros sincronizados (de un activo con la casilla, o ya enlazados con gestión)."""
    if db.scalar(select(FusionDocumento.id).where(FusionDocumento.documento_id == x.id, FusionDocumento.origen == "PMS")):
        return True
    for g in db.scalars(select(Expense).where((Expense.documento_id == x.id) | (Expense.justificante_id == x.id))):
        if (db.get(Asset, g.asset_id).sync_facturas or enlace(db, "recibida", g.id) is not None):
            return True
    return False


@router.get("/documento/{doc_id}")
def documento_para_gestion(doc_id: str, request: Request, db: Session = Depends(get_db)):
    """Gestión descarga un documento del PMS (descifrado aquí; la clave no sale). Firma: HMAC(fecha + "." + doc_id)."""
    _red_interna(request)
    gestion.comprobar(gestion.EVENTOS_SECRET, request.headers.get("x-pms-fecha"), request.headers.get("x-pms-firma"),
                      doc_id.encode())
    m = re.fullmatch(r"(rd|fd)-(\d+)", doc_id)
    if not m:
        raise HTTPException(404, "Documento no encontrado")
    if m.group(1) == "rd":
        x = db.get(ReceivedDocument, int(m.group(2)))
        if x is None or not _doc_sincronizado(db, x):
            raise HTTPException(404, "Documento no encontrado")
        datos, mime, nombre = documentos.leer(x.fichero), x.mime, x.nombre
    else:
        x = db.get(FusionDocumento, int(m.group(2)))
        if x is None or not x.fichero or x.origen != "PMS":
            raise HTTPException(404, "Documento no encontrado")
        datos, mime, nombre = documentos.leer(x.fichero), x.mime or "application/pdf", x.nombre or doc_id
    db.add(AuditLog(user_id=None, accion="documento_a_gestion", entidad="documento", entidad_id=x.id,
                    detalle={"doc_id": doc_id}))
    db.commit()
    return Response(datos, media_type=mime, headers={
        "X-Sha256": documentos.huella(datos), "Cache-Control": "no-store",
        "Content-Disposition": f'attachment; filename="{urllib.parse.quote(nombre)}"'})


@router.get("/fusion/inventario")
def inventario(request: Request, activo: str, desde: date, db: Session = Depends(get_db)):
    """Carga inicial («Emparejar facturas» de gestión): lo del activo desde la fecha, en el formato de los avisos y
    sin documentos. Firmado sobre la consulta: HMAC(fecha + "." + "activo=…&desde=…")."""
    _red_interna(request)
    gestion.comprobar(gestion.EVENTOS_SECRET, request.headers.get("x-pms-fecha"), request.headers.get("x-pms-firma"),
                      request.url.query.encode())
    a = _activo_pms(db, activo)
    if a is None:
        raise HTTPException(404, "Activo no encontrado en el PMS")
    gastos = list(db.scalars(select(Expense).where(Expense.asset_id == a.id, Expense.fecha >= desde)
                             .order_by(Expense.fecha, Expense.id)))
    facturas = list(db.scalars(select(Invoice).where(Invoice.asset_id == a.id, Invoice.fecha_expedicion >= desde)
                               .order_by(Invoice.fecha_expedicion, Invoice.id)))
    pagos = [{**datos_pago(db, g), "tipo": "PAGO"} for g in db.scalars(select(Expense).where(
        Expense.asset_id == a.id, Expense.pagado.is_(True), Expense.fecha_pago >= desde).order_by(Expense.fecha_pago))]
    pagos += [{**datos_cobro(db, f), "tipo": "COBRO"} for f in facturas if f.cobro == "cobrada"]
    prov_ids = {g.supplier_id for g in gastos if g.supplier_id}
    proveedores = [datos_proveedor(db, s) for s in db.scalars(select(Supplier).where(Supplier.id.in_(prov_ids or {-1}))
                                                              .order_by(Supplier.nombre))]
    productos = [datos_producto(p) for p in db.scalars(select(Product).where(Product.activo.is_(True))
                                                       .order_by(Product.referencia))]
    db.add(AuditLog(user_id=None, accion="inventario_gestion", entidad="activo", entidad_id=a.id,
                    detalle={"desde": desde.isoformat(), "recibidas": len(gastos), "emitidas": len(facturas)}))
    db.commit()
    return {"recibidas": [datos_recibida(db, g) for g in gastos], "emitidas": [datos_emitida(db, f) for f in facturas],
            "pagos": pagos, "proveedores": proveedores, "productos": productos}


# --------------------------------------------------------------------------- avisos de gestión → PMS
def descargar(doc_id: str) -> tuple[bytes, str | None]:
    """Documento de gestión por la red interna, con petición firmada. (bytes, cabecera X-Sha256)."""
    from . import adjuntos
    ts = str(int(time.time()))
    req = urllib.request.Request(
        f"{gestion.GESTION_URL}/api/pms/documento/{urllib.parse.quote(doc_id, safe='')}",
        headers={"X-INVG": "1", "X-PMS-Fecha": ts, "X-PMS-Firma": gestion.firmar(gestion.EVENTOS_SECRET, ts, doc_id.encode())})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(adjuntos.TAM_MAX + 1), r.headers.get("X-Sha256")


def _mime(datos: bytes) -> str | None:
    if datos.startswith(b"%PDF"):
        return "application/pdf"
    if datos.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if datos.startswith(b"\x89PNG"):
        return "image/png"
    return None


def _traer_documentos(db: Session, ent: str, ref: int, asset_id: int, unit_id: int | None, docs: list,
                      emisor: str | None = None, referencia: str | None = None) -> list[tuple[str, ReceivedDocument]]:
    """Descarga los documentos del aviso. Con la sha256 que no cuadra no se adjunta: queda «A revisar»."""
    from . import adjuntos
    out = []
    for d in docs or []:
        if not isinstance(d, dict) or not d.get("doc_id"):
            continue
        did, cat = str(d["doc_id"])[:120], (d.get("categoria") or "OTRO").upper()
        cat = cat if cat in CATEGORIAS_DOC else "OTRO"
        previo = db.scalar(select(FusionDocumento).where(FusionDocumento.doc_id_gestion == did,
                                                         FusionDocumento.origen == "GESTION"))
        if previo is not None and previo.estado == "ok":
            x = db.get(ReceivedDocument, previo.documento_id) if previo.documento_id else None
            if x:
                out.append((previo.categoria, x))
            continue
        try:
            datos, cabecera = descargar(did)
        except Exception as e:  # noqa: BLE001 — sin el documento no se aplica: gestión lo reintenta
            raise NoAplicable(f"No se pudo descargar el documento {did} de gestión: {str(e)[:120]}")
        huella = documentos.huella(datos)
        nombre = (d.get("nombre") or did)[-150:]
        mal = None
        if len(datos) > adjuntos.TAM_MAX:
            mal = "Supera los 20 MB"
        elif huella != (d.get("sha256") or "").lower() or (cabecera and cabecera.lower() != huella):
            mal = "La sha256 no cuadra con la del aviso"
        elif _mime(datos) is None:
            mal = "Formato no admitido (solo PDF, JPG o PNG)"
        if mal:
            if previo is None:
                previo = FusionDocumento(tipo=ent, pms_ref=ref, origen="GESTION", categoria=cat, doc_id_gestion=did)
                db.add(previo)
            previo.nombre, previo.sha256, previo.tamano = nombre, d.get("sha256"), len(datos)
            previo.estado, previo.motivo = "a_revisar", mal
            continue
        x = ReceivedDocument(asset_id=asset_id, unit_id=unit_id, tipo=CATEGORIAS_DOC[cat], fecha=date.today(),
                             emisor=(emisor or None) and emisor[:200], referencia=(referencia or None) and referencia[:60],
                             descripcion="Recibido de gestión (INVERGESTION)", nombre=nombre,
                             fichero=documentos.guardar(datos), mime=_mime(datos), tamano=len(datos), sha256=huella)
        db.add(x)
        db.flush()
        if previo is None:
            previo = FusionDocumento(tipo=ent, pms_ref=ref, origen="GESTION", categoria=cat, doc_id_gestion=did)
            db.add(previo)
        previo.documento_id, previo.nombre, previo.mime, previo.tamano = x.id, nombre, x.mime, len(datos)
        previo.sha256, previo.estado, previo.motivo = huella, "ok", None
        out.append((cat, x))
    return out


def _proveedor_de(db: Session, nombre: str | None, nif_: str | None, pais: str | None = None) -> Supplier | None:
    n = nif.normalizar(nif_)
    s = db.scalar(select(Supplier).where(Supplier.nif == n)) if n else None
    if s is None and nombre:
        clave = nif.nombre_clave(nombre)
        s = next((x for x in db.scalars(select(Supplier)) if nif.nombre_clave(x.nombre) == clave
                  and not (n and x.nif and x.nif != n)), None)
    if s is None and (n or nombre):
        t = nif.tipo(n) if n else None
        s = Supplier(nombre=" ".join((nombre or n).split())[:200], nif=n,
                     tipo_persona="empresa" if t in (None, "CIF") else "autonomo", pais=pais)
        db.add(s)
        db.flush()
    return s


FORMAS_PMS = {"TRANSFERENCIA": "transferencia", "DOMICILIACION": "domiciliacion", "EFECTIVO": "efectivo",
              "TARJETA": "tarjeta", "COMPENSACION_OTA": "plataforma", "OTA": "plataforma"}
CATEGORIAS_PMS = {v: k for k, v in ei.CATEGORIAS.items() if k not in ("telecom",)}


def _gasto(db: Session, d: dict, asset: Asset | None) -> Expense | None:
    """Identidad de la factura recibida: pms_id ↔ id de gestión; si no, NIF del proveedor + número + fecha."""
    g = db.get(Expense, ref_de(d.get("pms_id"), "recibida")) if ref_de(d.get("pms_id"), "recibida") else None
    if g is None and d.get("gestion_id"):
        e = db.scalar(select(FusionEnlace).where(FusionEnlace.tipo == "recibida",
                                                 FusionEnlace.gestion_id == str(d["gestion_id"])))
        g = db.get(Expense, e.pms_ref) if e else None
    if g is None and asset is not None and d.get("numero") and d.get("fecha_factura"):
        n = nif.normalizar(d.get("proveedor_nif"))
        s = db.scalar(select(Supplier).where(Supplier.nif == n)) if n else None
        num = re.sub(r"[^A-Z0-9]", "", str(d["numero"]).upper())
        for x in db.scalars(select(Expense).where(Expense.asset_id == asset.id,
                                                  Expense.fecha == date.fromisoformat(d["fecha_factura"]))):
            if re.sub(r"[^A-Z0-9]", "", (x.numero_factura or "").upper()) == num and \
                    (s is None or x.supplier_id in (None, s.id)):
                g = x
                break
    return g


def _dec(x) -> Decimal | None:
    return None if x is None or x == "" else dinero(Decimal(str(x)))


def _aplicar_recibida(db: Session, ev: dict, asset: Asset) -> dict:
    d = ev.get("datos") or {}
    g = _gasto(db, d, asset)
    nuevo = g is None
    if d.get("estado") == "ANULADA":
        return _anular_recibida(db, g, d) if g else {}
    s = _proveedor_de(db, d.get("proveedor_nombre"), d.get("proveedor_nif"), d.get("proveedor_pais"))
    if s is not None and d.get("proveedor_iban"):
        s.iban = str(d["proveedor_iban"]).replace(" ", "")[:34]
    base, cuota = _dec(d.get("base")), _dec(d.get("cuota_iva"))
    retencion = _dec(d.get("retencion")) or Decimal(0)
    liquido = _dec(d.get("total"))
    if base is None and liquido is not None:
        base = liquido + retencion - (cuota or Decimal(0))
    if cuota is None and base is not None and liquido is not None:
        cuota = liquido + retencion - base
    if base is None or cuota is None:
        raise NoAplicable("Faltan la base o el total de la factura")
    lineas = d.get("lineas") or []
    tipos = {float(x.get("tipo_iva") or 0) for x in lineas if isinstance(x, dict)}
    tipo_iva = tipos.pop() if len(tipos) == 1 else (round(float(cuota / base * 100)) if base else 0)
    u = db.scalar(select(Unit).where(Unit.asset_id == asset.id, Unit.codigo == d["unidad"])) if d.get("unidad") else None
    if nuevo:  # se añade a la sesión cuando tiene todos sus datos
        g = Expense(asset_id=asset.id, ambito="general", categoria="otros", concepto="", fecha=date.today(),
                    pagado=False, retencion=0, retencion_pct=0)
    if u is not None:
        g.ambito, g.unit_id, g.ambito_detalle = "apartamento", u.id, None
    if d.get("fecha_factura"):
        g.fecha = date.fromisoformat(d["fecha_factura"])
    g.vencimiento = date.fromisoformat(d["fecha_vencimiento"]) if d.get("fecha_vencimiento") else None
    g.concepto = (d.get("concepto") or g.concepto or "Factura de gestión")[:300]
    if d.get("categoria"):
        g.categoria = CATEGORIAS_PMS.get(str(d["categoria"]).upper(), g.categoria if not nuevo else "otros")
    g.proveedor = (d.get("proveedor_nombre") or (s.nombre if s else None) or g.proveedor)
    g.supplier_id = s.id if s else g.supplier_id
    g.numero_factura = (str(d["numero"])[:60] if d.get("numero") else g.numero_factura)
    g.base, g.cuota, g.total, g.tipo_iva = base, cuota, base + cuota, tipo_iva
    g.retencion = retencion
    g.retencion_pct = dinero(retencion / base * 100) if retencion and base else Decimal(0)
    g.retencion_tipo = (g.retencion_tipo or "otra") if retencion else None
    if d.get("forma_pago"):
        g.forma_pago = FORMAS_PMS.get(str(d["forma_pago"]).upper(), str(d["forma_pago"]).lower()[:30])
    if d.get("clase"):
        g.naturaleza = str(d["clase"]).upper()[:10]
    if d.get("estado_pago"):
        pagada = d["estado_pago"] == "PAGADA"
        g.pagado = pagada
        g.fecha_pago = (date.fromisoformat(d["fecha_pago"]) if d.get("fecha_pago") else (g.fecha_pago or date.today())) \
            if pagada else None
        if pagada:
            g.pago_retenido = False
    if nuevo:
        db.add(g)
    db.flush()
    for cat, x in _traer_documentos(db, "recibida", g.id, asset.id, g.unit_id, ev.get("documentos"), g.proveedor,
                                    g.numero_factura):
        if cat == "JUSTIFICANTE" and not g.justificante_id:
            g.justificante_id = x.id
        elif cat == "FACTURA" and not g.documento_id:
            g.documento_id = x.id
    e = _enlazar(db, "recibida", g.id, d.get("gestion_id"), asset.id, origen="GESTION" if nuevo else "PMS")
    if d.get("respuesta") in ("aceptada", "rechazada") or (ev.get("id_evento_causa") and e.solicitud == "correccion"):
        e.solicitud_datos = {**(e.solicitud_datos or {}), "respuesta": d.get("respuesta"), "contestada": _utc()}
        e.solicitud = None
    return {"pms_id": pid("recibida", g.id)}


def _anular_recibida(db: Session, g: Expense | None, d: dict) -> dict:
    """Gestión la ha mandado a la papelera: sale de la cuenta de gastos (sus documentos siguen en la carpeta)."""
    if g is None:
        return {}
    e = _enlazar(db, "recibida", g.id, d.get("gestion_id"), g.asset_id, estado="anulada")
    e.estado, e.solicitud = "anulada", None
    db.add(AuditLog(user_id=None, accion="anular_desde_gestion", entidad="gasto", entidad_id=g.id,
                    detalle={"proveedor": g.proveedor, "numero": g.numero_factura, "total": float(g.total),
                             "fecha": _iso(g.fecha), "documento": g.documento_id, "justificante": g.justificante_id}))
    db.delete(g)
    return {"pms_id": pid("recibida", g.id)}


def _factura_de_pago(db: Session, d: dict, emitida: bool):
    ent = "emitida" if emitida else "recibida"
    ref = ref_de(d.get("factura_pms_id"), ent)
    modelo = Invoice if emitida else Expense
    x = db.get(modelo, ref) if ref else None
    if x is None and d.get("factura_gestion_id"):
        e = db.scalar(select(FusionEnlace).where(FusionEnlace.tipo == ent,
                                                 FusionEnlace.gestion_id == str(d["factura_gestion_id"])))
        x = db.get(modelo, e.pms_ref) if e else None
    if x is None and emitida:
        r = ref_de(d.get("factura_pms_id"), "externa")
        if r is None and d.get("factura_gestion_id"):
            e = db.scalar(select(FusionEnlace).where(FusionEnlace.tipo == "externa",
                                                     FusionEnlace.gestion_id == str(d["factura_gestion_id"])))
            r = e.pms_ref if e else None
        x = db.get(ExternalInvoice, r) if r else None
    return x


def _aplicar_pago(db: Session, ev: dict, asset: Asset | None, registrado: bool) -> dict:
    d = ev.get("datos") or {}
    g = db.get(Expense, ref_de(d.get("pms_id"), "pago")) if ref_de(d.get("pms_id"), "pago") else None
    if g is None and d.get("gestion_id"):
        e = db.scalar(select(FusionEnlace).where(FusionEnlace.tipo == "pago", FusionEnlace.gestion_id == str(d["gestion_id"])))
        g = db.get(Expense, e.pms_ref) if e else None
    if g is None:
        g = _factura_de_pago(db, d, emitida=False)
    if g is None:
        if not registrado:
            return {}
        raise NoAplicable("La factura de este pago todavía no está en el PMS")
    if registrado:
        g.pagado, g.pago_retenido = True, False
        g.fecha_pago = date.fromisoformat(d["fecha"]) if d.get("fecha") else (g.fecha_pago or date.today())
        if d.get("forma_pago"):
            g.forma_pago = FORMAS_PMS.get(str(d["forma_pago"]).upper(), g.forma_pago)
        for cat, x in _traer_documentos(db, "pago", g.id, g.asset_id, g.unit_id, ev.get("documentos"), g.proveedor,
                                        g.numero_factura):
            if cat == "JUSTIFICANTE" or not g.justificante_id:
                g.justificante_id = x.id
        _enlazar(db, "pago", g.id, d.get("gestion_id"), g.asset_id, origen="GESTION")
    else:
        g.pagado, g.fecha_pago, g.justificante_id = False, None, None
        e = enlace(db, "pago", g.id)
        if e:
            e.estado = "anulada"
    return {"pms_id": pid("pago", g.id)}


def _aplicar_cobro(db: Session, ev: dict, asset: Asset | None, registrado: bool) -> dict:
    d = ev.get("datos") or {}
    f = db.get(Invoice, ref_de(d.get("pms_id"), "cobro")) if ref_de(d.get("pms_id"), "cobro") else None
    if f is None and d.get("gestion_id"):
        e = db.scalar(select(FusionEnlace).where(FusionEnlace.tipo == "cobro", FusionEnlace.gestion_id == str(d["gestion_id"])))
        f = db.get(Invoice, e.pms_ref) if e else None
    if f is None:
        f = _factura_de_pago(db, d, emitida=True)
    if f is None:
        if not registrado:
            return {}
        raise NoAplicable("La factura de este cobro todavía no está en el PMS")
    if isinstance(f, ExternalInvoice):
        f.detalle = {**(f.detalle or {}), "cobro": {"fecha": d.get("fecha"), "importe": d.get("importe"),
                                                    "forma_pago": d.get("forma_pago")} if registrado else None}
        return {"pms_id": pid("externa", f.id)}
    if registrado:
        f.cobro = "cobrada"
        f.cobro_fecha = date.fromisoformat(d["fecha"]) if d.get("fecha") else (f.cobro_fecha or date.today())
        if d.get("forma_pago"):
            f.cobro_forma = FORMAS_PMS.get(str(d["forma_pago"]).upper(), f.cobro_forma)
        f.cobro_ref = (d.get("referencia") or f.cobro_ref or None) and str(d.get("referencia") or f.cobro_ref)[:80]
        f.cobro_marcado = datetime.now()
        _traer_documentos(db, "cobro", f.id, f.asset_id, None, ev.get("documentos"), f.cliente.get("nombre"), f.codigo)
        _enlazar(db, "cobro", f.id, d.get("gestion_id"), f.asset_id, origen="GESTION")
    else:
        if f.cobro == "cobrada":
            f.cobro, f.cobro_fecha, f.cobro_marcado = "pendiente", None, None
        e = enlace(db, "cobro", f.id)
        if e:
            e.estado = "anulada"
    return {"pms_id": pid("cobro", f.id)}


def _aplicar_emitida(db: Session, ev: dict, asset: Asset) -> dict:
    """Las del PMS solo se enlazan (no se modifican: una factura emitida no cambia, se rectifica). Las de gestión
    de un activo del PMS se guardan como facturación externa («INVERGESTION»), fuera de la numeración del PMS."""
    d = ev.get("datos") or {}
    f = db.get(Invoice, ref_de(d.get("pms_id"), "emitida")) if ref_de(d.get("pms_id"), "emitida") else None
    if f is not None:
        _enlazar(db, "emitida", f.id, d.get("gestion_id"), f.asset_id)
        return {"pms_id": pid("emitida", f.id)}
    serie = str(d.get("serie") or "INVG")[:12]
    numero = str(d.get("numero") or d.get("gestion_id") or "")[:30]
    if not numero or not d.get("fecha_expedicion"):
        raise NoAplicable("Faltan el número o la fecha de la factura emitida")
    x = db.scalar(select(ExternalInvoice).where(ExternalInvoice.asset_id == asset.id, ExternalInvoice.tipo == "servicio",
                                                ExternalInvoice.serie == serie, ExternalInvoice.numero == numero))
    if x is None:
        x = ExternalInvoice(asset_id=asset.id, origen="INVERGESTION", tipo="servicio", serie=serie, numero=numero,
                            fecha=date.fromisoformat(d["fecha_expedicion"]))
        db.add(x)
    tipos = {float(t.get("tipo_iva") or 0) for t in d.get("lineas") or [] if isinstance(t, dict)}
    x.fecha = date.fromisoformat(d["fecha_expedicion"])
    x.nif, x.cliente = d.get("cliente_nif"), (d.get("cliente_nombre") or None) and str(d["cliente_nombre"])[:200]
    x.localizador = (d.get("reserva_id") or None) and str(d["reserva_id"])[:60]
    x.base, x.cuota, x.total = _dec(d.get("base")) or 0, _dec(d.get("cuota_iva")) or 0, _dec(d.get("total")) or 0
    x.tipo_iva = tipos.pop() if len(tipos) == 1 else None
    x.detalle = {**(x.detalle or {}), "gestion_id": d.get("gestion_id"), "concepto": d.get("concepto"),
                 "tipo_factura": d.get("tipo_factura"), "estado": d.get("estado")}
    db.flush()
    _traer_documentos(db, "externa", x.id, asset.id, None, ev.get("documentos"), d.get("cliente_nombre"), numero)
    _enlazar(db, "externa", x.id, d.get("gestion_id"), asset.id, origen="GESTION")
    return {"pms_id": pid("externa", x.id)}


def _aplicar_proveedor(db: Session, ev: dict, _asset) -> dict:
    d = ev.get("datos") or {}
    s = db.get(Supplier, ref_de(d.get("pms_id"), "proveedor")) if ref_de(d.get("pms_id"), "proveedor") else None
    n = nif.normalizar(d.get("nif"))
    if s is None and n:
        s = db.scalar(select(Supplier).where(Supplier.nif == n))
    if s is None:
        s = _proveedor_de(db, d.get("nombre"), n, d.get("pais"))
    if s is None:
        raise NoAplicable("Proveedor sin NIF ni nombre")
    if d.get("nombre"):
        s.nombre = " ".join(str(d["nombre"]).split())[:200]
    if n and n != s.nif and not db.scalar(select(Supplier.id).where(Supplier.nif == n, Supplier.id != s.id)):
        s.nif = n
    for campo, largo in (("pais", 60), ("email", 160), ("telefono", 40), ("forma_pago", 30)):
        if d.get(campo):
            setattr(s, campo, str(d[campo])[:largo])
    if d.get("iban"):
        s.iban = str(d["iban"]).replace(" ", "")[:34]
    db.flush()
    _enlazar(db, "proveedor", s.id, d.get("gestion_id"), None, origen="GESTION")
    return {"pms_id": pid("proveedor", s.id)}


def _aplicar_producto(db: Session, ev: dict, _asset) -> dict:
    from .pedidos import familia
    d = ev.get("datos") or {}
    p = db.get(Product, ref_de(d.get("pms_id"), "producto")) if ref_de(d.get("pms_id"), "producto") else None
    if p is None and d.get("referencia"):
        p = db.scalar(select(Product).where(Product.referencia == str(d["referencia"])[:60]))
    if p is None:
        if not d.get("referencia") or not d.get("articulo"):
            raise NoAplicable("Producto sin referencia o sin artículo")
        p = Product(referencia=str(d["referencia"])[:60], articulo=str(d["articulo"])[:250], origen="INVERGESTION")
        db.add(p)
    if d.get("articulo"):
        p.articulo = str(d["articulo"])[:250]
    if d.get("familia"):
        p.familia = familia(d["familia"])
    if d.get("unidad"):
        p.unidad = str(d["unidad"])[:20]
    p.actualizado = datetime.now()
    db.flush()
    _enlazar(db, "producto", p.id, d.get("gestion_id"), None, origen="GESTION")
    return {"pms_id": pid("producto", p.id)}


def _aplicar_documento(db: Session, ev: dict, _asset) -> dict:
    v = (ev.get("datos") or {}).get("vinculo") or {}
    ent = {"factura_recibida": "recibida", "factura_emitida": "emitida", "pago": "pago", "cobro": "cobro"}.get(v.get("tipo"))
    if not ent:
        raise NoAplicable("Vínculo del documento no válido")
    ref = ref_de(v.get("pms_id"), ent)
    if ref is None and v.get("gestion_id"):
        e = db.scalar(select(FusionEnlace).where(FusionEnlace.tipo == ent, FusionEnlace.gestion_id == str(v["gestion_id"])))
        ref = e.pms_ref if e else None
    if ent in ("recibida", "pago"):
        g = db.get(Expense, ref) if ref else None
        if g is None:
            raise NoAplicable("El registro del documento todavía no está en el PMS")
        for cat, x in _traer_documentos(db, ent, g.id, g.asset_id, g.unit_id, ev.get("documentos"), g.proveedor,
                                        g.numero_factura):
            if cat == "JUSTIFICANTE" and not g.justificante_id:
                g.justificante_id = x.id
            elif cat == "FACTURA" and not g.documento_id:
                g.documento_id = x.id
        return {"pms_id": pid(ent, g.id)}
    f = db.get(Invoice, ref) if ref else None
    if f is None:
        raise NoAplicable("El registro del documento todavía no está en el PMS")
    _traer_documentos(db, ent, f.id, f.asset_id, None, ev.get("documentos"), f.cliente.get("nombre"), f.codigo)
    return {"pms_id": pid(ent, f.id)}


def _aplicar_anulacion_pedida(db: Session, ev: dict, asset) -> dict:
    """Gestión pide anular una recibida del PMS: queda anotada para que la Dirección la vea (no se borra)."""
    d = ev.get("datos") or {}
    g = _gasto(db, d, asset)
    if g is None:
        return {}
    e = _enlazar(db, "recibida", g.id, d.get("gestion_id"), g.asset_id)
    e.solicitud, e.solicitud_fecha = "anulacion_gestion", datetime.now()
    e.solicitud_datos = {"motivo": d.get("motivo"), "desde": "GESTION"}
    return {"pms_id": pid("recibida", g.id)}


def _con_activo(fn):
    def f(db, ev, asset):
        if asset is None:
            return None  # activo que no está en el PMS: nada que hacer (se guarda «sin_tratar»)
        return fn(db, ev, asset)
    return f


APLICAR = {
    "factura_recibida.creada": _con_activo(_aplicar_recibida),
    "factura_recibida.actualizada": _con_activo(_aplicar_recibida),
    "factura_recibida.anulada": lambda db, ev, a: _anular_recibida(db, _gasto(db, ev.get("datos") or {}, a),
                                                                    ev.get("datos") or {}),
    "factura_recibida.anulacion_pedida": _aplicar_anulacion_pedida,
    "factura_emitida.emitida": _con_activo(_aplicar_emitida),
    "documento.adjuntado": _aplicar_documento,
    "pago.registrado": lambda db, ev, a: _aplicar_pago(db, ev, a, True),
    "pago.anulado": lambda db, ev, a: _aplicar_pago(db, ev, a, False),
    "cobro.registrado": lambda db, ev, a: _aplicar_cobro(db, ev, a, True),
    "cobro.anulado": lambda db, ev, a: _aplicar_cobro(db, ev, a, False),
    "proveedor.alta": _aplicar_proveedor,
    "proveedor.actualizado": _aplicar_proveedor,
    "producto.alta": _aplicar_producto,
    "producto.actualizado": _aplicar_producto,
}
POR_ACTIVO = {"factura_recibida.creada", "factura_recibida.actualizada", "factura_recibida.anulada",
              "factura_recibida.anulacion_pedida", "factura_emitida.emitida"}


@router.post("/eventos")
async def eventos_de_gestion(request: Request, db: Session = Depends(get_db)):
    """Avisos «fusion1» de gestión. Se aplican siempre (gestión manda). 200 {"ok": true} también si el id_evento ya
    se recibió; 200 «sin_tratar» si el tipo no se conoce; 400 si todavía no se puede aplicar (gestión reintenta)."""
    raw = await request.body()
    gestion.comprobar(gestion.EVENTOS_SECRET, request.headers.get("x-pms-fecha"), request.headers.get("x-pms-firma"), raw)
    try:
        ev = json.loads(raw or b"{}")
    except ValueError:
        bad_request("Formato no válido")
    if not isinstance(ev, dict) or not ID_EVENTO.match(str(ev.get("id_evento") or "")) or not ev.get("tipo"):
        bad_request("Aviso sin id_evento o sin tipo")
    ide, tipo = str(ev["id_evento"]), str(ev["tipo"])[:60]
    previo = db.scalar(select(FusionEntrada).where(FusionEntrada.id_evento == ide))
    if previo is not None:
        return {"ok": True, **(previo.resultado or {})}
    entrada = FusionEntrada(id_evento=ide, tipo=tipo, origen=(str(ev.get("origen") or "")[:20] or None),
                            id_evento_causa=(str(ev.get("id_evento_causa") or "")[:160] or None), cuerpo=ev)
    asset = _activo_pms(db, ev.get("activo"))
    fn = APLICAR.get(tipo)
    if ev.get("origen") == "PMS":
        entrada.estado = "eco"  # vuelta de un aviso nuestro: no se aplica otra vez
    elif tipo in maestros.TIPOS_ENTRADA:  # activos y unidades: su propia casilla (no PMS_GESTION_SYNC_FACTURAS)
        db.info[DESDE_GESTION] = True
        try:
            entrada.estado, entrada.resultado = maestros.recibir(db, ev)
            db.flush()
        finally:
            db.info.pop(DESDE_GESTION, None)
    elif tipo in calendario_comun.TIPOS_EVENTO:  # calendario común: su propia casilla (no PMS_GESTION_SYNC_FACTURAS)
        db.info[DESDE_GESTION] = True
        try:
            entrada.estado, entrada.resultado = calendario_comun.recibir(db, ev)
            db.flush()
        finally:
            db.info.pop(DESDE_GESTION, None)
    elif not SYNC or fn is None or (tipo in POR_ACTIVO and (asset is None or not asset.sync_facturas)):
        entrada.estado = "sin_tratar"
    else:
        db.info[DESDE_GESTION] = True
        try:
            res = fn(db, ev, asset)
            db.flush()
        except NoAplicable as e:
            db.rollback()
            return JSONResponse({"ok": False, "detail": str(e)}, status_code=400)
        finally:
            db.info.pop(DESDE_GESTION, None)
        entrada.estado = "aplicado" if res is not None else "sin_tratar"
        entrada.resultado = res or None
    db.info[DESDE_GESTION] = True
    try:
        db.add(entrada)
        db.add(AuditLog(user_id=None, accion="aviso_de_gestion", entidad="fusion", entidad_id=None,
                        detalle={"id_evento": ide, "tipo": tipo, "estado": entrada.estado, **(entrada.resultado or {})}))
        db.commit()
    finally:
        db.info.pop(DESDE_GESTION, None)
    return {"ok": True, **(entrada.resultado or {})}


# --------------------------------------------------------------------------- botón «PMS» de gestión (SSO inverso)
def _pagina(titulo: str, texto: str, status: int) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>{titulo}</title><body style='font-family:sans-serif;"
                        f"max-width:480px;margin:60px auto'><h2>{titulo}</h2><p>{texto}</p><p><a href='/'>Entrar en el "
                        "PMS</a></p></body>", status_code=status, headers={"Cache-Control": "no-store"})


@publico.get("/sso/gestion", include_in_schema=False)
def sso_desde_gestion(pase: str = "", firma: str = "", db: Session = Depends(get_db)):
    """Pase firmado por gestión (PMS_GESTION_SSO_SECRET): 60 s y un solo uso. Se busca el usuario por email; los
    permisos son los suyos en el PMS. Entra con su sesión normal y va a la pantalla pedida."""
    if not gestion.SSO_SECRET:
        return _pagina("Acceso directo no disponible", "El acceso desde gestión no está configurado.", 503)
    esperado = hmac.new(gestion.SSO_SECRET.encode(), pase.encode(), hashlib.sha256).hexdigest()
    if not pase or not firma or not hmac.compare_digest(esperado, firma.lower()):
        return _pagina("Enlace no válido", "El enlace de acceso no es válido. Entre con su usuario y contraseña.", 403)
    try:
        d = json.loads(base64.urlsafe_b64decode(pase + "=" * (-len(pase) % 4)))
        emitido = datetime.fromisoformat(str(d["emitido"]).replace("Z", "+00:00"))
        if emitido.tzinfo is None:
            emitido = emitido.replace(tzinfo=timezone.utc)
        nonce = str(d["nonce"])
    except (ValueError, KeyError, TypeError):
        return _pagina("Enlace no válido", "El enlace de acceso no es válido.", 403)
    edad = (datetime.now(timezone.utc) - emitido).total_seconds()
    if not -SSO_VALIDEZ <= edad <= SSO_VALIDEZ or not 16 <= len(nonce) <= 128:
        return _pagina("Enlace caducado", "El enlace de acceso ha caducado (vale 60 segundos). Vuelva a pulsar «PMS» "
                                          "en gestión.", 403)
    clave = "sso:" + hashlib.sha256(nonce.encode()).hexdigest()
    if db.scalar(select(FusionEntrada.id).where(FusionEntrada.id_evento == clave)):
        return _pagina("Enlace ya usado", "Este enlace ya se ha usado. Vuelva a pulsar «PMS» en gestión.", 403)
    email = str(d.get("email") or "").strip().lower()
    u = db.scalar(select(User).where(func.lower(User.email) == email)) if email else None
    if u is None or not u.activo:
        return _pagina("Sin acceso", "Su usuario de gestión no tiene cuenta activa en el PMS.", 403)
    destino = d.get("destino") if d.get("destino") in DESTINOS else "inicio"
    db.add(FusionEntrada(id_evento=clave, tipo="sso.gestion", estado="sso",
                         cuerpo={"email": email, "destino": destino, "id": d.get("id")}))
    audit(db, u, "entrar_desde_gestion", "usuario", u.id, {"destino": destino})
    db.commit()
    frag = urllib.parse.urlencode({"sso": create_token(u), "destino": destino, "id": d.get("id") or ""})
    return RedirectResponse(f"/#{frag}", status_code=303, headers={"Cache-Control": "no-store"})


# --------------------------------------------------------------------------- pantallas del PMS
def _solo_admin(scope: Scope) -> None:
    if not (scope.user.is_superadmin or scope.is_group_level("usuarios.gestionar")):
        raise HTTPException(403, "Solo dirección")


@router.get("/fusion/estado")
def estado(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _solo_admin(scope)
    cuenta = dict(db.execute(select(FusionEnlace.tipo, func.count()).where(FusionEnlace.estado == "sincronizada")
                             .group_by(FusionEnlace.tipo)).all())
    entradas = [{"id_evento": e.id_evento, "tipo": e.tipo, "estado": e.estado, "recibido": e.recibido.isoformat(timespec="seconds"),
                 "resultado": e.resultado} for e in db.scalars(select(FusionEntrada).where(FusionEntrada.estado != "sso")
                                                               .order_by(FusionEntrada.id.desc()).limit(100))]
    revisar = [{"id": x.id, "tipo": x.tipo, "pms_ref": x.pms_ref, "nombre": x.nombre, "motivo": x.motivo,
                "creado": x.creado.isoformat(timespec="seconds")}
               for x in db.scalars(select(FusionDocumento).where(FusionDocumento.estado == "a_revisar")
                                   .order_by(FusionDocumento.id.desc()).limit(100))]
    solicitudes = [{"tipo": e.tipo, "pms_ref": e.pms_ref, "solicitud": e.solicitud, "datos": e.solicitud_datos,
                    "fecha": e.solicitud_fecha.isoformat(timespec="seconds") if e.solicitud_fecha else None}
                   for e in db.scalars(select(FusionEnlace).where(FusionEnlace.solicitud.is_not(None)))]
    activos = [{"id": a.id, "codigo": a.codigo, "nombre": a.nombre, "codigo_gestion": gestion._codigo_gestion(a),
                "sync_facturas": bool(a.sync_facturas)} for a in db.scalars(select(Asset).where(Asset.activo.is_(True))
                                                                            .order_by(Asset.codigo))]
    return {"sync": SYNC, "configurado": bool(gestion.EVENTOS_SECRET), "sso": bool(gestion.SSO_SECRET),
            "enlazados": cuenta, "entradas": entradas, "a_revisar": revisar, "solicitudes": solicitudes,
            "activos": activos}


class SyncIn(BaseModel):
    sync_facturas: bool


@router.put("/fusion/activos/{aid}")
def casilla(aid: int, data: SyncIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Casilla «Sincronizar facturas» del activo. Al activarla no se manda lo anterior: eso es la carga inicial
    («Emparejar facturas» en gestión)."""
    _solo_admin(scope)
    a = get_or_404(db, Asset, aid)
    a.sync_facturas = data.sync_facturas
    audit(db, scope.user, "sincronizar_facturas", "activo", aid, {"sync_facturas": data.sync_facturas})
    db.commit()
    return {"id": a.id, "sync_facturas": a.sync_facturas}


def estado_gastos(db: Session, ids: list[int]) -> dict[int, dict]:
    """Para la cuenta de gastos: qué apuntes están ya en gestión, con su solicitud pendiente y documentos de más."""
    if not ids:
        return {}
    out: dict[int, dict] = {}
    for e in db.scalars(select(FusionEnlace).where(FusionEnlace.tipo.in_(("recibida", "pago")),
                                                   FusionEnlace.pms_ref.in_(ids))):
        x = out.setdefault(e.pms_ref, {"gestionada": False, "pago_gestionado": False, "solicitud": None, "adjuntos": []})
        if e.tipo == "recibida":
            x["gestionada"] = e.estado == "sincronizada"
            x["solicitud"] = e.solicitud
            x["origen"] = e.origen
        elif e.estado == "sincronizada":
            x["pago_gestionado"] = True
    for f in db.scalars(select(FusionDocumento).where(FusionDocumento.tipo.in_(("recibida", "pago")),
                                                      FusionDocumento.pms_ref.in_(ids))):
        x = out.setdefault(f.pms_ref, {"gestionada": False, "pago_gestionado": False, "solicitud": None, "adjuntos": []})
        x["adjuntos"].append({"id": f.id, "documento_id": f.documento_id, "nombre": f.nombre, "categoria": f.categoria,
                              "origen": f.origen, "estado": f.estado, "motivo": f.motivo})
    return out


def comprobar_edicion_gasto(db: Session, g: Expense, valores: dict, pagado: bool) -> None:
    """Con la factura en gestión, los datos contables solo se cambian allí."""
    if gestionada(db, "recibida", g.id) is None:
        return
    def igual(a, b):
        if isinstance(a, (Decimal, int, float)) or isinstance(b, (Decimal, int, float)):
            try:
                return dinero(a or 0) == dinero(b or 0)
            except Exception:  # noqa: BLE001
                return a == b
        return (a or None) == (b or None)
    distintos = [k for k in CONTABLES if k in valores and not igual(getattr(g, k), valores[k])]
    if distintos:
        raise HTTPException(409, "Factura gestionada en INVERGESTION: sus datos contables (" + ", ".join(distintos)
                                 + ") solo se cambian en gestión. Use «Pedir corrección».")
    if g.pagado and not pagado and gestionada(db, "pago", g.id):
        raise HTTPException(409, "El pago ya está en gestión: use «Pedir anulación» del pago.")


def comprobar_proveedor(db: Session, s: Supplier, valores: dict) -> None:
    if gestionada(db, "proveedor", s.id) is None:
        return
    distintos = [k for k in CONTABLES_PROVEEDOR if k in valores and (valores[k] or None) != (getattr(s, k) or None)]
    if distintos:
        raise HTTPException(409, "Proveedor gestionado en INVERGESTION: " + ", ".join(distintos)
                                 + " solo se cambian en gestión.")


def _gasto_editable(db: Session, scope: Scope, gid: int) -> Expense:
    g = get_or_404(db, Expense, gid)
    scope.require_asset("documentos.editar", g.asset_id)
    return g


class CorreccionIn(BaseModel):
    cambios: dict
    nota: str | None = Field(default=None, max_length=300)


@router.post("/fusion/recibida/{gid}/correccion")
def pedir_correccion(gid: int, data: CorreccionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Manda a gestión factura_recibida.actualizada con los datos corregidos. En el PMS no cambia nada: la acepta o la
    rechaza administración en gestión y la respuesta vuelve como aviso."""
    g = _gasto_editable(db, scope, gid)
    e = gestionada(db, "recibida", g.id)
    if e is None:
        bad_request("La factura aún no está en gestión: edítela con normalidad")
    cambios = {k: v for k, v in data.cambios.items() if k in CORREGIBLES and v not in (None, "")}
    if not cambios:
        bad_request("Indique qué hay que corregir")
    for k in ("base", "cuota_iva", "retencion", "total"):
        if k in cambios:
            try:
                cambios[k] = float(dinero(cambios[k]))
            except Exception:  # noqa: BLE001
                bad_request(f"Importe no válido: {k}")
    for k in ("fecha_factura", "fecha_vencimiento"):
        if k in cambios:
            try:
                cambios[k] = date.fromisoformat(str(cambios[k])).isoformat()
            except ValueError:
                bad_request(f"Fecha no válida: {k}")
    encolar(db, "factura_recibida.actualizada", "recibida", g.id, {"cambios": cambios, "nota": data.nota}, agrupar=False)
    e.solicitud, e.solicitud_fecha = "correccion", datetime.now()
    e.solicitud_datos = {"cambios": cambios, "nota": data.nota, "usuario": scope.user.id}
    audit(db, scope.user, "pedir_correccion", "gasto", g.id, {"cambios": cambios, "nota": data.nota})
    db.commit()
    return {"ok": True, "solicitud": "correccion"}


class NoContableIn(BaseModel):
    concepto: str = Field(min_length=2, max_length=300)
    categoria: str
    ambito: str = "general"
    unit_id: int | None = None
    ambito_detalle: str | None = Field(default=None, max_length=200)
    notas: str | None = None


@router.put("/fusion/recibida/{gid}/datos")
def editar_no_contable(gid: int, data: NoContableIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Factura ya en gestión: en el PMS solo se cambia lo que no es contable (concepto, categoría, a qué apartamento
    se imputa y notas). El cambio viaja a gestión como factura_recibida.actualizada."""
    from .models import AMBITOS_GASTO, CATEGORIAS_GASTO
    g = _gasto_editable(db, scope, gid)
    if data.categoria not in CATEGORIAS_GASTO:
        bad_request("Categoría no válida")
    if data.ambito not in AMBITOS_GASTO:
        bad_request("Ámbito no válido: general, apartamento u otro")
    if data.ambito == "apartamento":
        u = db.get(Unit, data.unit_id) if data.unit_id else None
        if u is None or u.asset_id != g.asset_id:
            bad_request("Indique el apartamento del gasto")
    antes = {k: getattr(g, k) for k in ("concepto", "categoria", "ambito", "unit_id", "ambito_detalle", "notas")}
    g.concepto, g.categoria, g.ambito, g.notas = data.concepto.strip(), data.categoria, data.ambito, data.notas
    g.unit_id = data.unit_id if data.ambito == "apartamento" else None
    g.ambito_detalle = data.ambito_detalle if data.ambito == "otro" else None
    audit(db, scope.user, "editar", "gasto", gid, {k: [str(v), str(getattr(g, k))] for k, v in antes.items()
                                                   if v != getattr(g, k)})
    db.commit()
    return {"ok": True}


class MotivoIn(BaseModel):
    motivo: str = Field(min_length=3, max_length=300)


@router.post("/fusion/recibida/{gid}/anulacion")
def pedir_anulacion(gid: int, data: MotivoIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Nunca anula por su cuenta: la pide a gestión (factura_recibida.anulacion_pedida)."""
    g = _gasto_editable(db, scope, gid)
    e = gestionada(db, "recibida", g.id)
    if e is None:
        bad_request("La factura aún no está en gestión: puede borrarla con normalidad")
    encolar(db, "factura_recibida.anulacion_pedida", "recibida", g.id, {"motivo": data.motivo}, agrupar=False)
    e.solicitud, e.solicitud_fecha = "anulacion", datetime.now()
    e.solicitud_datos = {"motivo": data.motivo, "usuario": scope.user.id}
    audit(db, scope.user, "pedir_anulacion", "gasto", g.id, {"motivo": data.motivo})
    db.commit()
    return {"ok": True, "solicitud": "anulacion"}


@router.post("/fusion/pago/{gid}/anulacion")
def pedir_anulacion_pago(gid: int, data: MotivoIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    g = _gasto_editable(db, scope, gid)
    if gestionada(db, "pago", g.id) is None:
        bad_request("El pago aún no está en gestión: desmárquelo con normalidad")
    encolar(db, "pago.anulado", "pago", g.id, {"motivo": data.motivo}, agrupar=False)
    audit(db, scope.user, "pedir_anulacion_pago", "gasto", g.id, {"motivo": data.motivo})
    db.commit()
    return {"ok": True}


@router.post("/fusion/recibida/{gid}/documento", status_code=201)
def adjuntar(gid: int, ficheros: list[UploadFile] = File(...), categoria: str = Form("OTRO"),
             scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """«Adjuntar documento» (también con la factura ya en gestión): se guarda en la carpeta del activo y, si la factura
    se sincroniza, viaja a gestión con documento.adjuntado."""
    from .routers.gastos import _fichero
    g = _gasto_editable(db, scope, gid)
    categoria = categoria.upper()
    if categoria not in CATEGORIAS_DOC:
        bad_request("Categoría no válida: FACTURA, JUSTIFICANTE, ALBARAN u OTRO")
    datos, mime, nombre = _fichero(ficheros)
    x = ReceivedDocument(asset_id=g.asset_id, unit_id=g.unit_id, tipo=CATEGORIAS_DOC[categoria], fecha=date.today(),
                         emisor=g.proveedor, referencia=g.numero_factura, descripcion=f"Adjunto · {g.concepto}"[:1000],
                         nombre=nombre, fichero=documentos.guardar(datos), mime=mime, tamano=len(datos),
                         sha256=documentos.huella(datos), user_id=scope.user.id)
    db.add(x)
    db.flush()
    db.add(FusionDocumento(tipo="recibida", pms_ref=g.id, origen="PMS", categoria=categoria, documento_id=x.id,
                           nombre=nombre, mime=mime, tamano=len(datos), sha256=x.sha256, estado="ok"))
    if sincroniza(db, g.asset_id):
        encolar(db, "documento.adjuntado", "recibida", g.id, {"rd": x.id, "cat": categoria}, agrupar=False)
    audit(db, scope.user, "adjuntar", "gasto", g.id, {"documento": x.id, "categoria": categoria})
    db.commit()
    return {"id": x.id, "nombre": nombre, "categoria": categoria}


@router.get("/fusion/abrir")
def abrir_en_gestion(tipo: str, ref: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Botón «Abrir en gestión»: el /sso/pms de siempre con destino recibida|emitida|pago|proveedor y el id de
    gestión. La firma se calcula aquí, en el servidor."""
    if not gestion.puede_ir(scope.user):
        raise HTTPException(403, "El acceso a gestión solo está habilitado para la Dirección")
    if tipo not in DESTINOS:
        bad_request("Destino no válido")
    e = enlace(db, tipo, ref)
    if e is None or e.estado != "sincronizada":
        bad_request("Este registro no está en gestión")
    a = db.get(Asset, e.asset_id) if e.asset_id else None
    if a is not None and scope.asset_ids("documentos.ver") is not None and a.id not in scope.asset_ids("documentos.ver"):
        raise HTTPException(403, "Sin acceso a ese activo")
    activo = gestion._codigo_gestion(a) if a else None
    if not gestion.SSO_SECRET:
        qs = urllib.parse.urlencode({k: v for k, v in (("destino", tipo), ("id", e.gestion_id), ("activo", activo)) if v})
        return {"url": f"{gestion.GESTION_PUBLICA}/?{qs}", "nivel": 1}
    datos = {"usuario_pms": scope.user.id, "email": scope.user.email, "destino": tipo, "id": e.gestion_id,
             "activo": activo, "unidad": None, "unidad_pms_id": None, "emitido": _utc(),
             "nonce": secrets.token_hex(16)}
    p = gestion._b64(json.dumps(datos, ensure_ascii=False, separators=(",", ":")).encode())
    f = hmac.new(gestion.SSO_SECRET.encode(), p.encode(), hashlib.sha256).hexdigest()
    audit(db, scope.user, "abrir_en_gestion", tipo, ref, {"gestion_id": e.gestion_id})
    db.commit()
    return {"url": f"{gestion.GESTION_PUBLICA}/sso/pms?pase={p}&firma={f}", "nivel": 2}
