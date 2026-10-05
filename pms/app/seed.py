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

# (razón social, CIF) según «Datos fiscales sociedades Grupo INVERSIETE S.A.». Todas con domicilio fiscal en
# C/ Campezo 8, 28022 Madrid.
SOCIEDADES = [
    ("INVERSIETE S.A.", "A78072915"),
    ("COMERCIAL DEL CAMPO S.A.", "A28362309"),
    ("EDIFICIOS CAMERANOS S.A.", "A28309433"),
    ("EMPRESA TURISTICA HOTELERA S.A.", "A28116853"),
]
DOMICILIO_FISCAL = dict(direccion="C/ Campezo 8", cp="28022", municipio="Madrid", provincia="Madrid")

# Unidades reales de cada activo (ver data/unidades_iniciales.json):
#  - BAB35: listado de cuotas de comunidad oct-2026 (solo viviendas y garajes de COMERCIAL DEL CAMPO)
#  - SFL:   listado 2026-10-02, 4 portales
#  - SAE:   listado 2026-10-02, bloques A y B
UNIDADES = Path(__file__).parent / "data" / "unidades_iniciales.json"

# gestora = sociedad que explota el activo; propietaria = titular del inmueble
ACTIVOS = [
    dict(codigo="BAB35", nombre="C/ Babilonia 35", modalidad="alquiler_residencial",
         gestora="COMERCIAL DEL CAMPO S.A.", propietaria="COMERCIAL DEL CAMPO S.A.",
         direccion="Calle Babilonia 35", municipio="Madrid", provincia="Madrid", serie_factura="B35"),
    # Registro de Empresas Turísticas de la Comunidad de Madrid (toma de nota de cambio de titular a
    # INVERSIETE S.A., presentada el 03/01/2025, resoluciones de 12/03/2025)
    dict(codigo="SFL", nombre="Suite Florida", modalidad="apartamentos_turisticos",
         gestora="INVERSIETE S.A.", propietaria="COMERCIAL DEL CAMPO S.A.",
         direccion="Calle Campezo 2", municipio="Madrid", provincia="Madrid", cp="28022",
         num_registro_turistico="AM 265", serie_factura="SF",
         notas="Apartamentos turísticos 1 llave. Cambio de titular a INVERSIETE S.A. con efectos 03/01/2025 "
               "(Ref. 09/503253.9/25)."),
    dict(codigo="SAE", nombre="Suite Aeropuerto", modalidad="apartamentos_turisticos",
         gestora="INVERSIETE S.A.", propietaria="COMERCIAL DEL CAMPO S.A.",
         direccion="Calle Campezo 8", municipio="Madrid", provincia="Madrid", cp="28022",
         num_registro_turistico="AM 259", serie_factura="SA",
         notas="Apartamentos turísticos 1 llave. Cambio de titular a INVERSIETE S.A. con efectos 03/01/2025 "
               "(Ref. 09/503243.9/25)."),
]

# Usuarios iniciales. Todos entran con PASSWORD_INICIAL y deben cambiarla en el primer acceso.
# Puestos aún sin titular (recepción 3, limpieza y mantenimiento de cada Suite) se darán de alta desde
# Administración > Usuarios cuando se asignen.
PASSWORD_INICIAL = "00000000"
USUARIOS_INICIALES = [  # (email, nombre, rol, código de activo o None = todo el grupo)
    ("jr@inversiete.es", "Presidente", "Dirección Grupo", None),
    ("barbara@inversiete.es", "Director General", "Dirección Grupo", None),
    ("alfonso@inversiete.es", "Director Técnico", "Dirección Grupo", None),
    ("juancarlos@apartamentossuitesflorida.es", "Recepción 1 · Suite Florida", "Recepción", "SFL"),
    ("info@apartamentossuitesflorida.es", "Recepción 2 · Suite Florida", "Recepción", "SFL"),
    ("jaime@apartamentossuitesaeropuerto.es", "Recepción 1 · Suite Aeropuerto", "Recepción", "SAE"),
    ("info@apartamentossuitesaeropuerto.es", "Recepción 2 · Suite Aeropuerto", "Recepción", "SAE"),
]


def _usuarios_iniciales(db: Session, assets: dict[str, Asset]) -> None:
    roles = {r.nombre: r for r in db.scalars(select(Role))}
    pw = hash_password(PASSWORD_INICIAL)
    for email, nombre, rol, codigo in USUARIOS_INICIALES:
        a = assets[codigo] if codigo else None
        db.add(User(email=email, nombre=nombre, password_hash=pw, debe_cambiar_password=True,
                    assignments=[Assignment(role_id=roles[rol].id, asset_id=a.id if a else None,
                                            company_id=a.company_id if a else None)]))


def seed(db: Session) -> None:
    if db.scalar(select(Company.id)):
        return
    matriz = Company(nombre=SOCIEDADES[0][0], cif=SOCIEDADES[0][1], **DOMICILIO_FISCAL)
    db.add(matriz)
    db.flush()
    soc = {matriz.nombre: matriz}
    for nombre, cif in SOCIEDADES[1:]:
        soc[nombre] = Company(nombre=nombre, cif=cif, parent_id=matriz.id, **DOMICILIO_FISCAL)
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
