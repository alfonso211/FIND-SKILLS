"""Usuarios, roles, auditoría (solo administradores a nivel de grupo)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Asset, Assignment, AuditLog, Company, Role, User
from ..schemas import AssignmentIn, RoleIn, UserIn, UserUpdate
from ..security import PERMISOS, Scope, audit, get_scope, hash_password
from ..utils import bad_request, get_or_404

router = APIRouter(prefix="/api/admin", tags=["administración"])


def _user_out(u: User) -> dict:
    d = u.to_dict(exclude=("password_hash",))
    d["asignaciones"] = [{"id": a.id, "role_id": a.role_id, "rol": a.role.nombre,
                          "company_id": a.company_id, "asset_id": a.asset_id} for a in u.assignments]
    return d


def _validate_assignments(db: Session, items: list[AssignmentIn]):
    for a in items:
        get_or_404(db, Role, a.role_id)
        if a.asset_id:
            asset = get_or_404(db, Asset, a.asset_id)
            if a.company_id and a.company_id != asset.company_id:
                bad_request("El activo no pertenece a la sociedad indicada")
            a.company_id = asset.company_id
        elif a.company_id:
            get_or_404(db, Company, a.company_id)


@router.get("/usuarios")
def list_users(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_group("usuarios.gestionar")
    return [_user_out(u) for u in db.scalars(select(User).order_by(User.nombre))]


@router.post("/usuarios", status_code=201)
def create_user(data: UserIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_group("usuarios.gestionar")
    if data.is_superadmin and not scope.user.is_superadmin:
        raise HTTPException(403, "Solo un superadministrador puede crear otro")
    email = data.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        bad_request("Ya existe un usuario con ese email")
    _validate_assignments(db, data.asignaciones)
    u = User(email=email, nombre=data.nombre, password_hash=hash_password(data.password),
             is_superadmin=data.is_superadmin, activo=data.activo, debe_cambiar_password=True,
             assignments=[Assignment(**a.model_dump()) for a in data.asignaciones])
    db.add(u)
    db.flush()
    audit(db, scope.user, "crear", "usuario", u.id,
          {"email": email, "asignaciones": [a.model_dump() for a in data.asignaciones]})
    db.commit()
    db.refresh(u)
    return _user_out(u)


@router.put("/usuarios/{uid}")
def update_user(uid: int, data: UserUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_group("usuarios.gestionar")
    u = get_or_404(db, User, uid)
    if (u.is_superadmin or data.is_superadmin) and not scope.user.is_superadmin:
        raise HTTPException(403, "Solo un superadministrador puede modificar superadministradores")
    if u.id == scope.user.id and (data.activo is False or data.is_superadmin is False):
        bad_request("No puede desactivarse ni quitarse privilegios a sí mismo")
    det = data.model_dump(exclude_unset=True, exclude={"password"})
    if data.email is not None and data.email.lower().strip() != u.email:
        email = data.email.lower().strip()
        if db.scalar(select(User).where(User.email == email)):
            bad_request("Ya existe un usuario con ese email")
        u.email = email
    if data.nombre is not None:
        u.nombre = data.nombre
    if data.activo is not None:
        u.activo = data.activo
    if data.is_superadmin is not None:
        u.is_superadmin = data.is_superadmin
    if data.password:
        u.password_hash = hash_password(data.password)
        u.debe_cambiar_password = True
        det["password"] = "restablecida (provisional)"
    if data.asignaciones is not None:
        _validate_assignments(db, data.asignaciones)
        u.assignments = [Assignment(**a.model_dump()) for a in data.asignaciones]
    audit(db, scope.user, "editar", "usuario", uid, det)
    db.commit()
    db.refresh(u)
    return _user_out(u)


@router.get("/roles")
def list_roles(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_group("usuarios.gestionar")
    return [r.to_dict() for r in db.scalars(select(Role).order_by(Role.nombre))]


def _check_perms(perms: list[str]):
    bad = [p for p in perms if p not in PERMISOS]
    if bad:
        bad_request(f"Permisos desconocidos: {', '.join(bad)}")


@router.post("/roles", status_code=201)
def create_role(data: RoleIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_group("usuarios.gestionar")
    _check_perms(data.permisos)
    if db.scalar(select(Role).where(Role.nombre == data.nombre)):
        bad_request("Ya existe un rol con ese nombre")
    r = Role(**data.model_dump())
    db.add(r)
    db.flush()
    audit(db, scope.user, "crear", "rol", r.id, data.model_dump())
    db.commit()
    return r.to_dict()


@router.put("/roles/{rid}")
def update_role(rid: int, data: RoleIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_group("usuarios.gestionar")
    _check_perms(data.permisos)
    r = get_or_404(db, Role, rid)
    old = list(r.permisos or [])
    r.nombre, r.descripcion, r.permisos = data.nombre, data.descripcion, list(data.permisos)
    audit(db, scope.user, "editar", "rol", rid, {"antes": old, "despues": data.permisos})
    db.commit()
    return r.to_dict()


@router.get("/auditoria")
def audit_log(entidad: str | None = None, user_id: int | None = None, limit: int = 300,
              scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_group("auditoria.ver")
    stmt = select(AuditLog, User.nombre).outerjoin(User, User.id == AuditLog.user_id)
    if entidad:
        stmt = stmt.where(AuditLog.entidad == entidad)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    rows = db.execute(stmt.order_by(AuditLog.id.desc()).limit(min(limit, 2000))).all()
    return [{**log.to_dict(), "usuario": nombre} for log, nombre in rows]
