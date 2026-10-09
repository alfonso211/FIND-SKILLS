"""Usuarios, roles, auditoría (solo administradores a nivel de grupo)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import secrets

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from .. import avisos
from ..config import settings
from ..database import get_db
from ..models import Asset, Assignment, AuditLog, Base, Company, EmailLog, Role, Supplier, User
from ..schemas import AssignmentIn, RoleIn, UserIn, UserUpdate
from ..security import PERMISOS, Scope, audit, get_scope, hash_password
from ..utils import bad_request, get_or_404

router = APIRouter(prefix="/api/admin", tags=["administración"])
BORRADO = "@usuario-borrado.invalid"  # dominio del email de los usuarios borrados que se conservan por su historial


def puede_borrar(u: User) -> bool:
    """Solo las cuentas autorizadas (PMS_BORRAR_USUARIOS y el administrador inicial) borran usuarios."""
    return u.activo and u.email.lower() in {*settings.borrar_usuarios, settings.admin_email.lower()}


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


def _validar_colaborador(db: Session, supplier_id: int | None, superadmin: bool) -> None:
    if supplier_id:
        get_or_404(db, Supplier, supplier_id)
        if superadmin:
            bad_request("Un colaborador externo no puede ser superadministrador")


@router.get("/usuarios")
def list_users(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_group("usuarios.gestionar")
    return [_user_out(u) for u in db.scalars(select(User).where(~User.email.endswith(BORRADO)).order_by(User.nombre))]


@router.post("/usuarios", status_code=201)
def create_user(data: UserIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_group("usuarios.gestionar")
    if data.is_superadmin and not scope.user.is_superadmin:
        raise HTTPException(403, "Solo un superadministrador puede crear otro")
    email = data.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        bad_request("Ya existe un usuario con ese email")
    _validate_assignments(db, data.asignaciones)
    _validar_colaborador(db, data.supplier_id, data.is_superadmin)
    u = User(email=email, nombre=data.nombre, password_hash=hash_password(data.password),
             is_superadmin=data.is_superadmin, activo=data.activo, debe_cambiar_password=True,
             no_asignable=data.no_asignable, supplier_id=data.supplier_id,
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
    if data.no_asignable is not None:
        u.no_asignable = data.no_asignable
    if "supplier_id" in data.model_fields_set:
        u.supplier_id = data.supplier_id or None
    _validar_colaborador(db, u.supplier_id, u.is_superadmin)
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


def _referencias(db: Session, uid: int) -> list[str]:
    """Tablas con registros del usuario (sin contar sus roles, que se borran con él)."""
    out = []
    for t in Base.metadata.sorted_tables:
        if t.name == "asignaciones":
            continue
        for c in t.columns:
            if any(fk.column.table.name == "usuarios" for fk in c.foreign_keys) and \
                    db.scalar(select(exists().where(c == uid))):
                out.append(t.name)
                break
    return out


@router.delete("/usuarios/{uid}")
def delete_user(uid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Borra un usuario. Si ya tiene actividad en el PMS (partes, gastos, auditoría…), se conserva solo su nombre
    para el historial: sin acceso, sin roles, fuera de la lista y con el email libre para volver a usarlo."""
    if not puede_borrar(scope.user):
        raise HTTPException(403, "Solo las cuentas autorizadas pueden borrar usuarios")
    u = get_or_404(db, User, uid)
    if u.email.endswith(BORRADO):
        raise HTTPException(404, "Usuario no encontrado")
    if u.id == scope.user.id:
        bad_request("No puede borrarse a sí mismo")
    if puede_borrar(u):
        bad_request("Es una de las cuentas que borran usuarios: no se puede borrar")
    if u.is_superadmin and not db.scalar(select(exists().where(User.is_superadmin.is_(True), User.activo.is_(True),
                                                                   User.id != u.id,
                                                                   ~User.email.endswith(BORRADO)))):
        bad_request("Es el único superadministrador activo: no se puede borrar")
    refs = _referencias(db, u.id)
    det = {"email": u.email, "nombre": u.nombre, "modo": "conservado por historial" if refs else "borrado"}
    if refs:
        u.email, u.activo, u.is_superadmin, u.supplier_id = f"{u.id}{BORRADO}", False, False, None
        u.password_hash = hash_password(secrets.token_urlsafe(24))
        u.debe_cambiar_password = False
        u.assignments = []
    else:
        db.delete(u)
    audit(db, scope.user, "borrar", "usuario", uid, det)
    db.commit()
    return {"ok": True, "historial": bool(refs)}


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


# --------------------------------------------------------------------------- avisos por correo
@router.get("/avisos")
def alerts_status(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_group("usuarios.gestionar")
    filas = db.execute(select(EmailLog, User.nombre).outerjoin(User, User.id == EmailLog.user_id)
                       .where(EmailLog.tipo != "sistema").order_by(EmailLog.id.desc()).limit(200)).all()
    return {"configurado": avisos.configurado(), "servidor": settings.smtp_host, "remitente": avisos.remitente(),
            "hora_resumen": settings.avisos_hora,
            "registro": [{**e.to_dict(), "usuario": n} for e, n in filas]}


class TestMail(BaseModel):
    email: str | None = None


@router.post("/avisos/probar")
def alerts_test(data: TestMail, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Envía un correo de prueba (por defecto, al propio administrador)."""
    scope.require_group("usuarios.gestionar")
    destino = data.email or scope.user.email
    try:
        avisos.enviar(destino, "PMS · Correo de prueba",
                      "Si recibe este correo, los avisos del PMS están bien configurados.",
                      avisos._html("Correo de prueba", "<p>Si recibe este correo, los avisos del PMS están bien "
                                                       "configurados.</p>"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"No se pudo enviar: {e}")
    audit(db, scope.user, "probar_correo", "avisos", None, {"destino": destino})
    db.commit()
    return {"ok": True, "destino": destino}


@router.post("/avisos/resumen")
def alerts_digest_now(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Envía ahora el resumen diario a todos los suscritos (aunque ya lo hubieran recibido hoy)."""
    scope.require_group("usuarios.gestionar")
    if not avisos.configurado():
        raise HTTPException(400, "Correo no configurado (falta PMS_SMTP_HOST en el servidor)")
    r = avisos.resumen_diario(db, forzar=True)
    audit(db, scope.user, "enviar_resumen", "avisos", None, r)
    db.commit()
    return r
