"""Facturación del programa anterior (SYADE): importación de sus listados y resumen mensual.
Cuenta en la producción del panel y del informe Excel; no entra en la numeración ni en la cadena de facturas."""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

import re

from .. import importacion_syade, nif
from ..database import get_db
from ..models import MODALIDADES_RESERVA, Asset, Contact, ExternalInvoice, Reservation, Unit
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404

router = APIRouter(prefix="/api/historico", tags=["histórico de facturación"])

TAM_MAX = 10 * 1024 * 1024
PERM_IMPORTAR = "facturas.rectificar"  # quien lleva la facturación del activo


def clave(doc: str | None) -> str | None:
    """Clave para cruzar el NIF del listado con el documento del cliente: sin espacios ni guiones, en mayúsculas y
    sin ceros a la izquierda (el paso de PDF a Excel convierte los DNI sin letra en números y pierde los ceros)."""
    n = (nif.normalizar(doc) or "").lstrip("0")
    return n or None


def claves_cliente(doc: str | None) -> set[str]:
    """El documento del cliente y, si es un DNI o NIE con letra, también sin ella (algunos listados la omiten)."""
    n = nif.normalizar(doc) or ""
    out = {clave(n)}
    if re.fullmatch(r"[XYZ]?\d{7,8}[A-Z]", n):
        out.add(clave(n[:-1]))
    return {k for k in out if k and len(k) >= 5}


def clientes_por_clave(db: Session, asset_ids: list[int]) -> dict[str, int]:
    """Clave del documento -> cliente de esos activos (el huésped primero y, si hay varias fichas, la más antigua)."""
    out: dict[str, int] = {}
    filas = db.execute(select(Contact.id, Contact.documento_num, Contact.tipo).where(
        Contact.asset_id.in_(asset_ids or [-1]), Contact.documento_num.isnot(None))
        .order_by((Contact.tipo != "huesped"), Contact.id)).all()
    for cid, doc, _ in filas:
        for k in claves_cliente(doc):
            out.setdefault(k, cid)
    return out


def del_cliente(db: Session, c: Contact) -> dict | None:
    """Facturación del programa anterior de un cliente del PMS: por su documento (NIF del listado) o por sus
    reservas (las fianzas devueltas no traen NIF). Solo para el control de producción."""
    if c.asset_id:
        activos = [c.asset_id]
    else:
        activos = list(db.scalars(select(Asset.id).where(Asset.company_id == c.company_id)))
    claves = claves_cliente(c.documento_num)
    reservas = set(db.scalars(select(Reservation.id).where(Reservation.guest_id == c.id)))
    if not claves and not reservas:
        return None
    filas = [x for x in db.scalars(select(ExternalInvoice).where(ExternalInvoice.asset_id.in_(activos or [-1]))
                                   .order_by(ExternalInvoice.fecha.desc(), ExternalInvoice.id.desc()))
             if (x.nif and clave(x.nif) in claves) or (x.reservation_id and x.reservation_id in reservas)]
    if not filas:
        return None
    fact = [x for x in filas if x.tipo != "fianza_devuelta"]
    return {"facturas": sum(1 for x in fact if x.tipo != "abono"), "abonos": sum(1 for x in fact if x.tipo == "abono"),
            "produccion": round(sum(float(x.base) for x in fact), 2),
            "alojamiento": round(sum(float(x.base) for x in fact if x.tipo != "servicio"), 2),
            "servicios": round(sum(float(x.base) for x in fact if x.tipo == "servicio"), 2),
            "total": round(sum(float(x.total) for x in fact), 2),
            "fianzas_cobradas": round(sum(float(x.fianza) for x in fact), 2),
            "fianzas_devueltas": round(sum(float(x.fianza) for x in filas if x.tipo == "fianza_devuelta"), 2),
            "desde": min(x.fecha for x in filas).isoformat(), "hasta": max(x.fecha for x in filas).isoformat(),
            "detalle": [{"tipo": x.tipo, "factura": f"{x.serie} {x.numero}", "fecha": x.fecha.isoformat(),
                         "localizador": x.localizador, "base": float(x.base), "total": float(x.total),
                         "fianza": float(x.fianza)} for x in filas]}


def _json(d: dict) -> dict:
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in d.items()}


@router.post("/importar")
def import_file(fichero: UploadFile = File(...), asset_id: int = Form(...), confirmar: bool = Form(False),
                anio: int | None = Form(None), scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Sin confirmar: lee el listado y devuelve el resumen y si cuadra con sus totales. Confirmado: lo guarda.
    Volver a importar el mismo listado actualiza los registros (no duplica)."""
    scope.require_asset(PERM_IMPORTAR, asset_id)
    asset = get_or_404(db, Asset, asset_id)
    datos = fichero.file.read(TAM_MAX + 1)
    if len(datos) > TAM_MAX:
        bad_request("El fichero supera 10 MB")
    try:
        r = importacion_syade.leer(datos, anio)
    except ValueError as e:
        bad_request(str(e))
    filas = r["filas"]
    previas = {(x.tipo, x.serie, x.numero): x for x in db.scalars(select(ExternalInvoice).where(
        ExternalInvoice.asset_id == asset_id, ExternalInvoice.tipo == r["tipo"]))}
    reservas = {}
    if asset.modalidad in MODALIDADES_RESERVA:
        reservas = dict(db.execute(select(Reservation.localizador, Reservation.id).join(Unit).where(
            Unit.asset_id == asset_id, Reservation.localizador.in_({f["localizador"] for f in filas if f["localizador"]}
                                                                   or {"-"}))).all())
    nuevas = sum(1 for f in filas if (r["tipo"], f["serie"], f["numero"]) not in previas)
    por_clave = clientes_por_clave(db, [asset_id])
    con_cliente = {por_clave[clave(f["nif"])] for f in filas if f["nif"] and clave(f["nif"]) in por_clave}
    resumen = {"tipo": r["tipo"], "tipo_nombre": importacion_syade.TIPOS[r["tipo"]], "registros": len(filas),
               "nuevas": nuevas, "actualizadas": len(filas) - nuevas, "cuadra": r["cuadra"],
               "leido": _json(r["leido"]), "esperado": _json(r["esperado"]) if r["esperado"] else None,
               "avisos": r["avisos"], "con_reserva": sum(1 for f in filas if f["localizador"] in reservas),
               "con_cliente": sum(1 for f in filas if f["nif"] and clave(f["nif"]) in por_clave),
               "clientes": len(con_cliente),
               "desde": min((f["fecha"] for f in filas), default=None),
               "hasta": max((f["fecha"] for f in filas), default=None)}
    if not confirmar:
        return resumen
    if not filas:
        bad_request("El listado no tiene registros")
    for f in filas:
        x = previas.get((r["tipo"], f["serie"], f["numero"]))
        if x is None:
            x = ExternalInvoice(asset_id=asset_id, tipo=r["tipo"], serie=f["serie"], numero=f["numero"])
            db.add(x)
        for k in ("fecha", "localizador", "nif", "cliente", "base", "tipo_iva", "cuota", "total", "fianza"):
            setattr(x, k, f[k])
        x.detalle = f.get("detalle")
        x.reservation_id = reservas.get(f["localizador"])
        x.user_id = scope.user.id
    audit(db, scope.user, "importar_historico", "activo", asset_id,
          {"fichero": fichero.filename, "tipo": r["tipo"], "registros": len(filas), "nuevas": nuevas,
           "cuadra": r["cuadra"], "base": float(r["leido"].get("base", 0))})
    db.commit()
    return {**resumen, "importado": True}


def mensual(db: Session, ids: list[int], desde: date, hasta: date) -> dict[tuple[int, str], dict[str, float]]:
    """Por activo y mes (fecha de factura): base de alojamiento (con los abonos), de servicios, IVA, total, nº y
    fianzas. Lo usan el panel, el informe de producción y el resumen."""
    out: dict[tuple[int, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for x in db.scalars(select(ExternalInvoice).where(ExternalInvoice.asset_id.in_(ids or [-1]),
                                                      ExternalInvoice.fecha >= desde, ExternalInvoice.fecha <= hasta)):
        acc = out[(x.asset_id, f"{x.fecha:%Y-%m}")]
        if x.tipo == "fianza_devuelta":
            acc["fianzas_devueltas"] += float(x.fianza)
            acc["fianzas_retenidas"] += float((x.detalle or {}).get("retenida") or 0)
            continue
        linea = "servicio" if x.tipo == "servicio" else "alojamiento"
        acc[linea] += float(x.base)
        if x.tipo == "abono":
            acc["abonos"] += float(x.base)
        acc["base"] += float(x.base)
        acc["iva"] += float(x.cuota)
        acc["total"] += float(x.total)
        acc["n"] += 1
        acc["fianzas_cobradas"] += float(x.fianza)
    return out


@router.get("")
def summary(asset_id: int | None = None, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ids = scope.asset_ids("finanzas.ver")
    stmt = select(ExternalInvoice.asset_id, func.min(ExternalInvoice.fecha), func.max(ExternalInvoice.fecha),
                  func.max(ExternalInvoice.importado)).group_by(ExternalInvoice.asset_id)
    if ids is not None:
        stmt = stmt.where(ExternalInvoice.asset_id.in_(ids or {-1}))
    if asset_id:
        stmt = stmt.where(ExternalInvoice.asset_id == asset_id)
    out = []
    nombres = dict(db.execute(select(Asset.id, Asset.nombre)).all())
    for aid, ini, fin, importado in db.execute(stmt).all():
        meses = mensual(db, [aid], ini, fin)
        tipos = dict(db.execute(select(ExternalInvoice.tipo, func.count()).where(ExternalInvoice.asset_id == aid)
                                .group_by(ExternalInvoice.tipo)).all())
        por_clave = clientes_por_clave(db, [aid])
        nifs = [clave(n) for n in db.scalars(select(ExternalInvoice.nif).where(
            ExternalInvoice.asset_id == aid, ExternalInvoice.tipo != "fianza_devuelta"))]
        enlazadas = [por_clave[k] for k in nifs if k in por_clave]
        out.append({"asset_id": aid, "activo": nombres.get(aid), "desde": ini.isoformat(), "hasta": fin.isoformat(),
                    "importado": importado.isoformat(timespec="minutes") if importado else None, "registros": tipos,
                    "clientes": {"facturas": len(nifs), "con_cliente": len(enlazadas), "clientes": len(set(enlazadas))},
                    "meses": [{"mes": m, **{k: round(v, 2) for k, v in d.items()},
                               "produccion": round(d.get("base", 0), 2)}
                              for (_, m), d in sorted(meses.items())]})
    return out


@router.delete("")
def remove(asset_id: int, tipo: str | None = None, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Borra lo importado de un activo (todo o un tipo de listado) para volver a cargarlo."""
    scope.require_asset(PERM_IMPORTAR, asset_id)
    if tipo and tipo not in importacion_syade.TIPOS:
        bad_request("Tipo de listado no válido")
    stmt = delete(ExternalInvoice).where(ExternalInvoice.asset_id == asset_id)
    if tipo:
        stmt = stmt.where(ExternalInvoice.tipo == tipo)
    n = db.execute(stmt).rowcount
    audit(db, scope.user, "borrar_historico", "activo", asset_id, {"tipo": tipo, "registros": n})
    db.commit()
    return {"borrados": n}
