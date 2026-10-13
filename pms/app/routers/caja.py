"""Caja de recepción: arqueo por turno y recepcionista.

El turno de cada recepcionista en un activo va desde su último cierre (o desde las 00:00 de hoy si no tiene) hasta
ahora. Entra lo que ha cobrado o devuelto esa persona: facturas emitidas ya cobradas, facturas pendientes que ha
marcado cobradas, fianzas cobradas al llegar y fianzas devueltas en efectivo o tarjeta. Al cerrar cuenta el efectivo:
si no cuadra hay que explicar el motivo y se avisa a la Dirección. Cada cierre va también a gestión (caja.cierre)."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import avisos, gestion
from ..config import settings
from ..database import get_db
from ..facturacion import FORMAS_PAGO, dinero
from ..fianzas import FORMAS_COBRO
from ..models import Asset, CashClose, DepositRefund, Invoice, Reservation, Unit, User
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404

router = APIRouter(prefix="/api/caja", tags=["caja"])
FORMAS = {**FORMAS_COBRO, **FORMAS_PAGO, "sin_forma": "Sin forma de pago"}


def inicio_turno(db: Session, asset_id: int, user_id: int, ahora: datetime) -> datetime:
    ultimo = db.scalar(select(CashClose.hasta).where(CashClose.asset_id == asset_id, CashClose.user_id == user_id)
                       .order_by(CashClose.hasta.desc()).limit(1))
    return ultimo or datetime.combine(ahora.date(), time.min)


def movimientos(db: Session, asset_id: int, user_id: int, desde: datetime, hasta: datetime) -> list[dict]:
    out = []
    for f in db.scalars(select(Invoice).where(Invoice.asset_id == asset_id, Invoice.user_id == user_id,
                                              Invoice.creada > desde, Invoice.creada <= hasta,
                                              Invoice.cobro == "cobrada", Invoice.cobro_marcado.is_(None))):
        out.append({"hora": f.creada.isoformat(timespec="minutes"), "tipo": "factura", "ref": f.codigo,
                    "forma": f.forma_pago or "sin_forma", "importe": float(f.total)})
    for f in db.scalars(select(Invoice).where(Invoice.asset_id == asset_id, Invoice.cobro_user_id == user_id,
                                              Invoice.cobro_marcado > desde, Invoice.cobro_marcado <= hasta)):
        out.append({"hora": f.cobro_marcado.isoformat(timespec="minutes"), "tipo": "cobro de factura", "ref": f.codigo,
                    "forma": f.cobro_forma or "sin_forma", "importe": float(f.total)})
    for r in db.scalars(select(Reservation).join(Unit, Unit.id == Reservation.unit_id).where(
            Unit.asset_id == asset_id, Reservation.fianza_cobro.is_not(None),
            Reservation.fecha_salida >= desde.date() - timedelta(days=60))):
        c = r.fianza_cobro or {}
        cuando = datetime.fromisoformat(c["fecha"]) if c.get("fecha") else None
        if c.get("user_id") == user_id and cuando and desde < cuando <= hasta:
            out.append({"hora": cuando.isoformat(timespec="minutes"), "tipo": "fianza cobrada",
                        "ref": r.localizador or f"R-{r.id}", "forma": c.get("forma") or "sin_forma",
                        "importe": float(c.get("importe") or 0)})
    for d in db.scalars(select(DepositRefund).where(DepositRefund.asset_id == asset_id, DepositRefund.user_id == user_id,
                                                    DepositRefund.creada > desde, DepositRefund.creada <= hasta,
                                                    DepositRefund.forma.in_(("efectivo", "tarjeta")))):
        r = db.get(Reservation, d.reservation_id)
        out.append({"hora": d.creada.isoformat(timespec="minutes"), "tipo": "fianza devuelta",
                    "ref": r.localizador or f"R-{r.id}", "forma": d.forma, "importe": -float(d.importe)})
    return sorted(out, key=lambda x: x["hora"])


def totales(movs: list[dict]) -> dict[str, float]:
    t: dict[str, Decimal] = {}
    for m in movs:
        t[m["forma"]] = t.get(m["forma"], Decimal(0)) + dinero(m["importe"])
    return {k: float(v) for k, v in sorted(t.items())}


def _activo(db: Session, scope: Scope, asset_id: int) -> Asset:
    scope.require_asset("reservas.editar", asset_id)
    return get_or_404(db, Asset, asset_id)


@router.get("/turno")
def current_shift(asset_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Lo cobrado y devuelto por el usuario en su turno abierto (desde su último cierre)."""
    _activo(db, scope, asset_id)
    ahora = datetime.now()
    desde = inicio_turno(db, asset_id, scope.user.id, ahora)
    movs = movimientos(db, asset_id, scope.user.id, desde, ahora)
    t = totales(movs)
    return {"desde": desde.isoformat(timespec="minutes"), "hasta": ahora.isoformat(timespec="minutes"),
            "movimientos": movs, "totales": t, "efectivo_esperado": t.get("efectivo", 0.0), "formas": FORMAS}


class CierreIn(BaseModel):
    asset_id: int
    efectivo_contado: float = Field(ge=0, le=1_000_000)
    fondo: float = Field(default=0, ge=0, le=100_000)  # fondo de caja que se deja (no es cobro del turno)
    nota: str | None = Field(default=None, max_length=1000)


def _out(c: CashClose, db: Session) -> dict:
    d = c.to_dict()
    d["recepcionista"] = db.scalar(select(User.nombre).where(User.id == c.user_id))
    d["activo"] = db.scalar(select(Asset.nombre).where(Asset.id == c.asset_id))
    return d


@router.post("/cierre", status_code=201)
def close_shift(data: CierreIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Cierre del turno: arqueo del efectivo. Si no cuadra hay que indicar el motivo y se avisa a la Dirección."""
    a = _activo(db, scope, data.asset_id)
    ahora = datetime.now()
    desde = inicio_turno(db, a.id, scope.user.id, ahora)
    movs = movimientos(db, a.id, scope.user.id, desde, ahora)
    t = totales(movs)
    esperado = dinero(t.get("efectivo", 0))
    contado, fondo = dinero(data.efectivo_contado), dinero(data.fondo)
    dif = contado - fondo - esperado
    nota = (data.nota or "").strip() or None
    if dif != 0 and not nota:
        bad_request(f"La caja no cuadra ({float(dif):+.2f} €): indique el motivo antes de cerrar")
    c = CashClose(asset_id=a.id, user_id=scope.user.id, desde=desde, hasta=ahora, totales=t, movimientos=movs,
                  fondo=fondo, efectivo_esperado=esperado, efectivo_contado=contado, diferencia=dif, nota=nota)
    db.add(c)
    db.flush()
    gestion.encolar(db, "caja.cierre", {
        "cierre_id": c.id, "activo": gestion._codigo_gestion(a), "activo_pms": a.codigo, "recepcionista": scope.user.nombre,
        "desde": desde.isoformat(timespec="seconds"), "hasta": ahora.isoformat(timespec="seconds"), "totales": t,
        "efectivo_esperado": float(esperado), "efectivo_contado": float(contado), "fondo": float(fondo),
        "diferencia": float(dif), "nota": nota, "movimientos": len(movs)})
    if dif != 0:
        _avisar_descuadre(db, c, a, scope.user)
    audit(db, scope.user, "cierre_caja", "activo", a.id, {"cierre": c.id, "diferencia": float(dif)})
    db.commit()
    return _out(c, db)


def _avisar_descuadre(db: Session, c: CashClose, a: Asset, u: User) -> None:
    asunto = f"Descuadre de caja · {a.nombre} · {u.nombre}: {float(c.diferencia):+.2f} €"
    filas = [["Turno", f"{c.desde:%d/%m/%Y %H:%M} – {c.hasta:%H:%M}"], ["Efectivo esperado", f"{float(c.efectivo_esperado):.2f} €"],
             ["Fondo", f"{float(c.fondo):.2f} €"], ["Efectivo contado", f"{float(c.efectivo_contado):.2f} €"],
             ["Diferencia", f"{float(c.diferencia):+.2f} €"], ["Motivo", c.nota or ""]]
    texto = asunto + "\n" + "\n".join(f"{k}: {v}" for k, v in filas)
    for e in settings.fianza_avisos:
        dest = db.scalar(select(User).where(User.email == e))
        avisos._enviar_registrado(db, dest, e, f"caja_descuadre:{c.id}", "caja", asunto, texto,
                                  avisos._html("Descuadre de caja", avisos._tabla(["", ""], filas)))


@router.get("/cierres")
def list_closes(asset_id: int | None = None, desde: date | None = None, hasta: date | None = None,
                scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Cierres de caja: cada recepcionista ve los suyos; la dirección (finanzas.ver) los de sus activos."""
    q = select(CashClose)
    if asset_id:
        q = q.where(CashClose.asset_id == asset_id)
    ids = scope.asset_ids("finanzas.ver")
    if ids is not None:
        q = q.where((CashClose.user_id == scope.user.id) | CashClose.asset_id.in_(ids or {-1}))
    if desde:
        q = q.where(CashClose.hasta >= datetime.combine(desde, time.min))
    if hasta:
        q = q.where(CashClose.hasta < datetime.combine(hasta + timedelta(days=1), time.min))
    return [_out(c, db) for c in db.scalars(q.order_by(CashClose.hasta.desc()).limit(300))]


@router.get("/cierres/{cid}")
def close_detail(cid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    c = get_or_404(db, CashClose, cid)
    if c.user_id != scope.user.id and not scope.can_asset("finanzas.ver", c.asset_id):
        raise HTTPException(403, "Sin permiso para ver este cierre de caja")
    return _out(c, db)
