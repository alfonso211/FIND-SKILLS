"""Facturación del programa anterior (SYADE): importación de sus listados y resumen mensual.
Cuenta en la producción del panel y del informe Excel; no entra en la numeración ni en la cadena de facturas."""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import delete, func, or_, select
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


FORMAS_SOCIALES = {"SL", "SA", "SLU", "SAU", "SLL", "SLP", "SC", "CB", "SCOOP", "SLNE"}


def clave_nombre(*partes: str | None) -> str | None:
    """Nombre sin tildes, signos ni orden: «GARCÍA LÓPEZ, ANA» y «Ana García López» dan la misma clave. Con una
    sola palabra no se cruza (demasiado ambiguo), salvo una empresa con su forma social."""
    texto = re.sub(r"\b(\w) (?=\w\b)", r"\1", nif.nombre_clave(*partes))  # «S L U» -> «SLU»
    palabras = texto.split()
    empresa = bool(palabras) and palabras[-1] in FORMAS_SOCIALES
    if empresa:  # «EMPRESA, S.L.» y «Empresa SL» son la misma
        palabras = palabras[:-1]
    palabras.sort()
    return " ".join(palabras) if len(palabras) >= 2 or (empresa and palabras) else None


class Cruce:
    """Clientes del PMS de unos activos para enlazar las líneas del listado: primero por DNI/NIF y, si no, por
    nombre y apellidos cuando el nombre corresponde a un único cliente (dos fichas con el mismo nombre no se usan)."""

    def __init__(self, db: Session, asset_ids: list[int]):
        self.docs: dict[str, int] = {}
        self.docs_de: dict[int, set[str]] = {}
        self.nombres: dict[str, int | None] = {}
        socs = select(Asset.company_id).where(Asset.id.in_(asset_ids or [-1]))
        filas = db.execute(select(Contact.id, Contact.documento_num, Contact.nombre, Contact.apellidos).where(
            or_(Contact.asset_id.in_(asset_ids or [-1]), Contact.asset_id.is_(None) & Contact.company_id.in_(socs)))
            .order_by(Contact.asset_id.is_(None), (Contact.tipo != "huesped"), Contact.id)).all()
        for cid, doc, nombre, apellidos in filas:
            self.docs_de[cid] = claves_cliente(doc)
            for k in self.docs_de[cid]:
                self.docs.setdefault(k, cid)
            k = clave_nombre(nombre, apellidos)
            if k:
                self.nombres[k] = cid if self.nombres.get(k, cid) == cid else None

    def cliente(self, nif_: str | None, nombre: str | None) -> tuple[int | None, str | None]:
        """(cliente, «documento» | «nombre») o (None, None)."""
        k = clave(nif_)
        if k and k in self.docs:
            return self.docs[k], "documento"
        cid = self.nombres.get(clave_nombre(nombre) or "")
        if not cid or (k and self.docs_de.get(cid)):  # mismo nombre pero el cliente tiene otro documento
            return None, None
        return cid, "nombre"


def del_cliente(db: Session, c: Contact) -> dict | None:
    """Facturación del programa anterior de un cliente del PMS: por su documento (NIF del listado), por su nombre
    (ver Cruce) o por sus reservas. Solo para el control de producción."""
    if c.asset_id:
        activos = [c.asset_id]
    else:
        activos = list(db.scalars(select(Asset.id).where(Asset.company_id == c.company_id)))
    reservas = set(db.scalars(select(Reservation.id).where(Reservation.guest_id == c.id)))
    cruce = Cruce(db, activos)
    filas, enlace = [], {}
    for x in db.scalars(select(ExternalInvoice).where(ExternalInvoice.asset_id.in_(activos or [-1]))
                        .order_by(ExternalInvoice.fecha.desc(), ExternalInvoice.id.desc())):
        cid, como = cruce.cliente(x.nif, x.cliente)
        como = como if cid == c.id else ("reserva" if x.reservation_id and x.reservation_id in reservas else None)
        if como:
            filas.append(x)
            enlace[x.id] = como
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
                         "fianza": float(x.fianza), "enlace": enlace[x.id]} for x in filas]}


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
    cruce = Cruce(db, [asset_id])
    enlaces = [cruce.cliente(f["nif"], f["cliente"]) for f in filas]
    resumen = {"tipo": r["tipo"], "tipo_nombre": importacion_syade.TIPOS[r["tipo"]], "registros": len(filas),
               "nuevas": nuevas, "actualizadas": len(filas) - nuevas, "cuadra": r["cuadra"],
               "leido": _json(r["leido"]), "esperado": _json(r["esperado"]) if r["esperado"] else None,
               "avisos": r["avisos"], "con_reserva": sum(1 for f in filas if f["localizador"] in reservas),
               "con_cliente": sum(1 for cid, _ in enlaces if cid),
               "por_nombre": sum(1 for _, como in enlaces if como == "nombre"),
               "clientes": len({cid for cid, _ in enlaces if cid}),
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
        cruce = Cruce(db, [aid])
        lineas = db.execute(select(ExternalInvoice.nif, ExternalInvoice.cliente).where(
            ExternalInvoice.asset_id == aid, ExternalInvoice.tipo != "fianza_devuelta")).all()
        enlaces = [cruce.cliente(n, nom) for n, nom in lineas]
        enlazadas = [cid for cid, _ in enlaces if cid]
        out.append({"asset_id": aid, "activo": nombres.get(aid), "desde": ini.isoformat(), "hasta": fin.isoformat(),
                    "importado": importado.isoformat(timespec="minutes") if importado else None, "registros": tipos,
                    "clientes": {"facturas": len(lineas), "con_cliente": len(enlazadas), "clientes": len(set(enlazadas)),
                                 "por_nombre": sum(1 for _, como in enlaces if como == "nombre")},
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
