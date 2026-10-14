from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import avisos, proteccion
from ..database import get_db
from ..models import Asset, Company, User, Supplier
from ..schemas import Login, PasswordChange
from ..security import (MAX_INTENTOS, PASSWORD_MIN, PERMISOS, Scope, audit, cerrar_sesiones, create_token, current_user,
                        get_scope, hash_password, limpiar_fallos, login_bloqueado, registrar_fallo, verify_password)
from ..gestion import puede_ir
from .admin import puede_borrar

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(data: Login, request: Request, db: Session = Depends(get_db)):
    email = data.email.lower().strip()
    ip = proteccion.ip_de(request)
    if proteccion.bloqueada("login", ip):
        raise HTTPException(429, "Demasiados intentos fallidos desde esta conexión. Espere 15 minutos.")
    if login_bloqueado(email):
        raise HTTPException(429, "Demasiados intentos fallidos. Espere 15 minutos.")
    user = db.scalar(select(User).where(User.email == email))
    if not user or not user.activo or not verify_password(data.password, user.password_hash):
        registrar_fallo(email)
        proteccion.fallo("login", ip, email)
        if login_bloqueado(email) and user:  # se avisa solo si el usuario existe (no de correos inventados)
            proteccion.avisar("cuenta", email, MAX_INTENTOS, ip)
        audit(db, None, "login_fallido", "usuario", user.id if user else None, {"email": email, "ip": ip})
        db.commit()
        raise HTTPException(401, "Credenciales incorrectas")
    limpiar_fallos(email)
    audit(db, user, "login", "usuario", user.id, {"ip": ip})
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
        "borrar_usuarios": puede_borrar(u),
        "gestion": puede_ir(u),  # botón «Gestión» (INVERGESTION)
        "ambitos": ambitos,
        "accesos": accesos_de(u),  # accesos rápidos de la barra superior
        # colaborador externo: solo su portal
        "colaborador": {"supplier_id": u.supplier_id, "proveedor": db.get(Supplier, u.supplier_id).nombre}
        if u.supplier_id else None,
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
    cerrar_sesiones(user)  # las demás sesiones abiertas (otro ordenador, móvil) se cierran
    audit(db, user, "cambio_password", "usuario", user.id)
    db.commit()
    return {"ok": True, "token": create_token(user)}  # esta sesión sigue con el token nuevo


# --------------------------------------------------------------------------- avisos por correo del propio usuario
@router.get("/avisos")
def my_alerts(scope: Scope = Depends(get_scope)):
    permitidos = avisos.tipos_permitidos(scope)
    elegidos = permitidos if scope.user.avisos is None else [t for t in scope.user.avisos if t in permitidos]
    return {"correo_configurado": avisos.configurado(), "email": scope.user.email,
            "tipos": [{"tipo": t, "descripcion": avisos.TIPOS[t][0], "activo": t in elegidos} for t in permitidos]}


class AlertPrefs(BaseModel):
    avisos: list[str]


@router.put("/avisos")
def set_my_alerts(data: AlertPrefs, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    permitidos = set(avisos.tipos_permitidos(scope))
    otros = set(data.avisos) - set(avisos.TIPOS)
    if otros:
        raise HTTPException(400, f"Avisos no válidos: {', '.join(sorted(otros))}")
    # se guardan también los no permitidos hoy que ya tuviera, por si recupera el permiso
    previos = set(scope.user.avisos or []) - permitidos
    scope.user.avisos = sorted((set(data.avisos) & permitidos) | previos)
    audit(db, scope.user, "avisos", "usuario", scope.user.id, {"avisos": scope.user.avisos})
    db.commit()
    return my_alerts(scope)


# --------------------------------------------------------------------------- accesos rápidos de la barra superior
# Se abren en una pestaña nueva; las versiones web porque el navegador no puede abrir programas del ordenador.
ACCESOS_DEFECTO = [
    {"nombre": "Gmail", "url": "https://mail.google.com/"},
    {"nombre": "Outlook", "url": "https://outlook.office.com/mail/"},
    {"nombre": "Excel", "url": "https://www.office.com/launch/excel"},
    {"nombre": "Word", "url": "https://www.office.com/launch/word"},
    {"nombre": "Teams", "url": "https://teams.microsoft.com/"},
]
ACCESOS_MAX, ACCESO_NOMBRE_MAX, ACCESO_URL_MAX = 10, 30, 500


def accesos_de(u: User) -> list[dict]:
    return [dict(a) for a in (ACCESOS_DEFECTO if u.accesos is None else u.accesos)]


class Acceso(BaseModel):
    nombre: str
    url: str


class AccesosIn(BaseModel):
    accesos: list[Acceso] | None  # None = volver a los de serie


def _acceso_valido(a: Acceso) -> dict:
    from urllib.parse import urlsplit
    nombre, url = " ".join(a.nombre.split()), a.url.strip()
    if not nombre:
        raise HTTPException(400, "Cada acceso necesita un nombre")
    if len(nombre) > ACCESO_NOMBRE_MAX:
        raise HTTPException(400, f"«{nombre[:40]}»: el nombre admite como máximo {ACCESO_NOMBRE_MAX} caracteres")
    partes = urlsplit(url)
    # solo páginas seguras: nada de javascript:, data:, file: ni direcciones con espacios o credenciales
    if (partes.scheme.lower() != "https" or not partes.hostname or partes.username or partes.password
            or len(url) > ACCESO_URL_MAX or any(c.isspace() for c in url)):
        raise HTTPException(400, f"«{nombre}»: la dirección debe empezar por https:// (por ejemplo https://mail.google.com)")
    return {"nombre": nombre, "url": url}


@router.get("/accesos")
def my_shortcuts(user: User = Depends(current_user)):
    return {"accesos": accesos_de(user), "de_serie": user.accesos is None, "maximo": ACCESOS_MAX}


@router.put("/accesos")
def set_my_shortcuts(data: AccesosIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.accesos is None:
        user.accesos = None
    else:
        if len(data.accesos) > ACCESOS_MAX:
            raise HTTPException(400, f"Como máximo {ACCESOS_MAX} accesos rápidos")
        user.accesos = [_acceso_valido(a) for a in data.accesos]
    audit(db, user, "accesos_rapidos", "usuario", user.id, {"accesos": user.accesos})
    db.commit()
    return my_shortcuts(user)


@router.get("/reloj")
def clock(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Hora del programa (Madrid), zona efectiva y hora de la base de datos: para comprobar que coinciden con la del
    ordenador de quien consulta (si su reloj va mal, las fechas que propone el navegador salen mal)."""
    import time
    from datetime import datetime, timezone
    from .. import ZONA
    ahora, utc = datetime.now(), datetime.now(timezone.utc)
    try:
        bd = db.execute(text("SELECT CURRENT_TIMESTAMP")).scalar()
        bd = bd.astimezone(timezone.utc) if getattr(bd, "tzinfo", None) else None
    except Exception:  # noqa: BLE001
        bd = None
    desfase = round((ahora - utc.replace(tzinfo=None)).total_seconds() / 3600, 2)
    return {"hora": ahora.isoformat(timespec="seconds"), "utc": utc.isoformat(timespec="seconds"),
            "zona": ZONA, "zona_efectiva": time.tzname[time.localtime().tm_isdst > 0], "horas_sobre_utc": desfase,
            "correcta": desfase in (1.0, 2.0),  # Madrid: UTC+1 en invierno, UTC+2 en verano
            "bd_utc": bd.isoformat(timespec="seconds") if bd else None,
            "bd_desfase_s": round((bd - utc).total_seconds()) if bd else None}
