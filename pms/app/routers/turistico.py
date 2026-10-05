"""Apartamentos turísticos: reservas, llegadas/salidas, disponibilidad y planning."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from .. import contratos, importacion
from ..facturacion import IVA_ALOJAMIENTO, datos_cliente, dinero, emitir, linea, lineas_servicios, serie_activo
from ..models import MODALIDADES_RESERVA, AccommodationContract, Asset, Contact, Reservation, Unit, User
from ..schemas import AccommodationContractIn, Payment, ReservationIn, ReservationUpdate
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
        db.add(guest)
        db.flush()
    else:
        bad_request("Indique guest_id o los datos del huésped")
    if data.documentos:
        adjuntar_pendientes(db, scope.user, data.documentos, guest)
    r = Reservation(**data.model_dump(exclude={"guest", "guest_id", "documentos", "importe_pagado", "forma_pago"}),
                    guest_id=guest.id, importe_pagado=0)
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
        concepto = (f"Alojamiento turístico · {a.nombre} · Apartamento {u.codigo} · "
                    f"{r.fecha_entrada:%d/%m/%Y} a {r.fecha_salida:%d/%m/%Y} ({noches} noche{'s' if noches != 1 else ''})"
                    f" · {r.adultos + r.ninos} huésped{'es' if r.adultos + r.ninos != 1 else ''}"
                    + (f" · Reserva {r.localizador}" if r.localizador else f" · Reserva R-{r.id}"))
        if dinero(data.importe) < pendiente:
            concepto = "Pago a cuenta · " + concepto
        lineas.append(linea("alojamiento", concepto, data.importe, IVA_ALOJAMIENTO))
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
    g = r.guest
    if not (g.documento_num and g.nacionalidad and g.fecha_nacimiento):
        bad_request("Faltan datos del huésped para el parte de viajeros (documento, nacionalidad, fecha nacimiento)")
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
def availability(asset_id: int, desde: date, hasta: date, capacidad: int = 1,
                 scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Unidades libres entre `desde` (entrada) y `hasta` (salida)."""
    scope.require_asset("reservas.ver", asset_id)
    if hasta <= desde:
        bad_request("Rango de fechas no válido")
    busy = select(Reservation.unit_id).where(Reservation.estado.in_(ACTIVAS),
                                             Reservation.fecha_entrada < hasta, Reservation.fecha_salida > desde)
    stmt = select(Unit).where(Unit.asset_id == asset_id, Unit.estado.not_in(NO_ASIGNABLE),
                              Unit.id.not_in(busy), or_(Unit.capacidad.is_(None), Unit.capacidad >= capacidad))
    units = [u.to_dict() for u in db.scalars(stmt.order_by(Unit.bloque, Unit.codigo))]
    return {"libres": len(units), "unidades": units}


@router.get("/planning")
def planning(asset_id: int, desde: date | None = None, dias: int = Query(14, ge=1, le=62),
             bloque: str | None = None, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Cuadro de ocupación unidad x día."""
    scope.require_asset("reservas.ver", asset_id)
    d0 = desde or date.today()
    d1 = d0 + timedelta(days=dias)
    ustmt = select(Unit).where(Unit.asset_id == asset_id)
    if bloque:
        ustmt = ustmt.where(Unit.bloque == bloque)
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
                          if x.estado not in NO_ASIGNABLE and (not x.capacidad or x.capacidad >= adultos + ninos)
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
                db.add(Reservation(unit_id=u.id, guest_id=g.id, localizador=r["localizador"],
                                   canal=importacion.canal(f.get("canal")), fecha_entrada=ent, fecha_salida=sal,
                                   adultos=adultos, ninos=ninos, importe_total=total,
                                   notas=(str(f.get("notas") or "").strip() or None)))
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
        "ocupantes": " ".join(x for x in (g.nombre, g.apellidos, f"({g.documento_tipo or 'doc.'} {g.documento_num})"
                                          if g.documento_num else None) if x),
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
    return base


def _datos_plantilla(r: Reservation, c: AccommodationContractIn) -> dict:
    d = c.model_dump()
    d.update(_apartamento(r.unit))
    d["registro_turistico"] = r.unit.asset.num_registro_turistico
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
    ruta = contratos.plantilla(r.unit.asset.codigo)
    if not ruta:
        bad_request("Este activo no tiene modelo de contrato de alojamiento")
    return r, ruta


def _descarga(contenido: bytes, r: Reservation) -> Response:
    nombre = f"Contrato_{(r.localizador or f'R-{r.id}').replace(' ', '_')}_{r.unit.codigo}.docx"
    return Response(contenido, media_type=DOCX, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@router.get("/reservas/{rid}/contrato")
def contract_form(rid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Datos propuestos para el contrato e historial de contratos impresos de la reserva."""
    r, _ = _contrato_reserva(rid, "reservas.ver", scope, db)
    historial = db.execute(select(AccommodationContract, User.nombre)
                           .outerjoin(User, User.id == AccommodationContract.user_id)
                           .where(AccommodationContract.reservation_id == rid)
                           .order_by(AccommodationContract.id.desc())).all()
    return {"datos": _prefill(r, db), "motivos": contratos.MOTIVOS, "acreditaciones": contratos.ACREDITACIONES,
            "historial": [{"id": c.id, "creado": c.creado.isoformat(), "usuario": n} for c, n in historial]}


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

    r.datos_contrato = data.model_dump(mode="json", exclude={"permitir_huecos", "solo_guardar"})
    if data.actualizar_huesped:
        g = r.guest
        for campo, valor in (("nacionalidad", data.cliente_nacionalidad), ("documento_num", data.cliente_documento),
                             ("direccion", data.cliente_domicilio), ("cp", data.cliente_cp),
                             ("municipio", data.cliente_municipio), ("pais", data.cliente_pais),
                             ("email", data.cliente_email), ("telefono", data.cliente_movil)):
            if valor:
                setattr(g, campo, valor)
    u = r.unit  # capacidad y dormitorios: se completan en la unidad si aún no constaban
    if data.capacidad and not u.capacidad:
        u.capacidad = data.capacidad
    if data.dormitorios is not None and u.dormitorios is None:
        u.dormitorios = data.dormitorios

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
