from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Asset, Company, User
from ..schemas import Login, PasswordChange
from ..security import (PASSWORD_MIN, PERMISOS, Scope, audit, create_token, current_user, get_scope, hash_password,
                        limpiar_fallos, login_bloqueado, registrar_fallo, verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(data: Login, db: Session = Depends(get_db)):
    email = data.email.lower().strip()
    if login_bloqueado(email):
        raise HTTPException(429, "Demasiados intentos fallidos. Espere 15 minutos.")
    user = db.scalar(select(User).where(User.email == email))
    if not user or not user.activo or not verify_password(data.password, user.password_hash):
        registrar_fallo(email)
        audit(db, None, "login_fallido", "usuario", user.id if user else None, {"email": email})
        db.commit()
        raise HTTPException(401, "Credenciales incorrectas")
    limpiar_fallos(email)
    audit(db, user, "login", "usuario", user.id)
    db.commit()
    return {"token": create_token(user)}


@router.get("/me")
def me(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    u = scope.user
    ambitos = []
    for a in u.assignments:
        if a.asset_id:
            amb = "Activo: " + (db.get(Asset, a.asset_id).nombre)
        elif a.company_id:
            amb = "Sociedad: " + (db.get(Company, a.company_id).nombre)
        else:
            amb = "Todo el grupo"
        ambitos.append({"rol": a.role.nombre, "ambito": amb})
    return {
        "id": u.id, "email": u.email, "nombre": u.nombre, "is_superadmin": u.is_superadmin,
        "debe_cambiar_password": u.debe_cambiar_password,
        "permisos": {p: scope.has_any(p) for p in PERMISOS},
        "admin_grupo": scope.is_group_level("usuarios.gestionar"),
        "ambitos": ambitos,
    }


@router.post("/password")
def change_password(data: PasswordChange, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(data.actual, user.password_hash):
        raise HTTPException(400, "Contraseña actual incorrecta")
    if data.nueva == data.actual:
        raise HTTPException(400, "La nueva contraseña debe ser distinta de la actual")
    if len(set(data.nueva)) < 4:
        raise HTTPException(400, "La contraseña es demasiado simple")
    if len(data.nueva) < PASSWORD_MIN:
        raise HTTPException(400, f"La contraseña debe tener al menos {PASSWORD_MIN} caracteres")
    user.password_hash = hash_password(data.nueva)
    user.debe_cambiar_password = False
    audit(db, user, "cambio_password", "usuario", user.id)
    db.commit()
    return {"ok": True}
