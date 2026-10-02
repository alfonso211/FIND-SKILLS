"""Carga inicial: sociedades del grupo, roles, superadministrador y activos de partida.
Solo se ejecuta si la base de datos está vacía."""
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Asset, Company, Role, Unit, User
from .security import ROLES_POR_DEFECTO, hash_password

SOCIEDADES = ["INVERSIETE SA", "COMERCIAL DEL CAMPO", "EDIFICIOS CAMERANOS", "EMPRESA TURISTICA HOTELERA (ETHOSA)"]

# Titularidad provisional: todos los activos cuelgan de INVERSIETE hasta confirmar sociedad propietaria.
ACTIVOS = [
    dict(codigo="BAB35", nombre="C/ Babilonia 35", modalidad="alquiler_residencial",
         direccion="Calle Babilonia 35", municipio="Madrid", provincia="Madrid"),
    dict(codigo="SFL", nombre="Suite Florida", modalidad="apartamentos_turisticos", prefijo="SF-", unidades=325),
    dict(codigo="SAE", nombre="Suite Aeropuerto", modalidad="apartamentos_turisticos", prefijo="SA-", unidades=300),
]


def seed(db: Session) -> None:
    if db.scalar(select(Company.id)):
        return
    matriz = Company(nombre=SOCIEDADES[0])
    db.add(matriz)
    db.flush()
    for nombre in SOCIEDADES[1:]:
        db.add(Company(nombre=nombre, parent_id=matriz.id))

    for nombre, (desc, perms) in ROLES_POR_DEFECTO.items():
        db.add(Role(nombre=nombre, descripcion=desc, permisos=perms))

    for spec in ACTIVOS:
        spec = dict(spec)
        n, prefijo = spec.pop("unidades", 0), spec.pop("prefijo", "")
        a = Asset(company_id=matriz.id, **spec)
        db.add(a)
        db.flush()
        for i in range(1, n + 1):
            db.add(Unit(asset_id=a.id, codigo=f"{prefijo}{i:03d}", tipologia="Apartamento"))

    password = settings.admin_password or secrets.token_urlsafe(12)
    db.add(User(email=settings.admin_email, nombre="Administrador", password_hash=hash_password(password),
                is_superadmin=True))
    db.commit()
    if not settings.admin_password:
        print(f"\n*** Usuario inicial: {settings.admin_email}  contraseña: {password}  (cámbiela al entrar) ***\n",
              flush=True)
