"""Sociedades, activos, unidades y terceros."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ESTADOS_UNIDAD, MODALIDADES, USOS_UNIDAD, Asset, Company, Contact, Lease, Reservation, Unit
from ..schemas import AssetIn, AssetUpdate, CompanyIn, ContactIn, UnitBulk, UnitIn, UnitUpdate
from ..security import PERMISOS, Scope, audit, get_scope
from ..utils import apply, bad_request, get_or_404, scoped

router = APIRouter(prefix="/api", tags=["estructura"])

# Qué permiso gobierna cada tipo de tercero
PERMISO_TERCERO = {"inquilino": "alquiler", "huesped": "reservas", "proveedor": "mantenimiento"}


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
    }


# --------------------------------------------------------------------------- sociedades
@router.get("/sociedades")
def list_companies(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ids = None if scope.is_group_level("usuarios.gestionar") else scope.company_ids("activos.ver")
    rows = db.scalars(scoped(select(Company).order_by(Company.id), Company.id, ids))
    return [c.to_dict() for c in rows]


@router.post("/sociedades", status_code=201)
def create_company(data: CompanyIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_group("usuarios.gestionar")
    c = Company(**data.model_dump())
    db.add(c)
    db.flush()
    audit(db, scope.user, "crear", "sociedad", c.id, data.model_dump())
    db.commit()
    return c.to_dict()


@router.put("/sociedades/{cid}")
def update_company(cid: int, data: CompanyIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_group("usuarios.gestionar")
    c = get_or_404(db, Company, cid)
    ch = apply(c, data)
    audit(db, scope.user, "editar", "sociedad", cid, ch)
    db.commit()
    return c.to_dict()


# --------------------------------------------------------------------------- activos
def _asset_out(a: Asset, n_units: int) -> dict:
    d = a.to_dict()
    d["sociedad"] = a.company.nombre  # gestora
    d["propietaria"] = a.propietaria.nombre if a.propietaria else a.company.nombre
    d["modalidad_nombre"] = MODALIDADES.get(a.modalidad, a.modalidad)
    d["num_unidades"] = n_units
    return d


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
    con ámbito de activo, solo los vinculados a reservas/contratos de esos activos (p.ej. la recepción de
    Suite Florida no ve huéspedes de Suite Aeropuerto aunque ambos los gestione la misma sociedad)."""
    perm = _contact_perm(tipo, accion)
    comp = scope.company_level_ids(perm)
    if comp is None:
        return None
    assets = scope.asset_ids(perm) or set()
    if tipo == "huesped":
        linked = select(Reservation.guest_id).join(Unit).where(Unit.asset_id.in_(assets or {-1}))
    elif tipo == "inquilino":
        linked = select(Lease.tenant_id).join(Unit).where(Unit.asset_id.in_(assets or {-1}))
    else:  # proveedores: catálogo de la sociedad
        linked = select(Contact.id).where(Contact.company_id.in_(
            select(Asset.company_id).where(Asset.id.in_(assets or {-1}))))
    return or_(Contact.company_id.in_(comp or {-1}), Contact.id.in_(linked))


@router.get("/terceros")
def list_contacts(tipo: str, company_id: int | None = None, q: str | None = None,
                  scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    stmt = select(Contact).where(Contact.tipo == tipo)
    cond = _contact_filter(scope, tipo, "ver")
    if cond is not None:
        stmt = stmt.where(cond)
    if company_id:
        stmt = stmt.where(Contact.company_id == company_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Contact.nombre.ilike(like), Contact.apellidos.ilike(like),
                              Contact.documento_num.ilike(like), Contact.email.ilike(like)))
    return [c.to_dict() for c in db.scalars(stmt.order_by(Contact.nombre).limit(500))]


def _require_contact(scope: Scope, tipo: str, accion: str, company_id: int):
    ids = scope.company_ids(_contact_perm(tipo, accion))
    if ids is not None and company_id not in ids:
        raise HTTPException(403, "Sin permiso sobre terceros de esta sociedad")


@router.post("/terceros", status_code=201)
def create_contact(data: ContactIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _require_contact(scope, data.tipo, "editar", data.company_id)
    c = Contact(**data.model_dump(exclude={"documentos"}))
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
    ch = apply(c, data)
    audit(db, scope.user, "editar", "tercero", cid, ch)
    db.commit()
    return c.to_dict()
