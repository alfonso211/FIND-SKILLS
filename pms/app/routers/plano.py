"""Plano interactivo por plantas: estado de cada apartamento, ficha completa, bloqueos y zonas comunes.

Colores (los mismos del PMS anterior): alquilado (huésped alojado), reserva (reserva confirmada pendiente de
llegada para ese día), disponible y bloqueado (bloqueado, fuera de servicio o en mantenimiento que lo bloquea).
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import planos
from ..database import get_db
from ..models import (AccommodationContract, Asset, Contact, Invoice, Reservation, Unit, UnitBlock, User,
                      WorkOrder)
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404
from .mantenimiento import ABIERTAS

router = APIRouter(prefix="/api/plano", tags=["plano"])

ESTADOS_BLOQUEO = ("bloqueada", "fuera_servicio", "mantenimiento")
ESTADOS_PLANO = ("alquilado", "reserva", "disponible", "bloqueado")


def _tipo_corto(u: Unit) -> str:
    if u.uso == "garaje":
        return ""
    t = (u.tipologia or "").lower()
    base = "Est" if "estudio" in t else f"{u.dormitorios or 1}d"
    if "terraza grande" in t:
        return base + " TG"
    if "terraza" in t:
        return base + " T"
    if "grande" in t:
        return base + " G"
    return base


def _nombre(c: Contact | None) -> str:
    return f"{c.nombre} {c.apellidos or ''}".strip() if c else ""


def estados(db: Session, units: list[Unit], dia: date) -> dict[int, dict]:
    """Estado de cada unidad para un día, con el huésped o la reserva que lo explica."""
    ids = [u.id for u in units]
    res = db.execute(select(Reservation, Contact).join(Contact, Contact.id == Reservation.guest_id).where(
        Reservation.unit_id.in_(ids or [-1]), Reservation.estado.in_(("confirmada", "checkin")),
        Reservation.fecha_entrada <= dia, Reservation.fecha_salida > dia)).all()
    por_unidad = {r.unit_id: (r, g) for r, g in res}
    hoy = date.today()
    out = {}
    for u in units:
        r, g = por_unidad.get(u.id, (None, None))
        if u.estado in ESTADOS_BLOQUEO:
            e = "bloqueado"
        elif r is not None and r.estado == "checkin":
            e = "alquilado"
        elif r is not None:
            e = "reserva"
        elif u.estado == "ocupada" and dia == hoy:
            e = "alquilado"
        else:
            e = "disponible"
        out[u.id] = {"estado": e, "estado_unidad": u.estado, "limpieza": u.estado == "pendiente_limpieza",
                     "reserva": {"id": r.id, "localizador": r.localizador, "huesped": _nombre(g),
                                 "entrada": r.fecha_entrada.isoformat(), "salida": r.fecha_salida.isoformat(),
                                 "estado": r.estado} if r else None}
    return out


def _activo_plano(db: Session, scope: Scope, asset_id: int) -> tuple[Asset, dict]:
    scope.require_asset("activos.ver", asset_id)
    a = get_or_404(db, Asset, asset_id)
    p = planos.plano(a.codigo)
    if not p:
        raise HTTPException(404, f"{a.nombre} aún no tiene plano")
    return a, p


@router.get("/activos")
def assets_with_plan(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ids = scope.asset_ids("activos.ver")
    stmt = select(Asset).where(Asset.codigo.in_(list(planos.PLANOS)))
    if ids is not None:
        stmt = stmt.where(Asset.id.in_(ids or {-1}))
    return [{"id": a.id, "codigo": a.codigo, "nombre": a.nombre} for a in db.scalars(stmt.order_by(Asset.codigo))]


@router.get("/{asset_id}")
def floor_plan(asset_id: int, fecha: date | None = None, scope: Scope = Depends(get_scope),
               db: Session = Depends(get_db)):
    """Plano completo del activo con el estado de cada apartamento y las OT abiertas (apartamentos y zonas)."""
    a, p = _activo_plano(db, scope, asset_id)
    dia = fecha or date.today()
    units = list(db.scalars(select(Unit).where(Unit.asset_id == asset_id)))
    por_num = {planos.numero(u.codigo): u for u in units}
    por_cod = {u.codigo: u for u in units}
    est = estados(db, units, dia)
    ve_mto = scope.can_asset("mantenimiento.ver", asset_id)
    ve_res = scope.can_asset("reservas.ver", asset_id)
    ot_unidad, ot_zona = {}, {}
    if ve_mto:
        for uid, zona, prio in db.execute(select(WorkOrder.unit_id, WorkOrder.zona, WorkOrder.prioridad).where(
                WorkOrder.asset_id == asset_id, WorkOrder.estado.in_(ABIERTAS))):
            destino = ot_unidad.setdefault(uid, [0, False]) if uid else ot_zona.setdefault(zona, [0, False]) if zona else None
            if destino is not None:
                destino[0] += 1
                destino[1] = destino[1] or prio == "urgente"
    plantas = []
    for pl in p["plantas"]:
        resumen = dict.fromkeys(ESTADOS_PLANO, 0)
        celdas = []
        for c in pl["celdas"]:
            c = dict(c)
            if c["t"] == "u":
                u = por_cod.get(c["cod"]) if "cod" in c else por_num.get(c["num"])
                if not u:
                    c["t"] = "falta"  # número del croquis que no existe en las unidades
                else:
                    e = est[u.id]
                    c.update(unit_id=u.id, codigo=u.codigo, tipo=_tipo_corto(u), tipologia=u.tipologia,
                             estado=e["estado"], limpieza=e["limpieza"],
                             ot=ot_unidad.get(u.id, [0, False])[0], urgente=ot_unidad.get(u.id, [0, False])[1])
                    if ve_res and e["reserva"]:
                        c["reserva"] = e["reserva"]
                    resumen[e["estado"]] += 1
            elif c["t"] == "zc":
                c.update(ot=ot_zona.get(c["zona"], [0, False])[0], urgente=ot_zona.get(c["zona"], [0, False])[1])
            celdas.append(c)
        resumen["total"] = sum(resumen.values())
        plantas.append({**pl, "celdas": celdas, "resumen": resumen})
    return {"asset": {"id": a.id, "codigo": a.codigo, "nombre": a.nombre}, "fecha": dia.isoformat(),
            "columnas": p["columnas"], "filas": p["filas"], "plantas": plantas,
            "puede": {"reservar": scope.can_asset("reservas.editar", asset_id),
                      "bloquear": _puede_bloquear(scope, asset_id),
                      "incidencia": scope.can_asset("mantenimiento.abrir", asset_id)
                      or scope.can_asset("mantenimiento.editar", asset_id),
                      "ver_reservas": ve_res, "ver_mantenimiento": ve_mto}}


def _puede_bloquear(scope: Scope, asset_id: int) -> bool:
    return scope.can_asset("reservas.editar", asset_id) or scope.can_asset("activos.editar", asset_id)


# --------------------------------------------------------------------------- ficha del apartamento
def _ot_out(w: WorkOrder, abierta: str | None) -> dict:
    return {"id": w.id, "titulo": w.titulo, "descripcion": w.descripcion, "estado": w.estado, "prioridad": w.prioridad,
            "categoria": w.categoria, "tipo": w.tipo, "fecha_apertura": w.fecha_apertura.isoformat(),
            "fecha_cierre": w.fecha_cierre.isoformat() if w.fecha_cierre else None, "solucion": w.solucion,
            "proveedor": w.proveedor, "abierta_por": abierta, "coste_real": float(w.coste_real) if w.coste_real else None}


def _ots(db: Session, cond) -> list[dict]:
    filas = db.execute(select(WorkOrder, User.nombre).outerjoin(User, User.id == WorkOrder.abierta_por)
                       .where(cond).order_by(WorkOrder.id.desc()).limit(300)).all()
    return [_ot_out(w, n) for w, n in filas]


@router.get("/unidades/{uid}/ficha")
def unit_sheet(uid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Todo lo registrado de un apartamento: estado, reservas y clientes, incidencias, bloqueos y facturas.
    Cada apartado solo aparece si el usuario tiene permiso para verlo."""
    u = get_or_404(db, Unit, uid)
    scope.require_asset("activos.ver", u.asset_id)
    hoy = date.today()
    e = estados(db, [u], hoy)[u.id]
    out = {"unidad": {**u.to_dict(), "tipo": _tipo_corto(u)}, "estado": e["estado"], "limpieza": e["limpieza"],
           "puede": {"reservar": scope.can_asset("reservas.editar", u.asset_id),
                     "bloquear": _puede_bloquear(scope, u.asset_id),
                     "incidencia": scope.can_asset("mantenimiento.abrir", u.asset_id)
                     or scope.can_asset("mantenimiento.editar", u.asset_id)}}
    if scope.can_asset("reservas.ver", u.asset_id):
        out["actual"] = e["reserva"]
        filas = db.execute(select(Reservation, Contact).join(Contact, Contact.id == Reservation.guest_id)
                           .where(Reservation.unit_id == uid).order_by(Reservation.fecha_entrada.desc()).limit(300)).all()
        contratos = set(db.scalars(select(AccommodationContract.reservation_id).where(
            AccommodationContract.reservation_id.in_([r.id for r, _ in filas] or [-1]))))
        out["reservas"] = [{"id": r.id, "localizador": r.localizador, "canal": r.canal, "estado": r.estado,
                            "entrada": r.fecha_entrada.isoformat(), "salida": r.fecha_salida.isoformat(),
                            "noches": (r.fecha_salida - r.fecha_entrada).days, "adultos": r.adultos, "ninos": r.ninos,
                            "importe_total": float(r.importe_total), "importe_pagado": float(r.importe_pagado),
                            "huesped": _nombre(g), "guest_id": g.id, "documento": g.documento_num,
                            "telefono": g.telefono, "email": g.email, "nacionalidad": g.nacionalidad,
                            "contrato": r.id in contratos, "notas": r.notas,
                            "proxima": r.fecha_entrada > hoy and r.estado == "confirmada"} for r, g in filas]
    if scope.can_asset("mantenimiento.ver", u.asset_id):
        out["incidencias"] = _ots(db, WorkOrder.unit_id == uid)
    out["bloqueos"] = [{"id": b.id, "motivo": b.motivo, "desde": b.desde.isoformat(),
                        "hasta": b.hasta.isoformat() if b.hasta else None, "usuario": n,
                        "levantado": b.levantado.isoformat() if b.levantado else None,
                        "nota_levantado": b.nota_levantado}
                       for b, n in db.execute(select(UnitBlock, User.nombre).outerjoin(User, User.id == UnitBlock.user_id)
                                              .where(UnitBlock.unit_id == uid).order_by(UnitBlock.id.desc()))]
    if scope.can_asset("facturas.ver", u.asset_id):
        out["facturas"] = [{"id": f.id, "codigo": f.codigo, "fecha": f.fecha_expedicion.isoformat(),
                            "cliente": f.cliente.get("nombre"), "total": float(f.total), "tipo": f.tipo}
                           for f in db.scalars(select(Invoice).join(Reservation, Reservation.id == Invoice.reservation_id)
                                               .where(Reservation.unit_id == uid).order_by(Invoice.id.desc()))]
    return out


@router.get("/{asset_id}/zonas/{zona}")
def common_area(asset_id: int, zona: str, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a, _ = _activo_plano(db, scope, asset_id)
    nombre = planos.zonas(a.codigo).get(zona)
    if not nombre:
        raise HTTPException(404, "Zona común no encontrada")
    out = {"zona": zona, "nombre": nombre,
           "puede": {"incidencia": scope.can_asset("mantenimiento.abrir", asset_id)
                     or scope.can_asset("mantenimiento.editar", asset_id)}}
    if scope.can_asset("mantenimiento.ver", asset_id):
        out["incidencias"] = _ots(db, (WorkOrder.asset_id == asset_id) & (WorkOrder.zona == zona))
    return out


# --------------------------------------------------------------------------- bloqueos
class BlockIn(BaseModel):
    motivo: str = Field(min_length=3)
    hasta: date | None = None


class UnblockIn(BaseModel):
    nota: str | None = None


@router.post("/unidades/{uid}/bloquear")
def block_unit(uid: int, data: BlockIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Saca el apartamento de venta con su motivo. Avisa de las reservas confirmadas que quedan afectadas."""
    u = get_or_404(db, Unit, uid)
    if not _puede_bloquear(scope, u.asset_id):
        raise HTTPException(403, "Sin permiso para bloquear apartamentos")
    if data.hasta and data.hasta < date.today():
        bad_request("La fecha prevista de fin no puede ser pasada")
    if u.estado in ESTADOS_BLOQUEO:
        bad_request(f"El apartamento ya está {u.estado.replace('_', ' ')}")
    alojado = db.scalar(select(Reservation.id).where(Reservation.unit_id == uid, Reservation.estado == "checkin"))
    if alojado:
        bad_request("Hay un huésped alojado: haga el check-out o cambie la reserva de apartamento antes de bloquear")
    afectadas_q = select(Reservation, Contact).join(Contact, Contact.id == Reservation.guest_id).where(
        Reservation.unit_id == uid, Reservation.estado == "confirmada", Reservation.fecha_salida > date.today())
    if data.hasta:
        afectadas_q = afectadas_q.where(Reservation.fecha_entrada <= data.hasta)
    afectadas = [{"id": r.id, "localizador": r.localizador, "huesped": _nombre(g), "entrada": r.fecha_entrada.isoformat(),
                  "salida": r.fecha_salida.isoformat()} for r, g in db.execute(afectadas_q.order_by(Reservation.fecha_entrada))]
    b = UnitBlock(unit_id=uid, motivo=data.motivo.strip(), hasta=data.hasta, user_id=scope.user.id)
    db.add(b)
    anterior = u.estado
    u.estado = "bloqueada"
    db.flush()
    audit(db, scope.user, "bloquear", "unidad", uid, {"motivo": b.motivo, "hasta": str(data.hasta) if data.hasta else None,
                                                     "estado_anterior": anterior, "reservas_afectadas": len(afectadas)})
    db.commit()
    return {"bloqueo": b.id, "estado": u.estado, "reservas_afectadas": afectadas}


@router.post("/unidades/{uid}/desbloquear")
def unblock_unit(uid: int, data: UnblockIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    u = get_or_404(db, Unit, uid)
    if not _puede_bloquear(scope, u.asset_id):
        raise HTTPException(403, "Sin permiso para desbloquear apartamentos")
    if u.estado == "mantenimiento":
        bad_request("Está bloqueado por una orden de trabajo: se desbloquea al cerrarla")
    if u.estado not in ("bloqueada", "fuera_servicio"):
        bad_request("El apartamento no está bloqueado")
    abiertos = list(db.scalars(select(UnitBlock).where(UnitBlock.unit_id == uid, UnitBlock.levantado.is_(None))))
    for b in abiertos:
        b.levantado, b.levantado_por, b.nota_levantado = datetime.now(), scope.user.id, data.nota
    u.estado = "disponible"
    audit(db, scope.user, "desbloquear", "unidad", uid, {"bloqueos": [b.id for b in abiertos], "nota": data.nota})
    db.commit()
    return {"estado": u.estado}
