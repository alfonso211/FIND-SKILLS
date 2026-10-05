"""Apartamentos turísticos: reservas, llegadas/salidas, disponibilidad y planning."""
import base64
import secrets
from html import escape
from urllib.parse import quote
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from .. import avisos, contratos, documentos, encuesta_ine, firma_contrato, importacion, planos, registro_viajeros
from ..facturacion import (IVA_ALOJAMIENTO, IVA_GENERAL, datos_cliente, dinero, emitir, linea, lineas_servicios,
                           serie_activo)
from ..models import (MODALIDADES_RESERVA, AccommodationContract, Asset, Contact, Invoice, Reservation,
                      ReservationGuest, Unit, User)
from ..schemas import (AccommodationContractIn, OccupantIn, Payment, ReservationIn, ReservationUpdate,
                       SendContractIn, SignatureIn)
from ..security import Scope, audit, get_scope
from ..utils import apply, bad_request, get_or_404, scoped
from .documentos import adjuntar_pendientes

router = APIRouter(prefix="/api/turistico", tags=["apartamentos turísticos"])

ESTADOS_RESERVA = {"confirmada", "checkin", "checkout", "cancelada", "no_show"}
ACTIVAS = ("confirmada", "checkin")
NO_ASIGNABLE = {"bloqueada", "fuera_servicio", "mantenimiento"}


def _res_out(r: Reservation) -> dict:
    d = r.to_dict()
    d["unidad"] = r.unit.codigo
    d["uso"] = r.unit.uso
    d["asset_id"] = r.unit.asset_id
    d["huesped"] = f"{r.guest.nombre} {r.guest.apellidos or ''}".strip()
    d["noches"] = (r.fecha_salida - r.fecha_entrada).days
    return d


def _conflict(db: Session, unit_id: int, ent: date, sal: date, exclude_id: int | None = None) -> bool:
    stmt = select(Reservation.id).where(
        Reservation.unit_id == unit_id, Reservation.estado.in_(ACTIVAS),
        Reservation.fecha_entrada < sal, Reservation.fecha_salida > ent)
    if exclude_id:
        stmt = stmt.where(Reservation.id != exclude_id)
    return db.scalar(stmt) is not None


def _tourist_unit(db: Session, unit_id: int) -> Unit:
    unit = get_or_404(db, Unit, unit_id)
    if unit.asset.modalidad not in MODALIDADES_RESERVA:
        bad_request("Este activo no admite reservas turísticas")
    if unit.estado in NO_ASIGNABLE:
        bad_request(f"La unidad {unit.codigo} está en estado '{unit.estado}' y no admite reservas")
    return unit


@router.get("/reservas")
def list_reservations(asset_id: int | None = None, desde: date | None = None, hasta: date | None = None,
                      estado: str | None = None, q: str | None = None,
                      scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ids = scope.asset_ids("reservas.ver")
    stmt = scoped(select(Reservation).join(Unit).join(Contact), Unit.asset_id, ids)
    if asset_id:
        stmt = stmt.where(Unit.asset_id == asset_id)
    if desde:
        stmt = stmt.where(Reservation.fecha_salida >= desde)
    if hasta:
        stmt = stmt.where(Reservation.fecha_entrada <= hasta)
    if estado:
        stmt = stmt.where(Reservation.estado == estado)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Reservation.localizador.ilike(like), Contact.nombre.ilike(like),
                              Contact.apellidos.ilike(like), Unit.codigo.ilike(like)))
    stmt = stmt.order_by(Reservation.fecha_entrada, Unit.codigo)
    return [_res_out(r) for r in db.scalars(stmt.limit(2000))]


@router.post("/reservas", status_code=201)
def create_reservation(data: ReservationIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    unit = _tourist_unit(db, data.unit_id)
    scope.require_asset("reservas.editar", unit.asset_id)
    if unit.capacidad and data.adultos + data.ninos > unit.capacidad:
        bad_request(f"Se supera la capacidad de la unidad ({unit.capacidad} plazas)")
    if _conflict(db, unit.id, data.fecha_entrada, data.fecha_salida):
        bad_request(f"La unidad {unit.codigo} ya está reservada en esas fechas")
    company_id = unit.asset.company_id
    if data.guest_id:
        guest = get_or_404(db, Contact, data.guest_id)
        if guest.company_id != company_id or guest.tipo != "huesped":
            bad_request("El huésped no pertenece a la sociedad del activo")
    elif data.guest:
        guest = Contact(company_id=company_id, tipo="huesped", **data.guest.model_dump())
        registro_viajeros.completar_municipio(guest)
        db.add(guest)
        db.flush()
    else:
        bad_request("Indique guest_id o los datos del huésped")
    if data.documentos:
        adjuntar_pendientes(db, scope.user, data.documentos, guest)
    r = Reservation(**data.model_dump(exclude={"guest", "guest_id", "documentos", "importe_pagado", "forma_pago"}),
                    guest_id=guest.id, importe_pagado=0)
    r.ocupantes.append(ReservationGuest(contact_id=guest.id, titular=True, orden=0))
    db.add(r)
    db.flush()
    audit(db, scope.user, "crear", "reserva", r.id,
          {"unidad": unit.codigo, "entrada": str(r.fecha_entrada), "salida": str(r.fecha_salida)})
    factura = None
    if data.importe_pagado:  # pagado al reservar: se registra el cobro y se factura
        factura = _cobrar(db, scope, r, Payment(importe=data.importe_pagado, forma_pago=data.forma_pago))
    db.commit()
    db.refresh(r)
    out = _res_out(r)
    if factura:
        out["factura"] = {"id": factura.id, "codigo": factura.codigo}
    return out


def _cobrar(db: Session, scope: Scope, r: Reservation, data: Payment):
    """Registra un cobro de la reserva y emite su factura."""
    pendiente = dinero(r.importe_total) - dinero(r.importe_pagado)
    if dinero(data.importe) > pendiente:
        bad_request(f"El cobro supera el importe pendiente de la reserva ({pendiente} €). "
                    "Si el importe total ha cambiado, corríjalo antes en la reserva.")
    u, a = r.unit, r.unit.asset
    lineas = []
    if data.importe:
        r.importe_pagado = dinero(r.importe_pagado) + dinero(data.importe)
        noches = (r.fecha_salida - r.fecha_entrada).days
        garaje = u.uso == "garaje"
        if garaje:  # alquiler de plaza de garaje: 21 %
            concepto = (f"Alquiler de plaza de garaje · {a.nombre} · {u.bloque or ''} plaza {planos.numero(u.codigo)} · "
                        f"{r.fecha_entrada:%d/%m/%Y} a {r.fecha_salida:%d/%m/%Y} ({noches} día{'s' if noches != 1 else ''})")
        else:
            concepto = (f"Alojamiento turístico · {a.nombre} · Apartamento {u.codigo} · "
                        f"{r.fecha_entrada:%d/%m/%Y} a {r.fecha_salida:%d/%m/%Y} ({noches} noche{'s' if noches != 1 else ''})"
                        f" · {r.adultos + r.ninos} huésped{'es' if r.adultos + r.ninos != 1 else ''}")
        concepto += f" · Reserva {r.localizador}" if r.localizador else f" · Reserva R-{r.id}"
        if dinero(data.importe) < pendiente:
            concepto = "Pago a cuenta · " + concepto
        lineas.append(linea("garaje", concepto, data.importe, IVA_GENERAL) if garaje
                      else linea("alojamiento", concepto, data.importe, IVA_ALOJAMIENTO))
    lineas += lineas_servicios(db, a.id, data.servicios)
    f = emitir(db, scope.user, company=a.company, serie=serie_activo(a), asset_id=a.id,
               cliente=datos_cliente(r.guest, data.facturar_a), contact_id=r.guest_id, lineas=lineas,
               fecha_operacion=data.fecha_pago or date.today(), forma_pago=data.forma_pago, reservation_id=r.id)
    audit(db, scope.user, "cobro", "reserva", r.id, {"importe": data.importe, "factura": f.codigo})
    return f


@router.post("/reservas/{rid}/cobro")
def register_payment(rid: int, data: Payment, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Cobro de una reserva: suma lo pagado y emite la factura (serie del activo)."""
    r = get_or_404(db, Reservation, rid)
    scope.require_asset("reservas.editar", r.unit.asset_id)
    f = _cobrar(db, scope, r, data)
    db.commit()
    return {**_res_out(r), "factura": {"id": f.id, "codigo": f.codigo}}


@router.put("/reservas/{rid}")
def update_reservation(rid: int, data: ReservationUpdate, scope: Scope = Depends(get_scope),
                       db: Session = Depends(get_db)):
    r = get_or_404(db, Reservation, rid)
    scope.require_asset("reservas.editar", r.unit.asset_id)
    if data.estado is not None and data.estado not in ESTADOS_RESERVA:
        bad_request("Estado de reserva no válido")
    unit_id = data.unit_id or r.unit_id
    if unit_id != r.unit_id:
        new_unit = _tourist_unit(db, unit_id)
        scope.require_asset("reservas.editar", new_unit.asset_id)
        if new_unit.asset.company_id != r.unit.asset.company_id:
            bad_request("No se puede mover una reserva a otra sociedad")
    ent = data.fecha_entrada or r.fecha_entrada
    sal = data.fecha_salida or r.fecha_salida
    if sal <= ent:
        bad_request("La fecha de salida debe ser posterior a la de entrada")
    if (data.estado or r.estado) in ACTIVAS and _conflict(db, unit_id, ent, sal, exclude_id=rid):
        bad_request("Conflicto con otra reserva en esas fechas")
    if data.importe_total is not None and dinero(data.importe_total) < dinero(r.importe_pagado):
        bad_request(f"El importe total no puede ser menor que lo ya cobrado ({dinero(r.importe_pagado)} €)")
    ch = apply(r, data)
    audit(db, scope.user, "editar", "reserva", rid, ch)
    db.commit()
    db.refresh(r)
    return _res_out(r)


@router.post("/reservas/{rid}/checkin")
def checkin(rid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r = get_or_404(db, Reservation, rid)
    scope.require_asset("reservas.editar", r.unit.asset_id)
    if r.estado != "confirmada":
        bad_request(f"No se puede hacer check-in de una reserva en estado '{r.estado}'")
    if r.fecha_entrada > date.today():
        bad_request("La fecha de entrada aún no ha llegado")
    if r.unit.uso != "garaje":
        problemas = _registro_incompleto(r)
        if problemas:
            bad_request("Registro de viajeros incompleto (obligatorio para el parte a SES.HOSPEDAJE): "
                        + "; ".join(problemas))
    r.estado = "checkin"
    r.unit.estado = "ocupada"
    audit(db, scope.user, "checkin", "reserva", rid)
    db.commit()
    return _res_out(r)


@router.post("/reservas/{rid}/checkout")
def checkout(rid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r = get_or_404(db, Reservation, rid)
    scope.require_asset("reservas.editar", r.unit.asset_id)
    if r.estado != "checkin":
        bad_request("Solo se puede hacer check-out de una reserva con check-in")
    r.estado = "checkout"
    r.unit.estado = "pendiente_limpieza"
    audit(db, scope.user, "checkout", "reserva", rid)
    db.commit()
    return _res_out(r)


@router.post("/reservas/{rid}/cancelar")
def cancel(rid: int, no_show: bool = False, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r = get_or_404(db, Reservation, rid)
    scope.require_asset("reservas.editar", r.unit.asset_id)
    if r.estado != "confirmada":
        bad_request("Solo se pueden cancelar reservas confirmadas")
    r.estado = "no_show" if no_show else "cancelada"
    audit(db, scope.user, r.estado, "reserva", rid)
    db.commit()
    return _res_out(r)


@router.get("/hoy")
def today(asset_id: int | None = None, fecha: date | None = None,
          scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Llegadas, salidas y alojados de un día (por defecto hoy)."""
    f = fecha or date.today()
    ids = scope.asset_ids("reservas.ver")
    base = scoped(select(Reservation).join(Unit), Unit.asset_id, ids)
    if asset_id:
        base = base.where(Unit.asset_id == asset_id)
    llegadas = db.scalars(base.where(Reservation.fecha_entrada == f, Reservation.estado.in_(ACTIVAS)))
    salidas = db.scalars(base.where(Reservation.fecha_salida == f, Reservation.estado.in_(("checkin", "checkout"))))
    alojados = db.scalars(base.where(Reservation.estado == "checkin"))
    return {"fecha": f.isoformat(),
            "llegadas": [_res_out(r) for r in llegadas],
            "salidas": [_res_out(r) for r in salidas],
            "alojados": [_res_out(r) for r in alojados]}


@router.get("/disponibilidad")
def availability(asset_id: int, desde: date, hasta: date, capacidad: int = 1, uso: str | None = None,
                 scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Unidades libres entre `desde` (entrada) y `hasta` (salida). Por defecto, alojamientos; con
    `uso=garaje`, plazas de garaje."""
    scope.require_asset("reservas.ver", asset_id)
    if hasta <= desde:
        bad_request("Rango de fechas no válido")
    busy = select(Reservation.unit_id).where(Reservation.estado.in_(ACTIVAS),
                                             Reservation.fecha_entrada < hasta, Reservation.fecha_salida > desde)
    stmt = select(Unit).where(Unit.asset_id == asset_id, Unit.estado.not_in(NO_ASIGNABLE),
                              Unit.id.not_in(busy), or_(Unit.capacidad.is_(None), Unit.capacidad >= capacidad),
                              Unit.uso == uso if uso else Unit.uso != "garaje")
    units = [u.to_dict() for u in db.scalars(stmt.order_by(Unit.bloque, Unit.codigo))]
    return {"libres": len(units), "unidades": units}


@router.get("/planning")
def planning(asset_id: int, desde: date | None = None, dias: int = Query(14, ge=1, le=62),
             bloque: str | None = None, uso: str | None = None, scope: Scope = Depends(get_scope),
             db: Session = Depends(get_db)):
    """Cuadro de ocupación unidad x día (alojamientos; las plazas de garaje con `uso=garaje` o su bloque)."""
    scope.require_asset("reservas.ver", asset_id)
    d0 = desde or date.today()
    d1 = d0 + timedelta(days=dias)
    ustmt = select(Unit).where(Unit.asset_id == asset_id)
    if bloque:
        ustmt = ustmt.where(Unit.bloque == bloque)
    elif uso:
        ustmt = ustmt.where(Unit.uso == uso)
    else:
        ustmt = ustmt.where(Unit.uso != "garaje")
    units = list(db.scalars(ustmt.order_by(Unit.bloque, Unit.codigo)))
    unit_ids = {u.id for u in units}
    res = db.scalars(select(Reservation).join(Unit).where(
        Unit.asset_id == asset_id, Reservation.estado.in_(("confirmada", "checkin", "checkout")),
        Reservation.fecha_entrada < d1, Reservation.fecha_salida > d0))
    by_unit: dict[int, list] = {}
    for r in res:
        if r.unit_id not in unit_ids:
            continue
        by_unit.setdefault(r.unit_id, []).append(
            {"id": r.id, "entrada": r.fecha_entrada.isoformat(), "salida": r.fecha_salida.isoformat(),
             "huesped": f"{r.guest.nombre} {r.guest.apellidos or ''}".strip(), "estado": r.estado})
    return {"desde": d0.isoformat(), "dias": dias,
            "unidades": [{"id": u.id, "codigo": u.codigo, "bloque": u.bloque, "estado": u.estado, "reservas": by_unit.get(u.id, [])}
                         for u in units]}


# --------------------------------------------------------------------------- ocupantes (registro de viajeros)
def _asegurar_titular(r: Reservation) -> None:
    if not any(o.titular for o in r.ocupantes):
        r.ocupantes.insert(0, ReservationGuest(contact_id=r.guest_id, titular=True, orden=0))


def _ocupante_out(o: ReservationGuest, r: Reservation) -> dict:
    c = o.contact
    d = c.to_dict(exclude=("iban", "notas"))
    return {"id": o.id, "titular": o.titular, "parentesco": o.parentesco, "contact": d,
            "nombre": f"{c.nombre} {c.apellidos or ''}".strip(),
            "edad": registro_viajeros.edad(c.fecha_nacimiento, r.fecha_entrada),
            "menor": registro_viajeros.es_menor(c.fecha_nacimiento, r.fecha_entrada),
            "faltan": registro_viajeros.faltan_persona(c, o.titular, o.parentesco, r.fecha_entrada)}


def _registro_incompleto(r: Reservation) -> list[str]:
    _asegurar_titular(r)
    out = []
    requeridos = r.adultos + r.ninos
    if len(r.ocupantes) < requeridos:
        out.append(f"faltan {requeridos - len(r.ocupantes)} ocupante(s) por registrar ({len(r.ocupantes)} de "
                   f"{requeridos})")
    elif len(r.ocupantes) > requeridos:
        out.append(f"hay {len(r.ocupantes)} ocupantes registrados y la reserva es para {requeridos}: "
                   "corrija adultos/niños")
    for o in r.ocupantes:
        f = registro_viajeros.faltan_persona(o.contact, o.titular, o.parentesco, r.fecha_entrada)
        if f:
            out.append(f"{o.contact.nombre} {o.contact.apellidos or ''}".strip() + ": " + ", ".join(f))
    return out


def ocupantes_texto(r: Reservation) -> str:
    """Relación de ocupantes para el contrato: nombre, documento (o edad del menor) y parentesco."""
    _asegurar_titular(r)
    lineas = []
    for o in r.ocupantes:
        c = o.contact
        nombre = f"{c.nombre} {c.apellidos or ''}".strip()
        if c.documento_num:
            doc = {"PAS": "Pasaporte"}.get(c.documento_tipo or "", c.documento_tipo or "Doc.")
            extra = f"{doc} {c.documento_num}"
        else:
            e = registro_viajeros.edad(c.fecha_nacimiento, r.fecha_entrada)
            extra = f"menor{f', {e} años' if e is not None else ''}, sin documento"
        if o.parentesco and registro_viajeros.es_menor(c.fecha_nacimiento, r.fecha_entrada):
            extra += f", {registro_viajeros.PARENTESCOS[o.parentesco].lower()} de un adulto de la reserva"
        lineas.append(f"{nombre} ({extra})")
    return "\n".join(lineas)


def _reserva_editable(db: Session, scope: Scope, rid: int) -> Reservation:
    r = get_or_404(db, Reservation, rid)
    scope.require_asset("reservas.editar", r.unit.asset_id)
    return r


@router.get("/reservas/{rid}/ocupantes")
def list_occupants(rid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r = get_or_404(db, Reservation, rid)
    scope.require_asset("reservas.ver", r.unit.asset_id)
    _asegurar_titular(r)
    db.commit()
    return {"requeridos": r.adultos + r.ninos, "adultos": r.adultos, "ninos": r.ninos,
            "ocupantes": [_ocupante_out(o, r) for o in r.ocupantes], "pendiente": _registro_incompleto(r),
            "parentescos": registro_viajeros.PARENTESCOS, "garaje": r.unit.uso == "garaje"}


@router.post("/reservas/{rid}/ocupantes", status_code=201)
def add_occupant(rid: int, data: OccupantIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Añade un ocupante: escaneado (copias en `documentos`) o registrado a mano (menores sin documento)."""
    r = _reserva_editable(db, scope, rid)
    _asegurar_titular(r)
    company_id = r.unit.asset.company_id
    if r.unit.capacidad and len(r.ocupantes) >= r.unit.capacidad:
        bad_request(f"El apartamento {r.unit.codigo} admite como máximo {r.unit.capacidad} personas")
    if data.contact_id:
        c = get_or_404(db, Contact, data.contact_id)
        if c.company_id != company_id or c.tipo != "huesped":
            bad_request("El huésped no pertenece a la sociedad del activo")
    elif data.contact:
        doc = (data.contact.documento_num or "").strip().upper() or None
        c = db.scalar(select(Contact).where(Contact.company_id == company_id, Contact.tipo == "huesped",
                                            Contact.documento_num == doc)) if doc else None
        if c is None:  # ficha nueva
            c = Contact(company_id=company_id, tipo="huesped", **data.contact.model_dump())
            db.add(c)
        else:  # el huésped ya estuvo alojado: se actualizan sus datos con los nuevos
            for k, v in data.contact.model_dump(exclude_unset=True).items():
                if v not in (None, ""):
                    setattr(c, k, v)
        registro_viajeros.completar_municipio(c)
        db.flush()
    else:
        bad_request("Indique los datos del ocupante")
    if any(o.contact_id == c.id for o in r.ocupantes):
        bad_request(f"{c.nombre} ya figura como ocupante de esta reserva")
    if data.documentos:
        adjuntar_pendientes(db, scope.user, data.documentos, c)
    if registro_viajeros.es_menor(c.fecha_nacimiento, r.fecha_entrada) and not data.parentesco:
        bad_request("Indique el parentesco del menor con un adulto de la reserva")
    o = ReservationGuest(contact_id=c.id, parentesco=data.parentesco,
                         orden=max((x.orden for x in r.ocupantes), default=0) + 1)
    r.ocupantes.append(o)
    total = len(r.ocupantes)
    if total > r.adultos + r.ninos:  # se ajusta la ocupación de la reserva
        if registro_viajeros.es_menor(c.fecha_nacimiento, r.fecha_entrada):
            r.ninos += 1
        else:
            r.adultos += 1
    db.flush()
    audit(db, scope.user, "añadir_ocupante", "reserva", r.id, {"tercero": c.id, "parentesco": data.parentesco})
    db.commit()
    return _ocupante_out(o, r)


@router.put("/reservas/{rid}/ocupantes/{oid}")
def update_occupant(rid: int, oid: int, data: OccupantIn, scope: Scope = Depends(get_scope),
                    db: Session = Depends(get_db)):
    r = _reserva_editable(db, scope, rid)
    o = get_or_404(db, ReservationGuest, oid)
    if o.reservation_id != r.id:
        bad_request("El ocupante no es de esta reserva")
    o.parentesco = data.parentesco
    if data.contact:
        for k, v in data.contact.model_dump(exclude_unset=True).items():
            setattr(o.contact, k, v)
        registro_viajeros.completar_municipio(o.contact)
    audit(db, scope.user, "editar_ocupante", "reserva", r.id, {"ocupante": oid})
    db.commit()
    return _ocupante_out(o, r)


@router.delete("/reservas/{rid}/ocupantes/{oid}")
def delete_occupant(rid: int, oid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r = _reserva_editable(db, scope, rid)
    o = get_or_404(db, ReservationGuest, oid)
    if o.reservation_id != r.id:
        bad_request("El ocupante no es de esta reserva")
    if o.titular:
        bad_request("El titular de la reserva no se puede quitar")
    r.ocupantes.remove(o)
    audit(db, scope.user, "quitar_ocupante", "reserva", r.id, {"tercero": o.contact_id})
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- parte de viajeros: SES.HOSPEDAJE
def _pago(db: Session, r: Reservation) -> tuple[str | None, date | None]:
    f = db.scalar(select(Invoice).where(Invoice.reservation_id == r.id, Invoice.tipo != "rectificativa")
                  .order_by(Invoice.id.desc()))
    return (f.forma_pago, f.fecha_operacion) if f else (None, None)


def _reservas_ses(db: Session, asset_id: int, desde: date, hasta: date) -> list[Reservation]:
    stmt = select(Reservation).join(Unit).where(
        Unit.asset_id == asset_id, Unit.uso != "garaje", Reservation.estado.in_(("confirmada", "checkin", "checkout")),
        Reservation.fecha_entrada >= desde, Reservation.fecha_entrada <= hasta)
    return list(db.scalars(stmt.order_by(Reservation.fecha_entrada, Unit.codigo)))


@router.get("/ses")
def ses_status(asset_id: int, desde: date | None = None, hasta: date | None = None,
               scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Estado del parte de viajeros de las llegadas de un periodo (por defecto, de ayer a mañana)."""
    scope.require_asset("reservas.ver", asset_id)
    a = get_or_404(db, Asset, asset_id)
    d0, d1 = desde or date.today() - timedelta(days=1), hasta or date.today() + timedelta(days=1)
    filas = []
    for r in _reservas_ses(db, asset_id, d0, d1):
        pend = _registro_incompleto(r)
        filas.append({**_res_out(r), "ocupantes_registrados": len(r.ocupantes), "pendiente": pend,
                      "completo": not pend, "ses_comunicado": r.ses_comunicado.isoformat() if r.ses_comunicado else None})
    db.commit()
    return {"activo": a.nombre, "codigo_establecimiento": a.ses_codigo_establecimiento, "desde": d0.isoformat(),
            "hasta": d1.isoformat(), "reservas": filas}


@router.post("/ses/partes.xml")
def ses_xml(asset_id: int, reservas: list[int], scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Fichero XML con los partes de viajeros de las reservas indicadas, para cargarlo en SES.HOSPEDAJE.
    Solo admite reservas con el registro completo. Las marca como comunicadas."""
    scope.require_asset("reservas.editar", asset_id)
    a = get_or_404(db, Asset, asset_id)
    if not a.ses_codigo_establecimiento:
        bad_request("Falta el código de establecimiento de SES.HOSPEDAJE en la ficha del activo")
    if not reservas:
        bad_request("Seleccione al menos una reserva")
    items = []
    for rid in reservas:
        r = get_or_404(db, Reservation, rid)
        if r.unit.asset_id != a.id or r.unit.uso == "garaje":
            bad_request(f"La reserva {r.localizador or r.id} no es de un apartamento de {a.nombre}")
        pend = _registro_incompleto(r)
        if pend:
            bad_request(f"Reserva {r.localizador or r.id}: " + "; ".join(pend))
        forma, fecha = _pago(db, r)
        items.append({"reserva": r, "ocupantes": [(o.contact, o.parentesco) for o in r.ocupantes],
                      "forma_pago": forma, "fecha_pago": fecha})
    xml = registro_viajeros.xml_partes(a.ses_codigo_establecimiento, items)
    ahora = datetime.now()
    for it in items:
        it["reserva"].ses_comunicado = ahora
    audit(db, scope.user, "parte_ses", "activo", a.id, {"reservas": reservas,
                                                         "viajeros": sum(len(i["ocupantes"]) for i in items)})
    db.commit()
    nombre = f"partes_SES_{a.codigo}_{ahora:%Y%m%d_%H%M}.xml"
    return Response(xml, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


# --------------------------------------------------------------------------- encuesta mensual del INE
def _ine(asset_id: int, anio: int, mes: int, scope: Scope, db: Session) -> dict:
    scope.require_asset("reservas.ver", asset_id)
    a = get_or_404(db, Asset, asset_id)
    if a.modalidad not in MODALIDADES_RESERVA:
        bad_request("La encuesta del INE es para los apartamentos turísticos")
    if not (1 <= mes <= 12 and 2000 <= anio <= 2100):
        bad_request("Mes no válido")
    return encuesta_ine.calcular(db, a, anio, mes)


@router.get("/ine")
def ine_survey(asset_id: int, anio: int, mes: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Datos del cuestionario mensual de la Encuesta de Ocupación en Apartamentos Turísticos del INE."""
    return _ine(asset_id, anio, mes, scope, db)


@router.get("/ine.xlsx")
def ine_survey_excel(asset_id: int, anio: int, mes: int, scope: Scope = Depends(get_scope),
                     db: Session = Depends(get_db)):
    datos = _ine(asset_id, anio, mes, scope, db)
    audit(db, scope.user, "encuesta_ine", "activo", asset_id, {"anio": anio, "mes": mes})
    db.commit()
    nombre = f"INE_apartamentos_{datos['activo'].replace(' ', '_')}_{anio}-{mes:02d}.xlsx"
    return Response(encuesta_ine.excel(datos), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


# --------------------------------------------------------------------------- importación desde Excel
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/importar/plantilla")
def import_template(scope: Scope = Depends(get_scope)):
    scope.require_any("reservas.editar")
    return Response(importacion.plantilla(), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="Plantilla_importar_reservas.xlsx"'})


@router.post("/importar")
def import_reservations(fichero: UploadFile = File(...), asset_id: int = Form(...), confirmar: bool = Form(False),
                        scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Importa reservas de un Excel o CSV. Sin `confirmar` solo comprueba y devuelve la vista previa, fila a fila.
    Con `confirmar` crea las reservas válidas; las filas con error no se importan. No registra cobros."""
    scope.require_asset("reservas.editar", asset_id)
    asset = get_or_404(db, Asset, asset_id)
    if asset.modalidad not in MODALIDADES_RESERVA:
        bad_request("Este activo no admite reservas turísticas")
    datos = fichero.file.read(10 * 1024 * 1024 + 1)
    if len(datos) > 10 * 1024 * 1024:
        bad_request("El fichero supera los 10 MB")
    try:
        filas, ignoradas = importacion.leer(datos, fichero.filename or "")
    except ValueError as e:
        bad_request(str(e))
    if len(filas) > 3000:
        bad_request("Máximo 3.000 reservas por fichero")

    unidades = {u.codigo.upper(): u for u in db.scalars(select(Unit).where(Unit.asset_id == asset_id))}
    existentes = set(db.scalars(select(Reservation.localizador).join(Unit).where(
        Unit.asset_id == asset_id, Reservation.localizador.is_not(None))))
    ocupadas: dict[int, list[tuple[date, date]]] = {}  # reservas del propio fichero, para detectar solapes entre filas
    libre = lambda uid, e, s: (not _conflict(db, uid, e, s)  # noqa: E731
                               and all(not (e < s2 and s > e2) for e2, s2 in ocupadas.get(uid, [])))
    resultado, creadas = [], 0
    for f in filas:
        r = {"fila": f["fila"], "localizador": str(f.get("localizador") or "").strip() or None}
        try:
            if "cancel" in importacion._norm(f.get("estado")) or "no show" in importacion._norm(f.get("estado")):
                r.update(estado="omitida", motivo="Reserva cancelada en el fichero")
                resultado.append(r)
                continue
            ent, sal = importacion.fecha(f.get("fecha_entrada")), importacion.fecha(f.get("fecha_salida"))
            if sal <= ent:
                raise ValueError("la salida debe ser posterior a la entrada")
            adultos, ninos = importacion.entero(f.get("adultos"), 1), importacion.entero(f.get("ninos"), 0)
            total = importacion.importe(f["importe_total"]) if f.get("importe_total") not in (None, "") else 0
            if r["localizador"] and r["localizador"] in existentes:
                r.update(estado="omitida", motivo="Ya existe una reserva con este localizador")
                resultado.append(r)
                continue
            codigo = str(f.get("unidad") or "").strip().upper()
            if codigo:
                u = unidades.get(codigo)
                if not u:
                    raise ValueError(f"la unidad {codigo} no existe en {asset.nombre}")
                if u.estado in NO_ASIGNABLE:
                    raise ValueError(f"la unidad {u.codigo} está en estado «{u.estado}»")
                if u.capacidad and adultos + ninos > u.capacidad:
                    raise ValueError(f"supera la capacidad de {u.codigo} ({u.capacidad} plazas)")
                if not libre(u.id, ent, sal):
                    raise ValueError(f"{u.codigo} ya está reservada en esas fechas")
                r["asignada"] = False
            else:  # sin unidad: la primera libre con capacidad
                u = next((x for x in sorted(unidades.values(), key=lambda x: (x.bloque or "", x.codigo))
                          if x.uso != "garaje" and x.estado not in NO_ASIGNABLE and (not x.capacidad or x.capacidad >= adultos + ninos)
                          and libre(x.id, ent, sal)), None)
                if not u:
                    raise ValueError("no queda ningún apartamento libre para esas fechas y ocupación")
                r["asignada"] = True
            nombre = str(f.get("nombre") or "").strip()
            if not nombre:
                raise ValueError("falta el nombre del huésped")
            ocupadas.setdefault(u.id, []).append((ent, sal))
            if r["localizador"]:
                existentes.add(r["localizador"])
            r.update(estado="valida", unidad=u.codigo, entrada=ent.isoformat(), salida=sal.isoformat(),
                     huesped=f"{nombre} {f.get('apellidos') or ''}".strip(), importe_total=total,
                     adultos=adultos, ninos=ninos)
            if confirmar:
                doc = str(f.get("documento_num") or "").strip().upper() or None
                g = db.scalar(select(Contact).where(Contact.company_id == asset.company_id, Contact.tipo == "huesped",
                                                    Contact.documento_num == doc)) if doc else None
                if g is None:
                    g = Contact(company_id=asset.company_id, tipo="huesped", nombre=nombre[:120],
                                apellidos=(str(f.get("apellidos") or "").strip() or None),
                                documento_num=doc, nacionalidad=(str(f.get("nacionalidad") or "").strip() or None),
                                email=(str(f.get("email") or "").strip() or None),
                                telefono=(str(f.get("telefono") or "").strip() or None))
                    db.add(g)
                    db.flush()
                nueva = Reservation(unit_id=u.id, guest_id=g.id, localizador=r["localizador"],
                                    canal=importacion.canal(f.get("canal")), fecha_entrada=ent, fecha_salida=sal,
                                    adultos=adultos, ninos=ninos, importe_total=total,
                                    notas=(str(f.get("notas") or "").strip() or None))
                nueva.ocupantes.append(ReservationGuest(contact_id=g.id, titular=True, orden=0))
                db.add(nueva)
                db.flush()
                creadas += 1
                r["estado"] = "importada"
        except (ValueError, KeyError) as e:
            r.update(estado="error", motivo=str(e)[:1].upper() + str(e)[1:])
        resultado.append(r)
    cuenta = lambda e: sum(1 for x in resultado if x["estado"] == e)  # noqa: E731
    if confirmar:
        audit(db, scope.user, "importar_reservas", "reserva", None,
              {"activo": asset.codigo, "fichero": fichero.filename, "importadas": creadas, "errores": cuenta("error")})
        db.commit()
    return {"filas": resultado, "validas": cuenta("valida") + cuenta("importada"), "importadas": creadas,
            "errores": cuenta("error"), "omitidas": cuenta("omitida"), "columnas_ignoradas": ignoradas}


# --------------------------------------------------------------------------- contrato de alojamiento
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _apartamento(u: Unit) -> dict:
    """Portal/bloque, planta y número tal como se escriben en el contrato (P1-1A -> Portal 1, planta 1, nº A)."""
    etiqueta, bloque = (u.bloque.split(" ", 1) + [""])[:2] if u.bloque else ("", "")
    numero = u.codigo.split("-")[-1]
    if u.planta and numero.startswith(u.planta) and numero[len(u.planta):].isalpha():
        numero = numero[len(u.planta):]
    return {"etiqueta_bloque": etiqueta or None, "portal": bloque or None, "planta": u.planta, "numero": numero}


def _prefill(r: Reservation, db: Session) -> dict:
    u, a, g = r.unit, r.unit.asset, r.guest
    ultimo = db.scalar(select(AccommodationContract).where(AccommodationContract.reservation_id == r.id)
                       .order_by(AccommodationContract.id.desc()))
    base = {
        "fecha_firma": date.today().isoformat(),
        "localizador": r.localizador or f"R-{r.id}",
        "representante": a.contrato_representante, "representante_dni": a.contrato_representante_dni,
        "email_empresa": a.contrato_email,
        "cliente_nombre": f"{g.nombre} {g.apellidos or ''}".strip(), "cliente_nacionalidad": g.nacionalidad,
        "cliente_documento": g.documento_num, "cliente_domicilio": g.direccion, "cliente_cp": g.cp,
        "cliente_municipio": g.municipio, "cliente_pais": g.pais, "cliente_email": g.email,
        "cliente_movil": g.telefono,
        "capacidad": u.capacidad, "dormitorios": u.dormitorios,
        "precio_total": float(r.importe_total) if r.importe_total else None,
        "ocupantes": ocupantes_texto(r),
        "motivo": [], "acreditacion": [],
    }
    # datos ya tecleados: borrador guardado en la reserva o, si no hay, la última impresión
    guardado = r.datos_contrato or (ultimo.datos if ultimo else None)
    if guardado:
        base.update({k: v for k, v in guardado.items()
                     if k in AccommodationContractIn.model_fields and v not in (None, "", [])
                     and k not in ("permitir_huecos", "solo_guardar")})
        base["fecha_firma"] = date.today().isoformat()
        base["motivo"] = AccommodationContractIn._lista(base.get("motivo"))
        base["acreditacion"] = AccommodationContractIn._lista(base.get("acreditacion"))
    if r.importe_total:  # el precio manda la reserva
        base["precio_total"] = float(r.importe_total)
    base["ocupantes"] = ocupantes_texto(r)  # siempre la relación registrada (la misma que va a SES)
    return base


def _datos_plantilla(r: Reservation, c: AccommodationContractIn) -> dict:
    d = c.model_dump()
    d.update(_apartamento(r.unit))
    d["registro_turistico"] = r.unit.asset.num_registro_turistico
    d["ocupantes"] = ocupantes_texto(r)
    f = contratos.fecha_es(c.fecha_firma)
    d.update(firma_dia=f["dia"], firma_mes=f["mes"], firma_anio=f["anio"])
    for pref, fecha in (("entrada", r.fecha_entrada), ("salida", r.fecha_salida)):
        d.update({f"{pref}_dia": f"{fecha.day:02d}", f"{pref}_mes": f"{fecha.month:02d}", f"{pref}_anio": fecha.year})
    d["noches"] = (r.fecha_salida - r.fecha_entrada).days
    if c.tarjeta_caducidad:
        d["tarjeta_cad_mes"], d["tarjeta_cad_anio"] = c.tarjeta_caducidad.split("/")
    # lo que no procede se omite en lugar de dejar puntos
    d["no_aplica"] = {campo for campo, lista in (("motivo_otro", c.motivo), ("acreditacion_otro", c.acreditacion))
                      if "otro" not in lista}
    return d


def _contrato_reserva(rid: int, perm: str, scope: Scope, db: Session) -> tuple[Reservation, object]:
    r = get_or_404(db, Reservation, rid)
    scope.require_asset(perm, r.unit.asset_id)
    if r.unit.uso == "garaje":
        bad_request("Las plazas de garaje no llevan contrato de alojamiento")
    ruta = contratos.plantilla(r.unit.asset.codigo)
    if not ruta:
        bad_request("Este activo no tiene modelo de contrato de alojamiento")
    return r, ruta


def _descarga(contenido: bytes, r: Reservation) -> Response:
    nombre = f"Contrato_{(r.localizador or f'R-{r.id}').replace(' ', '_')}_{r.unit.codigo}.docx"
    return Response(contenido, media_type=DOCX, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


def _guardar_datos_contrato(r: Reservation, data: AccommodationContractIn) -> None:
    """Guarda lo tecleado en la reserva y, si se pide, completa la ficha del cliente y de la unidad."""
    r.datos_contrato = data.model_dump(mode="json", exclude={"permitir_huecos", "solo_guardar"})
    if data.actualizar_huesped:
        g = r.guest
        for campo, valor in (("nacionalidad", data.cliente_nacionalidad), ("documento_num", data.cliente_documento),
                             ("direccion", data.cliente_domicilio), ("cp", data.cliente_cp),
                             ("municipio", data.cliente_municipio), ("pais", data.cliente_pais),
                             ("email", data.cliente_email), ("telefono", data.cliente_movil)):
            if valor:
                setattr(g, campo, valor)
        registro_viajeros.completar_municipio(g)
    u = r.unit  # capacidad y dormitorios: se completan en la unidad si aún no constaban
    if data.capacidad and not u.capacidad:
        u.capacidad = data.capacidad
    if data.dormitorios is not None and u.dormitorios is None:
        u.dormitorios = data.dormitorios


@router.get("/reservas/{rid}/contrato")
def contract_form(rid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Datos propuestos para el contrato e historial de contratos impresos de la reserva."""
    r, _ = _contrato_reserva(rid, "reservas.ver", scope, db)
    historial = db.execute(select(AccommodationContract, User.nombre)
                           .outerjoin(User, User.id == AccommodationContract.user_id)
                           .where(AccommodationContract.reservation_id == rid)
                           .order_by(AccommodationContract.id.desc())).all()
    return {"datos": _prefill(r, db), "motivos": contratos.MOTIVOS, "acreditaciones": contratos.ACREDITACIONES,
            "historial": [{"id": c.id, "creado": c.creado.isoformat(), "usuario": n,
                           "firmado": c.firmado.isoformat() if c.firmado else None, "envios": c.envios or []}
                          for c, n in historial if c.firmado or c.fichero is None],
            "firma_disponible": firma_contrato.disponible()}


@router.post("/reservas/{rid}/contrato")
def contract_print(rid: int, data: AccommodationContractIn, scope: Scope = Depends(get_scope),
                   db: Session = Depends(get_db)):
    """Guarda los datos del contrato en la reserva y, salvo `solo_guardar`, genera el .docx para imprimir.
    Si falta algún dato o casilla no se imprime (el cliente solo debe firmar), salvo `permitir_huecos`."""
    r, ruta = _contrato_reserva(rid, "reservas.editar", scope, db)
    contenido, pendientes = contratos.rellenar(ruta, _datos_plantilla(r, data))
    faltan = contratos.faltan(pendientes)
    if not data.motivo:
        faltan.append("Motivo de la estancia (marque al menos una casilla)")
    if not data.acreditacion:
        faltan.append("Acreditación del domicilio (marque al menos una casilla)")

    _guardar_datos_contrato(r, data)

    if data.solo_guardar:
        audit(db, scope.user, "guardar_contrato", "reserva", r.id, {"faltan": faltan})
        db.commit()
        return {"guardado": True, "faltan": faltan}
    if faltan and not data.permitir_huecos:
        db.commit()  # los datos tecleados no se pierden
        bad_request("Faltan datos para que el cliente solo tenga que firmar: " + "; ".join(faltan))

    c = AccommodationContract(reservation_id=r.id, plantilla=ruta.name, datos=r.datos_contrato,
                              user_id=scope.user.id)
    db.add(c)
    db.flush()
    audit(db, scope.user, "imprimir_contrato", "reserva", r.id, {"contrato": c.id, "huecos_a_mano": faltan})
    db.commit()
    resp = _descarga(contenido, r)
    resp.headers["X-Huecos-Pendientes"] = str(len(pendientes))
    return resp


@router.get("/reservas/{rid}/contrato/{cid}")
def contract_reprint(rid: int, cid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Reimprime un contrato ya generado, con los mismos datos."""
    r, ruta = _contrato_reserva(rid, "reservas.ver", scope, db)
    c = get_or_404(db, AccommodationContract, cid)
    if c.reservation_id != rid:
        bad_request("El contrato no pertenece a esta reserva")
    contenido, _ = contratos.rellenar(ruta, _datos_plantilla(r, AccommodationContractIn(**c.datos)))
    return _descarga(contenido, r)


# --------------------------------------------------------------------------- firma en tablet y envío al cliente
def _faltan_contrato(r: Reservation, data: AccommodationContractIn, pendientes: list[str]) -> list[str]:
    faltan = contratos.faltan(pendientes)
    if not data.motivo:
        faltan.append("Motivo de la estancia (marque al menos una casilla)")
    if not data.acreditacion:
        faltan.append("Acreditación del domicilio (marque al menos una casilla)")
    return faltan


def _contrato_de(db: Session, r: Reservation, cid: int) -> AccommodationContract:
    c = get_or_404(db, AccommodationContract, cid)
    if c.reservation_id != r.id:
        bad_request("El contrato no pertenece a esta reserva")
    return c


def _nombre_pdf(r: Reservation) -> str:
    return f"Contrato_{(r.localizador or f'R-{r.id}').replace(' ', '_')}_{r.unit.codigo}_firmado.pdf"


def _enlace(c: AccommodationContract, request: Request) -> str:
    """Enlace personal de descarga del contrato firmado (caduca a los 7 días). Sustituye al anterior."""
    token = secrets.token_urlsafe(24)
    c.token_hash = documentos.huella(token.encode())
    c.token_expira = datetime.now() + timedelta(days=firma_contrato.VALIDEZ_ENLACE_DIAS)
    base = settings.url or str(request.base_url).rstrip("/")
    return f"{base}/api/publico/contrato/{token}"


def _correo_cliente(r: Reservation, nombre: str, enlace: str) -> tuple[str, str, str]:
    a = r.unit.asset
    asunto = f"Su contrato de alojamiento · {a.nombre} · {r.localizador or f'R-{r.id}'}"
    texto = (f"Estimado/a {nombre}:\n\nAdjuntamos el contrato de alojamiento que ha firmado en {a.nombre} "
             f"(apartamento {r.unit.codigo}, del {r.fecha_entrada:%d/%m/%Y} al {r.fecha_salida:%d/%m/%Y}).\n"
             f"También puede descargarlo durante {firma_contrato.VALIDEZ_ENLACE_DIAS} días en: {enlace}\n\n"
             f"Gracias por su confianza.\n{a.company.nombre}")
    html = (f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1a1a1c;max-width:640px">'
            f'<div style="background:#0e0e10;padding:16px 22px;border-bottom:3px solid #c9a45a;color:#fff;'
            f'font-size:17px;letter-spacing:3px">{escape(a.nombre.upper())}</div><div style="padding:20px 22px">'
            f'<p>Estimado/a {escape(nombre)}:</p><p>Adjuntamos el contrato de alojamiento que ha firmado '
            f'(apartamento <b>{escape(r.unit.codigo)}</b>, del {r.fecha_entrada:%d/%m/%Y} al '
            f'{r.fecha_salida:%d/%m/%Y}).</p><p><a href="{escape(enlace)}" style="background:#c9a45a;color:#0e0e10;'
            f'padding:9px 16px;border-radius:8px;text-decoration:none;font-weight:600">Descargar el contrato</a></p>'
            f'<p style="color:#8d877b;font-size:12px">El enlace caduca a los {firma_contrato.VALIDEZ_ENLACE_DIAS} días. '
            f'{escape(a.company.nombre)}{" · " + escape(a.contrato_email) if a.contrato_email else ""}</p></div></div>')
    return asunto, texto, html


def _enviar(db: Session, scope: Scope, r: Reservation, c: AccommodationContract, canal: str, destino: str,
            request: Request) -> dict:
    nombre = (c.evidencias or {}).get("firmante") or r.guest.nombre
    enlace = _enlace(c, request)
    envio = {"canal": canal, "destino": destino, "fecha": datetime.now().isoformat(timespec="seconds"),
             "usuario": scope.user.nombre}
    out: dict = {"canal": canal}
    if canal == "email":
        if not avisos.configurado():
            bad_request("El correo no está configurado en el servidor: envíelo por WhatsApp")
        asunto, texto, html = _correo_cliente(r, nombre, enlace)
        try:
            avisos.enviar(destino, asunto, texto, html,
                          [(_nombre_pdf(r), documentos.leer(c.fichero), "application/pdf")])
        except Exception as e:  # noqa: BLE001
            bad_request(f"No se ha podido enviar el correo: {str(e)[:200]}")
        out["enviado"] = True
    else:
        movil = firma_contrato.movil_whatsapp(destino)
        if not movil:
            bad_request("Móvil no válido para WhatsApp (indique el prefijo del país si no es español)")
        texto = (f"Hola {nombre}, aquí tiene su contrato de alojamiento en {r.unit.asset.nombre} "
                 f"(apartamento {r.unit.codigo}). Puede descargarlo durante {firma_contrato.VALIDEZ_ENLACE_DIAS} "
                 f"días: {enlace}")
        out["whatsapp"] = f"https://wa.me/{movil}?text={quote(texto)}"
        envio["destino"] = movil
    c.envios = [*(c.envios or []), envio]
    audit(db, scope.user, "enviar_contrato", "reserva", r.id, {"contrato": c.id, "canal": canal,
                                                               "destino": envio["destino"]})
    return out


@router.post("/reservas/{rid}/contrato/firma")
def contract_sign_prepare(rid: int, data: AccommodationContractIn, scope: Scope = Depends(get_scope),
                          db: Session = Depends(get_db)):
    """Prepara el contrato para firmarlo en la tablet: comprueba que esté completo y devuelve sus páginas."""
    r, ruta = _contrato_reserva(rid, "reservas.editar", scope, db)
    if not firma_contrato.disponible():
        bad_request("El servidor no tiene instalado el conversor a PDF (LibreOffice): imprima el contrato")
    _guardar_datos_contrato(r, data)
    faltan = _faltan_contrato(r, data, contratos.rellenar(ruta, _datos_plantilla(r, data))[1])
    faltan += _registro_incompleto(r)
    db.commit()
    if faltan:
        bad_request("Para firmar en la tablet el contrato debe estar completo: " + "; ".join(faltan))
    contenido, _ = contratos.rellenar(ruta, _datos_plantilla(r, data))
    try:
        pdf = firma_contrato.a_pdf(contenido)
    except RuntimeError as e:
        bad_request(str(e))
    # contrato pendiente de firma: el PDF que ve el cliente queda guardado (cifrado) para la evidencia
    c = AccommodationContract(reservation_id=r.id, plantilla=ruta.name, datos=r.datos_contrato,
                              user_id=scope.user.id, fichero=documentos.guardar(pdf),
                              evidencias={"sha256_contrato": documentos.huella(pdf)})
    db.add(c)
    db.flush()
    audit(db, scope.user, "preparar_firma", "reserva", r.id, {"contrato": c.id})
    db.commit()
    paginas = ["data:image/png;base64," + base64.b64encode(p).decode() for p in firma_contrato.paginas_png(pdf)]
    return {"contrato_id": c.id, "paginas": paginas, "cliente": data.cliente_nombre,
            "email": data.cliente_email, "movil": data.cliente_movil}


@router.post("/reservas/{rid}/contrato/{cid}/firmar")
def contract_sign(rid: int, cid: int, data: SignatureIn, request: Request, scope: Scope = Depends(get_scope),
                  db: Session = Depends(get_db)):
    """Firma del cliente: incrusta la firma, añade la página de evidencias, guarda el PDF cifrado y lo envía."""
    r, ruta = _contrato_reserva(rid, "reservas.editar", scope, db)
    c = _contrato_de(db, r, cid)
    if c.firmado:
        bad_request("Este contrato ya está firmado")
    if not c.fichero:
        bad_request("Prepare antes el contrato para la firma")
    if not (data.acepta and data.acepta_privacidad):
        bad_request("El cliente debe aceptar el contrato y la información de protección de datos")
    try:
        firma = firma_contrato.imagen_firma(data.firma)
    except ValueError as e:
        bad_request(str(e))
    datos = AccommodationContractIn(**c.datos)
    contenido, _ = contratos.rellenar(ruta, _datos_plantilla(r, datos))
    try:
        firmado = firma_contrato.a_pdf(firma_contrato.insertar_firma(contenido, firma))
    except RuntimeError as e:
        bad_request(str(e))
    utc, local, utc_txt = firma_contrato.ahora()
    ev = {**(c.evidencias or {}), "documento": f"Contrato de alojamiento {datos.localizador or r.id} · "
                                               f"{r.unit.asset.nombre} · apartamento {r.unit.codigo}",
          "firmante": datos.cliente_nombre, "documento_firmante": datos.cliente_documento,
          "fecha_local": local, "fecha_utc": utc_txt,
          "dispositivo": (request.headers.get("user-agent") or "")[:300],
          "ip": request.client.host if request.client else "", "empleado": scope.user.nombre,
          "sha256_firma": documentos.huella(firma), "acepta": True, "acepta_privacidad": True}
    final = firma_contrato.unir(firmado, firma_contrato.pagina_evidencias(
        ev, firma, r.unit.asset.codigo, r.unit.asset.company.cif))
    documentos.borrar(c.fichero)  # el borrador sin firmar ya no hace falta (su huella queda en las evidencias)
    c.fichero, c.sha256, c.evidencias, c.firmado = documentos.guardar(final), documentos.huella(final), ev, datetime.now()
    g = r.guest
    if data.email and not g.email:
        g.email = data.email
    if data.movil and not g.telefono:
        g.telefono = data.movil
    audit(db, scope.user, "firmar_contrato", "reserva", r.id, {"contrato": c.id, "sha256": c.sha256})
    db.flush()
    out = {"contrato_id": c.id, "sha256": c.sha256, "envios": []}
    for canal, destino in (("email", data.email), ("whatsapp", data.movil)):
        if not destino:
            continue
        try:
            out["envios"].append(_enviar(db, scope, r, c, canal, destino, request))
        except HTTPException as e:
            out["envios"].append({"canal": canal, "error": e.detail})
    db.commit()
    return out


@router.post("/reservas/{rid}/contrato/{cid}/enviar")
def contract_send(rid: int, cid: int, data: SendContractIn, request: Request, scope: Scope = Depends(get_scope),
                  db: Session = Depends(get_db)):
    r, _ = _contrato_reserva(rid, "reservas.editar", scope, db)
    c = _contrato_de(db, r, cid)
    if not c.firmado:
        bad_request("El contrato aún no está firmado")
    out = _enviar(db, scope, r, c, data.canal, data.destino, request)
    db.commit()
    return out


@router.get("/reservas/{rid}/contrato/{cid}/pdf")
def contract_signed_pdf(rid: int, cid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r, _ = _contrato_reserva(rid, "reservas.ver", scope, db)
    c = _contrato_de(db, r, cid)
    if not c.firmado:
        bad_request("El contrato aún no está firmado")
    audit(db, scope.user, "ver_contrato_firmado", "reserva", r.id, {"contrato": c.id})
    db.commit()
    return Response(documentos.leer(c.fichero), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{_nombre_pdf(r)}"'})


publico = APIRouter(prefix="/api/publico", tags=["público"])


@publico.get("/contrato/{token}")
def public_contract(token: str, db: Session = Depends(get_db)):
    """Descarga del contrato firmado por el cliente con su enlace personal (sin usuario; caduca a los 7 días)."""
    c = db.scalar(select(AccommodationContract).where(
        AccommodationContract.token_hash == documentos.huella(token.encode())))
    if not c or not c.firmado or not c.token_expira or c.token_expira < datetime.now():
        raise HTTPException(404, "El enlace no es válido o ha caducado. Solicite uno nuevo en recepción.")
    r = db.get(Reservation, c.reservation_id)
    return Response(documentos.leer(c.fichero), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{_nombre_pdf(r)}"',
                             "Cache-Control": "private, no-store", "X-Robots-Tag": "noindex"})
