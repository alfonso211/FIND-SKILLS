"""Autenticación (JWT) y control de acceso por rol + ámbito (grupo / sociedad / activo)."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Asset, AuditLog, User

# Catálogo de permisos. Las claves son estables (se guardan en BD); la descripción es para la UI.
PERMISOS: dict[str, str] = {
    "activos.ver": "Ver activos y unidades",
    "activos.editar": "Crear / editar activos y unidades",
    "alquiler.ver": "Ver contratos, inquilinos y recibos",
    "alquiler.editar": "Gestionar contratos, inquilinos y recibos",
    "reservas.ver": "Ver reservas y huéspedes",
    "reservas.editar": "Gestionar reservas, check-in / check-out",
    "limpieza.editar": "Cambiar estado de limpieza de unidades",
    "limpieza.confirmar_ot": "Confirmar (o rechazar) la unidad tras una orden de trabajo",
    "mantenimiento.ver": "Ver órdenes de trabajo y planes preventivos",
    "mantenimiento.abrir": "Abrir órdenes de trabajo (avisos de avería)",
    "mantenimiento.editar": "Ejecutar órdenes de trabajo, confirmar trabajo realizado y gestionar preventivo",
    "mantenimiento.cerrar": "Cerrar órdenes de trabajo confirmadas por mantenimiento y limpieza",
    "finanzas.ver": "Ver indicadores económicos del panel (facturación, deuda)",
    "facturas.ver": "Ver, imprimir y exportar facturas emitidas",
    "facturas.rectificar": "Emitir facturas rectificativas (anula el cobro facturado)",
    "documentos.ver": "Ver los documentos recibidos (carpeta) y la cuenta de gastos",
    "documentos.editar": "Subir documentos recibidos y registrar gastos",
    "pedidos.crear": "Hacer pedidos de material (los autoriza Recepción 1 del activo)",
    "pedidos.autorizar": "Autorizar pedidos de material e intercambiar el catálogo con INVERGESTION",
    "partes.validar": "Validar los partes de trabajo diarios de mantenimiento y limpieza",
    "personal.autorizar": "Aprobar las ausencias de recepción, limpieza, conserjería y oficinas",
    "personal.autorizar_mto": "Director técnico: autorizar las ausencias del personal de mantenimiento",
    "usuarios.gestionar": "Gestionar usuarios, roles y sociedades",
    "auditoria.ver": "Consultar registro de auditoría",
}

# Solo los tiene el director técnico (rol «Dirección Técnica»), no toda la dirección
SOLO_DIRECCION_TECNICA = ("personal.autorizar_mto",)

# Roles iniciales; son editables desde Administración > Roles.
ROLES_POR_DEFECTO: dict[str, tuple[str, list[str]]] = {
    "Dirección Grupo": ("Acceso completo de consulta y gestión",
                        [p for p in PERMISOS if p not in SOLO_DIRECCION_TECNICA]),
    "Dirección Técnica": ("Director técnico: autoriza las ausencias de mantenimiento (se suma a su otro rol)",
                          ["activos.ver", "mantenimiento.ver", *SOLO_DIRECCION_TECNICA]),
    "Dirección Sociedad": ("Gestión completa de los activos de su ámbito", [
        "activos.ver", "activos.editar", "alquiler.ver", "alquiler.editar", "reservas.ver", "reservas.editar",
        "limpieza.editar", "limpieza.confirmar_ot", "mantenimiento.ver", "mantenimiento.abrir", "mantenimiento.editar",
        "mantenimiento.cerrar",
        "finanzas.ver", "facturas.ver", "facturas.rectificar", "auditoria.ver", "documentos.ver", "documentos.editar",
        "pedidos.crear", "pedidos.autorizar", "partes.validar", "personal.autorizar"]),
    "Gestor Alquiler Residencial": ("Contratos, inquilinos y cobros", [
        "activos.ver", "alquiler.ver", "alquiler.editar", "mantenimiento.ver", "finanzas.ver", "facturas.ver",
        "documentos.ver", "documentos.editar"]),
    "Recepción": ("Reservas, llegadas y salidas. Abre y cierra órdenes de trabajo", [
        "activos.ver", "reservas.ver", "reservas.editar", "facturas.ver", "limpieza.editar", "mantenimiento.ver",
        "mantenimiento.abrir", "mantenimiento.cerrar", "documentos.ver", "documentos.editar", "pedidos.crear",
        "partes.validar"]),
    "Gobernanta / Limpieza": ("Limpieza de unidades. Abre OT y confirma la unidad tras la reparación", [
        "activos.ver", "limpieza.editar", "limpieza.confirmar_ot", "mantenimiento.ver", "mantenimiento.abrir",
        "pedidos.crear"]),
    "Técnico Mantenimiento": ("Ejecuta y confirma órdenes de trabajo; preventivo", [
        "activos.ver", "mantenimiento.ver", "mantenimiento.abrir", "mantenimiento.editar", "pedidos.crear"]),
    "Administración / Finanzas": ("Consulta económica y cobros", [
        "activos.ver", "alquiler.ver", "alquiler.editar", "reservas.ver", "mantenimiento.ver", "finanzas.ver",
        "facturas.ver", "facturas.rectificar", "documentos.ver", "documentos.editar"]),
    "Consulta": ("Solo lectura", ["activos.ver", "alquiler.ver", "reservas.ver", "mantenimiento.ver",
                                  "documentos.ver"]),
}


# --------------------------------------------------------------------------- contraseñas / tokens
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.token_hours)
    return jwt.encode({"sub": str(user.id), "exp": exp}, settings.secret_key, algorithm="HS256")


_bearer = HTTPBearer(auto_error=False)


# Rutas permitidas mientras el usuario tiene una contraseña provisional
RUTAS_PASSWORD_PROVISIONAL = {"/api/auth/me", "/api/auth/password"}
PASSWORD_MIN = 10


def current_user(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 db: Session = Depends(get_db)) -> User:
    if not cred:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No autenticado")
    try:
        payload = jwt.decode(cred.credentials, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión no válida o caducada")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.activo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario inactivo")
    if user.debe_cambiar_password and request.url.path not in RUTAS_PASSWORD_PROVISIONAL:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Debe cambiar la contraseña provisional antes de continuar")
    return user


# --------------------------------------------------------------------------- bloqueo por intentos fallidos
MAX_INTENTOS, BLOQUEO_MIN = 5, 15
_fallos: dict[str, list[datetime]] = {}


def login_bloqueado(email: str) -> bool:
    limite = datetime.now(timezone.utc) - timedelta(minutes=BLOQUEO_MIN)
    _fallos[email] = [t for t in _fallos.get(email, []) if t > limite]
    return len(_fallos[email]) >= MAX_INTENTOS


def registrar_fallo(email: str) -> None:
    _fallos.setdefault(email, []).append(datetime.now(timezone.utc))


def limpiar_fallos(email: str) -> None:
    _fallos.pop(email, None)


# --------------------------------------------------------------------------- ámbitos
class Scope:
    """Resuelve qué activos / sociedades puede tocar el usuario para cada permiso.
    `None` significa "todos" (sin restricción)."""

    def __init__(self, user: User, db: Session):
        self.user = user
        self.db = db
        self._cache: dict[str, set[int] | None] = {}

    def asset_ids(self, perm: str) -> set[int] | None:
        if perm in self._cache:
            return self._cache[perm]
        result: set[int] | None = set()
        if self.user.is_superadmin:
            result = None
        else:
            companies: set[int] = set()
            for a in self.user.assignments:
                if perm not in (a.role.permisos or []):
                    continue
                if a.company_id is None and a.asset_id is None:
                    result = None
                    break
                if a.asset_id is not None:
                    result.add(a.asset_id)
                else:
                    companies.add(a.company_id)
            if result is not None and companies:
                result |= set(self.db.scalars(select(Asset.id).where(Asset.company_id.in_(companies))))
        self._cache[perm] = result
        return result

    def company_ids(self, perm: str) -> set[int] | None:
        """Sociedades en las que el usuario tiene el permiso sobre al menos un activo (o la sociedad entera)."""
        ids = self.asset_ids(perm)
        if ids is None:
            return None
        comps = {a.company_id for a in self.user.assignments if a.company_id and perm in (a.role.permisos or [])}
        if ids:
            comps |= set(self.db.scalars(select(Asset.company_id).where(Asset.id.in_(ids))))
        return comps

    def has_any(self, perm: str) -> bool:
        ids = self.asset_ids(perm)
        return ids is None or bool(ids) or bool(self.company_ids(perm))

    def can_asset(self, perm: str, asset_id: int) -> bool:
        ids = self.asset_ids(perm)
        return ids is None or asset_id in ids

    def can_company(self, perm: str, company_id: int) -> bool:
        """Permiso a nivel de sociedad completa (p.ej. dar de alta un activo nuevo en ella)."""
        if self.user.is_superadmin:
            return True
        for a in self.user.assignments:
            if perm in (a.role.permisos or []) and a.asset_id is None and a.company_id in (None, company_id):
                return True
        return False

    def company_level_ids(self, perm: str) -> set[int] | None:
        """Sociedades sobre las que el permiso se tiene a nivel de sociedad completa (no solo de algún activo)."""
        if self.is_group_level(perm):
            return None
        return {a.company_id for a in self.user.assignments
                if a.company_id and a.asset_id is None and perm in (a.role.permisos or [])}

    def is_group_level(self, perm: str) -> bool:
        if self.user.is_superadmin:
            return True
        return any(perm in (a.role.permisos or []) and a.company_id is None and a.asset_id is None
                   for a in self.user.assignments)

    # helpers que lanzan 403
    def require_asset(self, perm: str, asset_id: int) -> None:
        if not self.can_asset(perm, asset_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Sin permiso '{perm}' sobre este activo")

    def require_any(self, perm: str) -> None:
        if not self.has_any(perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Sin permiso '{perm}'")

    def require_group(self, perm: str) -> None:
        if not self.is_group_level(perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Se requiere permiso '{perm}' a nivel de grupo")


def get_scope(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Scope:
    return Scope(user, db)


def audit(db: Session, user: User | None, accion: str, entidad: str, entidad_id: int | None, detalle: dict | None = None):
    db.add(AuditLog(user_id=user.id if user else None, accion=accion, entidad=entidad,
                    entidad_id=entidad_id, detalle=detalle))
