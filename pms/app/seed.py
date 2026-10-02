"""Carga inicial: sociedades del grupo, roles, superadministrador y activos de partida.
Solo se ejecuta si la base de datos está vacía."""
import json
import secrets
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Asset, Assignment, Company, Role, Unit, User
from .security import ROLES_POR_DEFECTO, hash_password

SOCIEDADES = ["INVERSIETE SA", "COMERCIAL DEL CAMPO S.A.", "EDIFICIOS CAMERANOS",
              "EMPRESA TURISTICA HOTELERA (ETHOSA)"]

# Unidades reales de cada activo (ver data/unidades_iniciales.json):
#  - BAB35: listado de cuotas de comunidad oct-2026 (solo viviendas y garajes de COMERCIAL DEL CAMPO)
#  - SFL:   listado 2026-10-02, 4 portales
#  - SAE:   listado 2026-10-02, bloques A y B
UNIDADES = Path(__file__).parent / "data" / "unidades_iniciales.json"

# gestora = sociedad que explota el activo; propietaria = titular del inmueble
ACTIVOS = [
    dict(codigo="BAB35", nombre="C/ Babilonia 35", modalidad="alquiler_residencial",
         gestora="COMERCIAL DEL CAMPO S.A.", propietaria="COMERCIAL DEL CAMPO S.A.",
         direccion="Calle Babilonia 35", municipio="Madrid", provincia="Madrid"),
    dict(codigo="SFL", nombre="Suite Florida", modalidad="apartamentos_turisticos",
         gestora="INVERSIETE SA", propietaria="COMERCIAL DEL CAMPO S.A."),
    dict(codigo="SAE", nombre="Suite Aeropuerto", modalidad="apartamentos_turisticos",
         gestora="INVERSIETE SA", propietaria="COMERCIAL DEL CAMPO S.A."),
]

# Usuarios iniciales. Todos entran con PASSWORD_INICIAL y deben cambiarla en el primer acceso.
PASSWORD_INICIAL = "00000000"
DIRECCION = [  # (email, nombre) -> rol "Dirección Grupo" sobre todo el grupo
    ("presidente@inversiete.com", "Presidente"),
    ("director.general@inversiete.com", "Director General"),
    ("director.tecnico@inversiete.com", "Director Técnico"),
]
PERSONAL_ACTIVO = [  # (prefijo email, puesto, rol, nº de usuarios) por cada activo turístico
    ("recepcion", "Recepción", "Recepción", 3),
    ("limpieza", "Limpieza", "Gobernanta / Limpieza", 2),
    ("mantenimiento", "Mantenimiento", "Técnico Mantenimiento", 2),
]
ACTIVOS_PERSONAL = {"SFL": ("sflorida", "Suite Florida"), "SAE": ("saeropuerto", "Suite Aeropuerto")}


def _usuarios_iniciales(db: Session, assets: dict[str, Asset]) -> None:
    roles = {r.nombre: r for r in db.scalars(select(Role))}
    pw = hash_password(PASSWORD_INICIAL)

    def nuevo(email, nombre, rol, asset_id=None):
        db.add(User(email=email, nombre=nombre, password_hash=pw, debe_cambiar_password=True,
                    assignments=[Assignment(role_id=roles[rol].id, asset_id=asset_id,
                                            company_id=assets_by_id[asset_id].company_id if asset_id else None)]))

    assets_by_id = {a.id: a for a in assets.values()}
    for email, nombre in DIRECCION:
        nuevo(email, nombre, "Dirección Grupo")
    for codigo, (slug, nombre_activo) in ACTIVOS_PERSONAL.items():
        for pref, puesto, rol, n in PERSONAL_ACTIVO:
            for i in range(1, n + 1):
                nuevo(f"{pref}{i}.{slug}@inversiete.com", f"{puesto} {i} · {nombre_activo}", rol, assets[codigo].id)


def seed(db: Session) -> None:
    if db.scalar(select(Company.id)):
        return
    matriz = Company(nombre=SOCIEDADES[0])
    db.add(matriz)
    db.flush()
    soc = {matriz.nombre: matriz}
    for nombre in SOCIEDADES[1:]:
        soc[nombre] = Company(nombre=nombre, parent_id=matriz.id)
        db.add(soc[nombre])
    db.flush()

    for nombre, (desc, perms) in ROLES_POR_DEFECTO.items():
        db.add(Role(nombre=nombre, descripcion=desc, permisos=perms))

    unidades = json.loads(UNIDADES.read_text(encoding="utf-8"))
    assets: dict[str, Asset] = {}
    for spec in ACTIVOS:
        spec = dict(spec)
        gestora, propietaria = soc[spec.pop("gestora")], soc[spec.pop("propietaria")]
        a = Asset(company_id=gestora.id, propietaria_id=propietaria.id, **spec)
        db.add(a)
        db.flush()
        assets[a.codigo] = a
        for u in unidades.get(a.codigo, []):
            db.add(Unit(asset_id=a.id, **u))

    password = settings.admin_password or secrets.token_urlsafe(12)
    db.add(User(email=settings.admin_email, nombre="Administrador", password_hash=hash_password(password),
                is_superadmin=True, debe_cambiar_password=not settings.admin_password))
    db.flush()
    _usuarios_iniciales(db, assets)
    db.commit()
    if not settings.admin_password:
        print(f"\n*** Usuario inicial: {settings.admin_email}  contraseña: {password}  (cámbiela al entrar) ***\n",
              flush=True)
