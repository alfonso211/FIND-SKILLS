"""Sociedades, activos, unidades y terceros."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .. import avisos, limpiezas, marca, nif, registro_viajeros
from ..database import get_db
from ..facturacion import FORMAS_PAGO
from ..models import (ESTADOS_UNIDAD, MODALIDADES, USOS_UNIDAD, Asset, Company, Contact, ContactDistinct,
                      ContactDocument, Invoice, Lease, Reservation, ReservationGuest, Unit)
from ..schemas import AssetIn, AssetUpdate, CompanyIn, ContactIn, UnitBulk, UnitIn, UnitUpdate
from ..security import PERMISOS, Scope, audit, get_scope
from ..utils import apply, bad_request, get_or_404, scoped

router = APIRouter(prefix="/api", tags=["estructura"])

# Qué permiso gobierna cada tipo de tercero
PERMISO_TERCERO = {"inquilino": "alquiler", "huesped": "reservas",
                   "cliente_garaje": "reservas"}  # cliente externo de una plaza de garaje (no es huésped)


@router.get("/catalogos")
def catalogos(scope: Scope = Depends(get_scope)):
    return {
        "modalidades": MODALIDADES,
        "estados_unidad": ESTADOS_UNIDAD,
        "usos_unidad": USOS_UNIDAD,
        "permisos": PERMISOS,
        "canales": ["directo", "booking", "airbnb", "expedia", "web", "agencia", "otros"],
        "categorias_mto": ["general", "fontaneria", "electricidad", "climatizacion", "acs", "ascensores", "pci",
                           "carpinteria", "cerrajeria", "pintura", "albanileria", "cubiertas", "telecom",
                           "electrodomesticos", "limpieza", "jardineria", "plagas"],
        "estados_ot": ["abierta", "asignada", "en_curso", "pendiente_material", "trabajo_realizado",
                       "pendiente_cierre", "cerrada", "cancelada"],
        "prioridades": ["baja", "media", "alta", "urgente"],
        "formas_pago": FORMAS_PAGO,
        "parentescos": registro_viajeros.PARENTESCOS,
        "paises": registro_viajeros.lista_paises(),
        "correo": avisos.configurado(),  # sin correo, los envíos al personal se hacen por WhatsApp
    }


@router.get("/codigos-postales/{cp}")
def postal_code(cp: str, scope: Scope = Depends(get_scope)):
    """Población y provincia de un código postal (para rellenarlas solas en los formularios)."""
    r = registro_viajeros.por_cp(cp)
    if r is None:
        raise HTTPException(404, "Código postal no válido")
    return r


@router.get("/municipios")
def municipios(q: str, cp: str | None = None, scope: Scope = Depends(get_scope)):
    """Búsqueda en el nomenclátor de municipios del INE (para el domicilio de los residentes en España)."""
    return registro_viajeros.buscar_municipios(q, cp)


# --------------------------------------------------------------------------- sociedades
def _company_out(c: Company) -> dict:
    return {**c.to_dict(), "logo": marca.url(marca.clave_sociedad(c.cif))}


@router.get("/sociedades")
def list_companies(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ids = None if scope.is_group_level("usuarios.gestionar") else scope.company_ids("activos.ver")
    rows = db.scalars(scoped(select(Company).order_by(Company.id), Company.id, ids))
    return [_company_out(c) for c in rows]


@router.post("/sociedades", status_code=201)
def create_company(data: CompanyIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_group("usuarios.gestionar")
    c = Company(**data.model_dump())
    db.add(c)
    db.flush()
    audit(db, scope.user, "crear", "sociedad", c.id, data.model_dump())
    db.commit()
    return _company_out(c)


@router.put("/sociedades/{cid}")
def update_company(cid: int, data: CompanyIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_group("usuarios.gestionar")
    c = get_or_404(db, Company, cid)
    ch = apply(c, data)
    audit(db, scope.user, "editar", "sociedad", cid, ch)
    db.commit()
    return _company_out(c)


# --------------------------------------------------------------------------- activos
def _asset_out(a: Asset, n_units: int) -> dict:
    d = a.to_dict()
    d["logo"] = marca.url(marca.clave_activo(a.codigo))
    d["logo_sociedad"] = marca.url(marca.clave_sociedad(a.company.cif))
    d["sociedad"] = a.company.nombre  # gestora
    d["propietaria"] = a.propietaria.nombre if a.propietaria else a.company.nombre
    d["modalidad_nombre"] = MODALIDADES.get(a.modalidad, a.modalidad)
    d["num_unidades"] = n_units
    return d


def _serie_libre(db: Session, serie: str | None, aid: int | None = None) -> None:
    """Cada activo tiene su propia serie, para que la numeración no se mezcle."""
    if serie and db.scalar(select(Asset.id).where(Asset.serie_factura == serie, Asset.id != (aid or -1))):
        bad_request(f"La serie de facturación {serie} ya la usa otro activo")


@router.get("/activos")
def list_assets(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ids = scope.asset_ids("activos.ver")
    counts = dict(db.execute(select(Unit.asset_id, func.count()).group_by(Unit.asset_id)).all())
    rows = db.scalars(scoped(select(Asset).order_by(Asset.codigo), Asset.id, ids))
    return [_asset_out(a, counts.get(a.id, 0)) for a in rows]


@router.post("/activos", status_code=201)
def create_asset(data: AssetIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    if not scope.can_company("activos.editar", data.company_id):
        raise HTTPException(403, "Sin permiso para crear activos en esta sociedad")
    if data.modalidad not in MODALIDADES:
        bad_request(f"Modalidad no válida. Opciones: {', '.join(MODALIDADES)}")
    get_or_404(db, Company, data.company_id)
    if data.propietaria_id is not None:
        get_or_404(db, Company, data.propietaria_id)
    if db.scalar(select(Asset).where(Asset.codigo == data.codigo)):
        bad_request("Ya existe un activo con ese código")
    _serie_libre(db, data.serie_factura)
    a = Asset(**{**data.model_dump(), "propietaria_id": data.propietaria_id or data.company_id})
    db.add(a)
    db.flush()
    audit(db, scope.user, "crear", "activo", a.id, data.model_dump())
    db.commit()
    return _asset_out(a, 0)


@router.put("/activos/{aid}")
def update_asset(aid: int, data: AssetUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_asset("activos.editar", aid)
    a = get_or_404(db, Asset, aid)
    if data.company_id is not None and data.company_id != a.company_id:
        if not scope.can_company("activos.editar", data.company_id):
            raise HTTPException(403, "Sin permiso sobre la sociedad destino")
        get_or_404(db, Company, data.company_id)
    if data.propietaria_id is not None and data.propietaria_id != a.propietaria_id:
        get_or_404(db, Company, data.propietaria_id)
    _serie_libre(db, data.serie_factura, aid)
    ch = apply(a, data)
    audit(db, scope.user, "editar", "activo", aid, ch)
    db.commit()
    db.refresh(a)
    n = db.scalar(select(func.count()).select_from(Unit).where(Unit.asset_id == aid))
    return _asset_out(a, n)


# --------------------------------------------------------------------------- unidades
@router.get("/unidades")
def list_units(asset_id: int | None = None, estado: str | None = None, q: str | None = None,
               bloque: str | None = None, uso: str | None = None,
               scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ids = scope.asset_ids("activos.ver")
    stmt = scoped(select(Unit), Unit.asset_id, ids).order_by(Unit.asset_id, Unit.bloque, Unit.codigo)
    if asset_id:
        stmt = stmt.where(Unit.asset_id == asset_id)
    if estado:
        stmt = stmt.where(Unit.estado == estado)
    if bloque:
        stmt = stmt.where(Unit.bloque == bloque)
    if uso:
        stmt = stmt.where(Unit.uso == uso)
    if q:
        stmt = stmt.where(or_(Unit.codigo.ilike(f"%{q}%"), Unit.tipologia.ilike(f"%{q}%")))
    return [u.to_dict() for u in db.scalars(stmt)]


def _check_estado(estado: str | None, uso: str | None = None):
    if estado is not None and estado not in ESTADOS_UNIDAD:
        bad_request(f"Estado no válido. Opciones: {', '.join(ESTADOS_UNIDAD)}")
    if uso is not None and uso not in USOS_UNIDAD:
        bad_request(f"Uso no válido. Opciones: {', '.join(USOS_UNIDAD)}")


@router.post("/unidades", status_code=201)
def create_unit(data: UnitIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_asset("activos.editar", data.asset_id)
    get_or_404(db, Asset, data.asset_id)
    _check_estado(data.estado, data.uso)
    if db.scalar(select(Unit).where(Unit.asset_id == data.asset_id, Unit.codigo == data.codigo)):
        bad_request("Ya existe una unidad con ese código en el activo")
    u = Unit(**data.model_dump())
    db.add(u)
    db.flush()
    audit(db, scope.user, "crear", "unidad", u.id, data.model_dump())
    db.commit()
    return u.to_dict()


@router.post("/unidades/masivo", status_code=201)
def bulk_units(data: UnitBulk, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Alta masiva: p.ej. prefijo 'SF-', desde 1 hasta 325 -> SF-001 ... SF-325."""
    scope.require_asset("activos.editar", data.asset_id)
    get_or_404(db, Asset, data.asset_id)
    _check_estado(None, data.uso)
    if data.hasta < data.desde or data.hasta - data.desde > 2000:
        bad_request("Rango no válido (máx. 2000 unidades por operación)")
    existing = set(db.scalars(select(Unit.codigo).where(Unit.asset_id == data.asset_id)))
    created = 0
    for n in range(data.desde, data.hasta + 1):
        code = f"{data.prefijo}{n:0{data.digitos}d}"
        if code in existing:
            continue
        db.add(Unit(asset_id=data.asset_id, codigo=code, bloque=data.bloque, uso=data.uso,
                    tipologia=data.tipologia, capacidad=data.capacidad,
                    tarifa_base_noche=data.tarifa_base_noche, renta_base=data.renta_base))
        created += 1
    audit(db, scope.user, "alta_masiva", "unidad", None, {**data.model_dump(), "creadas": created})
    db.commit()
    return {"creadas": created, "omitidas": (data.hasta - data.desde + 1) - created}


@router.put("/unidades/{uid}")
def update_unit(uid: int, data: UnitUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    u = get_or_404(db, Unit, uid)
    scope.require_asset("activos.editar", u.asset_id)
    _check_estado(data.estado, data.uso)
    ch = apply(u, data)
    audit(db, scope.user, "editar", "unidad", uid, ch)
    db.commit()
    return u.to_dict()


@router.get("/unidades/bloques")
def list_blocks(asset_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_asset("activos.ver", asset_id)
    return [b for b in db.scalars(select(Unit.bloque).where(Unit.asset_id == asset_id, Unit.bloque.is_not(None))
                                  .distinct().order_by(Unit.bloque))]


@router.post("/unidades/{uid}/limpia")
def mark_clean(uid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Gobernanta: unidad pendiente de limpieza -> disponible."""
    u = get_or_404(db, Unit, uid)
    if not (scope.can_asset("limpieza.editar", u.asset_id) or scope.can_asset("activos.editar", u.asset_id)):
        raise HTTPException(403, "Sin permiso de limpieza en este activo")
    if u.estado != "pendiente_limpieza":
        bad_request("La unidad no está pendiente de limpieza")
    u.estado = "disponible"
    limpiezas.limpieza_unidad_hecha(db, u, scope.user)  # sus limpiezas de salida pendientes quedan validadas
    audit(db, scope.user, "limpieza_ok", "unidad", uid)
    db.commit()
    return u.to_dict()


# --------------------------------------------------------------------------- terceros
def _contact_perm(tipo: str, accion: str) -> str:
    if tipo not in PERMISO_TERCERO:
        bad_request(f"Tipo de tercero no válido: {', '.join(PERMISO_TERCERO)}")
    return f"{PERMISO_TERCERO[tipo]}.{accion}"


def _contact_filter(scope: Scope, tipo: str, accion: str):
    """Condición SQL de terceros visibles. Con ámbito de sociedad (o grupo) se ven todos los de la sociedad;
    con ámbito de activo, solo las fichas de esos activos: las recepciones no comparten clientes (la de Suite
    Florida no ve los de Suite Aeropuerto aunque las gestione la misma sociedad)."""
    perm = _contact_perm(tipo, accion)
    comp = scope.company_level_ids(perm)
    if comp is None:
        return None
    return or_(Contact.company_id.in_(comp or {-1}), Contact.asset_id.in_(scope.asset_ids(perm) or {-1}))


@router.get("/terceros")
def list_contacts(tipo: str, company_id: int | None = None, asset_id: int | None = None, q: str | None = None,
                  scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    stmt = select(Contact).where(Contact.tipo == tipo)
    cond = _contact_filter(scope, tipo, "ver")
    if cond is not None:
        stmt = stmt.where(cond)
    if company_id:
        stmt = stmt.where(Contact.company_id == company_id)
    if asset_id:
        stmt = stmt.where(Contact.asset_id == asset_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Contact.nombre.ilike(like), Contact.apellidos.ilike(like),
                              Contact.documento_num.ilike(like), Contact.email.ilike(like),
                              Contact.telefono.ilike(like)))
    filas = list(db.scalars(stmt.order_by(Contact.nombre, Contact.apellidos).limit(500)))
    uds = unidades_de(db, [c.id for c in filas])
    nombres = dict(db.execute(select(Asset.id, Asset.nombre)).all())
    out = []
    for c in filas:
        d = c.to_dict()
        d["activo"] = nombres.get(c.asset_id)
        u = uds.get(c.id, [])
        d["unidades"] = [x["codigo"] for x in u]
        d["n_apartamentos"] = sum(1 for x in u if x["uso"] != "garaje")
        out.append(d)
    return out


ACTIVAS = ("confirmada", "checkin")


def unidades_de(db: Session, ids: list[int]) -> dict[int, list[dict]]:
    """Apartamentos y plazas que tiene cada cliente ahora: reservas confirmadas o en curso y contratos vigentes."""
    out: dict[int, list[dict]] = {}
    if not ids:
        return out
    for r, u, a in db.execute(select(Reservation, Unit, Asset).join(Unit, Unit.id == Reservation.unit_id)
                              .join(Asset, Asset.id == Unit.asset_id)
                              .where(Reservation.guest_id.in_(ids), Reservation.estado.in_(ACTIVAS))
                              .order_by(Unit.codigo)):
        out.setdefault(r.guest_id, []).append({
            "codigo": u.codigo, "uso": u.uso, "activo": a.nombre, "tipo": "reserva", "localizador": r.localizador,
            "desde": r.fecha_entrada.isoformat(), "hasta": r.fecha_salida.isoformat(), "estado": r.estado})
    for l, u, a in db.execute(select(Lease, Unit, Asset).join(Unit, Unit.id == Lease.unit_id)
                              .join(Asset, Asset.id == Unit.asset_id)
                              .where(Lease.tenant_id.in_(ids), Lease.estado.in_(("borrador", "vigente")))
                              .order_by(Unit.codigo)):
        out.setdefault(l.tenant_id, []).append({
            "codigo": u.codigo, "uso": u.uso, "activo": a.nombre, "tipo": "contrato", "localizador": l.referencia,
            "desde": l.fecha_inicio.isoformat(), "hasta": l.fecha_fin.isoformat() if l.fecha_fin else None,
            "estado": l.estado})
    return out


def _visible(db: Session, scope: Scope, c: Contact, accion: str) -> None:
    cond = _contact_filter(scope, c.tipo, accion)
    if cond is not None and not db.scalar(select(Contact.id).where(Contact.id == c.id, cond)):
        raise HTTPException(403, "Sin permiso sobre este cliente")


@router.get("/terceros/duplicados")
def duplicate_contacts(tipo: str, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Fichas con el mismo nombre en el mismo activo (sin tildes ni mayúsculas). No se unen solas: dos clientes
    distintos pueden llamarse igual; se revisan y se unen con «fusionar». Las de activos distintos no son
    repetidas: cada recepción tiene su propia ficha del cliente."""
    stmt = select(Contact).where(Contact.tipo == tipo)
    cond = _contact_filter(scope, tipo, "editar")
    if cond is not None:
        stmt = stmt.where(cond)
    grupos: dict[tuple, list[Contact]] = {}
    for c in db.scalars(stmt.order_by(Contact.id)):
        grupos.setdefault((c.company_id, c.asset_id, nif.nombre_clave(c.nombre, c.apellidos)), []).append(c)
    repetidos = _sin_distintos(db, [g for g in grupos.values() if len(g) > 1])
    uds = unidades_de(db, [c.id for g in repetidos for c in g])
    n_res = dict(db.execute(select(Reservation.guest_id, func.count()).where(
        Reservation.guest_id.in_([c.id for g in repetidos for c in g] or [-1])).group_by(Reservation.guest_id)).all())
    out = []
    for g in repetidos:
        fichas = [{**c.to_dict(), "unidades": [x["codigo"] for x in uds.get(c.id, [])], "reservas": n_res.get(c.id, 0),
                   "datos": sum(1 for k in CAMPOS_FUSION if getattr(c, k))} for c in g]
        docs = {nif.normalizar(c.documento_num) for c in g if c.documento_num}
        principal = max(fichas, key=lambda f: (f["datos"], f["reservas"], -f["id"]))
        out.append({"nombre": f"{g[0].nombre} {g[0].apellidos or ''}".strip(), "fichas": fichas,
                    "activo": db.get(Asset, g[0].asset_id).nombre if g[0].asset_id else None,
                    "principal": principal["id"], "documentos_distintos": len(docs) > 1})
    return out


def _sin_distintos(db: Session, grupos: list[list[Contact]]) -> list[list[Contact]]:
    """Quita de cada grupo las parejas que recepción ya revisó como personas distintas: quedan juntas solo las fichas
    que pueden ser la misma persona (componentes conexos de las parejas sin revisar)."""
    ids = [c.id for g in grupos for c in g]
    distintas = set(db.execute(select(ContactDistinct.a_id, ContactDistinct.b_id).where(
        ContactDistinct.a_id.in_(ids or [-1]))).all())
    out = []
    for g in grupos:
        pendientes = list(g)
        while pendientes:
            comp = [pendientes.pop(0)]
            cola = [comp[0]]
            while cola:
                x = cola.pop()
                for y in [y for y in pendientes if (min(x.id, y.id), max(x.id, y.id)) not in distintas]:
                    pendientes.remove(y)
                    comp.append(y)
                    cola.append(y)
            if len(comp) > 1:
                out.append(sorted(comp, key=lambda c: c.id))
    return out


class DistinctIn(BaseModel):
    ids: list[int] = Field(min_length=2, max_length=50)


@router.post("/terceros/distintos")
def mark_distinct(data: DistinctIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """«No son la misma persona»: las fichas indicadas (mismo nombre) dejan de salir como repetidas entre sí."""
    fichas = [get_or_404(db, Contact, i) for i in sorted(set(data.ids))]
    for c in fichas:
        _visible(db, scope, c, "editar")
    if len({(c.company_id, c.asset_id, c.tipo) for c in fichas}) > 1:
        bad_request("Solo se revisan fichas del mismo activo y tipo")
    ya = set(db.execute(select(ContactDistinct.a_id, ContactDistinct.b_id).where(
        ContactDistinct.a_id.in_([c.id for c in fichas]))).all())
    nuevas = 0
    for i, a in enumerate(fichas):
        for b in fichas[i + 1:]:
            if (a.id, b.id) not in ya:
                db.add(ContactDistinct(a_id=a.id, b_id=b.id, user_id=scope.user.id))
                nuevas += 1
    audit(db, scope.user, "no_duplicado", "tercero", fichas[0].id, {"fichas": [c.id for c in fichas]})
    db.commit()
    return {"parejas": nuevas}


CAMPOS_FUSION = ("apellidos", "documento_tipo", "documento_num", "nacionalidad", "fecha_nacimiento", "sexo",
                 "num_soporte", "fecha_caducidad_doc", "email", "telefono", "direccion", "cp", "municipio",
                 "provincia", "municipio_ine", "pais", "iban")


class MergeIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=50)


@router.post("/terceros/{cid}/fusionar")
def merge_contacts(cid: int, data: MergeIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Une en la ficha `cid` las fichas repetidas del mismo cliente: pasan a ella sus reservas, ocupaciones,
    contratos, documentos escaneados y facturas; se completan los datos que le falten y se borran las demás."""
    c = get_or_404(db, Contact, cid)
    _visible(db, scope, c, "editar")
    otros = []
    for oid in dict.fromkeys(data.ids):
        if oid == cid:
            continue
        o = get_or_404(db, Contact, oid)
        _visible(db, scope, o, "editar")
        if (o.company_id, o.tipo) != (c.company_id, c.tipo) or None not in (c.asset_id, o.asset_id) \
                and c.asset_id != o.asset_id:
            bad_request("Solo se pueden unir fichas del mismo activo y del mismo tipo: cada recepción tiene las suyas")
        da, db_ = nif.normalizar(c.documento_num), nif.normalizar(o.documento_num)
        if da and db_ and da != db_:
            bad_request(f"{o.nombre} {o.apellidos or ''} tiene otro documento ({o.documento_num}): son personas "
                        "distintas y no se pueden unir")
        otros.append(o)
    if not otros:
        bad_request("Indique las fichas que se unen a esta")
    ids = [o.id for o in otros]
    for o in otros:  # datos que faltan en la ficha que se conserva
        c.asset_id = c.asset_id or o.asset_id
        for k in CAMPOS_FUSION:
            if not getattr(c, k) and getattr(o, k):
                setattr(c, k, getattr(o, k))
        if o.notas and o.notas not in (c.notas or ""):
            c.notas = f"{c.notas}\n{o.notas}" if c.notas else o.notas
    ya = set(db.scalars(select(ReservationGuest.reservation_id).where(ReservationGuest.contact_id == cid)))
    for og in db.scalars(select(ReservationGuest).where(ReservationGuest.contact_id.in_(ids))):
        if og.reservation_id in ya:
            db.delete(og)  # ya figuraba como ocupante de esa reserva
        else:
            og.contact_id = cid
            ya.add(og.reservation_id)
    db.flush()
    movidas = {}
    for modelo, col in ((Reservation, Reservation.guest_id), (Lease, Lease.tenant_id),
                        (ContactDocument, ContactDocument.contact_id), (Invoice, Invoice.contact_id)):
        filas = list(db.scalars(select(modelo).where(col.in_(ids))))
        for f in filas:
            setattr(f, col.key, cid)
        movidas[modelo.__tablename__] = len(filas)
    db.execute(delete(ContactDistinct).where(or_(ContactDistinct.a_id.in_(ids), ContactDistinct.b_id.in_(ids))))
    db.flush()
    for o in otros:
        db.delete(o)
    audit(db, scope.user, "fusionar", "tercero", cid, {"unidas": ids, "movidas": movidas})
    db.commit()
    return contact_detail(cid, scope, db)


@router.get("/terceros/{cid}")
def contact_detail(cid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Ficha del cliente con los apartamentos y plazas que tiene ahora y el número de estancias."""
    c = get_or_404(db, Contact, cid)
    _visible(db, scope, c, "ver")
    d = c.to_dict()
    d["activo"] = db.get(Asset, c.asset_id).nombre if c.asset_id else None
    d["unidades"] = unidades_de(db, [cid]).get(cid, [])
    d["n_apartamentos"] = sum(1 for x in d["unidades"] if x["uso"] != "garaje")
    d["n_estancias"] = db.scalar(select(func.count()).select_from(Reservation).where(Reservation.guest_id == cid))
    # otras fichas del mismo activo con el mismo nombre que aún no se han revisado (aviso de ficha repetida)
    clave = nif.nombre_clave(c.nombre, c.apellidos)
    mismas = [o for o in db.scalars(select(Contact).where(
        Contact.company_id == c.company_id, Contact.tipo == c.tipo, Contact.id != c.id,
        Contact.asset_id.is_(None) if c.asset_id is None else Contact.asset_id == c.asset_id))
        if nif.nombre_clave(o.nombre, o.apellidos) == clave]
    grupo = next((g for g in _sin_distintos(db, [[c, *mismas]]) if any(x.id == c.id for x in g)), []) if mismas else []
    d["repetidas"] = [{"id": o.id, "documento_num": o.documento_num, "telefono": o.telefono, "email": o.email}
                      for o in grupo if o.id != c.id]
    fin = scope.asset_ids("finanzas.ver")  # importes del programa anterior: solo quien ve las finanzas del activo
    if fin is None or (c.asset_id and c.asset_id in fin):
        from .historico import del_cliente  # import local: historico no depende de este módulo
        d["historico"] = del_cliente(db, c)
    return d


@router.post("/terceros", status_code=201)
def create_contact(data: ContactIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    perm = _contact_perm(data.tipo, "editar")
    if data.asset_id:
        a = get_or_404(db, Asset, data.asset_id)
        if a.company_id != data.company_id:
            bad_request("El activo no pertenece a la sociedad indicada")
        scope.require_asset(perm, a.id)
    else:  # ficha sin activo: solo quien gestiona toda la sociedad
        comp = scope.company_level_ids(perm)
        if comp is not None and data.company_id not in comp:
            bad_request("Indique el activo del cliente")
    doc = nif.normalizar(data.documento_num)
    if doc:
        dup = db.scalar(select(Contact).where(Contact.company_id == data.company_id, Contact.tipo == data.tipo,
                                              Contact.asset_id.is_(None) if data.asset_id is None
                                              else Contact.asset_id == data.asset_id,
                                              func.upper(Contact.documento_num) == doc))
        if dup:
            bad_request(f"Ya existe la ficha de {dup.nombre} {dup.apellidos or ''} con el documento {doc}: "
                        "búsquela y edítela en lugar de crear otra")
    c = Contact(**data.model_dump(exclude={"documentos"}))
    registro_viajeros.completar_municipio(c)
    db.add(c)
    db.flush()
    if data.documentos:
        from .documentos import adjuntar_pendientes  # import local: documentos importa este módulo
        adjuntar_pendientes(db, scope.user, data.documentos, c)
    audit(db, scope.user, "crear", "tercero", c.id, {"tipo": c.tipo, "nombre": c.nombre})
    db.commit()
    return c.to_dict()


@router.put("/terceros/{cid}")
def update_contact(cid: int, data: ContactIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    c = get_or_404(db, Contact, cid)
    cond = _contact_filter(scope, c.tipo, "editar")
    if cond is not None and not db.scalar(select(Contact.id).where(Contact.id == cid, cond)):
        raise HTTPException(403, "Sin permiso sobre este tercero")
    if data.company_id != c.company_id or data.tipo != c.tipo:
        bad_request("No se puede cambiar la sociedad ni el tipo de un tercero")
    if "asset_id" in data.model_fields_set and data.asset_id != c.asset_id:
        bad_request("No se puede cambiar el activo de la ficha: cada recepción tiene sus clientes")
    ch = apply(c, data)
    registro_viajeros.completar_municipio(c)
    audit(db, scope.user, "editar", "tercero", cid, ch)
    db.commit()
    return c.to_dict()
